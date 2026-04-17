# commands-extra

Additional slash commands for codebase audits, visual verification, guided walkthroughs, rule promotion, and safety-hook state management.

## What It Does

This module installs seven slash command files:

- **/audit** - Run a comprehensive codebase audit across 8 categories (security, dependencies, code quality, architecture, TypeScript/React, testing, documentation, performance) with auto-fix capabilities
- **/pwv** - Playwright Visual Verification for testing UI in a headless browser with screenshots, viewport checks, and theme verification
- **/walkthrough** - Enter step-by-step guide mode where Claude presents one step at a time and waits for confirmation before proceeding
- **/promote-rule** - Review repo-level CLAUDE.md files and suggest rules that should be promoted to the global configuration
- **/freeze** - Scope-lock Edit/Write to a directory by writing `~/.claude/freeze-dir.txt`. Reads by `check-freeze.py` (see the `hooks` module)
- **/unfreeze** - Clear the freeze scope by deleting `~/.claude/freeze-dir.txt`
- **/guard** - Compose careful + freeze for focused, safe sessions. Activates the freeze state file and confirms both safety hooks are installed

## Manual Installation

Copy the command files into your Claude configuration:

```bash
# Global (all projects)
cp commands/audit.md ~/.claude/commands/audit.md
cp commands/pwv.md ~/.claude/commands/pwv.md
cp commands/walkthrough.md ~/.claude/commands/walkthrough.md
cp commands/promote-rule.md ~/.claude/commands/promote-rule.md
cp commands/freeze.md ~/.claude/commands/freeze.md
cp commands/unfreeze.md ~/.claude/commands/unfreeze.md
cp commands/guard.md ~/.claude/commands/guard.md

# Project-level
cp commands/audit.md .claude/commands/audit.md
cp commands/pwv.md .claude/commands/pwv.md
cp commands/walkthrough.md .claude/commands/walkthrough.md
cp commands/promote-rule.md .claude/commands/promote-rule.md
cp commands/freeze.md .claude/commands/freeze.md
cp commands/unfreeze.md .claude/commands/unfreeze.md
cp commands/guard.md .claude/commands/guard.md
```

## Files

| File | Description |
|------|-------------|
| `commands/audit.md` | Codebase audit command with 8 audit categories and auto-fix |
| `commands/pwv.md` | Playwright visual verification command |
| `commands/walkthrough.md` | Step-by-step guided walkthrough command |
| `commands/promote-rule.md` | Rule promotion from repo to global config |
| `commands/freeze.md` | Activate the freeze scope (writes `~/.claude/freeze-dir.txt`) |
| `commands/unfreeze.md` | Clear the freeze scope (deletes `~/.claude/freeze-dir.txt`) |
| `commands/guard.md` | Compose careful + freeze for focused, safe sessions |
