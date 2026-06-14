#!/usr/bin/env python3
"""SessionStart hook: inject an installed plugin's bundled rules (issue #703).

WHY THIS EXISTS
---------------
When CCGM is installed via the native Claude Code plugin marketplace, a plugin's
root CLAUDE.md is NOT loaded as context, and a plugin can only contribute the
`agent`/`subagentStatusLine` settings keys. CCGM modules that are rules-only
(autonomy, code-quality, git-workflow, systematic-debugging, ...) would
therefore contribute nothing under the plugin path.

This hook is the documented workaround: at fresh session start it reads the
rules/*.md files bundled in THIS plugin (resolved via ${CLAUDE_PLUGIN_ROOT}) and
emits them as `additionalContext`, so the plugin's guidance reaches Claude the
same way the bash installer's ~/.claude/rules/ files do.

The generator (gen_marketplace.py) copies this exact file into every
rules-bearing plugin's hooks/ directory and wires the plugin.json SessionStart
hook to call ${CLAUDE_PLUGIN_ROOT}/hooks/plugin-rule-inject.py.

OPT-IN BY DEFAULT
-----------------
Injecting full rule bodies costs tokens. To stay conservative and match the
relevance-injection module's posture (issue #695), this hook is a strict NO-OP
unless an explicit opt-in flag is set:

    CCGM_PLUGIN_RULE_INJECTION=true   in ~/.claude/.ccgm.env  (or the environment)

With the flag unset, the plugin's commands/agents/skills still work natively;
only the rule-body injection is suppressed. When the flag is set, the hook emits
a header plus the concatenated rule files for this one plugin.

SAFETY
------
- Fires only on source == "startup" (not resume/compact).
- Never raises: any failure path returns without emitting, so it can never crash
  a session.
- Reads only files inside ${CLAUDE_PLUGIN_ROOT}/rules/; no network, no writes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"
FLAG = "CCGM_PLUGIN_RULE_INJECTION"


def _read_env_file() -> "dict[str, str]":
    """Parse ~/.claude/.ccgm.env into a flat dict. Missing file -> {}."""
    out: "dict[str, str]" = {}
    if not ENV_FILE.exists():
        return out
    try:
        with open(ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                out[key.strip()] = val.strip()
    except OSError:
        return {}
    return out


def _truthy(val: "str | None") -> bool:
    return (val or "").strip().lower() in ("true", "1", "yes")


def _flag_enabled() -> bool:
    """Opt-in flag from the environment first, then ~/.claude/.ccgm.env."""
    if _truthy(os.environ.get(FLAG)):
        return True
    return _truthy(_read_env_file().get(FLAG))


def _plugin_root() -> "Path | None":
    """Resolve the plugin's installed root.

    Prefers $CLAUDE_PLUGIN_ROOT (set by Claude Code for plugin hook processes).
    Falls back to two levels up from this file (hooks/ -> plugin root) so the
    hook is testable in-repo without the env var.
    """
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    cand = here.parent.parent  # hooks/<file> -> plugin root
    return cand if cand.is_dir() else None


def _plugin_name(root: Path) -> str:
    """Best-effort plugin name from .claude-plugin/plugin.json, else dir name."""
    manifest = root / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            name = data.get("name")
            if isinstance(name, str) and name:
                return name
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return root.name


def _rule_files(root: Path) -> "list[Path]":
    rules_dir = root / "rules"
    if not rules_dir.is_dir():
        return []
    return sorted(p for p in rules_dir.glob("*.md") if p.is_file())


def build_context(root: "Path | None") -> "str | None":
    """Build the additionalContext block, or None if there is nothing to emit."""
    if not _flag_enabled():
        return None
    if root is None:
        return None
    rule_paths = _rule_files(root)
    if not rule_paths:
        return None

    name = _plugin_name(root)
    parts: "list[str]" = [
        f"<ccgm-plugin-rules plugin=\"{name}\">",
        "These rules are bundled with the installed CCGM plugin "
        f"'{name}'. A plugin's CLAUDE.md is not auto-loaded, so they are "
        "injected here at session start. Treat them as project/global rules.",
        "",
    ]
    for path in rule_paths:
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not body:
            continue
        parts.append(f"## rule: {path.name}")
        parts.append(body)
        parts.append("")
    parts.append("</ccgm-plugin-rules>")
    return "\n".join(parts) + "\n"


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, EOFError):
        hook_input = {}

    # Only fire on fresh sessions, matching the other CCGM session-start hooks.
    if hook_input.get("source", "") != "startup":
        return

    context = build_context(_plugin_root())
    if context:
        sys.stdout.write(context)


if __name__ == "__main__":
    main()
