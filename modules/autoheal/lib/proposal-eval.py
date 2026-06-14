"""
Deterministic eval/regression harness for autoheal proposals (Epic #659, #705).

The structural auto-apply gate (plan.md §3.7, autoheal-auto-apply.sh) checks
only *shape*: confidence >= 9, breadth <= 1, kind == settings_allow_add,
target under modules/settings/, not snoozed, not blocked. None of those
verify that the proposal actually *improves* anything. A high-confidence,
narrow proposal that adds a useless — or worse, an over-broad — allow rule
sails straight through to auto-apply.

This module adds a behavioral precondition. A `settings_allow_add` proposal
effectively reproduces, at config time, what permission-request-suppress.py
does at runtime: it makes a (tool, command-signature) auto-allow without a
prompt. So we can score a proposal against a fixed set of representative
permission scenarios and measure whether applying it:

  * IMPROVES friction scenarios (a command the user repeatedly had to
    approve, or that was denied-by-friction, now resolves correctly), and
  * does NOT REGRESS guard scenarios (a command that must always still
    prompt or be denied is not silently auto-allowed).

A proposal passes the eval iff:

    improvements >= 1   AND   regressions == 0

The scoring is pure and deterministic — it is a script, not a judgment
(see latent-vs-deterministic). Given the same fixtures + proposal, the
verdict is always identical, which is exactly what a promotion gate needs.

----------------------------------------------------------------------------
Fixture format (tests/fixtures/eval-scenarios.json)
----------------------------------------------------------------------------

{
  "scenarios": [
    {
      "id": "git-diff-friction",
      "tool_name": "Bash",
      "command": "git diff --stat",
      "expected": "allow",   // allow | prompt | deny
      "note": "approved 5x across 3 sessions; should be auto-allowed"
    },
    ...
  ]
}

`expected` semantics, from the perspective of "what should happen to this
scenario once a GOOD config is in place":

  - "allow":  this is friction the system SHOULD eliminate. A proposal that
              causes this scenario to be auto-allowed is an IMPROVEMENT.
  - "prompt": this must keep prompting the user (not yet trusted enough). A
              proposal that auto-allows it is a REGRESSION.
  - "deny":   this must never be auto-allowed (dangerous). A proposal that
              auto-allows it is a REGRESSION (and the worst kind).

Baseline: with NO proposal applied, nothing is auto-allowed, so every
scenario "prompts". Eval measures the delta the proposal introduces.

----------------------------------------------------------------------------
Signature model
----------------------------------------------------------------------------

A scenario is "auto-allowed" by a proposal iff the proposal's added
allow-rules match the scenario's command. We reuse the same conservative
verb-prefix signature as permission-request-suppress.py so the eval models
real runtime behavior, not a parallel rule language:

  - Bash:  match on the allow-rule's inner command pattern. An allow rule
           "Bash(git diff:*)" or "Bash(git diff)" matches any command whose
           first tokens are "git diff". "Bash(git:*)" matches any git
           command (broad). "Bash(rm -rf:*)" matches "rm -rf ...".
  - Other tools: an allow rule "Read", "Read(...)", etc. matches a scenario
           whose tool_name is Read.

Env overrides (tests):
  - CCGM_AUTOHEAL_EVAL_SCENARIOS  path to the scenarios JSON (default:
                                  fixtures/eval-scenarios.json next to the
                                  module's tests/ dir).
"""
from __future__ import annotations

import json
import os
import re
import sys


# Verdict thresholds. A proposal must net-improve and never regress.
MIN_IMPROVEMENTS = 1
MAX_REGRESSIONS = 0


