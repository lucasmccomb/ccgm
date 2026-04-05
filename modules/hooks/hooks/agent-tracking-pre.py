#!/usr/bin/env python3
"""
PreToolUse:Bash hook for multi-agent issue tracking.

ADVISORY ONLY - this hook NEVER writes to tracking CSV.
It only emits warnings when an agent is about to work on an
issue that's already claimed by another agent.

Intercepts:
- git checkout -b {N}-* : Warn if issue N is already claimed
"""

from __future__ import annotations

import json
import os
import re
import sys

# Import tracking module
sys.path.insert(0, os.path.expanduser("~/.claude/lib"))


def is_multi_clone_repo() -> bool:
    """Check if current directory has .env.clone (multi-clone repo)."""
    return os.path.isfile(os.path.join(os.getcwd(), ".env.clone"))


def get_repo_name() -> str | None:
    """Get repo name from git remote."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            name = os.path.basename(result.stdout.strip())
            return name[:-4] if name.endswith(".git") else name
    except Exception:
        pass
    return None


def extract_issue_from_branch(command: str) -> str | None:
    """Extract issue number from git checkout -b {N}-* command."""
    match = re.search(r"git\s+checkout\s+-b\s+(\d+)-", command)
    if match:
        return match.group(1)
    return None


def warn(message: str) -> None:
    """Emit a warning (advisory, does not block)."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecisionReason": f"WARNING: {message}",
        }
    }
    print(json.dumps(output))


def check_live_session_in_cwd() -> dict | None:
    """Check if another live Claude session is running in this working directory."""
    try:
        from agent_sessions import get_active_sessions
        my_cwd = os.getcwd()
        sessions = get_active_sessions(exclude_cwd=my_cwd)
        # Check if any session is in the same directory
        for s in sessions:
            if s.get("cwd") and os.path.realpath(s["cwd"]) == os.path.realpath(my_cwd):
                return s
    except Exception:
        pass
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "").strip()
    if not command:
        sys.exit(0)

    # Early exit: not a multi-clone repo
    if not is_multi_clone_repo():
        sys.exit(0)

    # Only intercept git checkout -b
    if not re.match(r"git\s+checkout\s+-b\s+", command):
        sys.exit(0)

    # Check for live session in current directory (highest priority warning)
    live_session = check_live_session_in_cwd()
    if live_session:
        pid = live_session.get("pid", "?")
        uptime = live_session.get("uptime", "?")
        branch = live_session.get("branch") or "unknown branch"
        warn(
            f"A live Claude session (PID {pid}, up {uptime}) is already running in this directory "
            f"on branch '{branch}'. Creating a new branch here may conflict with that session's work. "
            f"Consider using a different clone directory."
        )

    issue_num = extract_issue_from_branch(command)
    if not issue_num:
        sys.exit(0)

    repo = get_repo_name()
    if not repo:
        sys.exit(0)

    # Check if issue is already claimed
    try:
        from agent_tracking import check_claim, get_agent_id
        agent, status = check_claim(repo, issue_num)
        my_id = get_agent_id()

        if agent and agent != my_id:
            warn(f"Issue #{issue_num} is already claimed by {agent} (status: {status})")
    except Exception:
        pass  # Never block on tracking errors

    sys.exit(0)


if __name__ == "__main__":
    main()
