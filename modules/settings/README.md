# settings

Base settings.json with comprehensive tool permissions (800+ allow entries), deny list for dangerous operations, and plugin configuration.

## What It Does

This module provides a `settings.base.json` that gets merged into `~/.claude/settings.json`. It includes:

- **Allow list**: ~800 Bash command prefixes covering git, package managers, build tools, languages, editors, system utilities, cloud CLIs, databases, and more
- **File operation permissions**: Read/Edit/Write permissions for your code directory, Claude config, and temp files
- **Deny list**: Dangerous operations blocked by default (rm -rf, force push to main, docker rm, DROP/TRUNCATE/DELETE SQL)
- **Tool permissions**: WebFetch, WebSearch, Skill, Glob, Grep, and Supabase MCP tools pre-approved
- **Plugin configuration**: Common Claude Code plugins enabled

## Template Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `__DEFAULT_MODE__` | Permission mode for unmatched commands (`ask` or `dontAsk`) | `ask` |
| `__HOME__` | Home directory path (replaced during installation) | System $HOME |
| `__CODE_DIR__` | Path to your code directory | `$HOME/code` |

## Manual Installation

```bash
# 1. Copy the base settings
cp settings.base.json ~/.claude/settings.json

# 2. Replace template variables
# Edit ~/.claude/settings.json and replace:
#   __DEFAULT_MODE__ -> ask (or dontAsk)
#   __HOME__ -> your home directory path (e.g., /Users/yourname)
#   __CODE_DIR__ -> your code directory (e.g., /Users/yourname/code)
```

## Security Notes

- **Default mode is `ask`**: Unrecognized commands will prompt for approval. Change to `dontAsk` only if you trust Claude to run any command.
- The deny list blocks destructive operations even in `dontAsk` mode.
- `skipDangerousModePermissionPrompt` is NOT included - you will be warned when switching to dangerous mode.

## Files

| File | Description |
|------|-------------|
| `settings.base.json` | Complete settings.json template with all permissions |
