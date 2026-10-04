#!/usr/bin/env python3
"""Detect user-correction patterns in UserPromptSubmit input and log them.

Registers on UserPromptSubmit (no matcher). A prompt is logged as a
user_correction only when ALL hold:

  1. it matches a pattern in lib/correction-patterns.json,
  2. it is short (<= 300 chars), so a pasted brief or spec never counts,
  3. the session logged a tool_failure or user_interrupt row after the
     prompt two turns back (a correction follows something that went wrong
     within the last two turns).

The user_correction row links to the failure/interrupt rows it follows.
Per-session prompt times live in $CCGM_AUTOHEAL_DIR/state/prompts/ to
count turns.

This hook NEVER blocks the prompt, NEVER modifies the prompt, and never asks
for clarification. exit 0 always.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time

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

_MAX_RECENT_CONTEXT = 3  # how many failure/interrupt rows to attach as context
_MAX_PROMPT_LEN = 300  # longer prompts are briefs, not corrections
_TURN_WINDOW = 2  # a failure must come after the prompt this many turns back
_FRICTION_KINDS = ("tool_failure", "user_interrupt")
_STATE_RETENTION_SECONDS = 2 * 24 * 3600


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


def _recent_friction(events_path: str, session_id: str, since: str) -> list[str]:
    """Timestamps (newest first, at most _MAX_RECENT_CONTEXT) of this
    session's tool_failure/user_interrupt rows stamped after `since`.
    Events are append-ordered, so scanning from the end is enough.
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
        if rec.get("kind") not in _FRICTION_KINDS or rec.get("session_id") != session_id:
            continue
        ts = rec.get("timestamp")
        if not isinstance(ts, str) or ts <= since:
            continue
        out.append(ts)
        if len(out) >= _MAX_RECENT_CONTEXT:
            break
    return out


def _prompt_state_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown"
    return os.path.join(_autoheal_dir(), "state", "prompts", safe + ".json")


def _load_prompt_times(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            times = json.load(fh)
    except (OSError, ValueError):
        return []
    return [t for t in times if isinstance(t, str)] if isinstance(times, list) else []


def _save_prompt_times(path: str, times: list[str]) -> None:
    """Keep the last _TURN_WINDOW prompt times; prune stale session files."""
    state_dir = os.path.dirname(path)
    os.makedirs(state_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(times[-_TURN_WINDOW:], fh)
    os.replace(tmp, path)
    cutoff = time.time() - _STATE_RETENTION_SECONDS
    for name in os.listdir(state_dir):
        full = os.path.join(state_dir, name)
        try:
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
        except OSError:
            pass


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
        session_id = str(data.get("session_id", ""))
        now = _now_iso()

        # Turn bookkeeping runs for every prompt so the window is real.
        state_path = _prompt_state_path(session_id)
        prior = _load_prompt_times(state_path)
        _save_prompt_times(state_path, prior + [now])

        if len(prompt_text) > _MAX_PROMPT_LEN:
            sys.exit(0)
        pattern = _match_pattern(prompt_text)
        if pattern is None:
            sys.exit(0)

        # Failure must come after the prompt _TURN_WINDOW turns back; with
        # fewer prior prompts, any failure in the session qualifies.
        since = prior[-_TURN_WINDOW] if len(prior) >= _TURN_WINDOW else ""
        events_path = os.path.join(
            _autoheal_dir(), "events", _today_iso() + ".jsonl"
        )
        context_ids = _recent_friction(events_path, session_id, since)
        if not context_ids:
            sys.exit(0)

        transcript_path = data.get("transcript_path")
        if not isinstance(transcript_path, str):
            transcript_path = None

        record = {
            "kind": "user_correction",
            "timestamp": now,
            "session_id": session_id,
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
