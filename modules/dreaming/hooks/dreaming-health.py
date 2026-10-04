#!/usr/bin/env python3
"""SessionStart hook: tell the next session when dreaming is broken, and say
once a day what it changed.

Reads ~/.claude/dreaming/state/health.json (written nightly by lib/health.py)
and the once-a-day sentinel state/notice.json, and writes only that sentinel.
No network, no subprocess, no imports beyond the standard library's
json/os/sys/datetime. Always exits 0; any error injects nothing.

  red, or last_success_at older than 36h  -> inject <dreaming-health status="red">
                                             with the top 2 reasons and fixes
  3+ consecutive red nights               -> also tell the agent to mention it
                                             to the user once this session
  no health.json, dreaming enabled        -> inject a "has never run" notice
  no health.json, not installed/disabled  -> inject nothing

Otherwise (#1098 §3.3), the first session of each local day gets one line
when the nightly engine integrated or retired learnings since the last
notice, from health.json's `recent_changes`:

  dreaming: integrated 2 learnings last night (devtrainer: "..."; _global: "...") · retired 1 · /dream-review to veto

`systemMessage` shows it to the user; `additionalContext` gives it to the
model as information, never a question. Later sessions that day, and days
with nothing new, print nothing. A red notice takes precedence and leaves the
day's notice for the next session.

Env: CCGM_DREAMING_DIR (default ~/.claude/dreaming); CCGM_DREAMING_NOW
(ISO time, tests only).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

STALE_HOURS = 36
MENTION_AFTER_RED_NIGHTS = 3
TOP_REASONS = 2
NOTICE_LOOKBACK_HOURS = 24      # first notice ever: changes from the last day
LAST_NIGHT_HOURS = 36           # every change newer than this reads "last night"
NOTICE_SLUGS = 3                # slugs quoted before "+N more"
NOTICE_QUOTE_CHARS = 40


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


# ---------------------------------------------------------------------------
# Daily notice
# ---------------------------------------------------------------------------


def _quote(text) -> str:
    text = " ".join(str(text or "").split()).replace('"', "'")
    return text if len(text) <= NOTICE_QUOTE_CHARS else text[:NOTICE_QUOTE_CHARS - 1].rstrip() + "…"


def _plural(n: int) -> str:
    return "learning" if n == 1 else "learnings"


def notice_line(changes: list, since: datetime, now: datetime):
    """One line for the changes, or None when there are none."""
    integrated = [c for c in changes if c.get("change") == "integrated"]
    retired = [c for c in changes if c.get("change") == "retired"]
    if not integrated and not retired:
        return None
    oldest = min(_parse(c.get("ts")) for c in changes)
    when = ("last night" if (now - oldest).total_seconds() <= LAST_NIGHT_HOURS * 3600
            else f"since {oldest.date().isoformat()}")
    parts = []
    if integrated:
        quotes = [f'{c.get("project") or "?"}: "{_quote(c.get("content"))}"' for c in integrated[:NOTICE_SLUGS]]
        if len(integrated) > NOTICE_SLUGS:
            quotes.append(f"+{len(integrated) - NOTICE_SLUGS} more")
        parts.append(f"integrated {len(integrated)} {_plural(len(integrated))} {when} ({'; '.join(quotes)})")
        if retired:
            parts.append(f"retired {len(retired)}")
    else:
        parts.append(f"retired {len(retired)} {_plural(len(retired))} {when}")
    return "dreaming: " + " · ".join(parts) + " · /dream-review to veto"


def build_notice(now: datetime):
    """The day's notice line, or None. Records today's check in the sentinel
    either way, so only the first session of a local day can print it."""
    root = _dreaming_dir()
    sentinel_path = os.path.join(root, "state", "notice.json")
    health = _load(os.path.join(root, "state", "health.json"))
    if not isinstance(health, dict):
        return None
    today = now.astimezone().date().isoformat()
    sentinel = _load(sentinel_path)
    sentinel = sentinel if isinstance(sentinel, dict) else {}
    if sentinel.get("date") == today:
        return None
    since = _parse(sentinel.get("checked_at")) or (now - timedelta(hours=NOTICE_LOOKBACK_HOURS))
    changes = []
    for c in health.get("recent_changes") or []:
        ts = _parse(c.get("ts")) if isinstance(c, dict) else None
        if ts is not None and since < ts <= now:
            changes.append(c)
    try:
        os.makedirs(os.path.dirname(sentinel_path), exist_ok=True)
        tmp = f"{sentinel_path}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"date": today, "checked_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, fh)
        os.replace(tmp, sentinel_path)
    except OSError:
        return None  # without a sentinel every session would repeat it; stay quiet
    return notice_line(changes, since, now)


def main() -> int:
    try:
        raw = os.environ.get("CCGM_DREAMING_NOW")
        now = (_parse(raw) if raw else None) or datetime.now(timezone.utc)
        context = build_context(now)
        if context:
            json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}, sys.stdout)
            return 0
        line = build_notice(now)
        if line:
            json.dump({
                "systemMessage": line,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        "<dreaming-notice>\n" + line + "\n"
                        "The user already sees this line. It needs no reply or acknowledgment; "
                        "do not ask about it.\n</dreaming-notice>"
                    ),
                },
            }, sys.stdout)
    except Exception:  # noqa: BLE001 -- a health hook must never block a session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
