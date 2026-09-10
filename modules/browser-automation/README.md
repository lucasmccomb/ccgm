# browser-automation

Rules for browser automation tool selection, verification priority order, and UI verification workflow.

## What It Does

This module installs a rules file that instructs Claude to:

- Use installed MCP plugins without asking permission (they are pre-authorized)
- Select the right browser automation tool: WebMCP for structured interaction, Chrome extension for authenticated/visual testing, Playwright for headless/unauthenticated
- Prefer CLI tools and APIs over browser automation for verification and debugging
- Follow a structured UI verification workflow (get context, navigate, wait, check errors, screenshot)
- Wait for deployments to complete before testing

## Manual Installation

Copy `skills/browser-automation/SKILL.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
mkdir -p ~/.claude/skills
cp -R skills/browser-automation ~/.claude/skills/browser-automation

# Project-level
mkdir -p .claude/rules
```

## Files

| File | Description |
|------|-------------|
| `skills/browser-automation/SKILL.md` | Rule file covering tool selection, verification priority, and UI verification workflow |
