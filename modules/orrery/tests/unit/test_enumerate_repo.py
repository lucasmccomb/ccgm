"""Unit tests for enumerate_repo.py (plan Epic 2, section 3.5a).

Hermetic: fixture-repo files are materialized into throwaway temp git repos.
Materialization reads the fixture from the ccgm repo's git INDEX (git ls-files
plus git cat-file), never the checkout: the fixture tracks both web/ and Web/,
which a case-insensitive filesystem collapses into one on-disk directory. For
the same reason the temp repos are built with git index plumbing
(update-index --index-info), so both cases exist as distinct tracked paths on
every platform.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[2]
SCRIPT = MODULE_DIR / "skills" / "orrery" / "scripts" / "enumerate_repo.py"
CCGM_ROOT = MODULE_DIR.parents[1]
FIXTURE_PREFIX = "modules/orrery/tests/fixtures/fixture-repo/"

AREA_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Import the script as a module: proves the Epic 5 import contract
# (diff_since.py imports MANIFEST_TABLE from here) and exposes the sanitizer.
_spec = importlib.util.spec_from_file_location("enumerate_repo", SCRIPT)
er = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(er)


# --- helpers -----------------------------------------------------------------
def git_env(tmp_path):
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig-does-not-exist"),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        }
    )
    return env


def _fixture_files():
    """{relative path: bytes} for every fixture-repo file, from the ccgm
    index (the checkout is case-folded on macOS and cannot be trusted)."""
    raw = subprocess.run(
        ["git", "-C", str(CCGM_ROOT), "ls-files", "-z", "--", FIXTURE_PREFIX.rstrip("/")],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    files = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        path = entry.decode("utf-8")
        content = subprocess.run(
            ["git", "-C", str(CCGM_ROOT), "cat-file", "blob", ":0:%s" % path],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        files[path[len(FIXTURE_PREFIX):]] = content
    assert files, "fixture-repo is empty - materialization is broken"
    return files


_FIXTURE_CACHE = None


def fixture_files():
    global _FIXTURE_CACHE
    if _FIXTURE_CACHE is None:
        _FIXTURE_CACHE = _fixture_files()
    return dict(_FIXTURE_CACHE)


def commit_tree(repo, files, env):
    """Create a git repo whose ONE commit tracks exactly `files`, via index
    plumbing so case-colliding paths (web/ + Web/) survive any filesystem."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        env=env,
        check=True,
        capture_output=True,
    )
    oid_by_content = {}
    for content in set(files.values()):
        oid = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=content,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode("ascii").strip()
        oid_by_content[content] = oid
    index_info = b"".join(
        b"100644 %s 0\t%s\n"
        % (oid_by_content[content].encode("ascii"), path.encode("utf-8"))
        for path, content in sorted(files.items())
    )
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--add", "--index-info"],
        input=index_info,
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture"],
        env=env,
        check=True,
        capture_output=True,
    )
    return repo


def run_census(tmp_path, files, name="repo"):
    env = git_env(tmp_path)
    repo = commit_tree(tmp_path / name, files, env)
    out = tmp_path / ("%s-census.json" % name)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--worktree", str(repo), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    census = json.loads(out.read_bytes())
    # Blanket acceptance criterion: EVERY emitted area id is element-id-legal.
    for area in census["areas"]:
        assert AREA_ID_RE.match(area["id"]), "illegal area id %r" % area["id"]
    assert census["id_namespace"]["area_ids"] == sorted(a["id"] for a in census["areas"])
    return census, out


def synth(dirs, root_files=None):
    """{path: content} with `count` distinct small files per directory."""
    files = {}
    for d, count in dirs.items():
        for i in range(count):
            files["%s/f%03d.js" % (d, i)] = b"// synthetic\n"
    for f in root_files or []:
        files[f] = b"# root\n"
    return files


def area_by_id(census, area_id):
    matches = [a for a in census["areas"] if a["id"] == area_id]
    assert len(matches) == 1, "expected exactly one area %r" % area_id
    return matches[0]


