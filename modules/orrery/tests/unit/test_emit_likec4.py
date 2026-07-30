"""Unit tests for emit_likec4.py (plan Epic 3)."""

import filecmp
import json
import os
import re
import subprocess

from conftest import ANCHOR_SHA, MODULE_DIR, SCRIPTS_DIR, write_json

GOLDEN_EMITTED = os.path.join(MODULE_DIR, "tests", "fixtures", "golden-emitted")
OUT_FILES = ["spec.c4", "model.c4", "views.c4", "likec4.config.json"]


def meta(remote="https://github.com/acme-fixture/acme-shop.git",
         source_links="github"):
    return {
        "slug": "acme-shop",
        "repo_title": "acme-shop",
        "remote_url": remote,
        "default_ref": "main",
        "anchor_sha": ANCHOR_SHA,
        "visibility": "public",
        "generated_at": "2026-01-01T00:00:00Z",
        "source_links": source_links,
        "areas": [{"id": "web", "title": "Web", "root_paths": ["Web"]}],
    }


def element(eid, **over):
    el = {
        "id": eid,
        "kind": "component",
        "title": "Element " + eid,
        "summary": "A fixture element.",
        "files": [{"path": "api/worker.js"}],
        "source_packs": ["one"],
    }
    el.update(over)
    return el


def base_elements():
    return [
        {"id": "system", "kind": "system", "title": "Acme Shop",
         "summary": "Fictional demo.", "files": [{"path": "README.md"}],
         "source_packs": ["product-vision"]},
        element("web", kind="container", parent="system",
                files=[{"path": "Web/src/main.ts", "start_line": 1, "end_line": 5}]),
        element("web__catalog", parent="web"),
    ]


def run_emit(emit_mod, tmp_path, model):
    os.makedirs(str(tmp_path), exist_ok=True)
    model_path = os.path.join(str(tmp_path), "model.json")
    write_json(model_path, model)
    code = emit_mod.run(["--model", model_path, "--out-dir", str(tmp_path)])
    assert code == 0
    out = {}
    for name in OUT_FILES:
        with open(os.path.join(str(tmp_path), "model", name), encoding="utf-8") as fh:
            out[name] = fh.read()
    return out


def all_text(out):
    return "\n".join(out.values())


# --- placement + palette ---------------------------------------------------

def test_outputs_land_inside_model_dir(emit_mod, tmp_path):
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": base_elements(), "relations": []})
    for name in OUT_FILES:
        # the config MUST sit INSIDE model/ (section 3.7) -- at the parent it
        # is silently ignored and the drill-down views vanish
        assert os.path.isfile(os.path.join(str(tmp_path), "model", name))
    assert not os.path.exists(os.path.join(str(tmp_path), "likec4.config.json"))
    config = json.loads(out["likec4.config.json"])
    assert config == {"name": "acme-shop", "implicitViews": True}


def test_spec_palette_named_colors_never_raw_hex_in_style(emit_mod, tmp_path):
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": base_elements(), "relations": []})
    spec = out["spec.c4"]
    # section 3.4a: one specification-level declaration per kind...
    for name, hexval in (
        ("orrery_system", "#4C6EF5"), ("orrery_actor", "#845EF7"),
        ("orrery_container", "#3B5BDB"), ("orrery_component", "#5C7CFA"),
        ("orrery_datastore", "#0CA678"), ("orrery_queue", "#0B7285"),
        ("orrery_cloud", "#495057"), ("orrery_external", "#868E96"),
        ("orrery_package", "#ADB5BD"), ("orrery_tool", "#CED4DA"),
        ("orrery_file", "#748FFC"),
    ):
        assert re.search(r"color %s\s+%s" % (name, hexval), spec)
    # ...and NEVER a raw hex inside a style block (a parse error at 1.59.2)
    for style_block in re.findall(r"style\s*\{[^}]*\}", spec):
        assert "#" not in style_block
    assert "size sm" in spec  # file tier size, split out of shape


