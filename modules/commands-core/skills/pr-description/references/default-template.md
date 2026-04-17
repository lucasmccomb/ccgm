# Default PR Body Template (value-first, no repo template found)

Use this structure when the target repo does not ship a PR template under the four paths the skill checks.

```markdown
Closes #{issue_number}

{One-sentence summary of what the PR does, in user-facing terms.}

## Why

{Two sentences max. What problem this solves, or what capability it unlocks.
Lead with the user outcome, not the implementation.}

## What Changed

- {Concrete change as a noun phrase with a verb}
- {...}
- {...}

## Test Plan

- {Named command or manual step, one line each}
- {...}

## Notes

{Optional. Include only if there is real carry-over work, a follow-up issue,
or a known limitation. Delete the section if empty.}
```

## Rules

- `Closes #N` goes on the first line, alone. GitHub uses it to auto-close the issue on merge.
- No `Co-Authored-By: Claude`, `Generated with Claude Code`, or any AI-attribution footer.
- If a section has nothing real to say, omit it rather than padding with filler.
- Keep bullets under ~12 words each. Long bullets are a sign the change should be split.

## When to Skip the Default

If any of these are true, do NOT use this template - the skill should have detected and used the repo's own template instead:

- A file named `pull_request_template.md` or `PULL_REQUEST_TEMPLATE.md` exists in the repo root
- A file exists under `.github/` with either casing
- The org's `.github` repo ships a default template (rare; check only if repo-level search returns nothing)
