#!/usr/bin/env python3
"""Event logger for autoheal observability loop.

Registers on PostToolUse, PostToolUseFailure, and PermissionRequest with no
matcher. Captures one append-only JSONL record per tool call / failure /
permission prompt to ~/.claude/autoheal/events/{YYYY-MM-DD}.jsonl.

Design constraints (plan.md §3 and Epic 3 spec):
  - Never blocks the host tool call: always exit 0.
  - Always applies hook_utils.redact_secrets() BEFORE truncation so the
    truncation boundary can never lop a redaction marker in half.
  - Uses hook_utils.file_locked_append() so 4 concurrent agents writing to
    the same file cannot interleave records.
  - Event dir is overridable via $CCGM_AUTOHEAL_DIR for tests.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402

# Hard cap on the stored command excerpt. 500 chars is long enough to
# diagnose most permission patterns while keeping the JSONL row small.
_MAX_COMMAND_LEN = 500
_MAX_STDERR_LEN = 200


def _autoheal_dir() -> str:
    """Resolve the autoheal data directory. Tests can override via env."""
    override = os.environ.get("CCGM_AUTOHEAL_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/autoheal")


def _today_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _truncate(text: str, limit: int) -> str:
    """Truncate text to `limit` chars, marking the cut with [...]."""
    if not text:
        return text
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 5)] + "[...]"


def _classify(data: dict) -> str:
    """Map hook event type to autoheal event kind.

    Claude Code passes the event name in `hook_event_name` (preferred) or
    falls back to inference from other fields. We honor either.
    """
    name = (data.get("hook_event_name") or "").strip()
    if name == "PostToolUseFailure":
        return "tool_failure"
    if name == "PermissionRequest":
        return "permission_request"
    if name == "PostToolUse":
        return "tool_use"

    # Fallback inference: presence of `permission_request` payload, exit
    # code, or stderr.
    if data.get("permission_request") is not None:
        return "permission_request"
    if data.get("exit_code") is not None and data.get("exit_code") != 0:
        return "tool_failure"
    return "tool_use"


def _build_record(data: dict, kind: str) -> dict:
    """Build a redacted event record. Schema: lib/event-schema.json."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    # Bash commands are the most common security/leak surface. Redact
    # BEFORE truncating so a partial redaction marker never escapes.
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command:
        redacted = hook_utils.redact_secrets(command)
        redacted_command = _truncate(redacted, _MAX_COMMAND_LEN)
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

    permission_decision = None
    pr = data.get("permission_request")
    if isinstance(pr, dict):
        decision = pr.get("decision")
        if isinstance(decision, str):
            permission_decision = decision

    return {
        "kind": kind,
        "timestamp": _now_iso(),
        "session_id": str(data.get("session_id", "")),
        "tool_name": str(tool_name),
        "redacted_command": redacted_command,
        "exit_code": exit_code,
        "stderr_excerpt": stderr_excerpt,
        "permission_decision": permission_decision,
        "cwd": data.get("cwd"),
        "clone_path": data.get("cwd"),
    }


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        kind = _classify(data)
        record = _build_record(data, kind)
        target = os.path.join(_autoheal_dir(), "events", _today_iso() + ".jsonl")
        hook_utils.file_locked_append(target, json.dumps(record))
    except Exception:
        # NEVER block the host tool call. Swallow logger errors silently.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
