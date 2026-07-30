"""Unit tests for diff_since.py (plan Epic 5).

Every case runs against a real two-commit throwaway git repo (hermetic,
hooks bypassed via core.hooksPath) plus a scratch orrery output dir carrying
state.json and a baseline model.json - the same layout the update flow
resolves under $ORRERY_HOME/{slug}.

Covered per the plan: path -> element/area mapping; delete/orphan; rename
with -M (anchor updated in place); unchanged short-circuit; misc routing;
rebuild_required on a new 5-file directory; history rewrite via reset --hard
divergence; manifest-path -> external-systems flag; README -> product-vision
flag; and the deterministic state gate diff_since encodes for the SKILL's
update flow (missing/unparseable state, schema_version != 1,
likec4_version != installed toolchain) - each with its own message.
"""

import importlib.util
import json
import os
import subprocess

import pytest

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(MODULE_DIR, "skills", "orrery", "scripts")
TOOLCHAIN_PKG = os.path.join(SCRIPTS_DIR, "toolchain", "package.json")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def diff_mod():
    return _load("diff_since")


@pytest.fixture(scope="session")
def installed_likec4():
    with open(TOOLCHAIN_PKG, "r", encoding="utf-8") as fh:
        return json.load(fh)["dependencies"]["likec4"]


# --- helpers -----------------------------------------------------------------
def git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, "-c", "user.name=orrery",
         "-c", "user.email=orrery@example.invalid",
         "-c", "core.hooksPath=/dev/null"] + list(args),
        check=True, capture_output=True, text=True,
    ).stdout


def make_repo(tmp_path, files):
    """Throwaway repo with an initial commit of `files`. Returns repo path."""
    repo = os.path.join(str(tmp_path), "repo")
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo],
                   check=True, capture_output=True)
    write_files(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "v1", "--no-verify")
    return repo


def write_files(repo, files):
    for rel, content in files.items():
        full = os.path.join(repo, rel)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)


def commit_all(repo, msg="v2"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg, "--no-verify")
    return head(repo)


def head(repo):
    return git(repo, "rev-parse", "HEAD").strip()


V1_FILES = {
    "web/src/app.ts": "export const app = 1;\n",
    "web/src/cart.ts": "export const cart = [];\n",
    "api/worker.js": "export default { fetch() {} };\n",
    "db/schema.sql": "CREATE TABLE orders (id integer);\n",
    "package.json": '{"name": "fixture", "dependencies": {}}\n',
    "README.md": "# fixture\n",
}

AREAS = [
    {"id": "web", "root_paths": ["web"]},
    {"id": "misc", "root_paths": ["api", "db", "package.json", "README.md"]},
]

ELEMENT_INDEX = {
    "web__app": ["web/src/app.ts"],
    "web__cart": ["web/src/cart.ts"],
    "misc__worker": ["api/worker.js"],
    "misc__schema": ["db/schema.sql"],
    "misc__multi": ["api/worker.js", "db/schema.sql"],
}


def make_out(tmp_path, anchor_sha, installed_likec4, *, schema_version=1,
             likec4_version=None, element_index=None, areas=None,
             write_state=True, write_model=True, model_elements=None):
    """Scratch orrery out dir: state.json + baseline model.json."""
    out = os.path.join(str(tmp_path), "out")
    os.makedirs(out, exist_ok=True)
    if write_state:
        state = {
            "schema_version": schema_version,
            "slug": "fixture",
            "anchor_sha": anchor_sha,
            "likec4_version": likec4_version if likec4_version is not None
            else installed_likec4,
            "areas": areas if areas is not None else AREAS,
            "element_index": element_index if element_index is not None
            else ELEMENT_INDEX,
        }
        with open(os.path.join(out, "state.json"), "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    if write_model:
        idx = element_index if element_index is not None else ELEMENT_INDEX
        elements = model_elements if model_elements is not None else [
            {"id": el_id, "kind": "component", "title": el_id,
             "files": [{"path": p} for p in paths]}
            for el_id, paths in sorted(idx.items())
        ]
        with open(os.path.join(out, "model.json"), "w", encoding="utf-8") as fh:
            json.dump({"elements": elements, "relations": []}, fh, indent=2)
    return out


def run_diff(diff_mod, repo, out, new_anchor):
    diff_path = os.path.join(out, "diff.json")
    code = diff_mod.run([
        "--repo", repo,
        "--state", os.path.join(out, "state.json"),
        "--new-anchor", new_anchor,
        "--out", diff_path,
    ])
    diff = None
    if os.path.exists(diff_path):
        with open(diff_path, "r", encoding="utf-8") as fh:
            diff = json.load(fh)
    return code, diff


ALL_FIELDS = {
    "affected_areas", "changed_paths", "deleted_paths", "elements_reanchored",
    "external_systems_flagged", "history_rewritten", "new_anchor_sha",
    "new_paths_routed_to_misc", "old_anchor_sha", "orphaned_elements",
    "product_vision_flagged", "rebuild_required", "rebuild_reason",
    "renamed_paths", "unchanged",
}


# --- single-source manifest table --------------------------------------------
def test_manifest_table_imported_from_enumerate_repo(diff_mod):
    enum_mod = _load("enumerate_repo")
    assert diff_mod.MANIFEST_TABLE == enum_mod.MANIFEST_TABLE
    # Never duplicated: the table's rows must not be re-declared in the source.
    src = open(os.path.join(SCRIPTS_DIR, "diff_since.py"), encoding="utf-8").read()
    assert "pnpm-workspace.yaml" not in src, (
        "diff_since.py re-declares manifest rows instead of importing MANIFEST_TABLE"
    )


# --- path -> element/area mapping --------------------------------------------
def test_changed_path_maps_to_area(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"web/src/app.ts": "export const app = 2;\n"})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert set(diff) == ALL_FIELDS
    assert diff["changed_paths"] == ["web/src/app.ts"]
    assert diff["affected_areas"] == ["web"]
    assert diff["deleted_paths"] == []
    assert diff["orphaned_elements"] == []
    assert diff["unchanged"] is False
    assert diff["history_rewritten"] is False
    assert diff["rebuild_required"] is False
    assert diff["external_systems_flagged"] is False
    assert diff["product_vision_flagged"] is False
    assert diff["old_anchor_sha"] == v1
    assert diff["new_anchor_sha"] == v2


