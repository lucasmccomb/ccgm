# Getting Started

This guide walks through installing CCGM, choosing modules, and running your first session.

## Prerequisites

CCGM requires:

- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** - the CLI tool from Anthropic (`npm install -g @anthropic-ai/claude-code`)
- **macOS or Linux** - Windows is not supported
- **bash 4+** or **zsh**
- **git** - for cloning and version tracking
- **Python 3** - hooks are written in Python
- **jq** - for JSON manipulation during settings merge

Optional but recommended:

- **[GitHub CLI](https://cli.github.com/)** (`gh`) - enables auto-detection of your GitHub username, issue management commands, and PR workflows
- **[gum](https://github.com/charmbracelet/gum)** - prettier interactive menus (the installer falls back to pure bash if gum is not available)

The installer checks for all prerequisites and offers to install missing tools using your system's package manager (Homebrew on macOS, apt/dnf/pacman on Linux).

## Installation

### 1. Clone and run

```bash
git clone https://github.com/YOUR_USERNAME/ccgm.git
cd ccgm
./start.sh
```

The interactive installer handles everything from here.

### 2. Choose a preset (or pick modules individually)

The installer offers four presets, or you can select modules one by one:

| Preset | What you get | Best for |
|--------|-------------|----------|
| **minimal** | Core autonomy + git workflow rules | Trying CCGM for the first time |
| **standard** | Minimal + hooks, settings, core commands | Most individual developers |
| **team** | Standard + github-protocols, code-quality, debugging, verification | Teams with shared repos |
| **full** | All 29 modules | Power users who want everything |

See [Presets](presets.md) for detailed breakdowns.

### 3. Answer configuration prompts

Depending on which modules you selected, the installer may ask:

- **GitHub username** - auto-detected from `gh api user` if GitHub CLI is installed
- **Code directory** - where your projects live (default: `~/code`)
- **Timezone** - auto-detected from system settings
- **Permission mode** - `ask` (confirm before risky actions) or `dontAsk` (full auto-approval)

### 4. Restart Claude Code

After installation, start a new Claude Code session. Your new rules, commands, and hooks will be active immediately.

## Install scopes

CCGM can install to two locations:

| Scope | Path | Effect |
|-------|------|--------|
| **Global** | `~/.claude/` | Applies to all projects and all Claude Code environments |
| **Project** | `.claude/` in current directory | Applies only to the current project |

```bash
./start.sh                    # Interactive scope selection
./start.sh --scope global     # Global only
./start.sh --scope project    # Project only
```

Global installation is the most common choice. Project-level installation is useful when you want different rules for a specific repo, or when sharing configuration with a team via version control.

## Install modes

| Mode | Flag | Behavior |
|------|------|----------|
| **Copy** (default) | - | Copies files to `~/.claude/`. Independent of the CCGM repo after install. |
| **Link** | `--link` | Creates symlinks to the CCGM repo. Changes to the repo are reflected immediately. Best for CCGM developers. |

## Your first session

After installation, start Claude Code:

```bash
claude
```

If you installed the **session-logging** module, Claude will automatically run the `/startup` command, which:

1. Identifies your agent and repo context
2. Pulls and reads session logs
3. Checks git status, open PRs, and open issues
4. Presents a dashboard with recommended next actions

If you installed **commands-core**, you now have these slash commands available:

- `/gs` - Git status dashboard
- `/commit` - Stage and commit with conventional format
- `/pr` - Push and create a pull request
- `/cpm` - One-shot commit + PR + merge workflow
- `/ghi` - Create a GitHub issue

Try `/gs` to see your project status at a glance.

## Non-interactive installation

For CI environments or agent-driven setup:

```bash
CCGM_NON_INTERACTIVE=1 \
  CCGM_USERNAME="your-github-username" \
  CCGM_CODE_DIR="$HOME/code" \
  CCGM_TIMEZONE="America/New_York" \
  ./start.sh --preset standard
```

See [Installer](installer.md) for the full list of environment variables.

## Updating

```bash
cd /path/to/ccgm
./update.sh
```

The updater fetches the latest changes, shows what changed, and offers to re-run the installer with your existing configuration. See [Installer - Updating](installer.md#updating) for details.

## Uninstalling

```bash
cd /path/to/ccgm
./uninstall.sh
```

Removes only CCGM-installed files (tracked via a manifest). Your personal files in `~/.claude/` are left untouched. See [Installer - Uninstalling](installer.md#uninstalling) for details.

## Next steps

- [Module Catalog](modules.md) - explore all 29 modules in detail
- [Commands Reference](commands.md) - learn every slash command
- [Hooks Reference](hooks.md) - understand the workflow automation
- [Configuration](configuration.md) - customize CCGM after installation
