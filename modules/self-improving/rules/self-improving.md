# Self-Improving Agent

Systematically learn from every task to improve future performance. Do not just complete work - extract reusable patterns and update your knowledge base.

## The Reflection Loop

After completing any significant task (feature, bug fix, debugging session):

### 1. Extract Experience

Ask yourself:
- What went well? What approach worked on the first try?
- What went wrong? Where did I waste time or go down the wrong path?
- What surprised me? What did I learn about this codebase, tool, or pattern?
- What would I do differently next time?

### 2. Identify Patterns

Distill specific experiences into general rules:
- "Debugging this callback issue" becomes "Always check async callback binding in this framework"
- "This migration failed because of reserved keywords" becomes "Always quote PostgreSQL reserved words in migrations"
- "The build broke because of missing env vars" becomes "Check .env.example after adding new env vars"

### 3. Update Memory

Write confirmed patterns to the learnings store. The store is a schema-validated JSONL file per project at `~/.claude/learnings/{project-slug}/learnings.jsonl`:

```bash
ccgm-learnings-log \
  --type pattern \
  --content "Always quote PostgreSQL reserved keywords in migrations" \
  --tag supabase --tag migrations \
  --confidence 8
```

See `learnings-store.md` for the full schema, type vocabulary, and confidence-decay model. `MEMORY.md` remains as a human-readable index that `/reflect` dual-writes into during the transition, but the JSONL is the source of truth.

Before logging, search for an existing entry (`ccgm-learnings-search --query "<topic>"`). If the pattern already exists, run `ccgm-learnings-log verify <id>` to reinforce it instead of creating a duplicate.

### 4. Consolidate

Periodically review learnings for:
- Duplicate or contradictory entries (the JSONL keeps them; the read path dedupes by key)
- Patterns that have been superseded by new learning (use `ccgm-learnings-log contradict <id>` or `deprecate <id>`)
- Entries whose `files[]` anchors no longer exist (stale)
- Entries below the effective-confidence threshold that should be retired explicitly

Use `/consolidate` to run a structured maintenance pass against both the JSONL store and any legacy MEMORY.md entries.

---

## When to Reflect

Reflection fires at specific moments. These are not suggestions - they are checkpoints in the workflow.

### Mandatory Triggers

1. **After PR merge** - Before moving to the next task, run the reflection checklist below. The PostToolUse hook provides an automated reminder when `gh pr merge` runs; this rule covers merges via other paths (web UI, admin override).

2. **After debugging that took 3+ attempts** - When the three-strike rule fires (see systematic-debugging rules), capture the debugging pattern after resolution. What was the misleading assumption? What was the actual root cause? What would have found it faster?

3. **After receiving user correction or feedback** - When the user corrects your approach or confirms a non-obvious choice, capture the preference or lesson. The auto-memory system handles some of this, but explicit reflection catches patterns the auto-system misses.

4. **Before context compaction** - When the PreCompact hook fires, check if there are unwritten patterns from this session that should be captured before context is compressed.

5. **After completing a feature or significant fix** - Before reporting completion, pause for 30 seconds of reflection. Not every task produces a pattern worth capturing, but the check should happen every time.

### Optional Triggers

- After a session that involved learning a new tool, framework, or API
- When you notice yourself repeating work you did in a previous session
- At any point you can invoke `/reflect` for a structured reflection pass

---

## Reflection Checklist

Follow this checklist at each mandatory trigger. It takes 1-2 minutes.

- [ ] **What was the task?** (one sentence)
- [ ] **What surprised me or took longer than expected?** (If nothing, skip)
- [ ] **Is there a reusable pattern here?** If yes, write to an appropriate memory file
- [ ] **Did I discover a common mistake?** If yes, consider adding to the common-mistakes rules (see that module's "Adding New Mistakes" section)
- [ ] **Did I learn a user preference?** If yes, write to a user-type memory file
- [ ] **Did I discover a tool/framework gotcha?** If yes, write to a feedback-type memory file

If none of the checklist items produce a pattern worth capturing, that is fine. Not every task yields a lesson. The point is to check, not to force output.

---

## What to Write to Memory

### Type Mapping (learnings store vocabulary)

| What you learned | Learnings type | Example |
|------------------|----------------|---------|
| Root cause of a tricky bug | `pitfall` | "PostgreSQL JSONB operators require explicit casting in WHERE clauses" |
| Codebase architecture pattern | `architecture` | "Auth middleware runs before rate limiting in this project's middleware chain" |
| Tool or framework gotcha | `tool` | "Tailwind v4 preflight does not set cursor:pointer on buttons" |
| User preference or working style | `preference` | "User prefers single bundled PRs for refactors, not many small ones" |
| Process that worked well | `pattern` | "Running migrations before writing TypeScript types prevents type drift" |
| Ops fact (deploy, CLI, infra) | `operational` | "Cloudflare Pages deploys take 2-3 minutes; do not test immediately after merge" |

### What NOT to Capture

- Task-specific details that will not recur (specific ticket numbers, one-time commands)
- Information already documented in CLAUDE.md or README files
- Speculative conclusions from a single observation (wait for confirmation)
- Code patterns derivable from reading the current project state

---

## Confidence Tracking

Every learning has an explicit `confidence` score 1-10. The read path applies time-based decay automatically, so you do not need to hand-manage staleness. You do need to set the initial score honestly:

- **8-10**: Confirmed across 3+ interactions, explicitly stated by the user, or directly evidenced by the codebase.
- **5-7**: Observed twice or strongly implied by project structure.
- **3-4**: Observed once; tentative. Consider waiting for confirmation before logging, OR log with the lower score and verify on next occurrence.
- **1-2**: Rarely worth logging. Speculative.

Log high and medium confidence learnings. For once-only observations, prefer a mental note until the pattern is confirmed; when it recurs, log it then.

Each successful reuse (`ccgm-learnings-log verify <id>`) slightly boosts effective confidence and refreshes `last_verified`. Contradictions (`contradict <id>`) cut it hard.

---

## Commands

- **`/reflect`** - Run the full reflection checklist inline. Dual-writes confirmed patterns to the JSONL learnings store and MEMORY.md index.
- **`/consolidate`** - Review the learnings store and legacy MEMORY.md: find duplicates, contradictions, stale anchors, and entries below threshold.
- **`/retro`** - Windowed retrospective over git history; surfaces candidate learnings for the next `/reflect` pass.