# --- source links ----------------------------------------------------------

def test_github_links_https_remote(emit_mod, tmp_path):
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": base_elements(), "relations": []})
    assert ("link https://github.com/acme-fixture/acme-shop/blob/%s/Web/src/main.ts#L1-L5 'source'"
            % ANCHOR_SHA) in out["model.c4"]


def test_github_links_ssh_remote_normalized(emit_mod, tmp_path):
    m = meta(remote="git@github.com:acme-fixture/acme-shop.git")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "https://github.com/acme-fixture/acme-shop/blob/" in out["model.c4"]
    assert "git@" not in out["model.c4"]


def test_github_links_ssh_scheme_remote_normalized(emit_mod, tmp_path):
    m = meta(remote="ssh://git@github.com/acme-fixture/acme-shop.git")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "https://github.com/acme-fixture/acme-shop/blob/" in out["model.c4"]


def test_github_links_credential_stripped(emit_mod, tmp_path):
    m = meta(remote="https://x-token:ghp_fakefake@github.com/acme-fixture/acme-shop.git")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "https://github.com/acme-fixture/acme-shop/blob/" in out["model.c4"]
    assert "x-token" not in all_text(out)
    assert "ghp_fakefake" not in all_text(out)


def test_gitlab_remote_emits_zero_github_urls(emit_mod, tmp_path):
    m = meta(remote="https://gitlab.com/acme-fixture/acme-shop.git",
             source_links="none (non-GitHub remote)")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "github.com" not in all_text(out)


def test_no_remote_emits_zero_github_urls(emit_mod, tmp_path):
    m = meta(remote=None, source_links="none (non-GitHub remote)")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "github.com" not in all_text(out)


def test_meta_github_but_non_github_remote_still_zero_links(emit_mod, tmp_path):
    # Belt and suspenders: even if meta claims github, a non-GitHub host must
    # never be templated into a github.com URL (a fabricated-link truthfulness
    # failure -- section 3.4).
    m = meta(remote="https://gitlab.com/acme-fixture/acme-shop.git", source_links="github")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": base_elements(), "relations": []})
    assert "github.com" not in all_text(out)


def test_external_url_link_survives_non_github_remote(emit_mod, tmp_path):
    m = meta(remote=None, source_links="none (non-GitHub remote)")
    els = base_elements() + [element(
        "stripe", kind="external_service", files=None,
        external_url="https://stripe.com/docs", parent=None,
    )]
    els[-1].pop("files")
    out = run_emit(emit_mod, tmp_path, {"meta": m, "elements": els, "relations": []})
    assert "link https://stripe.com/docs 'docs'" in out["model.c4"]


# --- escaping --------------------------------------------------------------

def test_html_entity_escaping_of_adversarial_markup(emit_mod, tmp_path):
    els = base_elements()
    els[2]["description"] = 'Payload: <img src=x onerror="window.orreryAdvPayload=1"> & more'
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": els, "relations": []})
    assert "&lt;img src=x onerror=&quot;window.orreryAdvPayload=1&quot;&gt; &amp; more" in out["model.c4"]
    assert "<img" not in out["model.c4"]


def test_escaping_edge_cases(emit_mod, tmp_path):
    els = base_elements()
    els[2]["title"] = "Acme's \"Grid\""
    els[2]["description"] = 'Triple: """ and a backslash: C:\\path\\to'
    els[2]["files"] = [{"path": "Web/it's odd.ts", "start_line": 1}]
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": els, "relations": []})
    model_c4 = out["model.c4"]
    assert "Acme&#39;s &quot;Grid&quot;" in model_c4
    assert "&quot;&quot;&quot;" in model_c4
    assert "C:\\path\\to" in model_c4  # backslash passes through literally
    # quote-in-path: percent-encoded in the link URL, never a raw quote
    assert "Web/it%27s%20odd.ts#L1" in model_c4
    assert "it's" not in model_c4


