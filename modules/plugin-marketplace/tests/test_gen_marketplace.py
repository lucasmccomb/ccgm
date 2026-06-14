#!/usr/bin/env python3
"""Tests for the plugin-marketplace generator + validator (issue #703).

These pin the projection's invariants:
  * The generator is deterministic and in sync with what is committed (--check
    passes against the live repo).
  * The committed marketplace.json + per-module plugin.json files are
    structurally valid (validate_marketplace passes).
  * Every module has a generated plugin.json; rules-bearing modules get the
    rule-injection hook wired and a copy of the hook on disk.
  * The marketplace name is not a reserved Anthropic name.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "modules" / "plugin-marketplace" / "lib"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_module("gen_marketplace", LIB / "gen_marketplace.py")
validator = _load_module("validate_marketplace", LIB / "validate_marketplace.py")


def _module_names() -> "list[str]":
    return [
        c.name
        for c in (REPO_ROOT / "modules").iterdir()
        if (c / "module.json").is_file()
    ]


def test_generator_check_is_clean():
    """Committed marketplace files must be in sync with module.json."""
    changed = gen.generate(check=True)
    assert changed == [], (
        "Generated marketplace files are stale. Run "
        "python3 modules/plugin-marketplace/lib/gen_marketplace.py. Stale: "
        + ", ".join(changed)
    )


def test_generator_is_deterministic():
    """Two check runs produce the same (empty) diff."""
    assert gen.generate(check=True) == gen.generate(check=True)


def test_marketplace_exists_and_valid_json():
    market = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    assert market.is_file()
    data = json.loads(market.read_text(encoding="utf-8"))
    assert data["name"] == gen.MARKETPLACE_NAME
    assert isinstance(data["plugins"], list)
    assert data["metadata"]["pluginRoot"] == "./modules"


def test_marketplace_name_not_reserved():
    assert gen.MARKETPLACE_NAME not in validator.RESERVED_MARKETPLACE_NAMES


def test_every_module_has_plugin_manifest():
    for name in _module_names():
        manifest = REPO_ROOT / "modules" / name / ".claude-plugin" / "plugin.json"
        assert manifest.is_file(), f"{name} is missing .claude-plugin/plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["name"] == name


def test_marketplace_lists_every_module():
    market = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    listed = {p["name"] for p in market["plugins"]}
    assert listed == set(_module_names())


def test_rules_bearing_plugins_wire_the_hook():
    for name in _module_names():
        manifest_path = REPO_ROOT / "modules" / name / "module.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plugin = json.loads(
            (REPO_ROOT / "modules" / name / ".claude-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        has_rule = gen._has_rule(manifest)
        if has_rule:
            assert "hooks" in plugin, f"{name} has rules but no SessionStart hook wired"
            cmd = plugin["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            assert "plugin-rule-inject.py" in cmd
            # the hook copy must exist on disk inside the plugin
            hook = REPO_ROOT / "modules" / name / gen.HOOK_REL
            assert hook.is_file(), f"{name} is missing its rule-inject hook copy"
        else:
            assert "hooks" not in plugin, f"{name} has no rules but a hook is wired"


def test_validator_passes_on_committed_output():
    r = validator.Result()
    market_path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    manifests = validator.validate_marketplace(r, market_path)
    for m in manifests:
        validator.validate_plugin(r, Path(m))
    assert r.errors == [], "validate_marketplace found errors: " + "; ".join(r.errors)
    assert len(manifests) == len(_module_names())
