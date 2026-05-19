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


# Each tuple: (pattern_name, compiled_regex). Order matters only for
# disambiguation when two patterns could match the same string; the first
# match wins. Patterns are case-insensitive and word-bounded where it
# makes sense. False positives are acceptable — the analyzer's threshold
# logic is the second line of defense.
_CORRECTION_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    (
        "no_not_like_that",
        re.compile(r"\bno,?\s+not\s+like\s+that\b", re.IGNORECASE),
    ),
    (
        "stop_doing",
        re.compile(r"\bstop\s+doing\b", re.IGNORECASE),
    ),
    (
        "dont_do_that",
        re.compile(r"\b(?:don'?t|do\s+not)\s+(?:do\s+that|do\s+this)\b", re.IGNORECASE),
    ),
    (
        "i_told_you",
        re.compile(r"\bI\s+told\s+you\b", re.IGNORECASE),
    ),
    (
        "wait_no",
        re.compile(r"\bwait,?\s+no\b", re.IGNORECASE),
    ),
    (
        "actually_correction",
        re.compile(r"\bactually,?\s+(?:no|that's\s+wrong|that\s+is\s+wrong|do)\b", re.IGNORECASE),
    ),
    (
        "instead",
        re.compile(r"\b(?:do\s+\w+\s+)?instead\b", re.IGNORECASE),
    ),
    (
        "thats_wrong",
        re.compile(r"\bthat'?s\s+(?:wrong|not\s+right|incorrect)\b", re.IGNORECASE),
    ),
    (
        "undo",
        re.compile(r"\b(?:undo|revert)\s+(?:that|this|what\s+you\s+did)\b", re.IGNORECASE),
    ),
]

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