def id_of_root_path(census, path):
    matches = [a for a in census["areas"] if a["root_paths"] == [path]]
    assert len(matches) == 1, "expected exactly one area rooted at %r" % path
    return matches[0]["id"]


# --- fixture census ----------------------------------------------------------
def test_fixture_census_areas(tmp_path):
    files = fixture_files()
    # The materialized index must carry BOTH cases distinctly.
    assert any(p.startswith("web/") for p in files)
    assert any(p.startswith("Web/") for p in files)

    census, _ = run_census(tmp_path, files)

    # Candidates: many (32) and web (12) survive; .github, 2fa, api, db,
    # my-app, Web are under 5 files and merge into misc with the root files.
    assert census["id_namespace"]["area_ids"] == ["many", "misc", "web"]
    assert census["bucketing"] == {
        "applied": False,
        "bucket_count": 0,
        "candidate_count": 2,
    }

    web = area_by_id(census, "web")
    assert web["bucketed"] is False
    assert web["root_paths"] == ["web"]
    assert web["file_count"] == sum(1 for p in files if p.startswith("web/"))

    many = area_by_id(census, "many")
    assert many["file_count"] == sum(1 for p in files if p.startswith("many/"))

    misc = area_by_id(census, "misc")
    misc_paths = {m["path"] for m in misc["members"]}
    assert {".github", "2fa", "Web", "api", "db", "my-app"} <= misc_paths
    assert {".env.example", "README.md", "package.json"} <= misc_paths

    assert census["tree"]["tracked_files"] == len(files)
    assert census["id_namespace"]["reserved_ids"] == ["misc", "system", "users"]
    assert census["id_namespace"]["reserved_bucket_ids"][0] == "bucket_01"
    assert census["id_namespace"]["reserved_bucket_ids"][-1] == "bucket_24"
    assert census["id_namespace"]["wave0_owned_kinds"] == [
        "actor",
        "container",
        "external",
    ]


def test_fixture_census_manifests_entrypoints_languages(tmp_path):
    files = fixture_files()
    census, _ = run_census(tmp_path, files)

    hits = {(m["kind"], m["path"]) for m in census["manifests"]}
    assert ("wrangler", "api/wrangler.toml") in hits
    assert ("env-example", ".env.example") in hits
    assert ("github-workflow", ".github/workflows/deploy.yml") in hits
    assert ("migrations", "db/migrations") in hits
    assert ("package.json", "package.json") in hits

    pkg = [m for m in census["manifests"] if m["kind"] == "package.json"][0]
    assert "stripe" in pkg["dependencies"]

    assert "api/src/worker.js" in census["entrypoints"]
    assert "web/src/main.ts" in census["entrypoints"]

    assert census["languages"]["js"] >= 1
    assert census["languages"]["ts"] >= 1


def test_census_byte_identical_across_two_runs(tmp_path):
    files = fixture_files()
    _, out1 = run_census(tmp_path, files, name="run1")
    _, out2 = run_census(tmp_path, files, name="run2")
    assert out1.read_bytes() == out2.read_bytes()


# --- bucketing (section 3.5a step 3, arch C2) --------------------------------
def test_many_tree_buckets_balanced(tmp_path):
    # The fixture's many/ tree carries 16 sibling dirs of 2 files each. Padded
    # to 5 files per sibling (the merge threshold would otherwise fold all 16
    # into misc), the tree alone makes many/ hold >60% of tracked files, so it
    # expands into 16 sibling candidates and bucketing engages.
    files = {p: c for p, c in fixture_files().items() if p.startswith("many/")}
    siblings = sorted({p.split("/")[1] for p in files})
    assert len(siblings) == 16
    for sub in siblings:
        for i in range(3):
            files["many/%s/pad%d.js" % (sub, i)] = b"// pad\n"

    census, _ = run_census(tmp_path, files)

    assert census["bucketing"]["applied"] is True
    assert census["bucketing"]["candidate_count"] == 16
    buckets = census["areas"]
    assert 0 < len(buckets) <= 24
    assert census["bucketing"]["bucket_count"] == len(buckets)
    # Target-12 rule: 16 candidates pack into 12 buckets.
    assert len(buckets) == 12
    assert [b["id"] for b in buckets] == ["bucket_%02d" % i for i in range(1, 13)]
    for b in buckets:
        assert b["bucketed"] is True
        assert b["members"], "bucket without members"
        assert b["root_paths"] == [m["path"] for m in b["members"]]

    # Membership: every candidate appears exactly once, and concatenating the
    # buckets in id order reproduces alphabetical sibling order (adjacency).
    concat = [m["path"] for b in buckets for m in b["members"]]
    assert concat == ["many/%s" % s for s in siblings]

    # Balance: 16 candidates of 5 files into 12 buckets has an optimal max of
    # 10 files (4 buckets of two siblings, 8 of one).
    sizes = [b["file_count"] for b in buckets]
    assert max(sizes) == 10
    assert min(sizes) == 5


