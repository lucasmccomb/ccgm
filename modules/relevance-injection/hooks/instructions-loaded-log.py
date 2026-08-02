#!/usr/bin/env python3
"""InstructionsLoaded hook: log which instruction files Claude Code loads.

PURPOSE (plan.md Epic 7 -- `~/code/plans/ccgm-dynamic-rule-injection/plan.md`)
------------------------------------------------------------------------------
This is the deterministic measurement oracle for the rest of the dynamic
rule-loading plan: it turns "did the right rule load?" from a model
judgment into a fact recorded on disk. Registers on the `InstructionsLoaded`
hook event with no matcher and appends one JSONL record per invocation to
`~/.claude/rule-loading/loaded-{YYYY-MM-DD}.jsonl`.

OBSERVED PAYLOAD SHAPE (confirmed live, `claude -p` 2.1.220, project-level
settings.json, recorded in decisions.md)
------------------------------------------------------------------------------
Claude Code invokes this hook ONCE PER LOADED INSTRUCTION FILE (not once per
session with a batched list). Each stdin payload is a flat JSON object:

    {
      "session_id": "...",
      "transcript_path": "...",
      "cwd": "...",
      "hook_event_name": "InstructionsLoaded",
      "file_path": "/absolute/path/to/the/loaded/file.md",
      "memory_type": "User",          # observed value; others are plausible
      "load_reason": "session_start"  # observed value; others are plausible
    }

This logger extracts those fields directly (so downstream parsing in
lib/loaded_log.py is a flat-field read, not a nested-list search) AND keeps
the full redacted raw payload under "raw" as a forward-compat safety net --
if Anthropic adds or renames a field, the raw payload still has it even
before the structured extraction above is updated.

DESIGN CONSTRAINTS (same as every CCGM hook)
------------------------------------------------------------------------------
  - NEVER blocks the host action: always exits 0, even on a malformed or
    empty stdin payload.
  - Applies hook_utils.redact_secrets() to the raw payload BEFORE it is
    stored, same as autoheal's event logger.
  - Uses hook_utils.file_locked_append() so concurrent clones / concurrent
    hook invocations within one session cannot interleave or tear a write.
  - Log directory is overridable via $CCGM_RULE_LOADING_DIR for tests.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


def _rule_loading_dir() -> str:
    """Resolve the rule-loading data directory. Tests can override via env."""
    override = os.environ.get("CCGM_RULE_LOADING_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/rule-loading")


def _today_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _str_or_none(value: object) -> "str | None":
    return value if isinstance(value, str) and value else None


def _redacted_raw(data: dict) -> dict:
    """Return `data` with any secret-shaped substring redacted.

    Round-trips through JSON so the result is guaranteed JSON-serializable
    even if `data` contains non-JSON-native values (defensive; hook stdin is
    already parsed JSON so this is normally a no-op transform).
    """
    try:
        raw_text = json.dumps(data, default=str)
    except (TypeError, ValueError):
        return {}
    redacted_text = hook_utils.redact_secrets(raw_text)
    try:
        result = json.loads(redacted_text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def build_record(data: dict) -> dict:
    """Build the JSONL record for one InstructionsLoaded invocation.

    Pure function of `data` (plus wall-clock time) so it is directly
    testable without stdin or filesystem I/O.
    """
    return {
        "hook_event_name": _str_or_none(data.get("hook_event_name")) or "InstructionsLoaded",
        "timestamp": _now_iso(),
        "session_id": _str_or_none(data.get("session_id")),
        "cwd": _str_or_none(data.get("cwd")),
        "file_path": _str_or_none(data.get("file_path")),
        "memory_type": _str_or_none(data.get("memory_type")),
        "load_reason": _str_or_none(data.get("load_reason")),
        "raw": _redacted_raw(data),
    }


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        record = build_record(data)
        target = os.path.join(_rule_loading_dir(), "loaded-" + _today_iso() + ".jsonl")
        hook_utils.file_locked_append(target, json.dumps(record))
    except Exception:
        # NEVER block the session. A logger failure must be invisible to the
        # host event, same contract as every other CCGM observability hook.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
