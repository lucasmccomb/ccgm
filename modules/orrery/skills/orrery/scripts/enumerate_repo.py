#!/usr/bin/env python3
"""Deterministic census of an anchored worktree (plan section 3.1 stage 2, Epic 2).

Usage:
    enumerate_repo.py --worktree <path> --out <census.json>

Tracked paths come from ``git ls-files`` and file contents from
``git cat-file blob :0:<path>`` - NEVER from raw filesystem walks. The fixture
repo tracks both ``web/`` and ``Web/``, which case-insensitive filesystems
collapse into one on-disk directory; the git index is the only truthful
listing, so the filesystem is never consulted for enumeration or content.

Output is byte-deterministic: sorted keys, sorted lists, ASCII escapes, one
trailing newline. Two runs over the same worktree produce identical bytes.
No LLM or tool calls - pure deterministic computation (plan 1.4 principle 3).

Census shape (plan section 3.2):
    {
      "areas":        [...],  # section 3.5a clustering + bucketing
      "bucketing":    {"applied", "bucket_count", "candidate_count"},
      "entrypoints":  [...],
      "id_namespace": {...},  # published area ids + reserved ids
      "languages":    {...},  # extension -> tracked-file count
      "manifests":    [...],  # detection table hits
      "tree":         {...}   # tracked-file stats
    }

MANIFEST_TABLE below is the single source of truth for manifest detection;
Epic 5's diff_since.py imports it from this module - never duplicate it.
"""

import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatchcase
from fractions import Fraction

# --- manifest detection table (imported by diff_since.py - Epic 5) -----------
# Rows are (kind, match_type, pattern). Match types:
#   basename - the file's basename equals pattern
#   suffix   - the path ends with pattern (extension-style, e.g. *.tf)
#   glob     - fnmatch of the full path against pattern
#   dir      - any tracked file sits under a directory named pattern; the hit
#              path is that directory (e.g. db/migrations)
# Row order mirrors the plan's Epic 2 table for easy diffing against the spec.
MANIFEST_TABLE = (
    ("package.json", "basename", "package.json"),
    ("pnpm-workspace", "basename", "pnpm-workspace.yaml"),
    ("requirements", "basename", "requirements.txt"),
    ("pyproject", "basename", "pyproject.toml"),
    ("gemfile", "basename", "Gemfile"),
    ("go-mod", "basename", "go.mod"),
    ("cargo", "basename", "Cargo.toml"),
    ("swiftpm", "basename", "Package.swift"),
    ("composer", "basename", "composer.json"),
    ("wrangler", "basename", "wrangler.toml"),
    ("vercel", "basename", "vercel.json"),
    ("netlify", "basename", "netlify.toml"),
    ("fly", "basename", "fly.toml"),
    ("dockerfile", "basename", "Dockerfile"),
    ("docker-compose", "basename", "docker-compose.yml"),
    ("terraform", "suffix", ".tf"),
    ("github-workflow", "glob", ".github/workflows/*.yml"),
    ("env-example", "basename", ".env.example"),
    ("supabase", "dir", "supabase"),
    ("prisma", "dir", "prisma"),
    ("drizzle", "dir", "drizzle"),
    ("migrations", "dir", "migrations"),
)

# Entry-point heuristics: a tracked file whose basename (extension stripped)
# is one of these names is a candidate entry point.
ENTRYPOINT_BASENAMES = frozenset(
    ("__main__", "app", "cli", "index", "main", "manage", "server", "worker")
)

# --- section 3.5a constants --------------------------------------------------
AREA_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
AREA_ID_MAX_LEN = 24
CANDIDATE_TARGET = 12   # candidate count above which bucketing engages
BUCKET_CEILING = 24     # hard ceiling on areas (3 waves of 8)
MERGE_THRESHOLD = 5     # candidates with fewer files merge into misc
SPLIT_THRESHOLD = 400   # candidates with more files split by subdirectory
EXPAND_NUM, EXPAND_DEN = 3, 5  # expand when a single dir holds > 3/5 of files

RESERVED_IDS = ("misc", "system", "users")
RESERVED_BUCKET_IDS = tuple("bucket_%02d" % i for i in range(1, BUCKET_CEILING + 1))
# Wave-0 packs (product-vision, external-systems) publish the container, actor,
# and external element ids at orchestration time (plan section 3.5).
WAVE0_OWNED_KINDS = ("actor", "container", "external")


