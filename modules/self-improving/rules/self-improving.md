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

Write confirmed patterns to your memory files:
- Add patterns to topic-specific memory files (e.g., `debugging.md`, `patterns.md`)
- Update MEMORY.md index with links to new topic files
- Remove or correct patterns that turned out to be wrong

### 4. Consolidate

Periodically review memory files for:
- Duplicate or contradictory entries
- Patterns that have been superseded by new learning
- Entries that are too specific (should be generalized) or too vague (should be made concrete)

Use `/consolidate` to run a structured memory maintenance pass.

---

## When to Reflect

Reflection fires at specific moments. These are not suggestions - they are checkpoints in the workflow.

### Mandatory Triggers

1. **After PR merge** - Before moving to the next task, run the reflection checklist below. The PostToolUse hook provides an automated reminder when `gh pr merge` runs; this rule covers merges via other paths (web UI, admin override). Cross-references session-logging mandatory trigger #8.

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

### Memory Type Mapping

| What you learned | Memory type | Example |
|------------------|-------------|---------|
| Root cause of a tricky bug | feedback | "PostgreSQL JSONB operators require explicit casting in WHERE clauses" |
| Codebase architecture pattern | project | "Auth middleware runs before rate limiting in this project's middleware chain" |
| Tool or framework gotcha | feedback | "Tailwind v4 preflight does not set cursor:pointer on buttons" |
| User preference or working style | user | "User prefers single bundled PRs for refactors, not many small ones" |
| Process that worked well | feedback | "Running migrations before writing TypeScript types prevents type drift" |

### What NOT to Capture

- Task-specific details that will not recur (specific ticket numbers, one-time commands)
- Information already documented in CLAUDE.md or README files
- Speculative conclusions from a single observation (wait for confirmation)
- Code patterns derivable from reading the current project state

---

## Confidence Tracking

Not all patterns are equally reliable:

- **High confidence**: Confirmed across 3+ interactions or explicitly stated by the user
- **Medium confidence**: Observed twice or strongly implied by project structure
- **Low confidence**: Observed once. Note as tentative, verify before relying on it.

Only write high and medium confidence patterns to memory. Keep low confidence observations as mental notes until confirmed.

---

## Commands

- **`/reflect`** - Run the full reflection checklist inline. Use after completing significant work or when prompted by a hook.
- **`/consolidate`** - Run a memory maintenance pass: review all memory files, identify duplicates/contradictions/stale entries, clean up.
