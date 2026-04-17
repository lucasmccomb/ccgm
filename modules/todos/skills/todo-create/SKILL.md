---
name: todo-create
description: >
  Capture a review finding, PR comment, or tech-debt item as a file under .claude/todos/ in the current repo. Writes NNN-{status}-{priority}-{slug}.md with YAML frontmatter per the schema. Canonical writer - other skills (todo-triage, todo-resolve, ce-review) call this one to avoid duplicating the file-naming and frontmatter rules. Todos start as status:pending by default; promote via /todo-triage.
  Triggers: todo, add todo, capture this as a todo, track this finding, write a todo, note this for later, add to todos.
disable-model-invocation: true
---

# /todo-create - Write a Todo

Capture a reviewable item that is not worth a full GitHub issue but is worth not forgetting. Writes `.claude/todos/NNN-{status}-{priority}-{slug}.md` in the current repo.

## When to Use

Write a todo when:

- A code reviewer flags a nitpick or small concern and the fix does not fit in this PR
- A PR reviewer leaves a comment that needs action later (not immediate)
- While solving problem A you notice problem B and do not want to context-switch
- `/xplan` surfaces a future-work item that is not scope for the current plan
- A debug session uncovers tech debt adjacent to the bug being fixed

Do NOT write a todo when:

- The item belongs in a GitHub issue (multi-session, cross-cutting, needs product input)
- The item belongs in team-shared knowledge (durable learning - use `/compound` instead)
- The item belongs in personal memory (user preference, working style - use self-improving)
- You can fix it right now in two minutes - just fix it

The rule: **agent time is cheap, tech debt is expensive. If an item is valid, capture it - including nitpicks.**

## Directory

Todos live in `.claude/todos/` in the repo being worked on, not in CCGM or `~/.claude/`. This is a per-repo concern, committed with the rest of the code.

If `.claude/todos/` does not exist:

1. Create it.
2. Write `.claude/todos/README.md` with a one-paragraph summary of the convention and a pointer to this skill.
3. Offer to add a short pointer block to the repo's `AGENTS.md` or `CLAUDE.md`:

   ```markdown
   ## Todos

   Review findings and PR nitpicks that do not warrant a GitHub issue live
   in `.claude/todos/` as `NNN-{status}-{priority}-{slug}.md` files. Run
   `/todo-triage` to promote pending todos to ready; run `/todo-resolve` to
   batch-fix ready todos.
   ```

## Inputs

Parse `$ARGUMENTS` for:

- A free-form description (everything else). Example: `/todo-create extract the auth middleware out of the request handler, p2, from ce-review`

If `$ARGUMENTS` is empty, use the most recent discussion context - the last review finding, PR comment, or debug observation visible in the current conversation.

Infer the following from context (ask only when genuinely unclear):

- `priority` - p1 (blocks something), p2 (this cycle), p3 (nitpick). Default p3 if the item came from a nitpick or style comment, p2 otherwise.
- `source` - review, pr-comment, debug, planning, ad-hoc. Default ad-hoc.
- `pr` - if a PR number is visible in context, record it.
- `files` - paths the todo touches, if known.
- `status` - always `pending` at creation. Triage promotes.

## Sequence Number Allocation

Pick the next number by scanning existing files:

```bash
ls .claude/todos/*.md 2>/dev/null \
  | sed -E 's#.*/([0-9]{3})-.*#\1#' \
  | sort -n | tail -1
```

Increment by one, zero-pad to three digits. If no files exist, start at `001`. Never reuse numbers.

## Filename and Frontmatter

Filename: `.claude/todos/NNN-pending-{priority}-{slug}.md`

Slug rules (matches `references/schema.yaml`):

- lowercase, kebab-case
- <= 40 chars
- no trailing punctuation
- truncate at a word boundary, not mid-word

Frontmatter - see `references/schema.yaml` for the full schema. Required fields on every todo:

```yaml
---
title: <one-line imperative>
status: pending
priority: <p1|p2|p3>
created: <YYYY-MM-DD>
source: <review|pr-comment|debug|planning|ad-hoc>
---
```

Include `pr`, `files`, `dependencies`, `tags` when known.

## Body

Write the body in this order:

1. **Context** - one paragraph. Where did this surface? Who flagged it? What were they working on?
2. **Problem** - what is wrong or missing, concretely. If the item came from a review comment, quote the relevant sentence.
3. (Skip **Proposed change** at create time - `/todo-triage` writes this when promoting to ready.)
4. **Notes** - optional. Links to the PR thread, prior docs, or adjacent todos.

Do not speculate about the fix at create time. The triage pass is the place to commit to a direction; capture just enough for triage to have the context it needs.

## Output

After writing the file, print one line:

```
Wrote .claude/todos/NNN-pending-{priority}-{slug}.md (source: {source})
```

If the caller is another skill (headless mode - see `modules/subagent-patterns/rules/subagent-patterns.md`), return the created path in a structured envelope instead of printing.

## When Called From Another Skill

`todo-create` is the canonical writer. `/todo-triage`, `/todo-resolve`, and the review orchestrator (`ce-review`) invoke it to avoid duplicating the filename/frontmatter rules. When called this way:

- Skip the Discoverability Check (the caller has already bootstrapped `.claude/todos/`)
- Accept a structured input object instead of parsing `$ARGUMENTS`
- Return the created path as structured output, no conversational prose

See `references/schema.yaml` for the exact fields.
