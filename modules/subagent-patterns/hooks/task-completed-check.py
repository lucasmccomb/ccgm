#!/usr/bin/env python3
"""
TaskCompleted hook: deterministic replacement for the former prompt-type hook.

Previous version fired a Haiku call on every task completion. It blocked
legitimate completions because the hook input (task_subject, task_description)
is insufficient to judge whether work was actually performed, and there is
no transcript to inspect.

This version always allows completion. The hook slot is kept so future
deterministic logic (telemetry, lint-on-placeholder-description, etc.) can
be wired in without a new registration. A light warning goes to stderr when
the task description is suspiciously empty or placeholder-like, but the
completion itself is never blocked.
"""
from __future__ import annotations

import json
import sys

_PLACEHOLDERS = {"", "todo", "tbd", "wip", "work", "tmp", "test"}


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print(json.dumps({"decision": "allow"}))
        return

    subject = (data.get("task_subject") or "").strip().lower()
    if subject in _PLACEHOLDERS or len(subject) < 3:
        print(
            "task-completed-check: placeholder-like task subject "
            f"{subject!r} — consider using a descriptive title.",
            file=sys.stderr,
        )

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
