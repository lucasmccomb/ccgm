#!/usr/bin/env python3
"""
SubagentStop hook: deterministic replacement for the former prompt-type hook.

Previous version fired a Haiku call on every subagent stop to judge whether
the agent "completed its task." In practice it over-blocked because the
hook input does not include enough transcript context for reliable judgment,
and it added up to 15s of latency per stop event.

This version checks only the unambiguous failure mode:
- Allow when stop_hook_active is set (loop protection).
- Block only when last_assistant_message is empty or whitespace-only.
- Allow otherwise.

Completion discipline is enforced upstream by the subagent-patterns rules
(DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT protocol) and by the
reviewer agents, not by static analysis of a single message.
"""
from __future__ import annotations

import json
import sys


def respond(decision: str, reason: str | None = None) -> None:
    payload: dict = {"decision": decision}
    if reason:
        payload["reason"] = reason
    print(json.dumps(payload))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        respond("allow")
        return

    if data.get("stop_hook_active"):
        respond("allow")
        return

    last = (data.get("last_assistant_message") or "").strip()
    if not last:
        respond(
            "block",
            "Your last response is empty. Produce a final message describing "
            "what you did, or declare BLOCKED / NEEDS_CONTEXT with specifics, "
            "before stopping.",
        )
        return

    respond("allow")


if __name__ == "__main__":
    main()
