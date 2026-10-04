#!/usr/bin/env python3
"""Permission-request logger and daily call counter for autoheal.

Registers on PostToolUse, PostToolUseFailure, and PermissionRequest with no
matcher.

  - PermissionRequest: appends one permission_request row to
    ~/.claude/autoheal/events/{YYYY-MM-DD}.jsonl.
  - PostToolUse / PostToolUseFailure: bumps a per-tool counter in
    ~/.claude/autoheal/counts/{YYYY-MM-DD}.json ({"Bash": 123, "Read": 77}).
    No event row is written. Routine calls were 97% of the old log and
    carried no signal; the counter keeps the denominator for failure rates.
    Failure rows come from failure-logger.py alone.

Design constraints:
  - Never blocks the host tool call: always exit 0.
  - Applies hook_utils.redact_secrets() BEFORE truncation so the
    truncation boundary can never lop a redaction marker in half.
  - Row appends use hook_utils.file_locked_append(); counter updates take
    an fcntl lock around the read-modify-write, so 4 concurrent agents
    cannot lose increments.
  - Data dir is overridable via $CCGM_AUTOHEAL_DIR for tests.
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402

# Hard cap on the stored command excerpt. 500 chars is long enough to
# diagnose most permission patterns while keeping the JSONL row small.
_MAX_COMMAND_LEN = 500


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


def _build_permission_record(data: dict) -> dict:
    """Build a redacted permission_request row. Schema: lib/event-schema.json."""
    tool_input = data.get("tool_input") or {}

    # Bash commands are the most common security/leak surface. Redact
    # BEFORE truncating so a partial redaction marker never escapes.
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command:
        redacted_command = _truncate(
            hook_utils.redact_secrets(command), _MAX_COMMAND_LEN
        )
    else:
        redacted_command = None

    permission_decision = None
    pr = data.get("permission_request")
    if isinstance(pr, dict):
        decision = pr.get("decision")
        if isinstance(decision, str):
            permission_decision = decision

    transcript_path = data.get("transcript_path")
    if not isinstance(transcript_path, str):
        transcript_path = None

    return {
        "kind": "permission_request",
        "timestamp": _now_iso(),
        "session_id": str(data.get("session_id", "")),
        "tool_name": str(data.get("tool_name", "")),
        "redacted_command": redacted_command,
        "permission_decision": permission_decision,
        "cwd": data.get("cwd"),
        "clone_path": data.get("cwd"),
        "transcript_path": transcript_path,
    }


def _bump_counter(tool_name: str) -> None:
    """Increment counts/{today}.json[tool_name] under an exclusive lock."""
    path = os.path.join(_autoheal_dir(), "counts", _today_iso() + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            raw = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
            try:
                counts = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except ValueError:
                counts = {}
            if not isinstance(counts, dict):
                counts = {}
            counts[tool_name] = int(counts.get(tool_name, 0)) + 1
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, json.dumps(counts, sort_keys=True).encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        name = (data.get("hook_event_name") or "").strip()
        if name in ("PostToolUse", "PostToolUseFailure"):
            _bump_counter(str(data.get("tool_name", "")) or "unknown")
        elif name == "PermissionRequest":
            target = os.path.join(_autoheal_dir(), "events", _today_iso() + ".jsonl")
            hook_utils.file_locked_append(
                target, json.dumps(_build_permission_record(data))
            )
    except Exception:
        # NEVER block the host tool call. Swallow logger errors silently.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
