# autonomy

Configure Claude as a fully autonomous Staff-level engineer who executes tasks end-to-end without asking unnecessary questions.

## What It Does

This module installs a rules file that instructs Claude to:

- Execute commands directly instead of telling you what to run
- Fix problems, chain operations, and debug issues without stopping to ask
- Only ask the user when genuinely blocked (missing credentials, ambiguous product decisions, destructive actions)
- Prompt with a call to action after completing tasks instead of just summarizing

## Manual Installation

Copy `rules/autonomy.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/autonomy.md ~/.claude/rules/autonomy.md

# Project-level
cp rules/autonomy.md .claude/rules/autonomy.md
```

## Files

| File | Description |
|------|-------------|
| `rules/autonomy.md` | Rule file with autonomy instructions and anti-patterns |
