#!/usr/bin/env python3
"""
PostToolUse:Bash hook that injects reflection reminders after significant events.

Detects:
- gh pr merge  -> remind to run post-merge reflection
- gh issue close -> remind to check for reusable patterns

PostToolUse input schema:
{
    "tool_name": "Bash",
    "tool_input": {"command": "...", "description": "..."},
    "tool_response": {"stdout": "...", "stderr": "...", "interrupted": false},
    "cwd": "/path/to/working/dir",
    ...
}
"""

from __future__ import annotations

import json
import os
import re
import sys


def is_log_repo(cwd: str) -> bool:
    """Check if we're in an agent log repo (skip reflection for log commits)."""
    code_dir = os.path.expanduser("~/code")
    if os.path.isdir(code_dir):
        for entry in os.listdir(code_dir):
            if entry.endswith("agent-logs"):
                log_path = os.path.join(code_dir, entry)
                try:
                    if os.path.realpath(cwd).startswith(os.path.realpath(log_path)):
                        return True
                except Exception:
                    pass
    return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    cwd = data.get("cwd", os.getcwd())

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "").strip()
    interrupted = tool_response.get("interrupted", False)

    if not command or interrupted:
        sys.exit(0)

    # Skip reflection reminders in the log repo
    if is_log_repo(cwd):
        sys.exit(0)

    # Detect PR merge
    if re.match(r"gh\s+pr\s+merge", command):
        print("<reflection-trigger>")
        print("PR merged. Run the post-merge reflection from the self-improving rules:")
        print("review what you learned, check if any patterns should be captured to memory.")
        print("</reflection-trigger>")
        sys.exit(0)

    # Detect issue close
    if re.match(r"gh\s+issue\s+close\s+\d+", command):
        print("<reflection-trigger>")
        print("Issue closed. Consider whether this issue revealed a reusable pattern")
        print("worth capturing to memory (root cause, debugging lesson, tool gotcha).")
        print("</reflection-trigger>")
        sys.exit(0)


if __name__ == "__main__":
    main()
