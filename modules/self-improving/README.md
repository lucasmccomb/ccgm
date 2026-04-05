# self-improving

Meta-learning system that triggers reflection at key moments and captures reusable patterns to memory.

## What It Does

Combines rules, commands, and hooks to create an active self-improvement loop:

### Rules (Always Active)

The reflection loop methodology with prescriptive trigger points:

1. **Extract Experience** - After each task, identify what worked, what failed, and what surprised you
2. **Identify Patterns** - Distill specific experiences into general reusable rules
3. **Update Memory** - Write confirmed patterns to memory files with proper organization
4. **Consolidate** - Periodically review and clean up memory for duplicates and contradictions

Includes a reflection checklist, mandatory trigger points, memory type mapping, and confidence tracking.

### Commands

| Command | Description |
|---------|-------------|
| `/reflect` | Run the full reflection checklist inline (preserves session context) |
| `/consolidate` | Review all memory files, find duplicates/contradictions/stale entries, clean up |

### Hooks

| Hook | Event | Trigger |
|------|-------|---------|
| `reflection-trigger.py` | PostToolUse:Bash | Injects reflection reminder after `gh pr merge` or `gh issue close` |
| `precompact-reflection.py` | PreCompact | Reminds agent to capture patterns before context compaction |

## Cross-Module Integration

This module works best alongside:

- **session-logging** - Mandatory trigger #8 prompts post-merge reflection
- **systematic-debugging** - Three-strike rule triggers debugging pattern capture
- **common-mistakes** - Living document that self-improving feeds new entries into

These are soft references, not hard dependencies. The self-improving module works standalone; the cross-module triggers add automation.

## Manual Installation

```bash
# Rules
cp rules/self-improving.md ~/.claude/rules/self-improving.md

# Commands
cp commands/reflect.md ~/.claude/commands/reflect.md
cp commands/consolidate.md ~/.claude/commands/consolidate.md

# Hooks
cp hooks/reflection-trigger.py ~/.claude/hooks/reflection-trigger.py
cp hooks/precompact-reflection.py ~/.claude/hooks/precompact-reflection.py

# Settings (merge into existing settings.json)
# Use jq or manually add the hook entries from settings.partial.json
```

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/self-improving.md` | rule | Reflection loop, trigger points, checklist, memory mapping, confidence tracking |
| `commands/reflect.md` | command | Inline structured reflection workflow |
| `commands/consolidate.md` | command | Memory maintenance via subagent |
| `hooks/reflection-trigger.py` | hook | PostToolUse detection for PR merge and issue close |
| `hooks/precompact-reflection.py` | hook | PreCompact reminder to capture patterns |
| `settings.partial.json` | config | Hook registration (PostToolUse:Bash, PreCompact) |
