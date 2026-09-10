#!/usr/bin/env python3
"""
UserPromptSubmit hook to enforce issue-first workflow.

This hook detects work requests and injects a reminder into Claude's context
to ensure the issue-first workflow is followed before making changes.

Scoped to ~/code/ — the reminder only fires when cwd is under that directory.
Outside that scope (e.g., a note-taking vault or other non-code working
directory), the hook stays silent. Coordination injection is additionally
conditional on .claude/logs/ existing in the current working directory.
"""

from __future__ import annotations

import json
import os
import re
import sys


def is_work_request(prompt: str) -> bool:
    """Detect if the prompt is a work request vs a question or research task."""
    prompt_lower = prompt.lower()

    # Work action verbs that indicate implementation tasks
    work_patterns = [
        r"\b(update|fix|add|create|implement|build|change|modify|refactor)\b",
        r"\b(write|make|set up|setup|configure|migrate|convert|move)\b",
        r"\b(delete|remove|rename|replace|upgrade|downgrade)\b",
        r"\b(enable|disable|install|uninstall)\b",
    ]

    # Patterns that indicate it's NOT a work request (questions, research)
    question_patterns = [
        r"^(what|why|how|where|when|which|who|can you explain|tell me)\b",
        r"\?$",  # Ends with question mark
        r"\b(explain|describe|show me|list|find|search|look for|check)\b",
    ]

    # Check if it looks like a question first
    for pattern in question_patterns:
        if re.search(pattern, prompt_lower):
            return False

    # Check if it matches work patterns
    for pattern in work_patterns:
        if re.search(pattern, prompt_lower):
            return True

    return False


def has_logs_directory() -> bool:
    """Check if .claude/logs/ exists in the current working directory."""
    return os.path.isdir(os.path.join(os.getcwd(), ".claude", "logs"))


def is_in_code_dir() -> bool:
    """Scope check: only fire the reminder when cwd is under ~/code/."""
    code_root = os.path.realpath(os.path.expanduser("~/code"))
    cwd = os.path.realpath(os.getcwd())
    return cwd == code_root or cwd.startswith(code_root + os.sep)


def build_reminder() -> str:
    """Build the workflow reminder, with optional coordination line."""
    coordination = ""
    if has_logs_directory():
        coordination = (
            "Coordination: read today's `.claude/logs/YYYYMMDD/` for other active "
            "sessions' file overlap (advisory), and log this session at "
            "`.claude/logs/YYYYMMDD/agent-N.md`.\n"
        )
    return (
        "\n<workflow-reminder>\n"
        "Work request in ~/code: use the issue-first workflow. Find or create the "
        "GitHub issue (`gh issue create`), branch `{issue#}-{description}` from "
        "origin/main, commit as `#{issue#}: {description}`, and open the PR with "
        "`Closes #{issue#}`. This covers docs and config changes too.\n"
        + coordination +
        "</workflow-reminder>\n"
    )


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure, don't block

    prompt = input_data.get("prompt", "")

    if is_work_request(prompt) and is_in_code_dir():
        print(build_reminder())

    sys.exit(0)


if __name__ == "__main__":
    main()