# --- delete / orphan ---------------------------------------------------------
def test_delete_orphans_element_whose_every_path_died(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    git(repo, "rm", "-q", "web/src/cart.ts")
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["deleted_paths"] == ["web/src/cart.ts"]
    assert diff["orphaned_elements"] == ["web__cart"]
    assert diff["affected_areas"] == ["web"]


def test_partial_delete_does_not_orphan(diff_mod, installed_likec4, tmp_path):
    """misc__multi anchors two paths; deleting one leaves it alive."""
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    git(repo, "rm", "-q", "db/schema.sql")
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert "misc__multi" not in diff["orphaned_elements"]
    # misc__schema anchored ONLY the deleted path: orphaned.
    assert diff["orphaned_elements"] == ["misc__schema"]


# --- rename with -M: anchor updated in place ---------------------------------
def test_rename_updates_owning_element_anchor_in_place(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    git(repo, "mv", "web/src/cart.ts", "web/src/basket.ts")
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["renamed_paths"] == [
        {"from": "web/src/cart.ts", "similarity": 100, "to": "web/src/basket.ts"}
    ]
    assert diff["elements_reanchored"] == ["web__cart"]
    # A pure same-area rename preserves continuity: nothing to re-investigate.
    assert diff["changed_paths"] == []
    assert diff["affected_areas"] == []
    assert diff["deleted_paths"] == []
    assert diff["orphaned_elements"] == []
    # The baseline model was rewritten IN PLACE with the new anchor path.
    with open(os.path.join(out, "model.json"), encoding="utf-8") as fh:
        model = json.load(fh)
    cart = [e for e in model["elements"] if e["id"] == "web__cart"][0]
    assert cart["files"][0]["path"] == "web/src/basket.ts"
    assert not os.path.exists(os.path.join(out, "model.json.tmp"))


# --- unchanged short-circuit -------------------------------------------------
def test_unchanged_short_circuit(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4)
    before = open(os.path.join(out, "model.json"), encoding="utf-8").read()

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["unchanged"] is True
    assert diff["rebuild_required"] is False
    assert diff["history_rewritten"] is False
    assert diff["changed_paths"] == []
    assert diff["affected_areas"] == []
    assert open(os.path.join(out, "model.json"), encoding="utf-8").read() == before


# --- misc routing ------------------------------------------------------------
def test_genuinely_new_paths_route_to_misc(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {
        "tools/lint.js": "// lint\n",
        "tools/fmt.js": "// fmt\n",
    })
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["new_paths_routed_to_misc"] == ["tools/fmt.js", "tools/lint.js"]
    assert diff["affected_areas"] == ["misc"]
    assert diff["rebuild_required"] is False


def test_new_path_inside_existing_area_is_a_change_not_misc(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"web/src/wishlist.ts": "export const wl = [];\n"})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["new_paths_routed_to_misc"] == []
    assert diff["changed_paths"] == ["web/src/wishlist.ts"]
    assert diff["affected_areas"] == ["web"]


# --- rebuild_required on a clustering-material change ------------------------
def test_rebuild_required_on_new_five_file_dir(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {
        "billing/a.js": "1\n", "billing/b.js": "2\n", "billing/c.js": "3\n",
        "billing/d.js": "4\n", "billing/e.js": "5\n",
    })
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)
    before = open(os.path.join(out, "model.json"), encoding="utf-8").read()

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["rebuild_required"] is True
    assert "billing" in diff["rebuild_reason"]
    assert diff["history_rewritten"] is False
    # A rebuild ignores the baseline: it is never mutated on this path.
    assert open(os.path.join(out, "model.json"), encoding="utf-8").read() == before


