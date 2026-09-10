# Self-Improving Agent

Learn from every task: extract reusable patterns and record them in the learnings store instead of only completing the work.

## The Reflection Loop

1. **Extract** what went well, what went wrong, what surprised you, and what you would do differently.
2. **Generalize** the specific experience into a rule: "this migration failed on a reserved keyword" becomes "always quote PostgreSQL reserved words in migrations."
3. **Record** confirmed patterns in the schema-validated JSONL store at `~/.claude/learnings/{project-slug}/learnings.jsonl`. Search first (`ccgm-learnings-search --query "<topic>"`); if the pattern exists, reinforce it with `ccgm-learnings-log verify <id>` instead of duplicating it. Otherwise:

   ```bash
   ccgm-learnings-log --type pattern \
     --content "Always quote PostgreSQL reserved keywords in migrations" \
     --tag supabase --tag migrations --confidence 8
   ```

4. **Consolidate** periodically with `/consolidate`: duplicates and contradictions, superseded patterns (`contradict <id>` or `deprecate <id>`), entries whose `files[]` anchors no longer exist, entries below the confidence threshold.

The `learnings-store` skill has the schema, type vocabulary, confidence decay, supersede chains, and sync and rollback commands. `MEMORY.md` remains a human-readable index that `/reflect` dual-writes; the JSONL is the source of truth.

## When to Reflect

Run the checklist after a PR merge, after debugging that took three or more attempts (capture the misleading assumption, the actual root cause, and the diagnostic that would have found it faster), after a user correction or a confirmed non-obvious choice, before context compaction (the PreCompact hook fires), and after completing a feature or significant fix. `/reflect` runs it on demand.

Checklist: what was the task; what surprised you or took longer than expected; is there a reusable pattern, a common mistake worth adding to `common-mistakes.md`, a user preference, or a tool gotcha. Not every task yields a lesson; the point is to check.

## What to Record

| What you learned | Type |
|------------------|------|
| Root cause of a tricky bug | `pitfall` |
| Codebase architecture fact | `architecture` |
| Tool or framework gotcha | `tool` |
| User preference or working style | `preference` |
| Process that worked well | `pattern` |
| Ops fact (deploy, CLI, infra) | `operational` |

Do not record task-specific details that will not recur, information already in CLAUDE.md or README files, speculative conclusions from a single observation, or code patterns derivable from the current project state.

## Confidence

Set the initial score honestly: 8 to 10 when confirmed across three or more interactions, stated by the user, or evidenced by the codebase; 5 to 7 when observed twice or strongly implied; 3 to 4 when observed once (prefer a mental note until it recurs). Reuse (`verify`) boosts effective confidence and refreshes `last_verified`; `contradict` cuts it hard; decay is applied at read time.

## Commands

`/reflect` runs the checklist and writes to the store and index; `/consolidate` maintains the store; `/retro` surfaces candidate learnings from a window of git history.
