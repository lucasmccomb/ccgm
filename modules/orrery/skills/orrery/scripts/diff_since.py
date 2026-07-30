#!/usr/bin/env python3
"""diff_since.py -- orrery update-path diff stage (plan Epic 5, section 3.1).

Usage:
    diff_since.py --repo <repo-path> --state <state.json> \
        --new-anchor <sha> --out <diff.json>

Deterministic, stdlib-only. Computes what changed between the recorded
anchor (state.json's anchor_sha) and the freshly pinned one, and classifies
the change so the update flow re-dispatches ONLY the affected packs.

Decision order (each stop still writes a complete diff.json):

1. State gate (business R5 / arch R5 / adrev2-009). The update flow rebuilds
   fully, with a message naming WHICH condition fired, unless ALL of: the
   state file exists, parses, carries anchor_sha, schema_version == 1, AND
   likec4_version equals the installed toolchain version (read from
   scripts/toolchain/package.json next to this script -- the same single
   source the build path's state writer reads). Any failure ->
   rebuild_required: true with the condition in rebuild_reason.
2. History-rewrite safety (business C3). The old anchor must be resolvable
   (git cat-file -e <old>^{commit}) AND an ancestor of the new one
   (git merge-base --is-ancestor). Either failing -> history_rewritten: true
   and stop -- never a guess-diff across rewritten history.
3. Unchanged short-circuit. old == new -> unchanged: true, nothing else.
4. Diff + classification: `git diff -M --name-status <old>..<new>` (explicit
   -M so rename detection never depends on ambient config -- arch R2).
   - Renamed files update the owning element's file anchors IN PLACE in the
     baseline model.json (sibling of --state; temp-file + atomic rename), so
     element continuity survives without re-investigation. A rename with
     content edits (similarity < 100) additionally counts as a change; a
     rename that crosses area boundaries marks both areas affected.
   - Changed paths map to affected areas via state.json areas[].root_paths;
     deletions map the same way, and elements whose every indexed path
     (state.json element_index) was deleted are listed as orphaned_elements
     for merge_fragments.py --patch to remove.
   - Genuinely-new paths (under no recorded area) route to the existing
     `misc` area first (arch R3). Full rebuild is reserved for
     clustering-material changes: a new top-level directory contributing
     >= 5 such files -> rebuild_required with the directory named.
   - Manifest-table paths (MANIFEST_TABLE imported from enumerate_repo.py --
     single source, never duplicated) always flag the external-systems pack;
     README.md / CLAUDE.md / docs/ paths flag the product-vision pack.

diff.json always carries every field:
    changed_paths, affected_areas, deleted_paths, orphaned_elements,
    new_paths_routed_to_misc, rebuild_required, rebuild_reason, unchanged,
    history_rewritten -- plus renamed_paths ([{from,to,similarity}]),
    elements_reanchored, external_systems_flagged, product_vision_flagged,
    old_anchor_sha, new_anchor_sha for the update flow's pack list and
    delta report.

Exit codes: 0 = diff.json written (any outcome, including rebuild_required /
history_rewritten / unchanged); 2 = usage or input error (unreachable repo,
unresolvable NEW anchor, unreadable toolchain manifest) -- nothing written.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from fnmatch import fnmatchcase

SCHEMA_VERSION = 1
NEW_DIR_REBUILD_THRESHOLD = 5  # new top-level dir with >= 5 files outside all areas
PRODUCT_VISION_BASENAMES = ("CLAUDE.md", "README.md")


# --- single-source manifest table (imported from enumerate_repo.py) ----------
def _load_manifest_table():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "enumerate_repo.py")
    spec = importlib.util.spec_from_file_location("orrery_enumerate_repo", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MANIFEST_TABLE


MANIFEST_TABLE = _load_manifest_table()


def _toolchain_likec4_version():
    """The installed toolchain version -- read from scripts/toolchain/
    package.json next to this script, the same way the build path's state
    writer reads it (single source for the pinned version)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "toolchain", "package.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["dependencies"]["likec4"]


