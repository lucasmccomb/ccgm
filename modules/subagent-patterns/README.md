# subagent-patterns

Subagent dispatch methodology for effective task delegation.

## What It Does

Installs rules covering subagent coordination:

- **When to use subagents** - 3+ independent tasks, parallel research, context protection
- **Task decomposition** - Write specs with objective, context, constraints, deliverable
- **Right-sizing** - Each task completable in one pass, independently verifiable, scoped to one concern
- **Dispatch patterns** - Parallel research, parallel implementation, dependency ordering
- **Pass paths, not contents** - Give subagents file paths to read, not pasted file bodies
- **Two-stage review** - Personal lead review by default: spec compliance gates code quality. Native cross-provider review requires explicit opt-in in a supported workflow
- **Coordination rules** - No shared state, aggregate results, report failures
- **Completion status protocol** - DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT
- **Skill invocation modes** - interactive / autofix / report-only / headless for composable skill calls
- **Reusable agent prompt templates** - `implementer`, `spec-compliance-reviewer`, `code-quality-reviewer` for consistent dispatch and review
- **Concurrency and rate limits** - Cap simultaneous heavy agents (4, never >5), launch fan-outs in waves, default to cheaper models / lower effort, and recover from server-side 429 throttles - covers both the Workflow tool and direct parallel Agent dispatch

## Manual Installation

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/subagent-patterns.md ~/.claude/rules/subagent-patterns.md
cp rules/concurrency-and-rate-limits.md ~/.claude/rules/concurrency-and-rate-limits.md
mkdir -p ~/.claude/agents
cp agents/implementer.md ~/.claude/agents/implementer.md
cp agents/spec-compliance-reviewer.md ~/.claude/agents/spec-compliance-reviewer.md
cp agents/code-quality-reviewer.md ~/.claude/agents/code-quality-reviewer.md

# Hooks
mkdir -p ~/.claude/hooks
cp hooks/subagent-stop-check.py ~/.claude/hooks/subagent-stop-check.py
cp hooks/task-completed-check.py ~/.claude/hooks/task-completed-check.py
chmod +x ~/.claude/hooks/subagent-stop-check.py
chmod +x ~/.claude/hooks/task-completed-check.py

# Merge settings.partial.json into ~/.claude/settings.json
# Add the relevant hook wiring from settings.partial.json
```

## Files

| File | Description |
|------|-------------|
| `rules/subagent-patterns.md` | Subagent decomposition, dispatch patterns, and review methodology |
| `rules/concurrency-and-rate-limits.md` | Caps heavy-agent fan-out concurrency, wave sizing, and 429-throttle recovery for the Workflow tool and direct parallel Agent dispatch |
| `agents/implementer.md` | Reusable prompt template for implementer subagents - enforces scope discipline and four-state status |
| `agents/spec-compliance-reviewer.md` | Stage 1 reviewer - adversarial stance, verifies deliverables and constraints independently of the implementer's self-report |
| `agents/code-quality-reviewer.md` | Stage 2 reviewer - refuses to run unless Stage 1 returned DONE; checks project patterns, edge cases, simplicity |
| `hooks/subagent-stop-check.py` | SubagentStop hook that verifies subagent returns a valid four-state status before returning control |
| `hooks/task-completed-check.py` | PostToolUse hook that nudges the dispatcher to verify subagent artifacts before accepting DONE |
| `settings.partial.json` | Hook wiring configuration to merge into settings.json |
