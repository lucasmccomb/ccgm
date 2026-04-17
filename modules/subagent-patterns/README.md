# subagent-patterns

Subagent dispatch methodology for effective task delegation.

## What It Does

Installs a rules file covering subagent coordination:

- **When to use subagents** - 3+ independent tasks, parallel research, context protection
- **Task decomposition** - Write specs with objective, context, constraints, deliverable
- **Right-sizing** - Each task completable in one pass, independently verifiable, scoped to one concern
- **Dispatch patterns** - Parallel research, parallel implementation, dependency ordering
- **Pass paths, not contents** - Give subagents file paths to read, not pasted file bodies
- **Two-stage review** - Stage 1: spec compliance, Stage 2: code quality
- **Coordination rules** - No shared state, aggregate results, report failures
- **Completion status protocol** - DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT
- **Skill invocation modes** - interactive / autofix / report-only / headless for composable skill calls

## Manual Installation

```bash
# Global (all projects)
cp rules/subagent-patterns.md ~/.claude/rules/subagent-patterns.md
```

## Files

| File | Description |
|------|-------------|
| `rules/subagent-patterns.md` | Subagent decomposition, dispatch patterns, and review methodology |
