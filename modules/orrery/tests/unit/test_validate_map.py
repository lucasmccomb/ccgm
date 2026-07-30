"""Unit tests for validate_map.py (plan Epic 3): the 7 ordered checks."""

import json
import os

import pytest

from conftest import FIXTURES_DIR, FRAGMENTS_DIR, make_git_repo, read_json, write_json

BROKEN_MODEL_DIR = os.path.join(FIXTURES_DIR, "broken-model")

REPO_FILES = {
    "README.md": "fixture readme\n",
    "api/worker.js": "// worker\n" * 40,
}


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_git_repo(tmp_path_factory.mktemp("vrepo"), REPO_FILES)


def model_for(sha, elements=None, relations=None):
    return {
        "meta": {
            "slug": "fixture",
            "repo_title": "fixture",
            "remote_url": "https://github.com/acme-fixture/fixture.git",
            "default_ref": "main",
            "anchor_sha": sha,
            "visibility": "public",
            "generated_at": "2026-01-01T00:00:00Z",
            "source_links": "github",
            "areas": [{"id": "api", "title": "api", "root_paths": ["api"]}],
        },
        "elements": elements if elements is not None else [
            {"id": "system", "kind": "system", "title": "Fixture",
             "summary": "The fixture system.", "files": [{"path": "README.md"}]},
            {"id": "worker", "kind": "component", "title": "Worker", "parent": "system",
             "summary": "The worker.", "files": [{"path": "api/worker.js", "start_line": 1, "end_line": 10}]},
        ],
        "relations": relations if relations is not None else [],
    }


def run_validate(validate_mod, tmp_path, model, repo_sha, model_dir=None):
    repo_path, sha = repo_sha
    model_path = os.path.join(str(tmp_path), "model.json")
    write_json(model_path, model)
    code = validate_mod.run([
        "--model", model_path,
        "--model-dir", model_dir or str(tmp_path),
        "--repo", repo_path,
        "--anchor-sha", sha,
    ])
    errors_path = os.path.join(str(tmp_path), "errors.json")
    errors = read_json(errors_path) if os.path.exists(errors_path) else None
    return code, errors


def checks(errors):
    return sorted({e["check"] for e in errors})


# --- green path (runs the real check 7 on real emitted DSL) -----------------

def test_valid_model_all_seven_checks_green(validate_mod, emit_mod, tmp_path, repo):
    repo_path, sha = repo
    model = model_for(sha, elements=model_for(sha)["elements"] + [
        # the actor exemption (section 3.3): no files, no external_url,
        # non-empty description -- must PASS check 2
        {"id": "shopper", "kind": "actor", "title": "Shopper",
         "summary": "A customer.", "description": "Evidence: the README describes a retail flow."},
    ])
    model_path = os.path.join(str(tmp_path), "model.json")
    write_json(model_path, model)
    assert emit_mod.run(["--model", model_path, "--out-dir", str(tmp_path)]) == 0
    # a stale errors.json from a previous red run must not outlive success
    stale = os.path.join(str(tmp_path), "errors.json")
    write_json(stale, [{"check": "stale", "element_id": None, "path": None, "message": "old"}])
    code = validate_mod.run([
        "--model", model_path,
        "--model-dir", os.path.join(str(tmp_path), "model"),
        "--repo", repo_path,
        "--anchor-sha", sha,
    ])
    assert code == 0
    assert not os.path.exists(stale)


# --- check 1: schema --------------------------------------------------------

def test_schema_invalid_kind_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["kind"] = "microservice"
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["schema"]


def test_schema_missing_meta_field_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    del model["meta"]["anchor_sha"]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert any("anchor_sha" in e["message"] for e in errors)


def test_schema_absolute_path_rejected(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "/etc/passwd"}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert any(e["check"] == "schema" and e["path"] == "/etc/passwd" for e in errors)


def test_schema_title_over_max_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["title"] = "x" * 61
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert any("maxLength" in e["message"] for e in errors)


# --- check 2: evidence + the actor exemption --------------------------------

def test_element_without_files_or_external_url_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"].append({"id": "bare", "kind": "component",
                              "title": "Bare", "summary": "No evidence."})
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert [e["element_id"] for e in errors] == ["bare"]
    assert checks(errors) == ["evidence"]


