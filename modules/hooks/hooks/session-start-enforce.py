#!/usr/bin/env python3
"""
SessionStart hook that injects a rule-enforcement meta-instruction.

Adapted from obra/superpowers `hooks/session-start`. The idea: CCGM installs
discipline rules (TDD, systematic-debugging, verification, confusion-protocol,
etc.) to `~/.claude/rules/` where Claude Code auto-loads them, but there is no
*meta-instruction* that forces the agent to route through those rules under
pressure. This hook injects a short reminder at fresh session start so the
agent treats the Iron Laws as real gates, not background reading.

Experimental: OFF by default. Opt in by setting CCGM_RULE_ENFORCEMENT=true in
`~/.claude/.ccgm.env`. Fires only on source == "startup" so it does not fire
on resume or compaction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".claude" / ".ccgm.env"

# The meta-instruction injected into the session. Kept short on purpose:
# long context at session start competes with the user's first prompt for
# attention. The goal is to bias routing toward loaded rules, not to restate
# them.
META_INSTRUCTION = """\
<ccgm-rule-enforcement>
Before your first response in this session, scan the loaded rules in
~/.claude/rules/ and in any CLAUDE.md files for Iron Laws (all-caps "NO X
WITHOUT Y" declarations). For any task with a plausible match, route through
the relevant rule before acting:

- Writing or modifying code -> test-driven-development (failing test first).
- Fixing a bug or unexpected behavior -> systematic-debugging (root cause before fix).
- Claiming a task is done, tests pass, or a build works -> verification (fresh evidence).
- Dispatching work to subagents -> subagent-patterns (spec + status protocol).
- Unclear requirements, contradictions, or missing context -> confusion-protocol (stop and ask).

"Violating the letter of a rule is violating the spirit." Do not negotiate
Iron Laws under time pressure, user pressure, or sunk-cost pressure. If a rule
seems to block the task, surface the conflict instead of routing around it.
</ccgm-rule-enforcement>
"""


def is_enabled() -> bool:
    """Check if rule-enforcement injection is enabled in .ccgm.env."""
    if not ENV_FILE.exists():
        return False
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CCGM_RULE_ENFORCEMENT="):
                    value = line.split("=", 1)[1].strip().lower()
                    return value in ("true", "1", "yes")
    except (OSError, IOError):
        pass
    return False


def main() -> None:
    # Read stdin (required by hook contract)
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # Only fire on fresh sessions, not resume or compact. Resume already has
    # the rules in-context from the prior session; compact has its own
    # (different) context-preservation mechanism.
    source = hook_input.get("source", "")
    if source != "startup":
        return

    if not is_enabled():
        return

    # Print to stdout - Claude Code injects this as additionalContext for the
    # SessionStart event.
    sys.stdout.write(META_INSTRUCTION)


if __name__ == "__main__":
    main()