# --- git plumbing ------------------------------------------------------------
def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _is_commit(repo, sha):
    return _git(repo, "cat-file", "-e", "%s^{commit}" % sha).returncode == 0


def _is_ancestor(repo, old, new):
    return _git(repo, "merge-base", "--is-ancestor", old, new).returncode == 0


def _name_status(repo, old, new):
    """Parse `git diff -M --name-status -z old..new` into
    (status_code, similarity, old_path, new_path) rows. For non-renames
    old_path == new_path and similarity is None."""
    proc = _git(repo, "diff", "-M", "--name-status", "-z", "%s..%s" % (old, new))
    if proc.returncode != 0:
        raise RuntimeError("git diff -M --name-status failed between %s and %s" % (old, new))
    tokens = proc.stdout.decode("utf-8", "replace").split("\0")
    rows = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if not status:
            i += 1
            continue
        code = status[0]
        if code in ("R", "C"):
            if i + 2 >= len(tokens):
                break
            try:
                similarity = int(status[1:]) if status[1:] else 100
            except ValueError:
                similarity = 100
            rows.append((code, similarity, tokens[i + 1], tokens[i + 2]))
            i += 3
        else:
            if i + 1 >= len(tokens):
                break
            rows.append((code, None, tokens[i + 1], tokens[i + 1]))
            i += 2
    return rows


# --- classification helpers --------------------------------------------------
def path_matches_manifest(path):
    """Mirror of enumerate_repo.detect_manifests match semantics, driven by
    the imported MANIFEST_TABLE."""
    base = path.rsplit("/", 1)[-1]
    for _kind, match_type, pattern in MANIFEST_TABLE:
        if match_type == "basename":
            if base == pattern:
                return True
        elif match_type == "suffix":
            if path.endswith(pattern):
                return True
        elif match_type == "glob":
            if fnmatchcase(path, pattern):
                return True
        elif match_type == "dir":
            if pattern in path.split("/")[:-1]:
                return True
    return False


def path_flags_product_vision(path):
    base = path.rsplit("/", 1)[-1]
    if base in PRODUCT_VISION_BASENAMES:
        return True
    return path == "docs" or path.startswith("docs/")


def areas_of(path, areas):
    """Area ids whose root_paths cover `path` (exact or prefix match)."""
    hits = set()
    for area in areas:
        area_id = area.get("id")
        if not area_id:
            continue
        for rp in area.get("root_paths") or []:
            if path == rp or path.startswith(rp + "/"):
                hits.add(area_id)
                break
    return hits


# --- state gate --------------------------------------------------------------
def state_gate(state_path, installed_version):
    """Returns (reason, state). A non-None reason means the update flow must
    fall back to a full rebuild; the reason names WHICH condition fired."""
    if not os.path.isfile(state_path):
        return (
            "no state.json at %s - if this map was built with a custom --out, "
            "pass the same --out to /orrery update; otherwise a full rebuild "
            "is required" % state_path,
            None,
        )
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except ValueError:
        return ("state.json at %s is unparseable - full rebuild required" % state_path, None)
    if not isinstance(state, dict):
        return ("state.json at %s is not a JSON object - full rebuild required" % state_path, None)
    sv = state.get("schema_version")
    if sv != SCHEMA_VERSION:
        return (
            "state.json schema_version is %r, expected %d - full rebuild required"
            % (sv, SCHEMA_VERSION),
            None,
        )
    recorded = state.get("likec4_version")
    if recorded != installed_version:
        return (
            "state.json likec4_version %r != installed toolchain %r - full rebuild "
            "required (a pinned-version bump changes emitted-DSL semantics; "
            "patch-merging across it corrupts the map)" % (recorded, installed_version),
            None,
        )
    if not state.get("anchor_sha"):
        return ("state.json at %s has no anchor_sha - full rebuild required" % state_path, None)
    return None, state