def test_four_new_files_stay_below_rebuild_threshold(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {
        "billing/a.js": "1\n", "billing/b.js": "2\n",
        "billing/c.js": "3\n", "billing/d.js": "4\n",
    })
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["rebuild_required"] is False
    assert len(diff["new_paths_routed_to_misc"]) == 4
    assert diff["affected_areas"] == ["misc"]


# --- history rewrite (business C3) -------------------------------------------
def test_history_rewrite_via_reset_hard_divergence(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"web/src/app.ts": "export const app = 2;\n"})
    v2 = commit_all(repo)
    # Rewrite: drop v2, commit a divergent tip. v2 stays resolvable (loose
    # object) but is no longer an ancestor of the new tip.
    git(repo, "reset", "-q", "--hard", v1)
    write_files(repo, {"web/src/app.ts": "export const app = 3;\n"})
    v2b = commit_all(repo, "v2-divergent")
    assert v2b != v2
    out = make_out(tmp_path, v2, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2b)
    assert code == 0
    assert diff["history_rewritten"] is True
    assert diff["rebuild_required"] is False
    assert diff["changed_paths"] == []
    assert diff["affected_areas"] == []


def test_history_rewrite_when_old_anchor_unresolvable(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, "deadbeef" * 5, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["history_rewritten"] is True


# --- pack flags --------------------------------------------------------------
def test_manifest_path_flags_external_systems(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"package.json": '{"name": "fixture", "dependencies": {"left-pad": "1.0.0"}}\n'})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["external_systems_flagged"] is True
    assert diff["product_vision_flagged"] is False
    assert diff["affected_areas"] == ["misc"]


def test_readme_change_flags_product_vision(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"README.md": "# fixture, now with a vision\n"})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["product_vision_flagged"] is True
    assert diff["external_systems_flagged"] is False


# --- the deterministic state gate (adrev2-009 / business R5) -----------------
def test_gate_missing_state_names_the_searched_path(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4, write_state=False)

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["rebuild_required"] is True
    # adrev2-014: the message names the resolved path that was searched and
    # points at the --out mismatch cause.
    assert os.path.join(out, "state.json") in diff["rebuild_reason"]
    assert "--out" in diff["rebuild_reason"]
    assert diff["unchanged"] is False
    assert diff["history_rewritten"] is False


def test_gate_unparseable_state(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4, write_state=False)
    with open(os.path.join(out, "state.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["rebuild_required"] is True
    assert "unparseable" in diff["rebuild_reason"]


def test_gate_schema_version_mismatch_names_the_version(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4, schema_version=2)

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["rebuild_required"] is True
    assert "schema_version" in diff["rebuild_reason"]
    assert "2" in diff["rebuild_reason"]
    assert "likec4_version" not in diff["rebuild_reason"]


def test_gate_likec4_version_mismatch_names_both_versions(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4, likec4_version="0.0.1")

    code, diff = run_diff(diff_mod, repo, out, v1)
    assert code == 0
    assert diff["rebuild_required"] is True
    assert "likec4_version" in diff["rebuild_reason"]
    assert "0.0.1" in diff["rebuild_reason"]
    assert installed_likec4 in diff["rebuild_reason"]
    assert "schema_version" not in diff["rebuild_reason"]


def test_gate_matching_state_passes(diff_mod, installed_likec4, tmp_path):
    """The gate reads the REAL toolchain pin: a state recording exactly the
    installed version passes through to the diff."""
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"web/src/app.ts": "export const app = 2;\n"})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["rebuild_required"] is False


def test_missing_baseline_model_forces_rebuild(diff_mod, installed_likec4, tmp_path):
    """merge --patch needs the baseline model; a patchable diff without one
    must degrade to a stated full rebuild, never a mid-patch crash."""
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    write_files(repo, {"web/src/app.ts": "export const app = 2;\n"})
    v2 = commit_all(repo)
    out = make_out(tmp_path, v1, installed_likec4, write_model=False)

    code, diff = run_diff(diff_mod, repo, out, v2)
    assert code == 0
    assert diff["rebuild_required"] is True
    assert "model.json" in diff["rebuild_reason"]


# --- input errors exit 2, never a silent diff --------------------------------
def test_unresolvable_new_anchor_exits_2(diff_mod, installed_likec4, tmp_path):
    repo = make_repo(tmp_path, V1_FILES)
    v1 = head(repo)
    out = make_out(tmp_path, v1, installed_likec4)

    code, diff = run_diff(diff_mod, repo, out, "feedface" * 5)
    assert code == 2
    assert diff is None


def test_non_repo_exits_2(diff_mod, installed_likec4, tmp_path):
    plain = os.path.join(str(tmp_path), "plain")
    os.makedirs(plain)
    out = make_out(tmp_path, "1234567890abcdef1234567890abcdef12345678", installed_likec4)

    code, diff = run_diff(diff_mod, plain, out, "1234567890abcdef1234567890abcdef12345678")
    assert code == 2
    assert diff is None