def test_actor_without_description_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"].append({"id": "ghost_actor", "kind": "actor",
                              "title": "Ghost", "summary": "No prose evidence."})
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert errors[0]["element_id"] == "ghost_actor"
    assert "description" in errors[0]["message"]


# --- check 3: traversal + git-native existence ------------------------------

def test_traversal_path_rejected(validate_mod, tmp_path, repo):
    # The checked-in traversal fixture: no leading slash (passes the schema
    # pattern) but climbs out with .. segments.
    fixture_el = read_json(os.path.join(FRAGMENTS_DIR, "traversal.json"))["elements"][0]
    model = model_for(repo[1])
    model["elements"].append(fixture_el)
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert [(e["check"], e["path"]) for e in errors] == [("path", "../../../etc/passwd")]
    assert ".. segment" in errors[0]["message"]


def test_nonexistent_path_rejected_via_git(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/fabricated.js"}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert errors[0]["check"] == "path"
    assert errors[0]["path"] == "api/fabricated.js"
    assert "not present at anchor sha" in errors[0]["message"]


def test_control_char_path_rejected(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/\x01worker.js"}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert errors[0]["check"] == "path"
    assert "control" in errors[0]["message"]


# --- check 4: line ranges ---------------------------------------------------

def test_inverted_range_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/worker.js", "start_line": 10, "end_line": 5}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["range"]


def test_end_without_start_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/worker.js", "end_line": 5}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert errors[0]["message"] == "end_line without start_line"


def test_end_line_beyond_eof_fails(validate_mod, tmp_path, repo):
    # Stage-2 finding 5: a #L link past the blob's real EOF is a
    # hallucinated citation. README.md is 1 line in the throwaway repo.
    model = model_for(repo[1])
    model["elements"][0]["files"] = [{"path": "README.md", "start_line": 1, "end_line": 5}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["range"]
    assert "exceeds the blob's 1 line(s)" in errors[0]["message"]
    assert errors[0]["path"] == "README.md"


def test_start_line_beyond_eof_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/worker.js", "start_line": 99}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["range"]
    assert "exceeds the blob's 40 line(s)" in errors[0]["message"]


# --- check 5: relation endpoints --------------------------------------------

def test_dangling_relation_endpoint_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1], relations=[
        {"from": "worker", "to": "phantom", "summary": "calls into the void"},
    ])
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["relation"]
    assert "phantom" in errors[0]["message"]


# --- check 6: parents -------------------------------------------------------

def test_missing_parent_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["parent"] = "nonexistent"
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert checks(errors) == ["parent"]


def test_parent_cycle_fails(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"] = [
        {"id": "a", "kind": "component", "title": "A", "summary": "s",
         "parent": "b", "files": [{"path": "README.md"}]},
        {"id": "b", "kind": "component", "title": "B", "summary": "s",
         "parent": "a", "files": [{"path": "README.md"}]},
    ]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    assert any(e["check"] == "parent" and "cycle" in e["message"] for e in errors)


# --- check 7: likec4 gate ---------------------------------------------------

def test_likec4_errors_merged_into_errors_json(validate_mod, tmp_path, repo):
    # Checks 1-6 green (valid model.json against the real repo), but the DSL
    # dir is the checked-in broken-model fixture: check 7 must merge the
    # structured likec4 errors and fail.
    model = model_for(repo[1])
    code, errors = run_validate(validate_mod, tmp_path, model, repo,
                                model_dir=BROKEN_MODEL_DIR)
    assert code == 1
    assert errors, "expected merged likec4 errors"
    assert checks(errors) == ["likec4"]
    assert all(e["element_id"] is None for e in errors)
    assert any(e["path"] for e in errors)


# --- errors.json contract ---------------------------------------------------

def test_errors_json_shape(validate_mod, tmp_path, repo):
    model = model_for(repo[1])
    model["elements"][1]["files"] = [{"path": "api/fabricated.js"}]
    code, errors = run_validate(validate_mod, tmp_path, model, repo)
    assert code == 1
    for e in errors:
        assert sorted(e.keys()) == sorted(["check", "element_id", "path", "message"])