def _default_scenarios_path() -> str:
    """Locate the bundled fixture scenarios.

    The lib file lives at modules/autoheal/lib/proposal-eval.py; the
    fixtures live at modules/autoheal/tests/fixtures/eval-scenarios.json.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    module_root = os.path.dirname(here)
    return os.path.join(module_root, "tests", "fixtures", "eval-scenarios.json")


def scenarios_path() -> str:
    return os.environ.get("CCGM_AUTOHEAL_EVAL_SCENARIOS") or _default_scenarios_path()


def load_scenarios(path: str | None = None) -> list[dict]:
    """Load and validate the fixture scenario set.

    Raises ValueError on a malformed fixture so a broken harness fails
    loudly rather than silently passing every proposal.
    """
    p = path or scenarios_path()
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        raise ValueError(f"eval scenarios file malformed: {p}")
    out: list[dict] = []
    for s in data["scenarios"]:
        if not isinstance(s, dict):
            raise ValueError(f"scenario not an object: {s!r}")
        expected = s.get("expected")
        if expected not in ("allow", "prompt", "deny"):
            raise ValueError(
                f"scenario {s.get('id')!r} has invalid expected={expected!r}"
            )
        if not s.get("tool_name"):
            raise ValueError(f"scenario {s.get('id')!r} missing tool_name")
        out.append(s)
    if not out:
        raise ValueError("eval scenarios file has zero scenarios")
    return out


# ----------------------------------------------------------------------------
# Allow-rule extraction.
#
# A settings_allow_add proposal adds entries to a permissions.allow array.
# The proposed_diff is a unified diff against a settings JSON. We pull the
# string literals added on '+' lines that look like permission rules
# (e.g. "Bash(git diff:*)"). This is deliberately tolerant: we want every
# allow-rule the diff introduces, however the analyzer formatted it.
# ----------------------------------------------------------------------------

# Matches a JSON string literal on an added diff line, e.g.
#   +      "Bash(git diff:*)",
_ADDED_RULE_RE = re.compile(r'^\+\s*"([^"]+)"\s*,?\s*$')


def extract_added_rules(proposal: dict) -> list[str]:
    """Return the list of allow-rule strings the proposal would add.

    Reads added ('+') lines from proposed_diff, ignoring the diff header
    lines (+++ ...). Falls back to an explicit `added_rules` array on the
    proposal if present (lets the analyzer state rules directly without a
    diff parse round-trip).
    """
    explicit = proposal.get("added_rules")
    if isinstance(explicit, list) and explicit:
        return [r for r in explicit if isinstance(r, str) and r]

    diff = proposal.get("proposed_diff") or ""
    rules: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++"):
            continue
        m = _ADDED_RULE_RE.match(line)
        if not m:
            continue
        rule = m.group(1)
        # Skip structural JSON tokens that happen to be quoted strings but
        # are not permission rules (keys like "allow", "permissions").
        if rule in ("allow", "deny", "ask", "permissions"):
            continue
        rules.append(rule)
    return rules


# ----------------------------------------------------------------------------
# Signature matching.
#
# Mirror permission-request-suppress.py's verb-prefix model so the eval
# predicts real runtime behavior. A rule "auto-allows" a scenario when the
# rule's tool + command-prefix subsumes the scenario's command.
# ----------------------------------------------------------------------------

# Parse a permission rule into (tool_name, inner). Examples:
#   "Bash(git diff:*)" -> ("Bash", "git diff:*")
#   "Bash(git diff)"   -> ("Bash", "git diff")
#   "Read(/etc/*)"     -> ("Read", "/etc/*")
#   "Read"             -> ("Read", None)
_RULE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(?:\((.*)\))?$")


def parse_rule(rule: str) -> tuple[str, str | None] | None:
    m = _RULE_RE.match(rule.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _bash_command_prefix(inner: str) -> str:
    """Normalize a Bash rule's inner pattern to its command prefix.

    Strips a trailing ':*' or '*' wildcard so "git diff:*" and "git diff"
    both reduce to "git diff". Commands are case-sensitive on POSIX, so we
    keep case.
    """
    inner = inner.strip()
    for suffix in (":*", ":", "*"):
        if inner.endswith(suffix):
            inner = inner[: -len(suffix)]
            break
    return inner.strip()


def rule_allows(rule: str, tool_name: str, command: str) -> bool:
    """Does this single allow-rule auto-allow the given (tool, command)?

    Bash rules match when the rule's command prefix is a token-prefix of the
    scenario command. "git diff" matches "git diff --stat" but NOT
    "git difftool"; matching is on whole tokens, not substrings, so a narrow
    rule cannot accidentally subsume an unrelated command.

    Non-Bash rules match purely on tool_name (an unparameterized "Read"
    rule auto-allows any Read). A parameterized non-Bash rule
    ("Read(/etc/*)") matches the tool and is treated as auto-allowing that
    tool for eval purposes (path-glob nuance is out of scope; the gate is
    conservative by requiring zero regressions).
    """
    parsed = parse_rule(rule)
    if parsed is None:
        return False
    rule_tool, inner = parsed
    if rule_tool != tool_name:
        return False

    if tool_name == "Bash":
        if inner is None:
            # Bare "Bash" allows everything — by far the broadest rule.
            return True
        prefix = _bash_command_prefix(inner)
        if not prefix:
            return True
        cmd_tokens = command.strip().split()
        pre_tokens = prefix.split()
        if len(pre_tokens) > len(cmd_tokens):
            return False
        return cmd_tokens[: len(pre_tokens)] == pre_tokens

    # Non-Bash: tool match is sufficient for the eval model.
    return True


def proposal_auto_allows(rules: list[str], tool_name: str, command: str) -> bool:
    """True iff ANY of the proposal's added rules auto-allows the scenario."""
    return any(rule_allows(r, tool_name, command) for r in rules)


