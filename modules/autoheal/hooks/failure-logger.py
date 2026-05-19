#!/usr/bin/env python3
"""Failure-specialized event logger for autoheal.

Registers on PostToolUseFailure (and runs alongside permission-event-logger.py
on PostToolUse so that successful + failed runs both end up in the events
JSONL with their respective kinds).

This hook writes a tool_failure record with stderr and exit_code populated,
in addition to the standard fields. permission-event-logger.py also writes a
tool_failure record on the failure surface — that double-write is intentional:
the analyzer dedupes on (session_id, timestamp, kind) and the redundancy
guards against a single hook's bugs taking the whole signal down.

Like permission-event-logger.py, this hook NEVER blocks the host tool call.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402

_MAX_COMMAND_LEN = 500
_MAX_STDERR_LEN = 200


def _autoheal_dir() -> str:
    override = os.environ.get("CCGM_AUTOHEAL_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/autoheal")


def _today_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _truncate(text: str, limit: int) -> str:
    if not text:
        return text
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 5)] + "[...]"


def _is_failure(data: dict) -> bool:
    """A PostToolUseFailure event is the obvious failure case. Also treat
    any event with exit_code != 0 as a failure for compatibility with
    older clients that omit hook_event_name.
    """
    name = (data.get("hook_event_name") or "").strip()
    if name == "PostToolUseFailure":
        return True
    exit_code = data.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return True
    return False


def _build_failure_record(data: dict) -> dict:
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command:
        redacted_command = _truncate(
            hook_utils.redact_secrets(command), _MAX_COMMAND_LEN
        )
    else:
        redacted_command = None

    stderr_text = data.get("stderr") or ""
    if isinstance(stderr_text, str) and stderr_text:
        stderr_excerpt = _truncate(
            hook_utils.redact_secrets(stderr_text), _MAX_STDERR_LEN
        )
    else:
        stderr_excerpt = None

    exit_code = data.get("exit_code")
    if not isinstance(exit_code, int):
        exit_code = None

    return {
        "kind": "tool_failure",
        "timestamp": _now_iso(),
        "session_id": str(data.get("session_id", "")),
        "tool_name": str(data.get("tool_name", "")),
        "redacted_command": redacted_command,
        "exit_code": exit_code,
        "stderr_excerpt": stderr_excerpt,
        "permission_decision": None,
        "cwd": data.get("cwd"),
        "clone_path": data.get("cwd"),
    }


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        if not _is_failure(data):
            # Failure logger fires on both PostToolUse and PostToolUseFailure
            # (registered on both surfaces). On PostToolUse with no failure
            # signal, do nothing — permission-event-logger handles the
            # tool_use record.
            sys.exit(0)
        record = _build_failure_record(data)
        target = os.path.join(_autoheal_dir(), "events", _today_iso() + ".jsonl")
        hook_utils.file_locked_append(target, json.dumps(record))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
