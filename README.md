# CCGM (Claude Code God Mode)

<img width="369" height="135" alt="image" src="https://github.com/user-attachments/assets/29953ee7-3e7c-47cc-9ef7-e8b2e8ccbc89" />

Modular configuration system for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - pick the modules you want, install in seconds. Works with Claude Code CLI, VS Code, Cursor, the macOS Claude app, and any other editor with Claude Code support.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Table of Contents

- [What is CCGM?](#what-is-ccgm)
- [Requirements](#requirements)
- [Install](#install)
- [Module Catalog](#module-catalog)
- [Customization](#customization)
- [Manual Installation](#manual-installation)
- [Documentation](#documentation)
- [Contributing](#contributing)

## What is CCGM?

CCGM is a curated collection of 25 configuration modules for Claude Code. Instead of hand-crafting rules, hooks, commands, and permissions from scratch, you pick modules and install them with a single command.

Each module is self-contained with its own README, so you can also [copy individual files manually](#manual-installation) without the installer.

### What gets installed

CCGM places files into `~/.claude/` (global) or `.claude/` (project-level):

| Directory | What | How Claude Uses It |
|-----------|------|-------------------|
| `rules/*.md` | Behavior rules | Loaded automatically at session start |
| `commands/*.md` | Slash commands | Available as `/commit`, `/pr`, etc. |
| `hooks/*.py` | Workflow hooks | Triggered on Claude Code events |
| `settings.json` | Permissions | Controls tool access and auto-approval |

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- macOS or Linux
- bash 4+ or zsh
- git

The installer checks for Claude Code, additional tools (jq, Python 3, gh CLI, gum), and offers to install any that are missing.

## Install

```bash
git clone https://github.com/lucasmccomb/ccgm.git
cd ccgm
./start.sh
```

The interactive setup handles everything: prerequisite checks, module selection, and configuration. No flags needed.

### Installing from an editor

If you use Claude Code in VS Code, Cursor, or another editor with a built-in terminal, run the install commands in that terminal. If your editor doesn't have one, use Terminal.app (macOS) or any terminal emulator. CCGM installs to `~/.claude/`, which is shared across all Claude Code environments - install once, works everywhere.

### Agent installation

For AI agents installing CCGM programmatically:

```bash
git clone https://github.com/lucasmccomb/ccgm.git ~/ccgm
cd ~/ccgm
CCGM_NON_INTERACTIVE=1 \
  CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo 'github-user')" \
  ./start.sh --preset standard
```

| Variable | Description | Default |
|----------|-------------|---------|
| `CCGM_NON_INTERACTIVE` | Set to `1` to skip all prompts | - |
| `CCGM_USERNAME` | GitHub username | auto-detected via `gh` |
| `CCGM_CODE_DIR` | Code workspace directory | `~/code` |
| `CCGM_TIMEZONE` | Timezone | auto-detected |

Restart Claude Code or start a new session after installation.

### Presets

For a quick install with a preset:

```bash
./start.sh --preset standard
```

| Preset | Modules | Best For |
|--------|---------|----------|
| **minimal** | autonomy, git-workflow | Getting started |
| **standard** | autonomy, git-workflow, hooks, settings, commands-core | Most users |
| **full** | All 25 modules | Power users |
| **team** | standard + github-protocols, code-quality | Teams |

### Other install options

```bash
./start.sh --scope project    # Install to .claude/ in current project instead of ~/.claude/
./start.sh --link             # Symlink instead of copy (for CCGM developers)
```

### Update / Uninstall

```bash
./update.sh      # Pull latest changes and re-apply
./uninstall.sh   # Remove only CCGM-installed files
```

## Module Catalog

| Module | Category | Description | Dependencies |
|--------|----------|-------------|--------------|
| **autonomy** | core | Claude as a fully autonomous engineer - executes tasks end-to-end without unnecessary questions | - |
| **git-workflow** | core | Git rules: sync before history changes, rebase by default, post-merge cleanup, no AI attribution | - |
| **settings** | core | Base settings.json with 800+ tool permissions, deny list, plugin config. Defaults to safe 'ask' mode | - |
| **hooks** | core | Python hooks: issue-first workflow, commit format, branch protection, auto-approval for safe ops | settings |
| **commands-core** | commands | /commit, /pr, /cpm (commit-PR-merge), /gs (git status), /ghi (create issue) | - |
| **commands-extra** | commands | /audit (codebase audit), /pwv (Playwright verify), /walkthrough, /promote-rule | - |
| **brand-naming** | commands | /brand (full naming pipeline with word exploration, domain/trademark/app store checks) and /brand-check (single-name deep verification) | - |
| **github-protocols** | workflow | Issue-first workflow, PR conventions, label taxonomy, code review standards | - |
| **session-logging** | workflow | Structured agent session logging with mandatory triggers and startup command | - |
| **multi-agent** | workflow | Multi-clone parallel agent work with issue claiming, port allocation, /mawf workflow | session-logging |
| **xplan** | workflow | Deep research + planning + execution framework with parallel agent waves | multi-agent |
| **self-improving** | workflow | Meta-learning: extract experience from tasks, identify patterns, update memory, improve across sessions | - |
| **subagent-patterns** | workflow | Subagent dispatch: task decomposition, spec-driven delegation, two-stage review, parallel coordination | - |
| **code-quality** | patterns | Code standards, testing requirements, error handling, security, build verification | - |
| **browser-automation** | patterns | Browser tool selection (Chrome, Playwright, WebMCP), verification priority, UI testing workflow | - |
| **common-mistakes** | patterns | 8 battle-tested anti-patterns: shallow exploration, dependency blindness, ESLint Fast Refresh, more | - |
| **frontend-design** | patterns | Distinctive web UI: intentional aesthetics, typography, color systems, spatial composition | - |
| **systematic-debugging** | patterns | 4-phase root cause investigation: investigate, analyze, test hypotheses, implement fix | - |
| **test-driven-development** | patterns | Strict red-green-refactor TDD discipline. No production code without a failing test first | - |
| **verification** | patterns | Evidence-before-claims: fresh execution of verification commands, read full output before asserting done | - |
| **cloudflare** | tech-specific | Pages vs Workers selection, deployment methods, Git integration requirements | - |
| **supabase** | tech-specific | API key terminology, env var naming, migration validation, database workflow | - |
| **mcp-development** | tech-specific | Building MCP servers: project structure, tool design, error handling, testing, evaluation patterns | - |
| **shadcn** | tech-specific | shadcn/ui patterns: composition, semantic theming tokens, form architecture, accessibility | - |
| **tailwind** | tech-specific | Tailwind CSS v4 design system: CSS-first config, design tokens, CVA variants, dark mode, responsive grids | - |

## Customization

| What | How |
|------|-----|
| Personal rules | Create `~/.claude/rules/personal.md` - CCGM won't overwrite it |
| Settings overrides | Use `~/.claude/settings.local.json` (native Claude Code feature) |
| MCP servers | Configure in `~/.claude/mcp.json` (not managed by CCGM) |

### Template variables

Config files use placeholders that are expanded during installation:

| Variable | Description | Used By |
|----------|-------------|---------|
| `__HOME__` | Home directory path | settings |
| `__USERNAME__` | GitHub username | hooks |
| `__CODE_DIR__` | Code workspace directory | settings |
| `__LOG_REPO__` | Agent log repo name | session-logging |
| `__TIMEZONE__` | Your timezone | session-logging |
| `__DEFAULT_MODE__` | Permission mode (ask/dontAsk) | settings |

## Manual Installation

Every module has its own README with copy-paste instructions. Browse `modules/` and copy what you want:

```bash
# Example: install the autonomy module
mkdir -p ~/.claude/rules
cp modules/autonomy/rules/autonomy.md ~/.claude/rules/

# Example: install core commands
mkdir -p ~/.claude/commands
cp modules/commands-core/commands/*.md ~/.claude/commands/
```

## Utilities

### statusline.sh - Claude Code Session Monitor

Display live session metrics at the bottom of your Claude Code terminal. Shows model, directory, git branch, context usage, and 5-hour & 7-day rate limits with reset countdowns.

**Usage:**

```bash
# Copy to your Claude Code config
cp lib/statusline.sh ~/.claude/statusline-command.sh
chmod +x ~/.claude/statusline-command.sh
```

Then configure Claude Code settings:

```bash
/statusline use ~/.claude/statusline-command.sh
```

Or manually add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline-command.sh"
  }
}
```

**Display Example:**

```
O-4.6 | code | ctx:8% | 5h:62% ███░░ 2h26m | 7d:79% ████░
```

**Features:**
- Abbreviated model (O-4.6, S-4.6, H-4.5, etc.)
- Current directory and git branch
- Context window usage (0-100%)
- 5-hour rate limit with bar and reset countdown
- 7-day rate limit with bar
- Color-coded by usage: green <60%, yellow <85%, red 85%+

## Documentation

The `docs/` directory contains comprehensive documentation:

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation walkthrough, first session, prerequisites |
| [Module Catalog](docs/modules.md) | Detailed reference for all 25 modules |
| [Commands Reference](docs/commands.md) | All 17 slash commands with usage examples |
| [Hooks Reference](docs/hooks.md) | All 9 hooks explained - what they do and when they fire |
| [Presets](docs/presets.md) | Preset breakdowns and recommendations |
| [Installer](docs/installer.md) | How the installer works, updating, uninstalling |
| [Configuration](docs/configuration.md) | Customization, template variables, settings overrides |
| [Multi-Agent System](docs/multi-agent.md) | Parallel agent coordination, port allocation, issue tracking |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on creating modules, the module.json schema, and how to submit changes.

## License

[MIT](LICENSE)