# --- output ------------------------------------------------------------------
def make_diff(new_anchor, old_anchor=None):
    return {
        "affected_areas": [],
        "changed_paths": [],
        "deleted_paths": [],
        "elements_reanchored": [],
        "external_systems_flagged": False,
        "history_rewritten": False,
        "new_anchor_sha": new_anchor,
        "new_paths_routed_to_misc": [],
        "old_anchor_sha": old_anchor,
        "orphaned_elements": [],
        "product_vision_flagged": False,
        "rebuild_required": False,
        "rebuild_reason": None,
        "renamed_paths": [],
        "unchanged": False,
    }


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_diff(out_path, diff):
    _atomic_write(out_path, json.dumps(diff, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


# --- main --------------------------------------------------------------------
def run(argv=None):
    ap = argparse.ArgumentParser(prog="diff_since.py")
    ap.add_argument("--repo", required=True, help="target repo path")
    ap.add_argument("--state", required=True, help="state.json from the previous build")
    ap.add_argument("--new-anchor", required=True, help="freshly pinned anchor SHA")
    ap.add_argument("--out", required=True, help="diff.json output path")
    args = ap.parse_args(argv)

    try:
        installed = _toolchain_likec4_version()
    except (OSError, ValueError, KeyError) as exc:
        print("diff_since.py: cannot read toolchain package.json: %s" % exc, file=sys.stderr)
        return 2

    # 1. State gate -> full rebuild with the condition named.
    reason, state = state_gate(args.state, installed)
    if reason is not None:
        diff = make_diff(args.new_anchor)
        diff["rebuild_required"] = True
        diff["rebuild_reason"] = reason
        write_diff(args.out, diff)
        print("diff_since.py: diff written: %s (rebuild required: %s)" % (args.out, reason))
        return 0

    old = state["anchor_sha"]
    diff = make_diff(args.new_anchor, old_anchor=old)

    if _git(args.repo, "rev-parse", "--git-dir").returncode != 0:
        print("diff_since.py: %s is not a git repository" % args.repo, file=sys.stderr)
        return 2
    if not _is_commit(args.repo, args.new_anchor):
        print(
            "diff_since.py: new anchor %s is not a resolvable commit in %s"
            % (args.new_anchor, args.repo),
            file=sys.stderr,
        )
        return 2

    # 2. History-rewrite safety: old anchor resolvable AND ancestor of new.
    if not _is_commit(args.repo, old) or not _is_ancestor(args.repo, old, args.new_anchor):
        diff["history_rewritten"] = True
        write_diff(args.out, diff)
        print("diff_since.py: diff written: %s (history rewritten - old anchor %s "
              "unresolvable or not an ancestor of %s)" % (args.out, old, args.new_anchor))
        return 0

    # 3. Unchanged short-circuit.
    if old == args.new_anchor:
        diff["unchanged"] = True
        write_diff(args.out, diff)
        print("diff_since.py: diff written: %s (unchanged - anchor %s)" % (args.out, old))
        return 0

    areas = state.get("areas") or []
    element_index = state.get("element_index") or {}
    if not isinstance(element_index, dict):
        element_index = {}

    # 4. Diff + classification.
    try:
        rows = _name_status(args.repo, old, args.new_anchor)
    except RuntimeError as exc:
        print("diff_since.py: %s" % exc, file=sys.stderr)
        return 2

    changed = set()
    deleted = set()
    renames = []          # (old_path, new_path, similarity)
    outside_new = []      # genuinely-new paths under no recorded area
    affected = set()
    touched = set()       # every path the diff mentions, for the pack flags

    for code, similarity, old_path, new_path in rows:
        if code == "D":
            deleted.add(old_path)
            touched.add(old_path)
            affected |= areas_of(old_path, areas)
        elif code in ("R", "C"):
            touched.add(old_path)
            touched.add(new_path)
            if code == "R":
                renames.append((old_path, new_path, similarity))
            old_areas = areas_of(old_path, areas)
            new_areas = areas_of(new_path, areas)
            if similarity is not None and similarity < 100:
                changed.add(new_path)
                affected |= new_areas
            if old_areas != new_areas:
                # The move crosses an area boundary: both sides need a look.
                affected |= old_areas | new_areas
        elif code == "A":
            touched.add(new_path)
            hit = areas_of(new_path, areas)
            if hit:
                changed.add(new_path)
                affected |= hit
            else:
                outside_new.append(new_path)
        else:
            # M, T (typechange), and anything unexpected: a content change.
            touched.add(new_path)
            changed.add(new_path)
            affected |= areas_of(new_path, areas)

    # Genuinely-new paths route to misc first (arch R3)...
    if outside_new:
        affected.add("misc")
    # ...unless the change is clustering-material: a new top-level directory
    # contributing >= NEW_DIR_REBUILD_THRESHOLD files outside every area.
    by_top_dir = {}
    for p in outside_new:
        if "/" in p:
            top = p.split("/", 1)[0]
            by_top_dir[top] = by_top_dir.get(top, 0) + 1
    for top in sorted(by_top_dir):
        if by_top_dir[top] >= NEW_DIR_REBUILD_THRESHOLD:
            diff["rebuild_required"] = True
            diff["rebuild_reason"] = (
                "new directory %s/ adds %d files outside every recorded area - "
                "clustering-material change, full rebuild required"
                % (top, by_top_dir[top])
            )
            break

    # Pack flags: manifest-table paths always flag external-systems; README/
    # docs/CLAUDE.md flag product-vision.
    for p in sorted(touched):
        if path_matches_manifest(p):
            diff["external_systems_flagged"] = True
        if path_flags_product_vision(p):
            diff["product_vision_flagged"] = True

    # Orphans: elements whose EVERY indexed path was deleted. Renamed paths
    # survive (they moved), so a rename never orphans its element.
    orphaned = []
    for el_id in sorted(element_index):
        paths = element_index.get(el_id)
        if isinstance(paths, list) and paths and all(p in deleted for p in paths):
            orphaned.append(el_id)

    diff["changed_paths"] = sorted(changed)
    diff["deleted_paths"] = sorted(deleted)
    diff["renamed_paths"] = [
        {"from": o, "similarity": s, "to": n}
        for o, n, s in sorted(renames)
    ]
    diff["affected_areas"] = sorted(affected)
    diff["orphaned_elements"] = orphaned
    diff["new_paths_routed_to_misc"] = sorted(outside_new)

    # 5. On the patch path the baseline model must be loadable (merge --patch
    # reads it as its baseline); renamed files get their element anchors
    # updated IN PLACE there so continuity survives without re-investigation.
    if not diff["rebuild_required"]:
        model_path = os.path.join(
            os.path.dirname(os.path.abspath(args.state)), "model.json"
        )
        try:
            with open(model_path, "r", encoding="utf-8") as fh:
                model = json.load(fh)
        except (OSError, ValueError):
            diff["rebuild_required"] = True
            diff["rebuild_reason"] = (
                "baseline model.json missing or unparseable at %s - full "
                "rebuild required" % model_path
            )
            model = None
        if model is not None and renames:
            rename_map = {o: n for o, n, _s in renames}
            reanchored = []
            for el in model.get("elements") or []:
                hit = False
                for f in el.get("files") or []:
                    p = f.get("path")
                    if p in rename_map:
                        f["path"] = rename_map[p]
                        hit = True
                if hit and el.get("id"):
                    reanchored.append(el["id"])
            if reanchored:
                _atomic_write(model_path, json.dumps(model, indent=2) + "\n")
                diff["elements_reanchored"] = sorted(reanchored)

    write_diff(args.out, diff)
    if diff["rebuild_required"]:
        print("diff_since.py: diff written: %s (rebuild required: %s)"
              % (args.out, diff["rebuild_reason"]))
    else:
        print("diff_since.py: diff written: %s (%d changed, %d deleted, %d renamed; "
              "affected areas: %s%s%s)"
              % (args.out, len(diff["changed_paths"]), len(diff["deleted_paths"]),
                 len(diff["renamed_paths"]),
                 ", ".join(diff["affected_areas"]) or "none",
                 "; external-systems flagged" if diff["external_systems_flagged"] else "",
                 "; product-vision flagged" if diff["product_vision_flagged"] else ""))
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
