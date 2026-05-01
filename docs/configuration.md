# Configuration

After installing CCGM, you can customize its behavior without modifying CCGM files directly.

## Adding personal rules

Create your own rule files in `~/.claude/rules/`. CCGM will never overwrite files it didn't install.

```bash
# Create a personal rule file
cat > ~/.claude/rules/personal.md << 'EOF'
# My Personal Rules

- Always use TypeScript strict mode
- Prefer functional components over class components
- Use pnpm instead of npm
EOF
```

Claude Code automatically loads all `.md` files from `rules/` at session start.

## Overriding settings

Claude Code supports a local override file for settings:

```bash
# ~/.claude/settings.local.json
{
  "permissions": {
    "defaultMode": "dontAsk"
  }
}
```

This file takes precedence over `settings.json` for the keys it defines. CCGM does not manage `settings.local.json`.

## MCP servers

MCP (Model Context Protocol) server configuration is managed by the `claude mcp` CLI and stored in `~/.claude.json`. CCGM does not write this file directly. Add servers with:

```bash
# stdio server with env vars (note the `--` before name)
claude mcp add --scope user --env KEY=value -- <name> <command> <args...>

# stdio server without env vars
claude mcp add --scope user -- <name> <command> <args...>

# complex/JSON config
claude mcp add-json --scope user <name> '<json>'

# verify
claude mcp get <name>
```

> **Migrating from `~/.claude/mcp.json`?** Older Claude Code versions (and old CCGM docs) used `~/.claude/mcp.json`. Current Claude Code does not read that file. If you have one, run `bash lib/mcp-migrate.sh` from the CCGM checkout to re-register every entry via the `claude mcp` CLI.

## Template variables

During installation, CCGM expands placeholder tokens in configuration files. These are only relevant during the install process - they don't affect runtime behavior.

| Variable | Description | Where it's used |
|----------|-------------|-----------------|
| `__HOME__` | Your home directory path (e.g., `/Users/jane`) | `settings.json` - path patterns in allow/deny lists |
| `__USERNAME__` | GitHub username (e.g., `janedoe`) | `enforce-git-workflow.py` - direct-to-main repo allowlist |
| `__CODE_DIR__` | Code workspace directory (e.g., `~/code`) | `settings.json` - path patterns, port registry |
| `__DEFAULT_MODE__` | Permission mode: `ask` or `dontAsk` | `settings.json` - `defaultMode` field |

Values are collected during installation and stored in `~/.claude/.ccgm.env`. They are applied via `sed` substitution when files are copied.

## The CCGM environment file

`~/.claude/.ccgm.env` stores all configuration values collected during installation:

```bash
# Example contents
CCGM_USERNAME=janedoe
CCGM_CODE_DIR=/Users/jane/code
CCGM_TIMEZONE=America/New_York
CCGM_DEFAULT_MODE=ask
CCGM_AUTO_UPDATE_CHECK=true
```

Some hooks read values from this file at runtime:
- `ccgm-update-check.py` reads `CCGM_AUTO_UPDATE_CHECK`

## The CCGM manifest

`~/.claude/.ccgm-manifest.json` records what was installed, when, and how. It is used by `update.sh` and `uninstall.sh`.

```json
{
  "version": "1.0.0",
  "installedAt": "2026-03-29T12:00:00Z",
  "preset": "standard",
  "scope": "global",
  "linkMode": false,
  "ccgmRoot": "/Users/jane/ccgm",
  "modules": ["autonomy", "git-workflow", "settings", "hooks", "commands-core"],
  "files": [
    "~/.claude/rules/autonomy.md",
    "~/.claude/rules/git-workflow.md",
    "~/.claude/commands/commit.md"
  ],
  "backups": [
    "~/.claude.backup-2026-03-29-120000"
  ]
}
```

## Module configuration prompts

Some modules ask questions during installation that affect their behavior:

| Module | Prompt | Options | Effect |
|--------|--------|---------|--------|
| **settings** | Permission mode | `ask` / `dontAsk` | Controls whether Claude asks before running tools or auto-approves |
| **hooks** | Protected branches | Custom list | Additional branch names to protect from direct commits |
| **hooks** | Auto update check | yes / no | Whether to check for CCGM updates once daily |
| **brand-naming** | Add MCP server | yes / no | Whether to register Instant Domain Search MCP server via `claude mcp add --scope user` |

## Customizing hooks

CCGM hooks are Python scripts in `~/.claude/hooks/`. They are registered in `settings.json` under the `hooks` key. If you need to modify a hook's behavior:

1. If using copy mode: edit the hook file directly in `~/.claude/hooks/`
2. If using link mode: the file is a symlink to the CCGM repo, so edit it there

To disable a specific hook without uninstalling, remove its entry from the `hooks` section in `settings.json`.

## Scope precedence

When both global (`~/.claude/`) and project (`.claude/`) configurations exist, Claude Code merges them with project-level taking precedence. This means:

- Project rules override global rules with the same filename
- Project settings override global settings for matching keys
- Both sets of hooks run (project hooks in addition to global hooks)
