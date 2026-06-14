#!/usr/bin/env python3
"""Tests for the plugin rule-injection SessionStart hook (issue #703)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / "modules" / "plugin-marketplace" / "hooks" / "plugin-rule-inject.py"


def _load():
    spec = importlib.util.spec_from_file_location("plugin_rule_inject", HOOK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load()


def _make_plugin(tmp_path: Path, rules: "dict[str, str]") -> Path:
    root = tmp_path / "my-plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "my-plugin"}', encoding="utf-8"
    )
    rules_dir = root / "rules"
    rules_dir.mkdir()
    for fname, body in rules.items():
        (rules_dir / fname).write_text(body, encoding="utf-8")
    return root


def test_noop_when_flag_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(hook.FLAG, raising=False)
    monkeypatch.setattr(hook, "_read_env_file", lambda: {})
    root = _make_plugin(tmp_path, {"a.md": "Rule A body"})
    assert hook.build_context(root) is None


def test_injects_rules_when_flag_set_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv(hook.FLAG, "true")
    monkeypatch.setattr(hook, "_read_env_file", lambda: {})
    root = _make_plugin(tmp_path, {"a.md": "Rule A body", "b.md": "Rule B body"})
    ctx = hook.build_context(root)
    assert ctx is not None
    assert "Rule A body" in ctx
    assert "Rule B body" in ctx
    assert '<ccgm-plugin-rules plugin="my-plugin">' in ctx
    assert "</ccgm-plugin-rules>" in ctx
    # rules emitted in sorted filename order
    assert ctx.index("Rule A body") < ctx.index("Rule B body")


def test_flag_via_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv(hook.FLAG, raising=False)
    monkeypatch.setattr(hook, "_read_env_file", lambda: {hook.FLAG: "1"})
    root = _make_plugin(tmp_path, {"a.md": "Rule A body"})
    assert hook.build_context(root) is not None


def test_none_when_no_rules_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(hook.FLAG, "true")
    monkeypatch.setattr(hook, "_read_env_file", lambda: {})
    root = tmp_path / "empty-plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name":"empty-plugin"}', encoding="utf-8")
    assert hook.build_context(root) is None


def test_none_when_root_is_none(monkeypatch):
    monkeypatch.setenv(hook.FLAG, "true")
    monkeypatch.setattr(hook, "_read_env_file", lambda: {})
    assert hook.build_context(None) is None


def test_truthy_values():
    assert hook._truthy("true")
    assert hook._truthy("TRUE")
    assert hook._truthy("1")
    assert hook._truthy("yes")
    assert not hook._truthy("false")
    assert not hook._truthy("0")
    assert not hook._truthy(None)
    assert not hook._truthy("")
