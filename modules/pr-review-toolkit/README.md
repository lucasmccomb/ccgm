# pr-review-toolkit

Augments the external `pr-review-toolkit` plugin (from `claude-plugins-official`) with two capabilities ported from garrytan/gstack's review skill:

1. **Scope-drift detection** - before code-quality review, compare stated intent against the actual diff. Classify every plan item as DONE / PARTIAL / NOT DONE / CHANGED. Flag out-of-scope changes. Gate only on HIGH-impact findings.
2. **Fix-First output format** - split review findings into two buckets. `AUTO-FIXED` findings are applied by the reviewer and reported. `NEEDS INPUT` findings are batched into a single user question. No more 30-item nit checklists.

These run alongside the external plugin's specialist agents (`code-reviewer`, `silent-failure-hunter`, `pr-test-analyzer`, `type-design-analyzer`, `comment-analyzer`, `code-simplifier`). Scope-drift runs first; Fix-First governs the output of the specialists and the final summary.

## What It Does

### `skills/scope-drift/SKILL.md`

A playbook the agent follows at the start of any PR review:

- Pull intent from PR body, closed issue, commit messages, and any plan file in the repo
- Extract up to 50 actionable items
- Walk the diff and classify each item against the code that actually shipped
- Walk the diff in reverse to flag changes that map to no stated item
- Rate impact HIGH / MEDIUM / LOW
- Gate only on HIGH items via a single `AskUserQuestion`
- Emit a `plan-delivery-gap` learning line for HIGH findings

### `rules/fix-first-review.md`

A global review format rule:

- Every finding is either `AUTO-FIXED` (mechanical, applied immediately) or `NEEDS INPUT` (taste, batched)
- Fix-First heuristic: five one-line checks that decide the bucket
- Severity is not a bucket (it belongs inside each bucket)
- Explicit opt-out conditions (architectural review, no-edit-access reviews)

## Manual Installation

```bash
# Skill
mkdir -p ~/.claude/skills/scope-drift
cp skills/scope-drift/SKILL.md ~/.claude/skills/scope-drift/SKILL.md

# Rule
cp rules/fix-first-review.md ~/.claude/rules/fix-first-review.md
```

## Files

| File | Target | Description |
|------|--------|-------------|
| `skills/scope-drift/SKILL.md` | `~/.claude/skills/scope-drift/SKILL.md` | Intent-versus-diff audit skill |
| `rules/fix-first-review.md` | `~/.claude/rules/fix-first-review.md` | Two-bucket output format rule |

## Relationship to the External Plugin

The external `pr-review-toolkit@claude-plugins-official` plugin provides the `/pr-review-toolkit:review-pr` command and six specialist agents. This CCGM module does not replace it; it installs additional guidance that the agent reads at session start (the rule) or invokes on demand (the skill).

When running `/pr-review-toolkit:review-pr`, the agent should:

1. Invoke the `scope-drift` skill first
2. Run the external plugin's specialists
3. Format the combined output per `fix-first-review.md`

## Source

Copycat port of items 5 and 6 from `~/code/plans/ccgm-copycat-analysis/gstack.md`. Issue #293.
