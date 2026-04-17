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

## Maintaining the Allow List

The `settings.base.json` allow list is a static, hand-curated baseline. To extend it for commands you actually run, use Claude Code's built-in `/less-permission-prompts` skill:

> "Scan your transcripts for common read-only Bash and MCP tool calls, then add a prioritized allowlist to project `.claude/settings.json` to reduce permission prompts."

Run `/less-permission-prompts` in any project to generate a project-local `.claude/settings.json` with allowlist additions derived from your session history. If patterns from a project-local file turn out to be universal across your work, promote them into this module's `settings.base.json` via a PR.

### Evaluation: CE claude-permissions-optimizer (issue #285)

EveryInc/compound-engineering-plugin previously shipped a `claude-permissions-optimizer` skill with similar goals (scan session history, classify commands, write allowlist entries). As of CE PR #578/#583 the skill was **removed from CE** and the CHANGELOG states: "drop skill in favor of `/less-permission-prompts`". CE's authors explicitly adopted Anthropic's first-party built-in as the recommended path.

**CCGM action**: none required. CCGM does not ship a permissions-optimizer skill (the `settings` module ships only a static allow list), and the CE version is no longer maintained. Users rely on the Anthropic-shipped `/less-permission-prompts` skill for dynamic allowlist additions. The transferable pipeline-design lessons from CE's defunct skill (ordering of filter / normalize / group / threshold / re-classify) are captured in their `docs/solutions/skill-design/claude-permissions-optimizer-classification-fix.md` if a future CCGM-native optimizer is ever written; they are not re-documented here to avoid duplicating upstream content.
