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

Copy `rules/browser-automation.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/browser-automation.md ~/.claude/rules/browser-automation.md

# Project-level
cp rules/browser-automation.md .claude/rules/browser-automation.md
```

## Files

| File | Description |
|------|-------------|
| `rules/browser-automation.md` | Rule file covering tool selection, verification priority, and UI verification workflow |
