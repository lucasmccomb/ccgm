#!/usr/bin/env python3
"""
PreToolUse:Bash hook for multi-agent issue tracking.

ADVISORY ONLY - this hook NEVER writes to tracking CSV.
It only emits warnings when an agent is about to work on an
issue that's already claimed by another agent.

Intercepts:
- git checkout -b {N}-* : Warn if issue N is already claimed
"""

import json
import os
import re
import sys

# Import tracking module
sys.path.insert(0, os.path.expanduser("~/.claude/lib"))


def is_multi_clone_repo():
    """Check if current directory has .env.clone (multi-clone repo)."""
    return os.path.isfile(os.path.join(os.getcwd(), ".env.clone"))


def get_repo_name():
    """Get repo name from git remote."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            name = os.path.basename(result.stdout.strip())
            return name.removesuffix(".git")
    except Exception:
        pass
    return None


def extract_issue_from_branch(command):
    """Extract issue number from git checkout -b {N}-* command."""
    match = re.search(r"git\s+checkout\s+-b\s+(\d+)-", command)
    if match:
        return match.group(1)
    return None


def warn(message):
    """Emit a warning (advisory, does not block)."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecisionReason": f"WARNING: {message}",
        }
    }
    print(json.dumps(output))


def main():
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
    if not re.match(r"git\s+checkout\s+-b\s+\d+-", command):
        sys.exit(0)

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
