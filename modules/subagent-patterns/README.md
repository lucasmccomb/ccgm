# subagent-patterns

Subagent dispatch methodology for effective task delegation.

## What It Does

Installs a rules file covering subagent coordination:

- **When to use subagents** - 3+ independent tasks, parallel research, context protection
- **Task decomposition** - Write specs with objective, context, constraints, deliverable
- **Right-sizing** - Each task completable in one pass, independently verifiable, scoped to one concern
- **Dispatch patterns** - Parallel research, parallel implementation, dependency ordering
- **Pass paths, not contents** - Give subagents file paths to read, not pasted file bodies
- **Two-stage review** - Stage 1: spec compliance (gates Stage 2), Stage 2: code quality
- **Coordination rules** - No shared state, aggregate results, report failures
- **Completion status protocol** - DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT
- **Skill invocation modes** - interactive / autofix / report-only / headless for composable skill calls
- **Reusable agent prompt templates** - `implementer`, `spec-compliance-reviewer`, `code-quality-reviewer` for consistent dispatch and review

## Manual Installation

```bash
# Global (all projects)
cp rules/subagent-patterns.md ~/.claude/rules/subagent-patterns.md
mkdir -p ~/.claude/agents
cp agents/implementer.md ~/.claude/agents/implementer.md
cp agents/spec-compliance-reviewer.md ~/.claude/agents/spec-compliance-reviewer.md
cp agents/code-quality-reviewer.md ~/.claude/agents/code-quality-reviewer.md
```

## Files

| File | Description |
|------|-------------|
| `rules/subagent-patterns.md` | Subagent decomposition, dispatch patterns, and review methodology |
| `agents/implementer.md` | Reusable prompt template for implementer subagents - enforces scope discipline and four-state status |
| `agents/spec-compliance-reviewer.md` | Stage 1 reviewer - adversarial stance, verifies deliverables and constraints independently of the implementer's self-report |
| `agents/code-quality-reviewer.md` | Stage 2 reviewer - refuses to run unless Stage 1 returned DONE; checks project patterns, edge cases, simplicity |
