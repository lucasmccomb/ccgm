---
name: todo-resolve
description: >
  Batch-resolve ready todos in .claude/todos/. Dispatches parallel subagents (one per todo) with pass-paths-not-contents, aggregates their fixes, updates each todo's status to complete, and optionally feeds the pattern back into /compound for team knowledge. Filter by priority, source, or explicit numbers. Skips todos whose dependencies are not complete. Modes - interactive (confirm before each) / autofix / report-only / headless.
  Triggers: todo resolve, resolve todos, fix ready todos, batch fix todos, burn down todos, process the todo list.
disable-model-invocation: true
---

# /todo-resolve - Batch-Fix Ready Todos

`/todo-triage` decides which todos are ready. `/todo-resolve` does the work.

This skill exists because small findings accumulate. Ten p3 nits are individually trivial but collectively a drag. Dispatching one subagent per todo lets the orchestrator burn through them in parallel without polluting the main context.

## When to Run

- At the start of a session, before diving into new feature work - clear the backlog first
- After `/todo-triage` promotes a batch of items to ready
- Before cutting a release or merging a long-lived branch - land the nitpicks with the feature
- When a reviewer comes back with cluster of small comments and you would rather batch than ping-pong

Do not run during active feature development on the same files - the parallel fan-out will conflict with in-flight edits.

## Mode Selection

Parse `$ARGUMENTS` for a mode token:

- `mode:interactive` (default) - Plan the batch, show the plan, ask before dispatching
- `mode:autofix` - Plan and dispatch without asking; write a run artifact at `.claude/todos/.runs/YYYYMMDD-HHMM.md` summarizing what landed
- `mode:report-only` - Produce the plan only. Do not dispatch. Safe for concurrent runs
- `mode:headless` - For skill-to-skill composition. Structured output envelope, no prompts, no conversational prose, terminal "Resolve complete" line

## Filtering

Parse `$ARGUMENTS` for optional filters (compose with the mode token):

- `priority:p1` (or `p2`, `p3`) - only this priority band
- `source:review` (or `pr-comment`, `debug`, `planning`, `ad-hoc`) - only this source
- `pr:123` - only todos tied to PR 123
- `only:7,12,19` - only the listed sequence numbers
- no filter - all `status: ready` todos

## Phase 1: Plan

1. List candidates: every `.claude/todos/NNN-ready-*.md` matching the filter.
2. For each candidate, read frontmatter and body.
3. Build a dependency graph from the `dependencies` frontmatter field.
4. Skip any todo whose dependencies are not `status: complete`. Record these as `blocked` in the plan, do not dispatch.
5. Print the plan:

   ```
   Plan: resolve N ready todos in parallel.

   dispatching:
     #007 [p2] extract-auth-middleware           (files: src/auth/*.ts)
     #012 [p3] rename-foo-to-bar                 (files: src/utils/foo.ts)

   blocked (dependencies not complete):
     #019 [p2] add-rate-limiter                  (waits on #015)

   skipped (out of filter):
     #003 [p1] ...
   ```

6. In `mode:interactive`, ask: `Dispatch N subagents in parallel? [y/n/edit]`. In `mode:autofix` and `mode:headless`, proceed. In `mode:report-only`, stop here.

## Phase 2: Dispatch

Dispatch one subagent per non-blocked todo, in parallel. Each subagent spec:

**Objective** - Implement the Proposed Change section of the todo file.

**Context** (pass paths, not contents - see `modules/subagent-patterns/rules/subagent-patterns.md`):

- Path to the todo file: `.claude/todos/NNN-ready-{priority}-{slug}.md`
- Paths from the todo's `files` frontmatter field (if present)
- Path to the repo's `AGENTS.md` or `CLAUDE.md` for house style

**Constraints**:

- Modify only the files in the todo's `files` field. If a change requires editing a path not listed, STOP and return `BLOCKED` with an explanation.
- No cross-todo edits. If the fix uncovers a second issue, write a new todo via `/todo-create` and keep it out of the current fix.
- One commit per todo if committing inside the subagent; otherwise return the diff for the orchestrator to commit.

**Deliverable** - Either:

- `DONE` + diff + one-paragraph resolution note, or
- `BLOCKED` + reason, or
- `NEEDS_CONTEXT` + the specific missing information, or
- `DONE_WITH_CONCERNS` + diff + concerns section

See `modules/subagent-patterns/rules/subagent-patterns.md` for the four-state completion protocol.

## Phase 3: Two-Stage Review

When subagents return, do not trust self-reports. Two passes (see subagent-patterns):

1. **Spec compliance** - Did each subagent do what was asked? Constraints respected?
2. **Code quality** - Does the diff match project patterns? Any missed edge cases?

Re-dispatch with specific feedback for any subagent that failed either stage. Do not silently patch subagent output.

## Phase 4: Commit and Close

For each `DONE` subagent:

1. Stage the diff if not already committed.
2. Commit with message: `#todo-NNN: {title}` (plural `todos: ...` if batching multiple into one commit).
3. Update the todo file:
   - Frontmatter: `status: ready` -> `status: complete`
   - Body: append a `## Resolution` section with the resolution note and commit SHA
4. Rename file: `NNN-ready-{priority}-{slug}.md` -> `NNN-complete-{priority}-{slug}.md`

For each `DONE_WITH_CONCERNS`: same as DONE, but preserve the concerns section in the Resolution body for future reference.

For each `BLOCKED` or `NEEDS_CONTEXT`: leave the todo as ready, append a `## Attempt` section noting what was tried and why it stalled.

## Phase 5: Report and Compound

Print a run summary:

```
Resolved N ready todos:
  complete            : M
  blocked             : K
  needs_context       : J
  concerns            : P

Commits: {shas}
```

If M >= 3 or any concerns were flagged, suggest:

```
Consider running /compound to capture the pattern that surfaced across these fixes.
```

Do not auto-invoke `/compound`. Compound is explicit - the user or the orchestrator decides when a batch of todos represents a durable team learning vs. just cleanup.

## PR Comment Back-Reference

For todos with a `pr:` frontmatter field and source `pr-comment`:

- After the fix commits, post a short inline reply on the GitHub PR thread via `gh api` noting the resolution (commit SHA + one-line summary).
- Do not resolve the thread automatically - the reviewer resolves. Post, do not close.

If `gh` is not authenticated or the PR is merged, skip the comment and note it in the run summary.

## Composition

When called from `ce-review` or a batch orchestrator in `mode:headless`:

- Accept explicit todo paths instead of scanning the directory
- Return a structured envelope: `{ complete: [...], blocked: [...], concerns: [...] }`
- Do not prompt, do not post conversational prose
- End with `Resolve complete` on its own line so the caller can detect termination

See `modules/subagent-patterns/rules/subagent-patterns.md` for the full mode contract.

## Agent Time vs. Tech Debt

The adoption rationale for this whole module: **agent time is cheap, tech debt is expensive**. A p3 nit that sits in a review thread forever costs more in re-review and context-switching than it does to fix in a parallel subagent. Default to resolving, not deferring. The only reason to leave a ready todo unresolved is a real dependency or a legitimate scope concern - not "it is small, I will get to it."
