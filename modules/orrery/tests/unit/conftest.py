"""Shared helpers for the orrery Epic 3 unit tests.

The pipeline scripts live in skills/orrery/scripts/ and are not a package;
they are loaded by file path. Throwaway git repos bypass any machine-level
hooks (core.hooksPath) because the fixture repo deliberately contains
secret-SHAPED fake values that a gitleaks pre-commit hook would reject.
"""

import importlib.util
import json
import os
import subprocess

import pytest

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(MODULE_DIR, "skills", "orrery", "scripts")
FIXTURES_DIR = os.path.join(MODULE_DIR, "tests", "fixtures")
FRAGMENTS_DIR = os.path.join(FIXTURES_DIR, "fragments")

ANCHOR_SHA = "1234567890abcdef1234567890abcdef12345678"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def merge_mod():
    return _load("merge_fragments")


@pytest.fixture(scope="session")
def emit_mod():
    return _load("emit_likec4")


@pytest.fixture(scope="session")
def validate_mod():
    return _load("validate_map")


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def make_anchor(remote_url="https://github.com/acme-fixture/acme-shop.git",
                no_remote=False, anchor_sha=ANCHOR_SHA):
    return {
        "repo_path": "/tmp/fixture/acme-shop",
        "remote_url": remote_url,
        "default_ref": "main",
        "anchor_sha": anchor_sha,
        "worktree": "/tmp/fixture/worktree",
        "slug": "acme-shop",
        "behind": False,
        "dirty": False,
        "no_remote": no_remote,
        "visibility": "public",
    }


def make_census():
    return {"areas": [
        {"id": "web", "title": "Web", "root_paths": ["Web"]},
        {"id": "api", "title": "api", "root_paths": ["api"]},
        {"id": "db", "title": "db", "root_paths": ["db"]},
    ]}


def materialize_area(tmpl_name, area_id, dest_dir):
    """Substitute the @AREA_ID@ placeholder token (the plan's substitutable
    <area_id>__ prefix) and write fragments/area-{id}.json."""
    with open(os.path.join(FRAGMENTS_DIR, tmpl_name), "r", encoding="utf-8") as fh:
        text = fh.read().replace("@AREA_ID@", area_id)
    dest = os.path.join(dest_dir, "area-%s.json" % area_id)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    return dest


def run_merge(merge_mod, tmp_path, packs, fragments=None, anchor=None, census=None,
              extra_args=None, env_generated_at="2026-01-01T00:00:00Z"):
    """Drive merge_fragments.run() against a scratch layout; returns
    (exit_code, model_or_None, report)."""
    frag_dir = os.path.join(str(tmp_path), "fragments")
    os.makedirs(frag_dir, exist_ok=True)
    for name, frag in (fragments or {}).items():
        if isinstance(frag, str):
            with open(os.path.join(frag_dir, name), "w", encoding="utf-8") as fh:
                fh.write(frag)
        else:
            write_json(os.path.join(frag_dir, name), frag)
    anchor_path = os.path.join(str(tmp_path), "anchor.json")
    census_path = os.path.join(str(tmp_path), "census.json")
    write_json(anchor_path, anchor or make_anchor())
    write_json(census_path, census or make_census())
    out_path = os.path.join(str(tmp_path), "model.json")
    argv = [
        "--fragments-dir", frag_dir,
        "--packs", ",".join(packs),
        "--census", census_path,
        "--anchor", anchor_path,
        "--out", out_path,
    ] + (extra_args or [])
    old = os.environ.get("ORRERY_GENERATED_AT")
    os.environ["ORRERY_GENERATED_AT"] = env_generated_at
    try:
        code = merge_mod.run(argv)
    finally:
        if old is None:
            os.environ.pop("ORRERY_GENERATED_AT", None)
        else:
            os.environ["ORRERY_GENERATED_AT"] = old
    model = read_json(out_path) if os.path.exists(out_path) else None
    report_path = os.path.join(str(tmp_path), "merge-report.json")
    report = read_json(report_path) if os.path.exists(report_path) else None
    return code, model, report


def make_git_repo(tmp_path, files):
    """Throwaway git repo with the given {relpath: content} files.
    Returns (repo_path, head_sha). Hooks bypassed (see module docstring)."""
    repo = os.path.join(str(tmp_path), "repo")
    os.makedirs(repo, exist_ok=True)
    for rel, content in files.items():
        full = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    def git(*args):
        subprocess.run(
            ["git", "-C", repo, "-c", "user.name=orrery",
             "-c", "user.email=orrery@example.invalid",
             "-c", "core.hooksPath=/dev/null"] + list(args),
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "fixture", "--no-verify")
    sha = subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return repo, sha