def sanitize_area_id(path, taken):
    """FROZEN section-3.5a step-5 rule. Do not alter without a plan revision.

    lowercase -> collapse every run of non-[a-z0-9] to _ -> if the result does
    not start with [a-z], prefix a_ -> trim trailing _ -> truncate to 24 chars
    -> on collision against `taken`, append _2, _3, ... in candidate order.

    Element-id-legal by construction: the result always matches
    ^[a-z][a-z0-9_]*$. `taken` is mutated with the id handed out.
    """
    s = path.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    if not s or not ("a" <= s[0] <= "z"):
        s = "a_" + s
    s = s.rstrip("_")
    if not s:  # a name with no [a-z0-9] at all collapses to the a_ prefix
        s = "a"
    s = s[:AREA_ID_MAX_LEN]
    base = s
    if base not in taken:
        taken.add(base)
        return base
    n = 2
    while True:
        candidate = "%s_%d" % (base, n)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1


# --- git plumbing ------------------------------------------------------------
def _git(worktree, *args):
    return subprocess.run(
        ["git", "-C", worktree] + list(args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout


def tracked_paths(worktree):
    raw = _git(worktree, "ls-files", "-z")
    return sorted(p.decode("utf-8", "replace") for p in raw.split(b"\0") if p)


def read_blob(worktree, path):
    """Index (stage 0) content of a tracked path; None when unreadable."""
    try:
        return _git(worktree, "cat-file", "blob", ":0:%s" % path)
    except subprocess.CalledProcessError:
        return None


# --- census pieces -----------------------------------------------------------
def _basename(path):
    return path.rsplit("/", 1)[-1]


def _extension(path):
    base = _basename(path)
    if "." in base[1:]:
        return base.rsplit(".", 1)[1].lower()
    return "(none)"


def language_stats(paths):
    counts = {}
    for p in paths:
        ext = _extension(p)
        counts[ext] = counts.get(ext, 0) + 1
    return counts


def detect_entrypoints(paths):
    hits = []
    for p in paths:
        base = _basename(p)
        stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
        if stem.lower() in ENTRYPOINT_BASENAMES:
            hits.append(p)
    return sorted(hits)


def _package_dependencies(worktree, path):
    """Sorted dependency + devDependency names; None on a parse failure."""
    blob = read_blob(worktree, path)
    if blob is None:
        return None
    try:
        data = json.loads(blob.decode("utf-8", "replace"))
    except ValueError:
        return None
    deps = set()
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(str(name) for name in section)
    return sorted(deps)


def detect_manifests(worktree, paths):
    hits = {}
    for p in paths:
        base = _basename(p)
        for kind, match_type, pattern in MANIFEST_TABLE:
            hit_path = None
            if match_type == "basename":
                if base == pattern:
                    hit_path = p
            elif match_type == "suffix":
                if p.endswith(pattern):
                    hit_path = p
            elif match_type == "glob":
                if fnmatchcase(p, pattern):
                    hit_path = p
            elif match_type == "dir":
                components = p.split("/")[:-1]
                if pattern in components:
                    idx = components.index(pattern)
                    hit_path = "/".join(components[: idx + 1])
            if hit_path is not None:
                hits.setdefault((hit_path, kind), None)
    manifests = []
    for (hit_path, kind) in sorted(hits):
        entry = {"kind": kind, "path": hit_path}
        if kind == "package.json":
            deps = _package_dependencies(worktree, hit_path)
            if deps is None:
                entry["dependencies"] = []
                entry["parse_error"] = True
            else:
                entry["dependencies"] = deps
        manifests.append(entry)
    return manifests


# --- section 3.5a area clustering + bucketing --------------------------------
def _split_candidate(path, files):
    """Partition a candidate one level down: per-subdir candidates plus a
    residual candidate (same path) for files directly inside it."""
    prefix = path + "/"
    loose = []
    by_child = {}
    for f in files:
        rest = f[len(prefix):]
        if "/" in rest:
            child = rest.split("/", 1)[0]
            by_child.setdefault(child, []).append(f)
        else:
            loose.append(f)
    out = [
        {"path": prefix + child, "files": child_files}
        for child, child_files in sorted(by_child.items())
    ]
    if loose:
        out.append({"path": path, "files": loose})
    return out


def compute_candidates(paths):
    """Steps 1-2 of section 3.5a. Returns (survivors, misc_members) where
    survivors are candidate dicts in byte-sorted path order and misc_members
    are {"file_count", "path"} rows (tiny candidates + root loose files)."""
    total = len(paths)
    root_files = [p for p in paths if "/" not in p]
    by_top = {}
    for p in paths:
        if "/" in p:
            top = p.split("/", 1)[0]
            by_top.setdefault(top, []).append(p)
    candidates = [{"path": d, "files": fs} for d, fs in sorted(by_top.items())]

    # Step 1: expand one level deeper when a single directory holds >60% of
    # tracked files (the modules/-style case). Integer math: n/total > 3/5.
    expanded = []
    for cand in candidates:
        if len(cand["files"]) * EXPAND_DEN > total * EXPAND_NUM:
            expanded.extend(_split_candidate(cand["path"], cand["files"]))
        else:
            expanded.append(cand)
    candidates = sorted(expanded, key=lambda c: c["path"])

    # Step 2: split any candidate >400 files by subdirectory (split first so
    # tiny split residue can still merge), then merge <5-file candidates into
    # misc.
    split_out = []
    for cand in candidates:
        if len(cand["files"]) > SPLIT_THRESHOLD:
            split_out.extend(_split_candidate(cand["path"], cand["files"]))
        else:
            split_out.append(cand)
    candidates = sorted(split_out, key=lambda c: c["path"])

    survivors = []
    misc_members = []
    for cand in candidates:
        if len(cand["files"]) < MERGE_THRESHOLD:
            misc_members.append({"file_count": len(cand["files"]), "path": cand["path"]})
        else:
            survivors.append(cand)
    for f in sorted(root_files):
        misc_members.append({"file_count": 1, "path": f})
    misc_members.sort(key=lambda m: m["path"])
    return survivors, misc_members


def _allocate_buckets(groups, bucket_total, total_files):
    """Largest-remainder allocation of bucket_total buckets across sibling
    groups, proportional to file count, each group getting 1..len(group).
    Exact Fraction arithmetic keeps it deterministic."""
    quotas = []
    for _parent, members in groups:
        group_files = sum(len(c["files"]) for c in members)
        if total_files:
            quotas.append(Fraction(bucket_total * group_files, total_files))
        else:
            quotas.append(Fraction(1))
    alloc = []
    for (_parent, members), quota in zip(groups, quotas):
        alloc.append(max(1, min(len(members), int(quota))))
    while sum(alloc) < bucket_total:
        best = None
        for i, (_parent, members) in enumerate(groups):
            if alloc[i] < len(members):
                key = (quotas[i] - alloc[i], -i)
                if best is None or key > best[0]:
                    best = (key, i)
        if best is None:
            break
        alloc[best[1]] += 1
    while sum(alloc) > bucket_total:
        best = None
        for i in range(len(groups)):
            if alloc[i] > 1:
                key = (alloc[i] - quotas[i], -i)
                if best is None or key > best[0]:
                    best = (key, i)
        if best is None:
            break
        alloc[best[1]] -= 1
    return alloc


def _partition_min_max(sizes, runs):
    """Contiguous partition of `sizes` into `runs` runs minimizing the max run
    sum (classic linear-partition DP). Deterministic: strict improvement only,
    so ties resolve to the earliest cut. Returns (start, end) index pairs."""
    n = len(sizes)
    prefix = [0]
    for s in sizes:
        prefix.append(prefix[-1] + s)
    inf = float("inf")
    dp = [[inf] * (n + 1) for _ in range(runs + 1)]
    cut = [[0] * (n + 1) for _ in range(runs + 1)]
    dp[0][0] = 0
    for j in range(1, runs + 1):
        for i in range(j, n - (runs - j) + 1):
            best = inf
            best_m = j - 1
            for m in range(j - 1, i):
                value = max(dp[j - 1][m], prefix[i] - prefix[m])
                if value < best:
                    best = value
                    best_m = m
            dp[j][i] = best
            cut[j][i] = best_m
    bounds = []
    i = n
    for j in range(runs, 0, -1):
        m = cut[j][i]
        bounds.append((m, i))
        i = m
    bounds.reverse()
    return bounds


def _bucketize(survivors, misc_exists):
    """Step 3: balanced bin-packing of sibling candidates (same parent,
    alphabetical adjacency preserved) into at most BUCKET_CEILING buckets,
    balanced by file count. Bucket count targets CANDIDATE_TARGET and grows
    ~1 bucket per 3 candidates so a sibling explosion (the ccgm demo, ~66
    candidates) lands at 22-24 buckets."""
    n = len(survivors)
    total_files = sum(len(c["files"]) for c in survivors)
    ceiling = BUCKET_CEILING - (1 if misc_exists else 0)

    by_parent = {}
    for cand in survivors:  # already path-sorted: adjacency == list order
        parent = cand["path"].rsplit("/", 1)[0] if "/" in cand["path"] else ""
        by_parent.setdefault(parent, []).append(cand)
    groups = sorted(by_parent.items())
    if len(groups) > ceiling:
        # Same error shape as the documented CLI failure: one line on stderr,
        # exit 2 (review finding 8).
        print(
            "enumerate_repo.py: %d sibling groups exceed the %d-bucket "
            "ceiling (outside the v1 boundary - plan section 3.5a)"
            % (len(groups), ceiling),
            file=sys.stderr,
        )
        raise SystemExit(2)

    target = min(ceiling, max(CANDIDATE_TARGET, -(-n // 3)))
    bucket_total = max(target, len(groups))
    alloc = _allocate_buckets(groups, bucket_total, total_files)

    areas = []
    number = 0
    for (_parent, members), runs in zip(groups, alloc):
        sizes = [len(c["files"]) for c in members]
        for start, end in _partition_min_max(sizes, runs):
            number += 1
            run = members[start:end]
            areas.append(
                {
                    "bucketed": True,
                    "file_count": sum(len(c["files"]) for c in run),
                    "id": "bucket_%02d" % number,
                    "members": [
                        {"file_count": len(c["files"]), "path": c["path"]}
                        for c in run
                    ],
                    "root_paths": [c["path"] for c in run],
                }
            )
    return areas


def compute_areas(paths):
    """Full section 3.5a pipeline. Returns (areas, bucketing_stats)."""
    survivors, misc_members = compute_candidates(paths)

    bucketing = {"applied": False, "bucket_count": 0, "candidate_count": len(survivors)}
    if len(survivors) > CANDIDATE_TARGET:
        areas = _bucketize(survivors, misc_exists=bool(misc_members))
        bucketing["applied"] = True
        bucketing["bucket_count"] = len(areas)
    else:
        taken = set(RESERVED_IDS) | set(RESERVED_BUCKET_IDS)
        areas = []
        for cand in survivors:  # candidate order: byte-sorted paths
            area_id = sanitize_area_id(cand["path"], taken)
            areas.append(
                {
                    "bucketed": False,
                    "file_count": len(cand["files"]),
                    "id": area_id,
                    "members": [
                        {"file_count": len(cand["files"]), "path": cand["path"]}
                    ],
                    "root_paths": [cand["path"]],
                }
            )

    if misc_members:
        areas.append(
            {
                "bucketed": False,
                "file_count": sum(m["file_count"] for m in misc_members),
                "id": "misc",
                "members": misc_members,
                "root_paths": [m["path"] for m in misc_members],
            }
        )

    areas.sort(key=lambda a: a["id"])
    for area in areas:
        if not AREA_ID_PATTERN.match(area["id"]):
            # Same error shape as the documented CLI failure (review finding 8).
            print(
                "enumerate_repo.py: internal error - area id %r is not "
                "element-id-legal" % area["id"],
                file=sys.stderr,
            )
            raise SystemExit(2)
    return areas, bucketing


# --- census ------------------------------------------------------------------
def build_census(worktree):
    paths = tracked_paths(worktree)
    areas, bucketing = compute_areas(paths)
    top_level_dirs = sorted({p.split("/", 1)[0] for p in paths if "/" in p})
    top_level_files = sorted(p for p in paths if "/" not in p)
    return {
        "areas": areas,
        "bucketing": bucketing,
        "entrypoints": detect_entrypoints(paths),
        "id_namespace": {
            "area_ids": sorted(a["id"] for a in areas),
            "reserved_bucket_ids": list(RESERVED_BUCKET_IDS),
            "reserved_ids": list(RESERVED_IDS),
            "wave0_owned_kinds": list(WAVE0_OWNED_KINDS),
        },
        "languages": language_stats(paths),
        "manifests": detect_manifests(worktree, paths),
        "tree": {
            "top_level_dirs": top_level_dirs,
            "top_level_files": top_level_files,
            "tracked_files": len(paths),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worktree", required=True, help="anchored worktree path")
    parser.add_argument("--out", required=True, help="census.json output path")
    args = parser.parse_args(argv)

    try:
        _git(args.worktree, "rev-parse", "--git-dir")
    except (subprocess.CalledProcessError, OSError):
        print(
            "enumerate_repo.py: %s is not a git worktree" % args.worktree,
            file=sys.stderr,
        )
        return 2

    census = build_census(args.worktree)
    payload = json.dumps(census, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    with open(args.out, "w", encoding="ascii") as fh:
        fh.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
