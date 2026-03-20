# self-improving

Meta-learning patterns for systematic improvement across sessions.

## What It Does

Installs a rules file that teaches the agent to learn from experience:

1. **Extract Experience** - After each task, identify what worked, what failed, and what surprised you
2. **Identify Patterns** - Distill specific experiences into general reusable rules
3. **Update Memory** - Write confirmed patterns to memory files with proper organization
4. **Consolidate** - Periodically review and clean up memory for duplicates and contradictions

Includes guidance on what to capture (high value: root causes, codebase patterns, tool gotchas) vs. skip (task-specific details, already-documented info), and confidence tracking (high/medium/low).

## Manual Installation

```bash
# Global (all projects)
cp rules/self-improving.md ~/.claude/rules/self-improving.md
```

## Files

| File | Description |
|------|-------------|
| `rules/self-improving.md` | Reflection loop, pattern extraction, memory management, and confidence tracking |
