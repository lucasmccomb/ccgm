#!/usr/bin/env python3
"""
Stop hook: keep the main agent working on a declared task until it is marked done.

Opt-in. The hook blocks a stop only while a state file exists for THIS session:
~/.claude/persist/<session_id>.json, written by `ccgm-persist start` (the
/persist command). With no state file the hook does nothing.

The value is the guard stack that keeps the loop from deadlocking or running
forever. The hook lets the stop through (fail open) when:

  1. stop_hook_active is true (Claude Code's re-entrancy flag)
  2. the stop is a context-limit stop (blocking it deadlocks compaction)
  3. transcript context is at or above 95 percent
  4. the user aborted or interrupted
  5. the stop is an auth error (401/403)
  6. the state file was last updated more than 2 hours ago
  7. the iteration cap is reached (the state is then set inactive)
  8. a cancel-signal file ~/.claude/persist/<session_id>.cancel exists
  9. the state belongs to a different session or project

Any parse or IO error also allows the stop. Output: a JSON object on stdout;
{"decision": "block", "reason": ...} blocks, {} allows.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

STALE_SECONDS = 2 * 60 * 60
HARD_MAX_ITERATIONS = 200
DEFAULT_MAX_ITERATIONS = 50
CRITICAL_CONTEXT_PERCENT = 95
TRANSCRIPT_TAIL_BYTES = 4096

SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")

CONTEXT_PATTERNS = (
    "context_limit", "context_window", "context_exceeded", "context_full",
    "max_context", "token_limit", "max_tokens", "conversation_too_long",
    "input_too_long",
)
ABORT_EXACT = ("aborted", "abort", "cancel", "interrupt")
ABORT_SUBSTRINGS = ("user_cancel", "user_interrupt", "ctrl_c", "manual_stop")
AUTH_PATTERNS = (
    "authentication_error", "authentication_failed", "auth_error",
    "unauthorized", "unauthorised", "401", "403", "forbidden",
    "invalid_token", "token_invalid", "token_expired", "expired_token",
    "oauth_expired", "oauth_token_expired", "invalid_grant",
    "insufficient_scope",
)


def allow() -> None:
    print("{}")


def block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))


def normalize(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s-]+", "_", value.strip().lower())


def stop_reasons(data: dict) -> list[str]:
    keys = ("stop_reason", "stopReason", "end_turn_reason", "endTurnReason", "reason")
    return [r for r in (normalize(data.get(k)) for k in keys) if r]


def is_context_limit_stop(data: dict) -> bool:
    return any(p in r for r in stop_reasons(data) for p in CONTEXT_PATTERNS)


def context_percent(transcript_path) -> int:
    """Last input_tokens over last context_window in the transcript tail; 0 if unknown."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return 0
    try:
        size = os.path.getsize(transcript_path)
        if size == 0:
            return 0
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
        windows = re.findall(r'"context_window"\s{0,5}:\s{0,5}(\d+)', tail)
        inputs = re.findall(r'"input_tokens"\s{0,5}:\s{0,5}(\d+)', tail)
        if not windows or not inputs or int(windows[-1]) <= 0:
            return 0
        return round(int(inputs[-1]) / int(windows[-1]) * 100)
    except (OSError, ValueError):
        return 0


def is_user_abort(data: dict) -> bool:
    if data.get("user_requested") or data.get("userRequested"):
        return True
    reason = normalize(data.get("stop_reason") or data.get("stopReason"))
    return reason in ABORT_EXACT or any(p in reason for p in ABORT_SUBSTRINGS)


def is_auth_error(data: dict) -> bool:
    reasons = [
        normalize(data.get("stop_reason") or data.get("stopReason")),
        normalize(data.get("end_turn_reason") or data.get("endTurnReason")),
    ]
    return any(p in r for r in reasons for p in AUTH_PATTERNS)


def session_id(data: dict) -> str | None:
    sid = data.get("session_id")
    if not isinstance(sid, str) or sid in (".", "..") or not SESSION_ID_RE.fullmatch(sid):
        return None
    return sid


def write_state(path: Path, state: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def int_field(state: dict, key: str, default: int) -> int | None:
    value = state.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def reason_text(state: dict, sid: str, iteration: int, max_iterations: int) -> str:
    task = state.get("task") if isinstance(state.get("task"), str) else "the declared task"
    criteria = state.get("done_criteria")
    criteria_line = (
        f"Done criteria: {criteria}\n" if isinstance(criteria, str) and criteria.strip() else ""
    )
    cli = f"python3 $HOME/.claude/bin/ccgm-persist --session {sid}"
    return (
        f"[PERSIST {iteration}/{max_iterations}] Work is NOT done. Continue the task: {task}\n"
        f"{criteria_line}"
        "Mark it done only after the done criteria are verified with fresh evidence "
        "(a command you ran this turn and its output), never from memory or reasoning alone. "
        f"To mark it done, run: {cli} done\n"
        f"If that command is denied, run: rm -f $HOME/.claude/persist/{sid}.json\n"
        f"To abandon the task instead, run: {cli} cancel"
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError, OSError):
        allow()
        return
    if not isinstance(data, dict):
        allow()
        return

    # Guards 1-5: facts about this stop event.
    if data.get("stop_hook_active") is True:
        return allow()
    if is_context_limit_stop(data):
        return allow()
    if context_percent(data.get("transcript_path")) >= CRITICAL_CONTEXT_PERCENT:
        return allow()
    if is_user_abort(data):
        return allow()
    if is_auth_error(data):
        return allow()

    # Guard 9 (session): the state file is keyed by session id, so a different
    # session never finds this one's file.
    sid = session_id(data)
    if sid is None:
        return allow()

    persist_dir = Path.home() / ".claude" / "persist"
    state_path = persist_dir / f"{sid}.json"
    cancel_path = persist_dir / f"{sid}.cancel"

    try:
        # Guard 8: cancel signal.
        if cancel_path.exists():
            state_path.unlink(missing_ok=True)
            cancel_path.unlink(missing_ok=True)
            return allow()

        if not state_path.exists():
            return allow()

        # Guard 6: stale state, by file mtime (each block refreshes it).
        if time.time() - state_path.stat().st_mtime > STALE_SECONDS:
            return allow()

        state = json.loads(state_path.read_text())
        if not isinstance(state, dict) or state.get("active") is False:
            return allow()

        # Guard 9 (project): both sides known and different means another project.
        project = state.get("project")
        current = os.environ.get("CLAUDE_PROJECT_DIR")
        if isinstance(project, str) and project and current and project != current:
            return allow()

        iteration = int_field(state, "iteration", 0)
        max_iterations = int_field(state, "max_iterations", DEFAULT_MAX_ITERATIONS)
        if iteration is None or max_iterations is None:
            return allow()
        max_iterations = min(max_iterations, HARD_MAX_ITERATIONS)

        # Guard 7: iteration cap deactivates the loop.
        if iteration >= max_iterations:
            state["active"] = False
            write_state(state_path, state)
            return allow()

        state["iteration"] = iteration + 1
        write_state(state_path, state)
        block(reason_text(state, sid, iteration + 1, max_iterations))
    except Exception:
        # Every IO or parse error fails open.
        allow()


if __name__ == "__main__":
    main()
