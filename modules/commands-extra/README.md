# commands-extra

Additional slash commands for codebase audits, visual verification, guided walkthroughs, and rule promotion.

## What It Does

This module installs four slash command files:

- **/audit** - Run a comprehensive codebase audit across 8 categories (security, dependencies, code quality, architecture, TypeScript/React, testing, documentation, performance) with auto-fix capabilities
- **/pwv** - Playwright Visual Verification for testing UI in a headless browser with screenshots, viewport checks, and theme verification
- **/walkthrough** - Enter step-by-step guide mode where Claude presents one step at a time and waits for confirmation before proceeding
- **/promote-rule** - Review repo-level CLAUDE.md files and suggest rules that should be promoted to the global configuration

## Manual Installation

Copy the command files into your Claude configuration:

```bash
# Global (all projects)
cp commands/audit.md ~/.claude/commands/audit.md
cp commands/pwv.md ~/.claude/commands/pwv.md
cp commands/walkthrough.md ~/.claude/commands/walkthrough.md
cp commands/promote-rule.md ~/.claude/commands/promote-rule.md

# Project-level
cp commands/audit.md .claude/commands/audit.md
cp commands/pwv.md .claude/commands/pwv.md
cp commands/walkthrough.md .claude/commands/walkthrough.md
cp commands/promote-rule.md .claude/commands/promote-rule.md
```

## Files

| File | Description |
|------|-------------|
| `commands/audit.md` | Codebase audit command with 8 audit categories and auto-fix |
| `commands/pwv.md` | Playwright visual verification command |
| `commands/walkthrough.md` | Step-by-step guided walkthrough command |
| `commands/promote-rule.md` | Rule promotion from repo to global config |
