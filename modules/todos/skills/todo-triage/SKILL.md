---
name: todo-triage
description: >
  Walk every pending todo in .claude/todos/ one at a time. For each, confirm / skip / modify / drop, and on confirm, promote to status:ready with a concrete Proposed Change section. Interactive by default; supports mode:autofix for low-risk promotions and mode:report-only for a dry-run table. Runs before /todo-resolve so the resolver only sees scoped, agreed-upon items.
  Triggers: todo triage, triage todos, review todos, promote todos, walk the todo list, clean up todos.
disable-model-invocation: true
---

# /todo-triage - Promote Pending Todos to Ready

`/todo-create` captures raw findings. `/todo-triage` decides which ones to fix.

The purpose of triage is not to be strict - it is to turn vague captures into scoped, agreed-upon work. A ready todo has a one-paragraph Proposed Change that another agent (or human) can execute without re-reading the review thread.

## When to Run

- Before starting `/todo-resolve` so the resolver only touches scoped items
- After a batch of `/todo-create` calls (e.g., at the end of a review session)
- Weekly, as a standing chore - pending todos drift into irrelevance faster than ready ones
- Before closing out a milestone, to decide which pending items graduate to ready vs. drop

## Mode Selection

Parse `$ARGUMENTS` for a mode token (convention from `modules/subagent-patterns/rules/subagent-patterns.md`):

- `mode:interactive` (default) - For each pending todo, ask the user confirm / skip / modify / drop
- `mode:autofix` - Auto-promote any pending todo where the body is concrete enough to write a Proposed Change without user input; leave everything else as pending
- `mode:report-only` - Strictly read-only. Print a classification table per todo and exit

When composed from another skill (e.g., `ce-review`), prefer `mode:report-only` and let the caller decide per-item.

## Phase 1: Inventory

List every `.claude/todos/NNN-pending-*.md` in the current repo:

```bash
ls .claude/todos/*-pending-*.md 2>/dev/null
```

Sort by priority (p1 > p2 > p3), then by sequence number ascending within each priority band. This surfaces the most urgent items first and preserves capture order as a tiebreaker.

If zero pending todos: print "No pending todos. Nothing to triage." and exit.

## Phase 2: Per-Todo Decision

For each pending todo in the sorted list:

1. Read the file (frontmatter + body).
2. Summarize in two to three lines:
   - `#NNN [{priority}] {title}`
   - Context one-liner (from body Context section)
   - What would Proposed Change look like, in one sentence
3. Prompt the user (interactive mode):

   ```
   [C]onfirm + promote to ready   [S]kip (leave pending)
   [M]odify title / priority      [D]rop (delete file)
   ```

4. Apply the decision:

   - **Confirm** - write the Proposed Change section in the body (one paragraph, imperative voice). Change frontmatter `status: pending` -> `status: ready`. Rename file from `NNN-pending-{priority}-{slug}.md` to `NNN-ready-{priority}-{slug}.md`.
   - **Skip** - no-op. Todo stays pending.
   - **Modify** - ask only for the fields being changed (title, priority). Rewrite frontmatter and rename file if priority changed.
   - **Drop** - delete the file. Print the NNN and title so there is a record in the session.

In `mode:autofix`:

- Confirm automatically if the body already contains explicit direction (e.g., the Context section says "reviewer suggests extracting X into Y")
- Skip (leave pending) if the body is vague or a decision is needed
- Never auto-drop

In `mode:report-only`:

- Print the per-todo summary above, plus a recommended decision (Confirm / Skip / Drop), but take no action

## Phase 3: Proposed Change Template

When promoting to ready, write or append a `## Proposed change` section to the body. Use this template:

```markdown
## Proposed change

<one paragraph in imperative voice describing the fix. Be specific about which file(s) or function(s) to touch. Avoid hedging.>

**Files**: <comma-separated list, or "TBD during implementation">
**Estimated effort**: <S | M | L> (< 30 min / 30-120 min / > 2 hr)
**Acceptance check**: <one sentence describing how to confirm the fix landed>
```

If the Proposed Change is uncertain enough that the user would need to provide it, do not autofix - prompt.

## Phase 4: Summary

After the walk, print a compact summary:

```
Triaged N pending todos:
  promoted -> ready : M
  dropped           : K
  modified          : J
  still pending     : P
```

If any ready todos now exist, suggest the next step:

```
Next: run /todo-resolve to batch-fix M ready todos, or pick specific ones.
```

## File Renaming Notes

Renaming is atomic per todo. If a rename fails (filesystem, permissions), roll back the frontmatter edit so the file and frontmatter stay consistent. Never leave a file where the frontmatter status does not match the filename status - `/todo-resolve` relies on both being in sync.

## Composition

When called from `ce-review` or another orchestrator in headless mode:

- Accept a list of todo paths as structured input instead of walking the whole directory
- Return a structured report: `{ promoted: [...], skipped: [...], dropped: [...] }`
- Do not prompt the user; honor `mode:autofix` or `mode:report-only` strictly

See `modules/subagent-patterns/rules/subagent-patterns.md` for the mode contract.
