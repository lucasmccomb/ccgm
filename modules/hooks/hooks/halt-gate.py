#!/usr/bin/env python3
"""
PreToolUse hook that blocks tool calls when the 5hr usage block is at/over threshold.

Reads halt state from ~/.claude/halt.flag (written by usage-monitor.sh).
Flag format (key=value, one per line):
    reset_iso=2026-04-16T19:00:00.000Z
    percent=99.2
    triggered_at=2026-04-16T17:30:00Z

If the flag exists and reset_iso is in the future, every tool call is denied.
If reset_iso has passed, the stale flag is removed and the call is allowed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FLAG = Path.home() / ".claude" / "halt.flag"


def parse_flag() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in FLAG.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass

    if not FLAG.exists():
        allow()

    try:
        data = parse_flag()
        reset = parse_iso(data["reset_iso"])
    except Exception:
        allow()

    now = datetime.now(timezone.utc)
    if now >= reset:
        try:
            FLAG.unlink()
        except FileNotFoundError:
            pass
        allow()

    mins = int((reset - now).total_seconds() // 60)
    percent = data.get("percent", "?")
    deny(
        f"Claude Code 5hr usage block at {percent}% — halted until "
        f"{reset.astimezone().strftime('%H:%M %Z')} (~{mins}m). "
        f"Remove {FLAG} to override."
    )


if __name__ == "__main__":
    main()
