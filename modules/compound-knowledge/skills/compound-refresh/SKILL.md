---
name: compound-refresh
description: >
  Periodic maintenance pass over docs/solutions/. For each doc, classify as Keep / Update / Consolidate / Replace / Delete based on staleness, referenced-code existence, and overlap with newer learnings. Run monthly or after a major refactor. Modes - interactive, autofix, report-only.
  Triggers: compound refresh, clean up solutions docs, docs/solutions maintenance, solution doc audit.
disable-model-invocation: true
---

# /compound-refresh - Maintain docs/solutions/

`/compound` writes new learnings; `/compound-refresh` reviews existing ones. Over time, solution docs go stale:

- The code they reference gets deleted or moved
- A newer doc supersedes them
- Multiple adjacent docs should merge into one
- The underlying problem stopped being a problem

This skill walks `docs/solutions/**/*.md` in the current repo and classifies each doc into one of five outcomes, then applies (or reports) the classification.

## When to Run

Run `/compound-refresh`:

- Monthly, as a standing maintenance chore
- After a major refactor that moves or deletes files many solution docs reference
- Before a milestone that will attract new contributors (clean docs help onboarding)
- When retrieval feels noisy - too many false-positive hits from `learnings-researcher`

Do NOT run during active feature work - the autofix mode will create a large diff that muddies the signal of the feature branch.

## Mode Selection

Parse `$ARGUMENTS` for a mode token:

- `mode:interactive` (default) - Classify, then ask per-doc before applying any change
- `mode:autofix` - Apply `Keep`, `Update`, and `Delete` automatically; ask for `Consolidate` and `Replace`
- `mode:report-only` - Strictly read-only; print the classification table and exit

When composed from other skills (e.g., called from a repo-wide `/audit`), prefer `mode:report-only` so the caller decides.

## Phase 1: Inventory

Use the native file-search tool (e.g., Glob) to list every `docs/solutions/**/*.md` in the current repo. Skip `docs/solutions/README.md`.

For each doc, read the frontmatter and the body. Record:

- Path
- Frontmatter fields (`title`, `date`, `problem_type`, `category`, `tags`, `files`, `related`, `severity`)
- File mtime (`git log -1 --format=%ct {path}` for the last change time)
- Body length in lines

Skip any doc with invalid frontmatter - surface it at the end as a validation failure for the user to fix before re-running.

## Phase 2: Staleness Probes

For each doc, run two probes in parallel across docs (one per file at a time per doc):

### Probe A: Referenced Code Still Exists

For each path in frontmatter `files`:

- Use the native file-search tool to check if the path exists
- If the path is a file that has been moved, `git log --follow -- {path}` finds the new location
- If the file still exists, grep it for any identifiers or line ranges referenced in the body (function names, class names, error strings)

Record:

- `files_missing`: count of files no longer present
- `files_moved`: count of files that moved
- `identifiers_missing`: count of named symbols in the body no longer present in the code

### Probe B: Age vs Severity

Compute age in days from the frontmatter `date`. Combine with `severity`:

| Severity | Stale after |
|----------|-------------|
| P0 | 180 days |
| P1 | 270 days |
| P2 | 365 days |
| P3 | 540 days |

Rationale: higher severity issues are more likely to have been patched at the root by follow-up work; lower severity evergreen-knowledge docs age slower.

Record:

- `age_days`
- `is_aged`: true if `age_days` > threshold for that severity

## Phase 3: Classify

For each doc, output one of five outcomes:

### Keep

Criteria (all must hold):

- `files_missing` == 0
- `identifiers_missing` == 0
- No newer doc supersedes it (no other doc with `related: [this-path]` and a later `date`)
- `is_aged` is false OR the doc is `problem_type: knowledge` and still accurate

Action: none.

### Update

Criteria (any one holds):

- `files_moved` > 0 and `files_missing` == 0 (paths need rewriting but the substance is intact)
- `is_aged` is true but the substance still applies (re-date, optionally freshen language)
- Minor drift from a newer related doc but the two cover different angles

Action: rewrite paths, bump `date`, refresh stale wording. Preserve the substance.

### Consolidate

Criteria:

- Two or more docs share a root cause and a fix, or a tag set of 3+ common tags, and their combined content would be clearer as one doc

Action: Merge content, pick the best slug, set the merged doc's `related: []` to the other paths (now deleted), and `git rm` the obsolete files in the same commit.

### Replace

Criteria:

- `files_missing` > 0 AND a newer doc already exists that correctly captures the current state
- The doc's `solution` is now wrong (contradicted by the current codebase) but the problem described is real and has a better documented fix elsewhere

Action: Delete this doc. If the replacement doc does not reference it, add a `related` entry to the replacement pointing at the deleted slug in case of link collisions.

### Delete

Criteria (any one holds):

- `files_missing` counts the majority of `files` in frontmatter (the doc is about code that no longer exists)
- The underlying problem has been fixed at the root and the fix is documented in code comments or in a rule file
- The doc is a duplicate of another with the same `root_cause` and no additional content

Action: `git rm` the file. If other docs reference it in their `related` list, remove those references in the same commit.

## Phase 4: Apply or Report

### Interactive Mode

For each doc classified as anything other than `Keep`:

1. Print the classification, the reasoning in one line, and a summary of the proposed action
2. Use an AskUserQuestion with options: `Apply | Skip | Show Details`
3. On `Show Details`, print the full doc and any supersession candidates
4. On `Apply`, execute the action; on `Skip`, move to the next doc

### Autofix Mode

Apply `Keep`, `Update`, and `Delete` without prompting. For `Consolidate` and `Replace`, batch the pending items at the end and ask once per category.

Write a run artifact at `docs/solutions/.refresh/{YYYYMMDD-HHMM}.md` summarizing:

- Count of each outcome
- Every path touched, with the outcome
- Any failures or skipped items

### Report-Only Mode

Print the classification table, one row per doc:

```
Path                                                     Outcome    Reason
docs/solutions/build-errors/vite-preflight.md            Keep       -
docs/solutions/build-errors/old-webpack-quirk.md         Delete     All referenced files missing
docs/solutions/data-migrations/reserved-words.md         Keep       -
docs/solutions/testing/flaky-auth.md                     Consolidate  3-tag overlap with flaky-session-expiry
```

Do NOT write anything, including the run artifact.

## Phase 5: Commit

In `autofix` and `interactive` modes, stage only the touched `docs/solutions/**` files and the run artifact. Commit with:

```
compound-refresh: {kept} kept, {updated} updated, {consolidated} consolidated, {replaced} replaced, {deleted} deleted
```

Do not mix refresh changes with code or config changes. If the working tree has unrelated staged changes, prompt the user to commit or stash (commit - see `git-workflow` rules about never stashing) before running.

## Anti-Patterns

- **Aggressive deletion.** When in doubt, classify as `Update` and re-date. A doc that was useful once may be useful again; deletion is destructive.
- **Consolidating across categories.** Docs with the same tags in different categories usually cover different angles - merging them hides the distinction.
- **Running in autofix during a feature branch.** The refresh diff buries the feature diff. Do this on its own branch.
- **Skipping the run artifact.** Without the artifact, the next refresh cannot tell which docs were last reviewed and when.

## Source

Ported from EveryInc/compound-engineering-plugin's `ce-compound-refresh`. Kept: the 5-outcome classification, the age/severity table, the staleness probes. Adapted: mode names now match CCGM skill-authoring conventions (see `modules/skill-authoring/rules/skill-authoring.md`).
