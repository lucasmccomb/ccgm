---
name: pr-description
description: Pure writer for PR titles and bodies. Takes a PR reference (or the current branch), reads diff + commits + linked issue + PR template, and returns structured {title, body}. Does NOT call `gh pr create` or `gh pr edit`. Invoke from `/pr`, `/cpm`, or any caller that needs a CCGM-voice PR body without the publishing plumbing.
disable-model-invocation: false
---

# PR Description Writer

A pure writer skill. One job: produce `{title, body}` for a pull request in CCGM voice, value-first, matching the repo's PR template when one exists.

Never publishes. Never calls `gh pr create`, `gh pr edit`, `gh pr comment`, or any mutating GitHub command. The caller is responsible for doing something with the returned text.

## When to Run

- A caller (e.g., `/pr`, `/cpm`, a coordinator agent) needs PR text and wants the voice separated from the publishing flow
- Rewriting an existing PR body to sharpen it before a second review pass
- Generating text for a PR that does not yet exist, so the caller can preview before pushing

Do NOT run this skill when the caller already has a finalized title and body - pass them through instead.

## Input Parsing

Accept any of the following as the PR reference:

| Form | Example | Meaning |
|------|---------|---------|
| bare number | `561` | PR #561 in the current repo |
| hash number | `#561` | same |
| prefixed | `pr:561` | same |
| full URL | `https://github.com/owner/repo/pull/561` | PR in that repo |
| branch name | `288-pr-description-writer-skill` | find the open PR for this branch, or fall through to "no PR yet" |
| empty / current | (no argument) | current branch; PR may or may not exist |
| steering text | `emphasize the benchmarks` | applied on top of any other input as a tone/content hint |

Multiple forms can coexist. `pr:561 emphasize the perf numbers` means "PR #561, lean on perf."

If no PR exists yet (e.g., the caller is about to create one), operate on the branch: compare `origin/main...HEAD` for the diff and commit set.

## Inputs to Collect

Collect in this order. Stop once each input is captured or confirmed absent.

1. **Linked issue** - from the branch name (`{issue-number}-{description}` convention) or from the PR body's `Closes #N` line. Read with `gh issue view {num}`.
2. **Commits on the branch** - `git log origin/main..HEAD --pretty=format:"%s%n%n%b%n---"`
3. **Diff stat** - `git diff origin/main...HEAD --stat`
4. **Full diff** - `git diff origin/main...HEAD` (sampled; see "Diff Sampling" below)
5. **PR template** - check in order:
   - `pull_request_template.md` in the repo root
   - `PULL_REQUEST_TEMPLATE.md` in the repo root
   - `.github/pull_request_template.md`
   - `.github/PULL_REQUEST_TEMPLATE.md`
   - If none found, use the fallback structure in `references/default-template.md`
6. **Existing PR body** - if a PR already exists, `gh pr view {num} --json body,title`. Treat as prior art to improve, not replace wholesale.
7. **Steering text** - whatever hint the caller passed. Apply after drafting; do not let it override the template structure.

### Diff Sampling

For diffs over ~500 lines, sample rather than dump:

- Read the full diff stat (every file, every ± count)
- Read full diffs for files with substantive changes (>20 lines added or removed)
- For large generated/lockfile changes, record one line: "`{file}`: {N} lines; generated/lockfile, skipped"

Never claim coverage of a file you did not actually read.

## Title Rules

- Conventional-commit shape: `{type}({scope}): {summary}` or CCGM-style `#{issue}: {summary}` if the branch name carries an issue number
- Under 72 characters total, including any prefix
- Imperative mood (`add`, `extract`, `fix`), not past tense
- Lead with the value or action, not the filename
- If the repo uses `#{issue}:` prefix (check recent `git log --oneline -20` on main), match that convention

Examples:

| Bad | Good |
|-----|------|
| Updated pr.md and cpm.md to use new skill | #288: extract PR description writer as reusable skill |
| Refactor commands-core | #288: move inline PR body generation into pr-description skill |
| Big changes to review flow | feat(review): add scope-drift audit before specialist agents |

## Body Rules - Value-First

The body leads with what the PR enables, fixes, or changes in the user's world. File churn is supporting evidence, not the lead.

### Structure (when no PR template exists)

1. **Closes #N** - first line if the PR closes an issue. No other content on this line.
2. **One-sentence summary** - what this PR does, in user-facing terms. No filenames.
3. **Why** - what problem this solves or what capability it unlocks. Two sentences max.
4. **What changed** - bulleted list of concrete changes, each one a noun phrase with a verb:
   - "Adds `pr-description` skill under `commands-core`"
   - "Updates `/pr` to delegate body generation to the skill"
   - "Removes inline body template from `cpm.md`"
5. **Test plan** - how the change was verified. Name commands: `bash tests/test-modules.sh`, manual smoke test of `/pr` on a test issue, etc.
6. **Notes / follow-ups** - optional; only include if there is real carry-over work.

### When a PR Template Exists

Fill the template's sections verbatim. Do not add sections the template does not include. Do not remove sections the template marks required.

If a section in the template does not apply to this PR (e.g., "Screenshots" for a backend-only change), write `N/A - {one-line reason}` rather than leaving it blank.

### Value-First Rationalizations to Avoid

| You are about to write... | The reality is... |
|---------------------------|-------------------|
| "This PR modifies `foo.ts` and `bar.ts`..." | Lead with what those modifications do for the user. File names are not value. |
| "I refactored the review flow for cleanliness." | Cleanliness is not a user-visible outcome. What does the refactor enable? |
| "Adds a new module." | Which module, what does it do, why does that matter? One sentence each. |
| "Various improvements." | If you cannot name them, do not mention them. Delete the bullet. |

## Output Format

Return exactly this structure as the skill's output. The caller parses it.

```
### TITLE
{title, single line, no trailing punctuation}

### BODY
{full body, markdown, starts with `Closes #N` line if applicable}

### METADATA
- Issue: #{num} or "none"
- Branch: {branch-name}
- Commits: {count}
- Files changed: {count}
- Template used: {path} or "default"
- Steering applied: {yes/no}; {one-line summary if yes}
```

Do NOT wrap in additional prose. Do NOT invoke `gh` commands with the result. Do NOT emit a "here's your PR body" preamble.

## Non-Goals

- Creating the PR (`gh pr create`)
- Editing an existing PR (`gh pr edit`)
- Commenting on the PR
- Pushing the branch
- Running verification (tests, lint, build)
- Deciding whether the PR is mergeable

The caller handles all of the above.

## Integration With Callers

### `/pr` and `/cpm`

Both commands currently write PR bodies inline. A caller that delegates to this skill should:

1. Gather context the skill needs (branch, issue number, template detection) if it already did that work
2. Pass `$ARGUMENTS` (steering text) straight through
3. Use the returned `TITLE` and `BODY` blocks as `--title` and `--body` args to `gh pr create`
4. Leave publishing, merging, and issue-closing to the caller's own flow

This keeps the writer pure and the publisher in charge of side effects.

### Headless Mode

When invoked by another skill or agent (not a human), behave as if `mode:headless`:

- No clarifying questions
- No asking the user to choose between drafts
- Return the single best draft given the inputs available
- If a required input is missing, emit a one-line `BLOCKED` note at the top of the output and stop

## Source

Ported from EveryInc/compound-engineering's `skills/ce-pr-description/SKILL.md`. Adapted to CCGM voice, to match existing commands-core conventions (`{issue}: {description}` title prefix, `Closes #N` body line), and to slot into the skill-authoring rules (imperative voice, no AI attribution, value-first body, references file for the default template).
