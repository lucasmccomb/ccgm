# autonomy

Configure Claude as a fully autonomous Staff-level engineer who executes tasks end-to-end without asking unnecessary questions.

## What It Does

This module installs rule files that instruct Claude to:

- Execute commands directly instead of telling you what to run
- Fix problems, chain operations, and debug issues without stopping to ask
- Only ask the user when genuinely blocked (missing credentials, ambiguous product decisions, destructive actions)
- Prompt with a call to action after completing tasks instead of just summarizing
- Stop and ask at true architectural forks via the Confusion Protocol (instead of guessing)

## Manual Installation

Copy the rule files into your Claude configuration:

```bash
# Global (all projects)
cp rules/autonomy.md ~/.claude/rules/autonomy.md
cp rules/confusion-protocol.md ~/.claude/rules/confusion-protocol.md

# Project-level
cp rules/autonomy.md .claude/rules/autonomy.md
cp rules/confusion-protocol.md .claude/rules/confusion-protocol.md
```

## Files

| File | Description |
|------|-------------|
| `rules/autonomy.md` | Rule file with autonomy instructions and anti-patterns |
| `rules/confusion-protocol.md` | Structured ambiguity escalation for high-stakes architectural forks |