def test_adversarial_emission_validates_via_likec4(emit_mod, tmp_path):
    # The escaped edge cases must actually PARSE at likec4@1.59.2 -- this is
    # also the section 3.4a spec-block compile test (spec.c4 ships in the dir).
    els = base_elements()
    els[2]["title"] = "Acme's \"Grid\""
    els[2]["summary"] = 'Quotes: \' and " and """ together'
    els[2]["description"] = 'Backslash \\ and <img src=x onerror="x()"> payload'
    els[2]["files"] = [{"path": "Web/it's odd.ts", "start_line": 1}]
    run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": els, "relations": []})
    proc = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "likec4.sh"), "validate", "--json",
         os.path.join(str(tmp_path), "model")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["valid"] is True


# --- views -----------------------------------------------------------------

def test_views_of_targets_are_parent_qualified(emit_mod, tmp_path):
    # `view <id> of <nested>` needs the QUALIFIED FQN (Epic 1 spike record):
    # `of web` fails to resolve, `of system.web` validates.
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": base_elements(), "relations": []})
    views = out["views.c4"]
    assert "view system_containers of system {" in views
    assert "view web_components of system.web {" in views
    assert re.search(r"of web \{", views) is None


def test_views_have_l1_index(emit_mod, tmp_path):
    els = base_elements() + [
        element("shopper", kind="actor", files=None),
        element("stripe", kind="external_service", external_url="https://stripe.com/docs"),
    ]
    els[-2].pop("files")
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": els, "relations": []})
    m = re.search(r"view index \{\n    title '([^']*)'\n    include ([^\n]*)", out["views.c4"])
    assert m, out["views.c4"]
    assert m.group(1) == "acme-shop - system landscape"
    assert m.group(2) == "shopper, stripe, system"


# --- file-tier cap ---------------------------------------------------------

def test_file_cap_truncation_note_and_dropped_relations(emit_mod, tmp_path):
    els = base_elements()
    file_ids = []
    for i in range(15):
        fid = "web__catalog_f%02d" % i
        file_ids.append(fid)
        els.append(element(fid, kind="file", parent="web__catalog",
                           files=[{"path": "api/worker.js"}]))
    rels = [{"from": "web__catalog", "to": file_ids[13], "summary": "reads"}]
    out = run_emit(emit_mod, tmp_path, {"meta": meta(), "elements": els, "relations": rels})
    model_c4 = out["model.c4"]
    emitted = [fid for fid in file_ids if ("%s = file" % fid) in model_c4]
    assert emitted == file_ids[:12]
    assert "showing 12 of 15 files" in model_c4
    # a relation touching a capped-out file element must not dangle in the DSL
    assert file_ids[13] not in model_c4


# --- determinism + golden --------------------------------------------------

def test_byte_deterministic_emission(emit_mod, tmp_path):
    model = {"meta": meta(), "elements": base_elements(), "relations": [
        {"from": "web__catalog", "to": "web", "kind": "uses", "summary": "renders in"},
    ]}
    out_a = run_emit(emit_mod, os.path.join(str(tmp_path), "a"), model)
    out_b = run_emit(emit_mod, os.path.join(str(tmp_path), "b"), model)
    assert out_a == out_b


def test_golden_emitted_comparison(emit_mod, tmp_path):
    # Byte-for-byte against the checked-in expected emission.
    model_path = os.path.join(GOLDEN_EMITTED, "model.json")
    code = emit_mod.run(["--model", model_path, "--out-dir", str(tmp_path)])
    assert code == 0
    for name in OUT_FILES:
        got = os.path.join(str(tmp_path), "model", name)
        want = os.path.join(GOLDEN_EMITTED, "model", name)
        assert filecmp.cmp(got, want, shallow=False), (
            "%s drifted from the checked-in golden emission" % name
        )
