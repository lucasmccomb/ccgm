#!/usr/bin/env python3
"""
UserPromptSubmit hook: while advisor mode is on for THIS session, remind each
turn that the session is an orchestrator.

State is per session: the flag is ~/.claude/advisor-mode/<session_id>, read
from the hook input's session_id (CLAUDE_CODE_SESSION_ID as the fallback), so
another session's mode never injects here. The injection also names the
session id, which is what /advisor uses to find its own flag when the
environment variable is missing.

The guard (advisor-guard.py) enforces the posture mechanically; this injection
explains it so the model delegates instead of fighting denials. Adapted from
baton's orchestrator-mode injection pattern. One stat() per prompt when the
mode is off.
"""

import json
import os
import re
import sys

SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

# Session ids are uuids; anything else cannot name a flag file. Rejecting
# separators and dot-entries keeps the flag inside the state directory.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")

CONTEXT = (
    "advisor mode is ON — you are the orchestrator: a PreToolUse hook blocks "
    "your direct file edits and non-orchestration Bash. Your deliverable is "
    "the spec, not the diff: decompose the work, dispatch implementer "
    "subagents (four-field spec with file paths and the objective's why; "
    "isolation: worktree; sonnet by default, haiku for mechanical work, opus "
    "for genuinely hard units), review through separate reviewer agents with "
    "explicit success criteria, triage their findings, and delegate fixes "
    "(max 3 rounds, then escalate). Route plan- or issue-shaped work through "
    "/etp. Batch small related items into one dispatch — a subagent spawn "
    "costs real overhead — and copy any safety-critical session constraints "
    "into every spec, because subagents do not inherit them. Trivial or "
    "conversational turns: just answer directly. A guard denial means "
    "delegate it, never shell-trick around it. /advisor off ends the mode."
)

TRAILER = (
    " The mode is per session: this session's id is {sid}, and its flag is "
    "~/.claude/advisor-mode/{sid}. Other sessions are unaffected."
)


def session_id(data):
    """This turn's session id: hook input first, environment as fallback."""
    for candidate in (data.get("session_id"), os.environ.get(SESSION_ID_ENV)):
        if not isinstance(candidate, str):
            continue
        candidate = candidate.strip()
        if candidate in (".", "..") or not SESSION_ID_RE.fullmatch(candidate):
            continue
        return candidate
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    sid = session_id(data)
    if not sid:
        sys.exit(0)
    flag = os.path.join(
        os.path.expanduser("~"), ".claude", "advisor-mode", sid)
    if not os.path.isfile(flag):
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CONTEXT + TRAILER.format(sid=sid),
        },
        "suppressOutput": True,
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
