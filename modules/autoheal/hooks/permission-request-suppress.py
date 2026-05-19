#!/usr/bin/env python3
"""Contextual auto-allow for PermissionRequest events.

Registers on PermissionRequest with no matcher. The hook decides whether to
auto-allow the prompt based on the historical event log. The gate is
deliberately conservative: ALL of the following must hold for auto-allow:

  1. The session is in bypass mode (bypassPermissions / dontAsk / auto).
     If the user is in default mode they explicitly opted in to seeing
     prompts, so we never suppress.
  2. The (tool_name, command-or-path-signature) has been approved >= 3
     times across >= 2 distinct session_ids in the events log. This
     prevents one rogue session from establishing a precedent.
  3. The signature is NOT currently snoozed (no entry in snoozed.json
     with snoozed_until > now).

If all conditions hold we emit a PermissionRequest 'allow' decision via
hook_utils.emit_decision('allow', ...). Otherwise we exit 0 and let the
normal permission flow continue (user sees the prompt).

The hook NEVER blocks the host call; the worst case is the user sees a
prompt they could have skipped.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402


_MIN_APPROVALS = 3
_MIN_DISTINCT_SESSIONS = 2


def _autoheal_dir() -> str:
    override = os.environ.get("CCGM_AUTOHEAL_DIR")
    if override:
        return override
    return os.path.expanduser("~/.claude/autoheal")


def _events_dir() -> str:
    return os.path.join(_autoheal_dir(), "events")


def _snoozed_path() -> str:
    return os.path.join(_autoheal_dir(), "snoozed.json")


def _signature(tool_name: str, tool_input: dict) -> str:
    """Build a stable signature string for the (tool, target) pair.

    For Bash, the command's first token is the signature; for other tools
    we use the file_path field if present, else a sentinel. This
    deliberately ignores arguments after the verb so 'git diff foo' and
    'git diff bar' are the same signature.
    """
    if tool_name == "Bash":
        command = (tool_input or {}).get("command") or ""
        # First two tokens of the command. Conservative: 'git diff foo'
        # and 'git diff bar' share a signature, but 'git diff' and 'git
        # log' do not.
        tokens = command.strip().split()
        head = " ".join(tokens[:2]) if tokens else ""
        return f"Bash::{head}"
    path = (tool_input or {}).get("file_path") or ""
    return f"{tool_name}::{path}"


def _scan_history(signature: str) -> tuple[int, set[str]]:
    """Walk all events JSONL files; count prior 'allow' approvals for
    this signature. Returns (approval_count, distinct_session_ids).

    A prior approval is any event record with:
      - kind == 'permission_request'
      - permission_decision == 'allow'
      - signature matching `signature`
    """
    events_dir = _events_dir()
    approvals = 0
    sessions: set[str] = set()

    if not os.path.isdir(events_dir):
        return (0, sessions)

    try:
        files = sorted(os.listdir(events_dir))
    except OSError:
        return (0, sessions)

    for name in files:
        # Only consider current .jsonl files; ignore gzipped archives.
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(events_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("kind") != "permission_request":
                        continue
                    if rec.get("permission_decision") != "allow":
                        continue
                    # Compute signature for this stored event from its
                    # tool_name + redacted_command. This is approximate:
                    # the redaction is already applied so the prefix
                    # match still works for command verbs.
                    stored_sig = _signature(
                        rec.get("tool_name", ""),
                        {"command": rec.get("redacted_command") or ""},
                    )
                    if stored_sig == signature:
                        approvals += 1
                        sid = rec.get("session_id")
                        if isinstance(sid, str) and sid:
                            sessions.add(sid)
        except OSError:
            continue

    return (approvals, sessions)


def _is_snoozed(signature: str) -> bool:
    """Read snoozed.json; return True iff `signature` is snoozed and the
    snooze hasn't expired.

    Schema:
        {
          "<signature>": {"snoozed_until": "<ISO 8601>"},
          ...
        }
    """
    path = _snoozed_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    entry = data.get(signature)
    if not isinstance(entry, dict):
        return False
    until_str = entry.get("snoozed_until")
    if not isinstance(until_str, str):
        return False
    try:
        until = _dt.datetime.fromisoformat(until_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = _dt.datetime.now(_dt.timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=_dt.timezone.utc)
    return until > now


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        if not hook_utils.is_bypass_mode(data):
            sys.exit(0)

        tool_name = str(data.get("tool_name", ""))
        tool_input = data.get("tool_input") or {}
        if not tool_name:
            sys.exit(0)
        signature = _signature(tool_name, tool_input if isinstance(tool_input, dict) else {})

        if _is_snoozed(signature):
            sys.exit(0)

        approvals, sessions = _scan_history(signature)
        if approvals < _MIN_APPROVALS:
            sys.exit(0)
        if len(sessions) < _MIN_DISTINCT_SESSIONS:
            sys.exit(0)

        # All gates passed: auto-allow.
        hook_utils.emit_decision(
            "allow",
            f"autoheal: auto-allowed via pattern match "
            f"({approvals} prior approvals across {len(sessions)} sessions).",
        )
    except SystemExit:
        raise
    except Exception:
        # Never break the user flow if the suppression hook errors.
        sys.exit(0)


if __name__ == "__main__":
    main()
