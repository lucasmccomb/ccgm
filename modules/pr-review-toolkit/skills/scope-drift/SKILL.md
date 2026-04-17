---
name: scope-drift
description: Before reviewing code quality, compare stated intent (PR body, commit messages, TODOs, plan files) against the actual diff. Classify every plan item as DONE / PARTIAL / NOT DONE / CHANGED and flag out-of-scope changes. Use at the start of any PR review or before claiming a task complete.
disable-model-invocation: false
---

# Scope Drift Detection

An intent-versus-diff audit that runs **before** code-quality review. Answers one question: did this change do what it said it would do, and only that?

Scope drift is the primary failure mode for multi-agent workflows. Agents routinely "while I was in there" into adjacent files, silently defer stated requirements, or reshape the plan without surfacing the change. This skill makes that observable.

## When to Run

- At the start of any PR review, before running specialist agents
- Before claiming a task is DONE
- When a diff feels larger than the task description suggests
- When multiple plan items were in flight and you want to confirm which actually shipped

Skip only when the change is a trivial single-line fix with no plan file or PR body.

## Inputs

Collect every available statement of intent. Use whichever sources exist:

1. **PR body** - `gh pr view --json body,title` for title and description
2. **Issue body** - `gh issue view {num}` for any issue the PR closes
3. **Commit messages** - `git log origin/main..HEAD --pretty=format:"%s%n%b"`
4. **Plan file** - any `plans/**/plan.md`, `TODOS.md`, `TODO.md`, `ROADMAP.md`, or similar referenced in the PR or living in the repo root
5. **Task description** - whatever the user or parent agent handed to this agent

If none exist, state that explicitly and proceed with a one-line reconstructed intent based on the first commit message.

## Extraction: Actionable Items

From the combined intent sources, extract up to **50** actionable items. An actionable item is one the PR either must do or must not do.

Look for:

- Markdown checkboxes (`- [ ]` or `- [x]`)
- Numbered steps in plan files
- Imperative sentences in the PR body ("adds X", "removes Y", "renames Z")
- Explicit acceptance criteria sections
- Items in a "Scope" or "Deliverables" list
- Issue titles and labels that imply a verb-object pair

Normalize each to a single short line, for example:

- `Add scope-drift skill to pr-review-toolkit`
- `Update module.json with new file entries`
- `Do NOT touch other modules`
- `Keep edits minimal`

If the combined intent produces more than 50 items, note the count and work with the top 50 by apparent priority (explicit scope > deliverables > nice-to-haves).

## Classification

For each actionable item, classify against the actual diff. Use `git diff origin/main...HEAD --stat` and `git diff origin/main...HEAD` on relevant files.

| Status | Meaning |
|--------|---------|
| **DONE** | Item is fully implemented in the diff, with evidence (file, approximate line) |
| **PARTIAL** | Item is started but not complete. Name what is missing. |
| **NOT DONE** | Item is absent from the diff entirely |
| **CHANGED** | Item's implementation diverged from its description. Name what changed. |

Record evidence as `path/to/file.ext:line` pointers so the next reviewer can verify without re-running the diff.

## Out-of-Scope Changes

Walk the diff in the opposite direction: every changed file that does NOT map to an actionable item is a scope drift candidate.

For each candidate, decide:

- **Justified** - Small, mechanical, obviously required by a stated item (e.g., import reorder, generated file, formatting that the linter enforces). Record and move on.
- **Drift** - Not implied by any stated item. Flag it. Include the file, the nature of the change in one line, and why it seems unrelated.

Do NOT remove drift changes automatically. The author may have a reason. Surface them for a decision.

## Impact Rating

Rate every PARTIAL, NOT DONE, CHANGED, and DRIFT finding as HIGH / MEDIUM / LOW impact.

- **HIGH** - Would change review outcome, risk merging wrong code, or miss a hard requirement (security, migration, API contract, stated "must have")
- **MEDIUM** - Worth raising but merge can proceed with acknowledgement
- **LOW** - Informational; author may choose to defer

## Output Format

Produce one section at the top of the review report:

```markdown
## Scope Drift Audit

**Intent sources**: {PR body | issue #N | commit messages | plans/foo/plan.md}
**Items extracted**: {count}

### Plan Completion
- [DONE] {item} - {evidence: path:line}
- [PARTIAL] {item} - {what is missing} - {path:line}
- [NOT DONE] {item} - {impact: HIGH/MED/LOW}
- [CHANGED] {item} - {what diverged} - {path:line}

### Out-of-Scope Changes
- [DRIFT, HIGH] {file} - {one-line description of change} - {why it appears unrelated}
- [DRIFT, LOW] {file} - {one-line description} - {likely benign reason}

### Verdict
- In scope: {count} items DONE + {count} justified supporting changes
- Gaps: {count} PARTIAL + {count} NOT DONE
- Drift: {count} HIGH + {count} LOW
```

## Gating

Gate the review only on HIGH-impact findings. For each HIGH gap or drift, issue a single `AskUserQuestion` (batched) before continuing to code-quality review. Present options:

- Accept the gap / drift and continue
- Block the review until the item is addressed
- Mark the plan item as explicitly descoped (update PR body)

LOW and MEDIUM findings are informational. Record them in the report and proceed.

## Learning Log

For every HIGH-impact gap or drift, emit a one-line learning entry that a future reviewer can use:

```
plan-delivery-gap: {repo}#{pr} - {item or drift} - {cause hypothesis}
```

Example causes: "agent lost track after rebase", "scope unclear from PR body", "added dependency without explicit approval".

These feed the self-improving loop. The CCGM `self-improving` module's MEMORY files are the current store.

## Integration With Existing Review

Scope-drift runs **before** the existing specialist agents (`code-reviewer`, `silent-failure-hunter`, etc.) from the external `pr-review-toolkit` plugin. Its output is a prerequisite, not a replacement.

Flow:

1. Run scope-drift audit.
2. If any HIGH gating question is answered "block", stop and surface to user.
3. Otherwise proceed to specialist reviews with the audit attached as context.
4. Final review report starts with the Scope Drift Audit section, then the specialist findings in Fix-First format (see `rules/fix-first-review.md`).

## Anti-Patterns

- Running code-quality review first and adding scope-drift as an afterthought. Order matters: if scope is wrong, code quality is noise.
- Auto-removing drift changes. Surface, do not delete.
- Extracting fewer than 5 items from a multi-file PR. Usually means the intent sources were not read carefully enough.
- Treating every formatting nit as drift. Mechanical and generated changes are justified.
- Gating on LOW findings. That defeats the purpose.

## Source

Ported from the Scope Drift + Plan Completion Audit section of garrytan/gstack's `review/SKILL.md`. Adapted to CCGM voice and the external `pr-review-toolkit` plugin's agent-based review flow.
