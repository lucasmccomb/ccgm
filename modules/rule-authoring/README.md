# rule-authoring

Discipline for writing rules that hold up when an agent is under pressure to cut corners.

## What It Does

Treats rule authoring as TDD. A rule is not finished because it reads well; it is finished when an agent under stress still follows it. This module installs:

- **`rules/rule-authoring.md`** - the iron-law framing for rule authoring itself, the required structural elements (Iron Law, rationalization table, Red Flags list, Announce-at-start), and the four-state subagent protocol used when dispatching pressure tests.
- **`rules/pressure-testing.md`** - the concrete methodology: pick a candidate rule, generate 5-10 adversarial scenarios, run them in subagents with and without the rule loaded, capture the rationalizations verbatim, rewrite the rule to close those loopholes, and repeat.
- **`commands/pressure-test.md`** - an interactive slash command that walks through the pressure-testing loop against a candidate rule file.

## Why This Exists

CCGM already has `/copycat` (steal good rules from other configs) and `/promote-rule` (move repo rules to global). Neither validates that a newly written rule actually changes agent behavior. Rules written from armchair intuition get explained away under pressure. This module closes that gap.

The methodology is adapted from obra/superpowers' `writing-skills` discipline, which treats skill authoring as RED-GREEN-REFACTOR: run pressure scenarios without the rule (RED), watch agents rationalize, then write the rule to address those specific rationalizations (GREEN), then close new loopholes that emerge (REFACTOR). Meincke et al. (2025) showed persuasion techniques roughly double LLM compliance with undesirable requests (33% to 72%). A rule that does not anticipate those persuasion vectors will be explained away.

## How It Fits

| Command | Purpose |
|---------|---------|
| `/copycat` | Find good rules in other repos |
| `/promote-rule` | Move repo-level rules to global |
| `/pressure-test` | Validate a rule actually changes behavior before shipping |

`/pressure-test` runs after a candidate rule is drafted and before it lands in `~/.claude/rules/`. It should be standard practice for any rule that enforces a non-negotiable discipline (TDD, verification, systematic debugging, safety protocols).

## Manual Installation

```bash
# Global (all projects)
cp rules/rule-authoring.md ~/.claude/rules/rule-authoring.md
cp rules/pressure-testing.md ~/.claude/rules/pressure-testing.md
cp commands/pressure-test.md ~/.claude/commands/pressure-test.md

# Project-level
cp rules/rule-authoring.md .claude/rules/rule-authoring.md
cp rules/pressure-testing.md .claude/rules/pressure-testing.md
cp commands/pressure-test.md .claude/commands/pressure-test.md
```

## Files

| File | Description |
|------|-------------|
| `rules/rule-authoring.md` | Authoring discipline for rules: Iron Law framing, required structural elements, four-state subagent protocol |
| `rules/pressure-testing.md` | Concrete methodology for pressure-testing a candidate rule with adversarial scenarios |
| `commands/pressure-test.md` | Interactive slash command for running the pressure-testing loop |
