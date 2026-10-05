#!/usr/bin/env python3
"""Failure logger for autoheal. The only writer of failure rows.

Registers on PostToolUseFailure. Claude Code sends this input shape:

    {hook_event_name, session_id, transcript_path, cwd, tool_name,
     tool_input, tool_use_id, error, is_interrupt, duration_ms}

`error` carries the failure text (for Bash it starts with "Exit code N" on its first line).
`is_interrupt` is true when the user stopped the tool. There are no
top-level `stderr` or `exit_code` fields.

One row per failure:
  - kind "tool_failure": error (redacted, <= 400 chars), error_class
    (lib/error_classes.json, via lib/error_classes.py), cmd_head (first program of a Bash command,
    redacted), exit_code (parsed from "Exit code N").
  - kind "user_interrupt": the same fields, when is_interrupt is true.

permission-event-logger.py no longer writes failure rows, so a failure is
never logged twice.

Like every autoheal hook, this one NEVER blocks the host tool call.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import error_classes  # noqa: E402  (lib/error_classes.py, shared with the aggregator)
import hook_utils  # noqa: E402

_MAX_COMMAND_LEN = 500
_MAX_ERROR_LEN = 400
_MAX_HEAD_LEN = 60

# Programs whose second word is a subcommand worth keeping in cmd_head
# ("git add", "wrangler d1"). For anything else the head is one word.
_SUBCOMMAND_PROGRAMS = frozenset(
    {
        "git", "gh", "npm", "pnpm", "yarn", "npx", "bun", "wrangler",
        "docker", "kubectl", "supabase", "cargo", "go", "brew", "launchctl",
        "uv", "pip", "pip3", "xcrun", "xcodebuild", "claude", "make",
    }
)
# Global options that sit between the program and its subcommand, for the
# programs where that is routine (`git -C <path> log`, `gh -R o/r pr view`).
# Value: options that consume the next word. Any other leading `-...` word
# is skipped alone. Programs not listed here keep a flag-first command as a
# bare program, because a flag there is not known to precede a subcommand.
_GLOBAL_OPTS_WITH_ARG = {
    "git": frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"}),
    "gh": frozenset({"-R", "--repo"}),
}
_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9_:-]*$")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
_SKIP_PROGRAMS = frozenset({"cd", "export", "set", "source", ".", "time", "sudo"})
_EXIT_CODE_RE = re.compile(r"^Exit code (\d+)")


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
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 5)] + "[...]"


def classify_error(error: str) -> str:
    return error_classes.classify(error)


def cmd_head(command: str) -> str | None:
    """First program of a shell command, plus its subcommand for CLIs that
    have them. Skips env assignments and leading `cd x &&` style segments."""
    for segment in _SEGMENT_SPLIT_RE.split(command):
        words = segment.split()
        while words and _ENV_ASSIGN_RE.match(words[0]):
            words.pop(0)
        if not words or words[0] in _SKIP_PROGRAMS:
            continue
        head = words[0]
        rest = words[1:]
        with_arg = _GLOBAL_OPTS_WITH_ARG.get(head)
        if with_arg is not None:
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in with_arg else rest[1:]
        if head in _SUBCOMMAND_PROGRAMS and rest and _SUBCOMMAND_RE.match(rest[0]):
            head = head + " " + rest[0]
        return _truncate(hook_utils.redact_secrets(head), _MAX_HEAD_LEN)
    return None


def _build_failure_record(data: dict) -> dict:
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command:
        redacted_command = _truncate(
            hook_utils.redact_secrets(command), _MAX_COMMAND_LEN
        )
        head = cmd_head(command)
    else:
        redacted_command = None
        head = None

    error_raw = data.get("error")
    if isinstance(error_raw, str) and error_raw:
        error_class = classify_error(error_raw)
        match = _EXIT_CODE_RE.match(error_raw)
        exit_code = int(match.group(1)) if match else None
        # Redact before truncating so the cut cannot split a marker.
        error = _truncate(hook_utils.redact_secrets(error_raw), _MAX_ERROR_LEN)
    else:
        error_class, exit_code, error = None, None, None

    transcript_path = data.get("transcript_path")
    if not isinstance(transcript_path, str):
        transcript_path = None

    return {
        "kind": "user_interrupt" if data.get("is_interrupt") is True else "tool_failure",
        "timestamp": _now_iso(),
        "session_id": str(data.get("session_id", "")),
        "tool_name": str(data.get("tool_name", "")),
        "redacted_command": redacted_command,
        "cmd_head": head,
        "error": error,
        "error_class": error_class,
        "exit_code": exit_code,
        "cwd": data.get("cwd"),
        "clone_path": data.get("cwd"),
        "transcript_path": transcript_path,
    }


def main() -> None:
    try:
        data = hook_utils.read_hook_input()
        if (data.get("hook_event_name") or "").strip() != "PostToolUseFailure":
            sys.exit(0)
        record = _build_failure_record(data)
        target = os.path.join(_autoheal_dir(), "events", _today_iso() + ".jsonl")
        hook_utils.file_locked_append(target, json.dumps(record))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
