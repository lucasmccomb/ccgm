# CCGM (Claude Code God Mode)

Modular Claude Code configuration system - pick the modules you want, install in seconds.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What is CCGM?

CCGM is a curated collection of configuration modules for [Claude Code](https://claude.ai/code), Anthropic's CLI coding agent. Instead of hand-crafting rules, hooks, commands, and permissions from scratch, CCGM lets you pick from 15 ready-made modules and install them with a single command.

Each module is self-contained with its own documentation, so you can also copy individual files manually if you prefer.

## Quick Start

```bash
git clone https://github.com/your-username/ccgm.git
cd ccgm
./install.sh
```

The interactive installer walks you through module selection. For a quick setup, use a preset:

```bash
./install.sh --preset standard
```

## Module Catalog

| Module | Category | Description | Dependencies | Scope |
|--------|----------|-------------|--------------|-------|
| **autonomy** | core | Configure Claude as a fully autonomous Staff-level engineer who executes tasks end-to-end without asking unnecessary questions. | - | global, project |
| **git-workflow** | core | Git workflow rules: sync before history changes, rebase by default, post-merge cleanup, PR template detection, no AI attribution in commits. | - | global, project |
| **settings** | core | Base settings.json with comprehensive tool permissions (800+ allow entries), deny list for dangerous operations, and plugin configuration. Defaults to 'ask' mode for safety. | - | global |
| **hooks** | core | Python hooks that enforce git workflow rules: issue-first workflow, commit message format, branch protection, and auto-approval for file operations. | settings | global |
| **commands-core** | commands | Essential slash commands: /commit, /pr, /cpm (commit-PR-merge), /gs (git status), /ghi (create issue). | - | global |
| **commands-extra** | commands | Additional slash commands: /audit (codebase audit), /pwv (Playwright visual verify), /walkthrough (step-by-step guide), /promote-rule (promote repo rules to global). | - | global |
| **github-protocols** | workflow | GitHub repository management protocols: issue-first workflow, PR conventions, label taxonomy, code review standards. | - | global, project |
| **session-logging** | workflow | Structured agent session logging system with mandatory log triggers, log repo management, and session startup command. | - | global |
| **multi-agent** | workflow | Multi-clone architecture for parallel agent work with issue claiming, port allocation, and the /mawf workflow command. | session-logging | global |
| **xplan** | workflow | Deep research + planning + execution framework. Spawns parallel research/review agents, creates comprehensive plans, and executes via parallel agent waves. | multi-agent | global |
| **code-quality** | patterns | Code standards, testing requirements, error handling patterns, security practices, build verification, and living documents maintenance. | - | global, project |
| **browser-automation** | patterns | Rules for browser automation tool selection: Chrome extension, Playwright, and WebMCP. Includes verification priority order and UI verification workflow. | - | global |
| **common-mistakes** | patterns | 8 battle-tested anti-patterns to avoid: shallow directory exploration, dependency blindness, ESLint Fast Refresh, and more. | - | global, project |
| **cloudflare** | tech-specific | Cloudflare-specific rules: Pages vs Workers selection, deployment methods, Git integration requirements. | - | global, project |
| **supabase** | tech-specific | Supabase-specific rules: API key terminology (publishable/secret), environment variable naming, migration validation, and database change workflow. | - | global, project |

## Presets

Presets are named collections of modules for common use cases:

| Preset | Modules | Best For |
|--------|---------|----------|
| **minimal** | autonomy, git-workflow | Getting started with the basics |
| **standard** | autonomy, git-workflow, hooks, settings, commands-core | Most users |
| **full** | All 15 modules | Power users who want everything |
| **team** | autonomy, git-workflow, hooks, settings, commands-core, github-protocols, code-quality | Teams with shared conventions |

## Installation Options

```bash
# Interactive mode - choose modules one by one
./install.sh

# Preset mode - install a named collection
./install.sh --preset standard

# Project-level install - writes to .claude/ in current project instead of ~/.claude/
./install.sh --scope project

# Symlink mode - symlinks files instead of copying (for CCGM developers)
./install.sh --link
```

## What Gets Installed

CCGM installs files into `~/.claude/` (global) or `.claude/` (project-level):

```
~/.claude/
├── rules/*.md             # Claude Code rules (loaded automatically)
├── commands/*.md           # Custom slash commands (available as /command-name)
├── hooks/*.py              # Git workflow automation hooks
├── settings.json           # Permissions and tool configurations
├── .ccgm-manifest.json     # Tracks which modules are installed
└── .ccgm.env               # Your configuration values (template variables)
```

- **Rules** are markdown files that Claude reads automatically at session start. They shape Claude's behavior, coding style, and decision-making.
- **Commands** are slash commands you can invoke in Claude Code (e.g., `/commit`, `/pr`).
- **Hooks** are Python scripts triggered by Claude Code events (PreToolUse, UserPromptSubmit) that enforce workflow rules and auto-approve safe operations.
- **Settings** control which tools Claude can use without asking, which commands are denied, and plugin configuration.
- **Manifest** tracks installed modules so updates and uninstalls work correctly.
- **Env file** stores your personal configuration values (GitHub username, code directory path, etc.) used to expand template variables.

## Customization

### Personal rules

Create `~/.claude/rules/personal.md` with any rules specific to your workflow. CCGM will not overwrite this file.

### Settings overrides

Claude Code natively supports `~/.claude/settings.local.json` as a local override file. Any settings you put there will take precedence over the CCGM-managed `settings.json`.

### MCP servers

MCP server configuration lives in `~/.claude/mcp.json`, which is not managed by CCGM. Configure your MCP servers there independently.

### Template variables

Some modules use `__PLACEHOLDER__` template variables in their config files. During installation, you are prompted for values. These are stored in `~/.ccgm.env` and expanded at install time:

| Variable | Description | Used By |
|----------|-------------|---------|
| `__HOME__` | Home directory path | settings |
| `__USERNAME__` | GitHub username | hooks |
| `__CODE_DIR__` | Code workspace directory | settings |
| `__LOG_REPO__` | Agent log repo name | session-logging |
| `__TIMEZONE__` | Your timezone | session-logging |
| `__DEFAULT_MODE__` | Permission mode (ask/dontAsk) | settings |

## Updating

Pull the latest changes and re-run the installer to pick up new modules or updates to existing ones:

```bash
cd ccgm
./update.sh
```

## Uninstalling

Remove all CCGM-installed files (uses the manifest to remove only what CCGM installed):

```bash
cd ccgm
./uninstall.sh
```

## Manual Installation

Every module has its own `README.md` with copy-paste instructions for manual installation without the installer. Browse the `modules/` directory and copy the files you want:

```bash
# Example: manually install the autonomy module
cp modules/autonomy/rules/autonomy.md ~/.claude/rules/autonomy.md

# Example: manually install core commands
mkdir -p ~/.claude/commands
cp modules/commands-core/commands/*.md ~/.claude/commands/
```

## Requirements

- macOS or Linux
- bash 4+ or zsh
- git
- **gh CLI** (for modules that interact with GitHub: commands-core, commands-extra, github-protocols)
- **Python 3** (for the hooks module)
- **jq** (for the settings and hooks modules - merges JSON configurations)
- **gum** (optional - provides enhanced terminal UI during installation; falls back to plain bash prompts)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on creating modules, the module.json schema, and how to submit changes.

## License

[MIT](LICENSE)
