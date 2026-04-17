# Fix-First Review Output

**Iron Law:** MECHANICAL FIXES ARE APPLIED BY THE REVIEWER. TASTE CALLS ARE BATCHED INTO ONE QUESTION.

Violating the letter of this rule is violating the spirit of this rule. A review that returns a checklist of 30 nits and asks the author to process each one has failed. A review that silently rewrites the intent of the code has also failed. Fix-First formalizes the line between them.

**Announce at start:** "I'm using the Fix-First review format. Mechanical findings auto-applied; taste calls batched."

## Scope

This rule governs the output format of any PR review produced by:

- The external `pr-review-toolkit` plugin's `/review-pr` command
- The `scope-drift` skill in this module
- Any CCGM command or skill that reviews a diff and proposes fixes

It does NOT govern debugging output, architecture discussions, or free-form code commentary. Those are conversations; reviews are decision support.

## The Two Buckets

Every finding lands in exactly one of two buckets.

### `**AUTO-FIXED:**` - Reviewer applied, reports what changed

Findings where:

- The fix is mechanical or obvious
- There is exactly one reasonable way to resolve it
- The change cannot plausibly break behavior
- No subjective judgment is required

Examples:

- Unused import removed
- `const` inferred where `let` had no reassignment
- Missing semicolon, trailing comma, or prettier/linter-driven formatting
- Typo in a string literal or comment
- Dead code reachable only by a branch that was already deleted
- TODO comment referring to a closed ticket
- `console.log` left behind from debugging
- `any` replaced with the obvious inferred type when the context makes it unambiguous
- Reserved-keyword identifier in a migration quoted

For each AUTO-FIXED finding, apply the edit, then record:

```
- {file}:{line} - {what was changed} - applied
```

Attach a unified diff at the bottom of the report if the auto-fix edits are numerous.

### `**NEEDS INPUT:**` - Batched into one user question

Findings where:

- Multiple valid resolutions exist
- The fix implies a product, architecture, or UX decision
- Behavior could change in a way the author did not intend
- A tradeoff (performance vs clarity, flexibility vs simplicity) is in play
- The finding is a suspicion, not a confirmed bug

Examples:

- An API contract change that affects callers
- A function longer than comfortable but with a plausible reason to stay monolithic
- A choice between two valid error-handling strategies
- A new dependency added to solve a problem that could be solved with the standard library
- A naming choice that is not wrong but is unusual for the codebase
- An apparent race condition that may or may not actually be reachable
- Missing tests for a branch where the correct assertion is unclear

Do NOT ask separate questions for each NEEDS INPUT finding. Group them into one `AskUserQuestion` call with the findings as options or numbered items.

Record each as:

```
- {file}:{line} - {finding} - {why it needs input} - {proposed direction}
```

Then issue the single batched question.

## Fix-First Heuristic

When deciding which bucket a finding lands in, run this check:

1. **Can I state the fix in one unambiguous sentence?** If no, NEEDS INPUT.
2. **Does the fix change observable behavior?** If yes, NEEDS INPUT.
3. **Would two competent engineers write the same fix?** If no, NEEDS INPUT.
4. **Is the fix larger than ~5 lines?** If yes, lean NEEDS INPUT (show the diff, let the author decide).
5. **Does the codebase have an established pattern for this case?** If yes, AUTO-FIX to match. If no, NEEDS INPUT.

When in doubt, NEEDS INPUT. A surprise auto-fix is more costly than one extra question.

## Output Template

Every review that uses this format produces output shaped like:

```markdown
## Review Summary

**Scope**: {scope-drift verdict from scope-drift skill, if used}
**Specialists run**: {code-reviewer, silent-failure-hunter, ...}

### AUTO-FIXED ({count})

- {file}:{line} - {change} - applied
- {file}:{line} - {change} - applied
- ...

### NEEDS INPUT ({count})

Batched question follows. Please answer once:

1. {file}:{line} - {finding} - {proposed direction}
2. {file}:{line} - {finding} - {proposed direction}
3. ...

### Strengths (optional)

- {what is well done in this PR}

### Next Step

{If AUTO-FIXED count > 0: "Review the applied edits in the attached diff."}
{If NEEDS INPUT count > 0: "Answer the batched question to proceed."}
{If both are zero: "No changes requested. Ready to merge."}
```

## Severity Is Not a Bucket

Do NOT split the output into Critical / Important / Suggestion tiers the way the external `pr-review-toolkit` default prompt does. Severity belongs inside each bucket:

- An AUTO-FIXED finding can be critical (e.g., a reserved keyword causing a migration failure) or cosmetic (trailing whitespace). Either way, reviewer applies it.
- A NEEDS INPUT finding can be critical (e.g., potential race) or cosmetic (naming preference). Either way, reviewer asks.

The bucket is about who acts; severity is about how much it matters. Keep them orthogonal and you get concise, actionable reviews.

## When Fix-First Does Not Apply

- Initial architectural review where no code exists yet (all findings are NEEDS INPUT by construction).
- Reviews of work the reviewer did not write and does not have edit access to.
- Reviews where the author explicitly said "just comment, do not edit."

In those cases, state upfront that Fix-First is suspended and fall back to the plugin's default format.

## Source

Adapted from garrytan/gstack's `review/checklist.md` Fix-First Heuristic.
