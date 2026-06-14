"""In-process hook composition dispatcher with declarative precedence.

Problem this solves
-------------------
Today every Claude Code event fans out into one OS process per registered
hook script (see modules/*/settings.partial.json). A single PreToolUse:Bash
tool call spawns six python interpreters in sequence, each re-importing
hook_utils, each re-parsing stdin. There is also no explicit, testable
ordering contract: precedence is an emergent property of the array order in
settings.json across several modules that do not know about each other.

This module provides a *backward-compatible* alternative: a single dispatcher
per event that runs a DECLARATIVE manifest of checks in-process, by priority,
with an explicit precedence resolution that exactly mirrors the behavior the
separate-process chain produces today:

    hard_block (exit 2)  >  deny  >  allow  >  ask  >  (advisory / pass)

Precedence guarantees (the safety contract — preserved bit-for-bit):

  * The FIRST hard_block wins and is emitted via hook_utils.hard_block()
    (exit 2). This is the only signal Claude Code honors regardless of
    permission_mode (GitHub issue #39344), so it survives bypass mode.
  * A `deny` beats any `allow`. If any check denies and none hard-block,
    the dispatcher emits deny.
  * An `allow` is emitted only if some check allows and nothing denies or
    hard-blocks.
  * `ask` is the weakest decision; it is emitted only if nothing above it
    fired.
  * Advisory output (stderr warnings) NEVER affects the decision and is
    flushed for every matching check whose result carries it, regardless
    of which decision ultimately wins.
  * Bypass-mode short-circuit: a check may declare `runs_in_bypass=False`.
    Such checks are skipped when hook_utils.is_bypass_mode() is true. Checks
    that must survive bypass (the curated destructive set, data-integrity
    hard blocks, protected-branch enforcement) declare `runs_in_bypass=True`
    and run ABOVE the short-circuit — exactly the current arrangement in
    auto-approve-bash.py and check-careful.py.

The dispatcher does NOT replace hook_utils; it composes its primitives.
redact_secrets-before-truncation, fcntl file locking, and bypass detection
all continue to live in hook_utils and are reused unchanged.

Coexistence
-----------
This is additive. Installing the dispatcher does not remove or rewrite any
existing hook. A module may migrate onto the dispatcher by registering a
single entry hook that calls dispatch(); modules not yet migrated keep their
own settings.partial.json entries and run on the legacy per-process path.
The two paths produce identical decisions because the dispatcher's precedence
rules are derived from the legacy chain's observed behavior.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_utils  # noqa: E402

__all__ = [
    "ALLOW",
    "DENY",
    "ASK",
    "HARD_BLOCK",
    "PASS",
    "DECISION_RANK",
    "Result",
    "Check",
    "Manifest",
    "dispatch",
    "tool_matcher",
]

# ─── Decision vocabulary ─────────────────────────────────────────────
# Ranked weakest → strongest. A larger rank wins precedence.
PASS = "pass"            # check did not fire; no opinion
ASK = "ask"              # request a permission prompt (suppressible in bypass)
ALLOW = "allow"          # auto-approve
DENY = "deny"            # block (overridable by hard_block, beats allow)
HARD_BLOCK = "hard_block"  # bypass-proof block via exit 2

DECISION_RANK = {
    PASS: 0,
    ASK: 1,
    ALLOW: 2,
    DENY: 3,
    HARD_BLOCK: 4,
}


@dataclass
class Result:
    """What a single check decided.

    `decision` is one of the decision-vocabulary constants. `reason` is the
    human-readable explanation surfaced to Claude / the user. `advisory` is
    optional stderr text that is ALWAYS printed (it never participates in the
    decision) — this is how port-check / agent-tracking-style warnings are
    represented without giving them blocking power.
    """

    decision: str = PASS
    reason: str = ""
    advisory: str = ""

    def __post_init__(self) -> None:
        if self.decision not in DECISION_RANK:
            raise ValueError(f"unknown decision: {self.decision!r}")


# A handler receives the full hook envelope (the parsed stdin dict) and
# returns a Result. It must be pure with respect to the decision (no
# sys.exit, no printing of permission JSON) — the dispatcher owns emission.
Handler = Callable[[dict], "Result"]


def tool_matcher(*tool_names: str) -> Callable[[dict], bool]:
    """Build a matcher that fires only for the named tools.

    Mirrors settings.json `matcher` semantics: a check registered for "Bash"
    only runs when tool_name == "Bash". An empty matcher (no names) matches
    every tool, mirroring a settings.json block with no `matcher` key.
    """
    wanted = frozenset(tool_names)

    def _match(data: dict) -> bool:
        if not wanted:
            return True
        return data.get("tool_name", "") in wanted

    return _match


@dataclass
class Check:
    """A declarative entry in a dispatcher manifest.

    Fields:
      priority      Lower runs first. Hard-block-capable checks that must beat
                    a downstream allow are given a smaller number so they are
                    evaluated before it. (Precedence resolution does NOT rely
                    on priority alone — DECISION_RANK is authoritative — but
                    priority fixes a deterministic, documented run order and
                    decides ties between same-rank decisions: first wins.)
      name          Stable identifier (used in tests + audit).
      matches       Predicate over the hook envelope; True ⇒ run the handler.
      handler       Callable returning a Result.
      runs_in_bypass  If False, the check is SKIPPED in bypass mode. Safety
                    checks that must survive bypass set this True.
      short_circuit If True, ANY decisive (non-PASS) result from this check is
                    emitted immediately without consulting later checks. This
                    reproduces a legacy hook that calls emit_decision()/
                    hard_block() and exits the instant it fires — e.g. the
                    curated destructive set (hard_block) and the
                    git-reset-to-remote smart-rule (allow), both of which the
                    standalone auto-approve-bash.py emits before any later
                    check runs. A PASS never short-circuits regardless of this
                    flag (a check with no opinion yields to the rest).
    """

    priority: int
    name: str
    matches: Callable[[dict], bool]
    handler: Handler
    runs_in_bypass: bool = True
    short_circuit: bool = False


@dataclass
class Manifest:
    """An ordered set of checks for one event (optionally one tool)."""

    event: str
    checks: list = field(default_factory=list)

    def add(self, check: "Check") -> "Manifest":
        self.checks.append(check)
        return self

    def ordered(self) -> list:
        # Stable sort by priority; registration order breaks ties.
        return sorted(self.checks, key=lambda c: c.priority)


def _emit_and_exit(decision: str, reason: str) -> None:
    """Emit a decision through the hook_utils primitives and terminate.

    hard_block → exit 2 (bypass-proof). deny/allow/ask → JSON on stdout,
    exit 0. The dispatcher routes EVERY winning decision through these same
    primitives so behavior is identical to a standalone hook calling them.
    """
    if decision == HARD_BLOCK:
        hook_utils.hard_block(reason or "hard-blocked")
    if decision in (ALLOW, DENY, ASK):
        hook_utils.emit_decision(decision, reason)
    # PASS: no output, exit 0.
    sys.exit(0)


def dispatch(manifest: "Manifest", data: Optional[dict] = None) -> None:
    """Run the manifest's checks in-process and emit the winning decision.

    This function does not return on a decisive outcome — it calls
    hook_utils.hard_block() (exit 2) or hook_utils.emit_decision() (exit 0),
    exactly as a standalone hook would. On PASS it exits 0.

    Execution model (mirrors the legacy per-process chain):

      1. Read the envelope once (data is read here if not supplied) — replaces
         N separate stdin reads with one.
      2. Determine bypass mode once.
      3. For each check in priority order:
           a. Skip if its matcher does not match the tool.
           b. Skip if bypass mode is active AND the check is not bypass-safe.
           c. Run the handler.
           d. Always flush any advisory text to stderr (never blocks).
           e. If the result is a hard_block AND the check is short_circuit,
              emit it immediately (nothing can override the curated
              destructive set).
           f. Otherwise track the strongest decision seen so far (ties keep
              the earlier check, matching first-wins chain order).
      4. After all checks, emit the strongest tracked decision.

    Precedence is governed by DECISION_RANK, so the final outcome is
    independent of how many checks fired: one hard_block beats any number of
    allows; one deny beats any number of allows; etc.
    """
    if data is None:
        data = hook_utils.read_hook_input()

    bypass = hook_utils.is_bypass_mode(data)

    best_decision = PASS
    best_reason = ""

    for check in manifest.ordered():
        if not check.matches(data):
            continue
        if bypass and not check.runs_in_bypass:
            continue

        result = check.handler(data)

        # Advisory output is decision-independent and always surfaced.
        if result.advisory:
            sys.stderr.write(result.advisory.rstrip("\n") + "\n")
            sys.stderr.flush()

        if result.decision == PASS:
            continue

        # A short-circuit check emits its decisive result immediately — this
        # reproduces a legacy hook that calls emit_decision()/hard_block() and
        # exits the instant it fires (the curated destructive set's hard_block
        # and the smart-rule's allow both behave this way standalone). No later
        # check can override a short-circuited decision.
        if check.short_circuit:
            _emit_and_exit(result.decision, result.reason)

        # Otherwise, keep the strongest decision. First-wins on ties keeps
        # the priority-ordered chain's behavior (an earlier deny's reason is
        # the one surfaced).
        if DECISION_RANK[result.decision] > DECISION_RANK[best_decision]:
            best_decision = result.decision
            best_reason = result.reason

    _emit_and_exit(best_decision, best_reason)
