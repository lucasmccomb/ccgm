#!/usr/bin/env python3
"""SessionStart hook: tell the next session when dreaming is broken.

Reads ~/.claude/dreaming/state/health.json (written nightly by lib/health.py)
and nothing else. No network, no subprocess, no imports beyond the standard
library's json/os/sys/datetime. Always exits 0; any error injects nothing.

  red, or last_success_at older than 36h  -> inject <dreaming-health status="red">
                                             with the top 2 reasons and fixes
  3+ consecutive red nights               -> also tell the agent to mention it
                                             to the user once this session
  green or yellow                         -> inject nothing
  no health.json, dreaming enabled        -> inject a "has never run" notice
  no health.json, not installed/disabled  -> inject nothing

Env: CCGM_DREAMING_DIR (default ~/.claude/dreaming); CCGM_DREAMING_NOW
(ISO time, tests only).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

STALE_HOURS = 36
MENTION_AFTER_RED_NIGHTS = 3
TOP_REASONS = 2


def _dreaming_dir() -> str:
    return os.environ.get("CCGM_DREAMING_DIR") or os.path.expanduser("~/.claude/dreaming")


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _parse(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _block(lines: list) -> str:
    return '<dreaming-health status="red">\n' + "\n".join(lines) + "\n</dreaming-health>"


def build_context(now: datetime):
    root = _dreaming_dir()
    health = _load(os.path.join(root, "state", "health.json"))
    if not isinstance(health, dict):
        config = _load(os.path.join(root, "config.json"))
        if isinstance(config, dict) and config.get("enabled", True) is not False:
            return _block([
                "Dreaming is enabled but has never run: there is no state/health.json.",
                "fix: bash ~/.claude/bin/dream-install.sh && bash ~/.claude/bin/dream-daily.sh",
            ])
        return None

    reasons = [r for r in (health.get("reasons") or []) if isinstance(r, dict)]
    last = _parse(health.get("last_success_at"))
    stale = last is None or (now - last).total_seconds() > STALE_HOURS * 3600
    if health.get("status") != "red" and not stale:
        return None

    if health.get("status") != "red":
        when = health.get("last_success_at") or "never"
        reasons = [{
            "message": f"dreaming has not run successfully since {when}; the nightly job may have stopped",
            "fix": "bash ~/.claude/bin/dream-install.sh",
        }] + reasons

    lines = ["Dreaming (the nightly memory pipeline) is broken."]
    for reason in reasons[:TOP_REASONS]:
        lines.append(f"- {reason.get('message', 'unknown problem')}")
        lines.append(f"  fix: {reason.get('fix', 'see ~/.claude/dreaming/state/health.json')}")
    nights = health.get("consecutive_red_nights")
    if isinstance(nights, int) and nights >= MENTION_AFTER_RED_NIGHTS:
        lines.append(
            f"It has been red {nights} nights running. Mention it to the user once, "
            "in one sentence, early in this session. Do not repeat it after that."
        )
    return _block(lines)


def main() -> int:
    try:
        raw = os.environ.get("CCGM_DREAMING_NOW")
        now = _parse(raw) if raw else None
        context = build_context(now or datetime.now(timezone.utc))
        if context:
            json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}, sys.stdout)
    except Exception:  # noqa: BLE001 -- a health hook must never block a session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
