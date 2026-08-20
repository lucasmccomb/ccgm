#!/usr/bin/env python3
"""
UserPromptSubmit hook: while advisor mode is on, remind each turn that the
session is an orchestrator.

The guard (advisor-guard.py) enforces the posture mechanically; this injection
explains it so the model delegates instead of fighting denials. Adapted from
baton's orchestrator-mode injection pattern. One stat() per prompt when the
mode is off.
"""

import json
import os
import sys

FLAG_ENV = "CCGM_ADVISOR_FLAG"

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


def main():
    flag = os.environ.get(FLAG_ENV) or os.path.join(
        os.path.expanduser("~"), ".claude", "advisor-mode")
    if not os.path.isfile(flag):
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CONTEXT,
        },
        "suppressOutput": True,
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
