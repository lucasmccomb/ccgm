#!/usr/bin/env python3
"""
SessionStart hook: instruct Claude to run /startup on fresh sessions.

Fires on SessionStart events whose `source == "startup"` (matcher scopes
this to `startup|resume` but the script stays silent on `resume` so that
resumed sessions pick up mid-task without being overridden by a dashboard
render).

Gated by CCGM_AUTO_STARTUP in ~/.claude/.ccgm.env. Disable by setting to
false (or unsetting).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"


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


if __name__ == "__main__":
    main()
