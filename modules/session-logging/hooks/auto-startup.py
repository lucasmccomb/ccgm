#!/usr/bin/env python3
"""
SessionStart hook that instructs Claude to run /startup on new sessions.

When a fresh session starts (source == "startup"), prints an instruction to
stdout which gets injected into Claude's context. This works across all
Claude Code clients (terminal, VS Code, Cursor, desktop app).

Can be disabled by setting CCGM_AUTO_STARTUP=false in ~/.claude/.ccgm.env
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"


def is_enabled() -> bool:
    """Check if auto-startup is enabled in .ccgm.env."""
    if not ENV_FILE.exists():
        return False
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CCGM_AUTO_STARTUP="):
                    value = line.split("=", 1)[1].strip().lower()
                    return value in ("true", "1", "yes")
    except (OSError, IOError):
        pass
    return False


def main() -> None:
    # Read stdin (required by hook contract)
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # Only fire on fresh sessions, not resume or compact
    source = hook_input.get("source", "")
    if source != "startup":
        return

    if not is_enabled():
        return

    # Print instruction to stdout - this gets injected into Claude's context
    print("<auto-startup>")
    print("Run the /startup command now to initialize this session.")
    print("</auto-startup>")


if __name__ == "__main__":
    main()
