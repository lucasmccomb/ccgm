#!/usr/bin/env python3
"""SessionStart hook: opt-in relevance-scoped rule injection (issue #695).

PURPOSE
-------
CCGM installs every selected module's rules to ~/.claude/rules/, where Claude
Code auto-loads ALL of them on every session (~53k tokens always-on). This
hook offers an OPT-IN alternative: at fresh session start, surface a short
pointer to the SUBSET of rules relevant to the current task profile, while
guaranteeing the safety core is always surfaced.

CRITICAL SAFETY PROPERTY
------------------------
This hook is a strict NO-OP unless an explicit opt-in flag is set:

    CCGM_RELEVANCE_INJECTION=true   in ~/.claude/.ccgm.env

When the flag is unset (the default for every existing and new install), the
hook reads stdin, finds the flag absent, and returns without emitting
anything. Claude Code's normal all-rules-always-loaded behavior is completely
untouched. The feature can only ever ADD a pointer; it never removes a rule
file from disk and never suppresses the auto-load path.

It additionally fires only on source == "startup" (not resume/compact), and
only injects a non-authoritative POINTER (additionalContext) — the rule files
themselves still live in ~/.claude/rules/ and remain loadable. The pointer
biases attention toward the relevant subset; it does not gate access.

This hook deliberately keeps the latent/deterministic split clean: all
selection logic lives in the pure relevance_select library (testable), and
this file only does I/O wiring.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"
FLAG = "CCGM_RELEVANCE_INJECTION"
LANGS_VAR = "CCGM_RELEVANCE_LANGS"
TASKS_VAR = "CCGM_RELEVANCE_TASKTYPES"

# The selection library is installed alongside this hook's repo copy, and at
# ~/.claude/lib/relevance_select.py once CCGM installs it. Make both importable.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
sys.path.insert(0, str(_HERE.parent / "lib"))

try:
    import relevance_select  # type: ignore
except Exception:  # pragma: no cover - import guard; hook must never crash a session
    relevance_select = None


def _read_env() -> "dict[str, str]":
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


def _split_csv(val: "str | None") -> "list[str]":
    if not val:
        return []
    return [p.strip() for p in val.replace(";", ",").split(",") if p.strip()]


def _installed_modules() -> "list[str]":
    """Read the installed-module list from the global CCGM manifest."""
    manifest = Path.home() / ".claude" / ".ccgm-manifest.json"
    if not manifest.exists():
        return []
    try:
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
        mods = data.get("modules")
        return [m for m in mods if isinstance(m, str)] if isinstance(mods, list) else []
    except (OSError, json.JSONDecodeError, ValueError):
        return []


def _modules_dir(env: "dict[str, str]") -> "str | None":
    """Locate the CCGM repo modules/ dir from the manifest's ccgmRoot."""
    manifest = Path.home() / ".claude" / ".ccgm-manifest.json"
    if manifest.exists():
        try:
            with open(manifest, encoding="utf-8") as fh:
                root = json.load(fh).get("ccgmRoot")
            if isinstance(root, str) and root:
                cand = os.path.join(root, "modules")
                if os.path.isdir(cand):
                    return cand
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return None


def build_context(env: "dict[str, str]") -> "str | None":
    """Build the additionalContext pointer, or None if nothing to emit.

    Pure-ish: depends only on env + filesystem state, no stdin. Returns None
    when the feature is disabled or the data needed for selection is missing —
    in every "None" case the caller emits nothing and behavior is unchanged.
    """
    if not _truthy(env.get(FLAG)):
        return None
    if relevance_select is None:
        return None

    modules_dir = _modules_dir(env)
    installed = _installed_modules()
    if not modules_dir or not installed:
        return None

    langs = _split_csv(env.get(LANGS_VAR))
    task_types = _split_csv(env.get(TASKS_VAR))

    selected = relevance_select.select_modules(
        installed, modules_dir, langs=langs, task_types=task_types
    )
    if not selected:
        return None

    core = [m for m in selected if relevance_select.is_safety_core(m)]
    situational = [m for m in selected if not relevance_select.is_safety_core(m)]

    lines = [
        "<ccgm-relevance-injection>",
        "Relevance-scoped rule injection is ON for this session. The rules in",
        "~/.claude/rules/ remain loaded; this pointer highlights the subset most",
        "relevant to the current task profile so you route through them first.",
        "",
        "ALWAYS-ON safety core (highest precedence, never scoped away):",
        "  " + ", ".join(core),
    ]
    if situational:
        lines += [
            "",
            "Relevant to this profile"
            + (f" (langs={','.join(langs)}" if langs else " (")
            + (f" taskTypes={','.join(task_types)})" if task_types else ")"),
            "  " + ", ".join(situational),
        ]
    lines += [
        "",
        "The safety core is non-negotiable regardless of profile. If a task",
        "touches a discipline not listed above, consult its rule anyway.",
        "</ccgm-relevance-injection>",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, EOFError):
        hook_input = {}

    # Only fire on fresh sessions, matching session-start-enforce.py.
    if hook_input.get("source", "") != "startup":
        return

    env = _read_env()
    context = build_context(env)
    if context:
        sys.stdout.write(context)


if __name__ == "__main__":
    main()
