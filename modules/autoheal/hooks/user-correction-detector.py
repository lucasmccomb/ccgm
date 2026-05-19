#!/usr/bin/env python3
"""Detect user-correction patterns in UserPromptSubmit input and log them.

Registers on UserPromptSubmit (no matcher). When the user's prompt matches a
correction pattern (e.g. "no, not like that", "stop doing X", "I told you"),
log a user_correction event linking to the most recent tool_use events from
today's JSONL. The analyzer uses these as supervised signals that the agent's
recent actions were wrong.

This hook NEVER blocks the prompt, NEVER modifies the prompt, and never asks
for clarification. exit 0 always.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


# Default location of the patterns file once installed. Tests override
# via CCGM_CORRECTION_PATTERNS so they can point at the in-repo source.
# Mirrors the realtime-security-scanner.py loading pattern.
_DEFAULT_PATTERNS_PATH = os.path.expanduser(
    "~/.claude/lib/correction-patterns.json"
)


def _patterns_path() -> str:
    override = os.environ.get("CCGM_CORRECTION_PATTERNS")
    if override:
        return override
    return _DEFAULT_PATTERNS_PATH


def _load_correction_patterns() -> list[tuple[str, "re.Pattern[str]"]]:
    """Load (name, compiled_regex) pairs from the patterns JSON file.

    Order matters only for disambiguation when two patterns could match
    the same string; the first match wins. Patterns are case-insensitive
    and word-bounded where it makes sense. False positives are acceptable
    -- the analyzer's threshold logic is the second line of defense.

    Falls back to an empty list if the file is missing or malformed
    (graceful degradation: the hook becomes a no-op rather than crashing
    the prompt pipeline).
    """
    try:
        with open(_patterns_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    raw = data.get("patterns") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, "re.Pattern[str]"]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        regex_src = entry.get("regex")
        if not isinstance(name, str) or not isinstance(regex_src, str):
            continue
        try:
            compiled = re.compile(regex_src, re.IGNORECASE)
        except re.error:
            # Bad regex in the patterns file is a config bug. Skip it.
            continue
        out.append((name, compiled))
    return out


_CORRECTION_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = _load_correction_patterns()

_MAX_RECENT_CONTEXT = 3  # how many recent tool_use events to attach as context


def _autoheal_dir() -> str:
    override = os.environ.get("CCGM_AUTOHEAL_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/autoheal")


def _today_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _match_pattern(text: str) -> str | None:
    """Return the first matching pattern name, or None."""
    if not text:
        return None
    for name, regex in _CORRECTION_PATTERNS:
        if regex.search(text):
            return name
    return None


def _recent_tool_use_ids(events_path: str) -> list[str]:
    """Read up to _MAX_RECENT_CONTEXT trailing tool_use timestamps from
    today's events JSONL. Returns the timestamps (used as light-weight
    event ids — the event-schema allows but doesn't require an explicit
    id field).
    """
    if not os.path.isfile(events_path):
        return []
    try:
        with open(events_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    out: list[str] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "tool_use":
            ts = rec.get("timestamp") or rec.get("id")
            if isinstance(ts, str):
                out.append(ts)
                if len(out) >= _MAX_RECENT_CONTEXT:
                    break
    return out


def _extract_prompt(data: dict) -> str:
    """Pull the user prompt text out of the hook input. The exact key
    name varies by client version; try the documented ones in order.
    """
    for key in ("prompt", "user_prompt", "user_message", "text", "input"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
        if isinstance(val, dict):
            inner = val.get("text") or val.get("content")
            if isinstance(inner, str) and inner:
                return inner
    # Last-resort fallback for UserPromptSubmit shape variants.
    submit = data.get("user_prompt_submit") or data.get("prompt_submit")
    if isinstance(submit, dict):
        text = submit.get("text") or submit.get("prompt")
        if isinstance(text, str):
            return text
    return ""


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        prompt_text = _extract_prompt(data)
        pattern = _match_pattern(prompt_text)
        if pattern is None:
            sys.exit(0)

        events_path = os.path.join(
            _autoheal_dir(), "events", _today_iso() + ".jsonl"
        )
        context_ids = _recent_tool_use_ids(events_path)

        transcript_path = data.get("transcript_path")
        if not isinstance(transcript_path, str):
            transcript_path = None

        record = {
            "kind": "user_correction",
            "timestamp": _now_iso(),
            "session_id": str(data.get("session_id", "")),
            "tool_name": "UserPrompt",
            "redacted_command": None,
            "exit_code": None,
            "stderr_excerpt": None,
            "permission_decision": None,
            "cwd": data.get("cwd"),
            "clone_path": data.get("cwd"),
            "correction_pattern_matched": pattern,
            "context_event_ids": context_ids,
            "transcript_path": transcript_path,
        }
        hook_utils.file_locked_append(events_path, json.dumps(record))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
