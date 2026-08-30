#!/usr/bin/env python3
"""
SessionEnd hook: drop this session's advisor-mode flag.

Advisor-mode state is one flag file per session,
`~/.claude/advisor-mode/<session_id>`. Removing it when the session ends keeps
the state directory from filling with dead sessions. A session that dies
without firing SessionEnd is caught later by advisor-session-start.py's
garbage collection.

Never raises, always exits 0.
"""

import json
import os
import re
import sys

SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

# Session ids are uuids; anything else cannot name a flag file. Rejecting
# separators and dot-entries keeps the flag inside the state directory.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def session_id(data):
    """This session's id: hook input first, environment as fallback."""
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
        return
    flag = os.path.join(
        os.path.expanduser("~"), ".claude", "advisor-mode", sid)
    try:
        os.remove(flag)
    except OSError:
        pass  # already gone, or never created


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
