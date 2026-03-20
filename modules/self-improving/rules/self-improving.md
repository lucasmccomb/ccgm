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

## What to Capture

### High Value

- Root causes of bugs that took multiple attempts to find
- Codebase-specific patterns (architecture decisions, naming conventions, file organization)
- Tool-specific gotchas (framework quirks, CLI flags that matter, configuration pitfalls)
- User preferences confirmed across multiple interactions

### Low Value (Skip These)

- Task-specific details that will not recur (specific ticket numbers, one-time commands)
- Information already documented in project CLAUDE.md or README
- Speculative conclusions from a single observation

## Confidence Tracking

Not all patterns are equally reliable:

- **High confidence**: Confirmed across 3+ interactions or explicitly stated by the user
- **Medium confidence**: Observed twice or strongly implied by project structure
- **Low confidence**: Observed once. Note as tentative, verify before relying on it.

Only write high and medium confidence patterns to memory. Keep low confidence observations as mental notes until confirmed.

## When to Reflect

- After completing a feature or fix (before moving to the next task)
- After a debugging session that took more than 2 attempts
- After receiving user feedback or corrections
- At the end of a session before context compaction
