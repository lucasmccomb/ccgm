#!/usr/bin/env python3
"""
SessionStart hook: instruct Claude to run /startup on fresh sessions and
surface recent peer handoffs for the current repo.

Fires on SessionStart events whose `source == "startup"` (matcher scopes
this to `startup|resume` but the script stays silent on `resume` so that
resumed sessions pick up mid-task without being overridden by a dashboard
render).

Gated by CCGM_AUTO_STARTUP in ~/.claude/.ccgm.env. Disable by setting to
false (or unsetting).

Side effects on startup:
- Prints run-/startup reminder (always).
- Prints peer handoffs block (if any recent handoffs from OTHER clones).
- Prunes handoffs older than 30 days for the current repo (opportunistic).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"
HANDOFF_LIB = Path.home() / ".claude" / "lib" / "handoff.py"


def is_enabled() -> bool:
    if not ENV_FILE.exists():
        return False
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("CCGM_AUTO_STARTUP="):
                return line.split("=", 1)[1].strip().lower() in ("true", "1", "yes")
    except OSError:
        pass
    return False


def _try_import_handoff():
    """Dynamically import the handoff lib without requiring sys.path setup."""
    if not HANDOFF_LIB.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("handoff", str(HANDOFF_LIB))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def emit_handoff_block(cwd: str) -> None:
    """If peer handoffs exist for the current repo, print the summary block."""
    handoff = _try_import_handoff()
    if handoff is None:
        return
    try:
        repo = handoff.detect_repo(cwd=cwd)
        if not repo:
            return
        agent = handoff.detect_agent(cwd=cwd)
        summary = handoff.summarize_for_startup(repo, agent)
        if summary:
            print(summary)
        # Opportunistic cleanup: prune handoffs >30d for this repo
        try:
            handoff.prune_old_handoffs(repo=repo, days=30)
        except Exception:
            pass
    except Exception:
        # Never let handoff logic block the startup hook
        pass


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        payload = {}

    # Only fire on fresh sessions. Resume, clear, and compact are silent.
    if payload.get("source", "") != "startup":
        return

    if not is_enabled():
        return

    print("<auto-startup>")
    print("Run the /startup command now to initialize this session.")
    print("</auto-startup>")

    cwd = payload.get("cwd") or os.getcwd()
    emit_handoff_block(cwd)


if __name__ == "__main__":
    main()