# ----------------------------------------------------------------------------
# Scoring.
# ----------------------------------------------------------------------------


def score_proposal(proposal: dict, scenarios: list[dict]) -> dict:
    """Replay every scenario under the proposal; tally improvements/regressions.

    Returns a structured result:
        {
          "passed": bool,
          "improvements": int,
          "regressions": int,
          "neutral": int,
          "added_rules": [...],
          "details": [ {scenario_id, expected, auto_allowed, verdict}, ... ],
          "reason": "<human-readable summary>",
        }

    Per-scenario verdicts:
      - "improvement": expected == "allow" AND the proposal auto-allows it.
      - "regression":  expected in ("prompt","deny") AND the proposal
                       auto-allows it.
      - "neutral":     everything else (expected allow but not matched =
                       missed-but-harmless; expected prompt/deny and not
                       matched = correctly left alone).
    """
    rules = extract_added_rules(proposal)
    improvements = 0
    regressions = 0
    neutral = 0
    details: list[dict] = []

    for s in scenarios:
        tool_name = str(s.get("tool_name", ""))
        command = str(s.get("command", ""))
        expected = s.get("expected")
        auto_allowed = proposal_auto_allows(rules, tool_name, command)

        if expected == "allow" and auto_allowed:
            verdict = "improvement"
            improvements += 1
        elif expected in ("prompt", "deny") and auto_allowed:
            verdict = "regression"
            regressions += 1
        else:
            verdict = "neutral"
            neutral += 1

        details.append(
            {
                "scenario_id": s.get("id"),
                "expected": expected,
                "auto_allowed": auto_allowed,
                "verdict": verdict,
            }
        )

    passed = improvements >= MIN_IMPROVEMENTS and regressions <= MAX_REGRESSIONS

    if not rules:
        reason = "no allow-rules extracted from proposal; nothing to evaluate"
    elif regressions > 0:
        reason = (
            f"{regressions} regression(s): proposal would auto-allow a "
            f"scenario that must keep prompting or be denied"
        )
    elif improvements < MIN_IMPROVEMENTS:
        reason = (
            f"no improvement: proposal resolves 0 friction scenarios "
            f"(need >= {MIN_IMPROVEMENTS})"
        )
    else:
        reason = f"pass: {improvements} improvement(s), 0 regression(s)"

    return {
        "passed": passed,
        "improvements": improvements,
        "regressions": regressions,
        "neutral": neutral,
        "added_rules": rules,
        "details": details,
        "reason": reason,
    }


def evaluate(proposal: dict, scenarios_file: str | None = None) -> dict:
    """High-level entry: load fixtures, score one proposal, return the result."""
    scenarios = load_scenarios(scenarios_file)
    return score_proposal(proposal, scenarios)


# ----------------------------------------------------------------------------
# CLI: `python proposal-eval.py <proposal-json-file> [scenarios-file]`
#
# Reads a single proposal record (one JSON object, NOT a JSONL stream) from
# the given path, scores it, prints the JSON result to stdout, and exits:
#   0  proposal passes the eval (safe to promote)
#   1  proposal fails the eval (block promotion)
#   2  usage / load error
#
# A '-' path reads the proposal JSON from stdin so the gate script can pipe.
# ----------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write(
            "usage: proposal-eval.py <proposal-json|-> [scenarios-file]\n"
        )
        return 2

    src = argv[1]
    scenarios_file = argv[2] if len(argv) >= 3 else None

    try:
        if src == "-":
            proposal = json.load(sys.stdin)
        else:
            with open(src, "r", encoding="utf-8") as fh:
                proposal = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"failed to read proposal: {exc}\n")
        return 2

    if not isinstance(proposal, dict):
        sys.stderr.write("proposal must be a single JSON object\n")
        return 2

    try:
        result = evaluate(proposal, scenarios_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"eval failed: {exc}\n")
        return 2

    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv))