# --- expansion (section 3.5a step 1) -----------------------------------------
def test_expansion_over_60_percent(tmp_path):
    dirs = {"big/sub%02d" % i: 6 for i in range(10)}
    dirs["api"] = 6
    files = synth(dirs, root_files=["README.md", "notes.txt"])
    census, _ = run_census(tmp_path, files)

    ids = census["id_namespace"]["area_ids"]
    assert "big_sub00" in ids
    assert "big_sub09" in ids
    assert "api" in ids
    assert "big" not in ids  # expanded away
    assert "misc" in ids  # the two root files
    assert census["bucketing"]["applied"] is False


def test_no_expansion_at_exactly_60_percent(tmp_path):
    # 60 of 100 files is not >60%: strict inequality, no expansion.
    files = synth({"big/inner": 60, "other": 40})
    census, _ = run_census(tmp_path, files)
    assert "big" in census["id_namespace"]["area_ids"]
    assert "big_inner" not in census["id_namespace"]["area_ids"]


# --- split (section 3.5a step 2) ---------------------------------------------
def test_split_over_400_files(tmp_path):
    files = synth({"big/sub1": 300, "big/sub2": 150, "other": 400})
    census, _ = run_census(tmp_path, files)

    ids = census["id_namespace"]["area_ids"]
    # big (450) splits by subdirectory; other (exactly 400) does not.
    assert "big_sub1" in ids
    assert "big_sub2" in ids
    assert "big" not in ids
    assert "other" in ids


# --- merge (section 3.5a step 2) ---------------------------------------------
def test_merge_under_5_files_into_misc(tmp_path):
    files = synth({"kept": 5, "tiny": 4})
    census, _ = run_census(tmp_path, files)

    assert census["id_namespace"]["area_ids"] == ["kept", "misc"]
    misc = area_by_id(census, "misc")
    assert [m["path"] for m in misc["members"]] == ["tiny"]
    assert misc["file_count"] == 4


# --- area-id rule (section 3.5a step 5, FROZEN) ------------------------------
def test_area_id_adversarial_matrix(tmp_path):
    files = synth(
        {
            ".github": 5,
            "2fa": 5,
            "Web": 5,
            "my-app": 5,
            "src.new": 5,
            "web": 5,
        }
    )
    census, _ = run_census(tmp_path, files)

    # Candidate order is byte-sorted paths: ".github" < "2fa" < "Web" <
    # "my-app" < "src.new" < "web", so Web claims "web" first and lowercase
    # web/ takes the deterministic collision suffix.
    assert id_of_root_path(census, ".github") == "a__github"
    assert id_of_root_path(census, "2fa") == "a_2fa"
    assert id_of_root_path(census, "Web") == "web"
    assert id_of_root_path(census, "my-app") == "my_app"
    assert id_of_root_path(census, "src.new") == "src_new"
    assert id_of_root_path(census, "web") == "web_2"


def test_fixture_web_case_collision_resolves_deterministically(tmp_path):
    # The fixture repo itself carries both web/ and Web/. Padded above the
    # merge threshold so both survive as areas, the collision must resolve
    # the same way on every platform and every run.
    files = fixture_files()
    for i in range(3):
        files["Web/pad%d.js" % i] = b"// pad\n"
    census1, out1 = run_census(tmp_path, files, name="one")
    census2, out2 = run_census(tmp_path, files, name="two")

    assert id_of_root_path(census1, "Web") == "web"
    assert id_of_root_path(census1, "web") == "web_2"
    assert out1.read_bytes() == out2.read_bytes()


def test_area_id_collision_my_app_my_app(tmp_path):
    files = synth({"my-app": 5, "my_app": 5})
    census, _ = run_census(tmp_path, files)
    # Byte order: "my-app" (hyphen 0x2D) precedes "my_app" (underscore 0x5F).
    assert id_of_root_path(census, "my-app") == "my_app"
    assert id_of_root_path(census, "my_app") == "my_app_2"


def test_area_id_long_and_unicode_names(tmp_path):
    long_name = "x" * 200
    files = synth({long_name: 5, "café-zone": 5})
    census, _ = run_census(tmp_path, files)
    assert id_of_root_path(census, long_name) == "x" * 24
    assert id_of_root_path(census, "café-zone") == "caf_zone"


def test_sanitize_area_id_unit_cases():
    taken = set(er.RESERVED_IDS) | set(er.RESERVED_BUCKET_IDS)
    assert er.sanitize_area_id("my-app", taken) == "my_app"
    assert er.sanitize_area_id(".github", taken) == "a__github"
    assert er.sanitize_area_id("2fa", taken) == "a_2fa"
    assert er.sanitize_area_id("Web", taken) == "web"
    assert er.sanitize_area_id("web", taken) == "web_2"
    assert er.sanitize_area_id("src.new", taken) == "src_new"
    # A reserved id is collision-suffixed, never claimed.
    assert er.sanitize_area_id("misc", taken) == "misc_2"
    # A name with no [a-z0-9] at all still yields a legal id.
    assert er.sanitize_area_id("...", taken) == "a"
    for area_id in taken:
        if area_id.startswith("bucket_") or area_id in er.RESERVED_IDS:
            continue
        assert AREA_ID_RE.match(area_id)


# --- manifest table import contract (Epic 5) ---------------------------------
def test_manifest_table_is_importable_constant():
    assert isinstance(er.MANIFEST_TABLE, tuple)
    patterns = {(mtype, pattern) for _kind, mtype, pattern in er.MANIFEST_TABLE}
    expected = {
        ("basename", "package.json"),
        ("basename", "pnpm-workspace.yaml"),
        ("basename", "requirements.txt"),
        ("basename", "pyproject.toml"),
        ("basename", "Gemfile"),
        ("basename", "go.mod"),
        ("basename", "Cargo.toml"),
        ("basename", "Package.swift"),
        ("basename", "composer.json"),
        ("basename", "wrangler.toml"),
        ("basename", "vercel.json"),
        ("basename", "netlify.toml"),
        ("basename", "fly.toml"),
        ("basename", "Dockerfile"),
        ("basename", "docker-compose.yml"),
        ("suffix", ".tf"),
        ("glob", ".github/workflows/*.yml"),
        ("basename", ".env.example"),
        ("dir", "supabase"),
        ("dir", "prisma"),
        ("dir", "drizzle"),
        ("dir", "migrations"),
    }
    assert patterns == expected
    for row in er.MANIFEST_TABLE:
        assert len(row) == 3


def test_manifest_suffix_and_dir_kinds(tmp_path):
    files = synth({"infra": 4, "supabase": 4, "app": 5})
    files["infra/main.tf"] = b"# tf\n"
    files["supabase/config.toml"] = b"# supabase\n"
    census, _ = run_census(tmp_path, files)

    hits = {(m["kind"], m["path"]) for m in census["manifests"]}
    assert ("terraform", "infra/main.tf") in hits
    assert ("supabase", "supabase") in hits


# --- CLI error path ----------------------------------------------------------
def test_missing_worktree_exits_2(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--worktree",
            str(tmp_path / "nope"),
            "--out",
            str(tmp_path / "census.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not a git worktree" in result.stderr
