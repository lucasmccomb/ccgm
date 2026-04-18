# Installer

The CCGM installer (`start.sh`) is an interactive bash script that handles prerequisite checking, module selection, dependency resolution, file installation, and verification.

## Installation flow

The installer runs 15 sequential steps:

### Step 1: Welcome

Displays a banner with the CCGM name and version.

### Step 2: Prerequisites

Checks for required and optional tools:

| Tool | Required | Purpose |
|------|----------|---------|
| `claude` | Yes | Claude Code CLI |
| `git` | Yes | Version control |
| `python3` | Yes | Hook scripts |
| `jq` | Yes | JSON manipulation for settings merge |
| `gh` | No | GitHub CLI for auto-detecting username, issue/PR commands |

If a required tool is missing, the installer detects your package manager (Homebrew, apt, dnf, or pacman) and offers to install it. On macOS without Homebrew, it offers to install Homebrew first.

### Step 3: Configuration

Collects user-specific values:

- **GitHub username** - auto-detected via `gh api user` if GitHub CLI is installed, otherwise prompted
- **Code directory** - defaults to `~/code`
- **Timezone** - auto-detected from system settings

### Step 4: Scope selection

Choose where to install:

- **Global** (`~/.claude/`) - applies to all projects
- **Project** (`.claude/` in current directory) - applies only here
- **Both** - installs to both locations

### Step 5: Module selection

Choose a preset (minimal, standard, full, team) or select individual modules from a checkbox menu. The menu groups modules by category (core, commands, workflow, patterns, tech-specific).

### Step 6: Dependency resolution

Automatically adds any modules required by your selection. Uses a depth-first topological sort with cycle detection. Reports any automatically added dependencies.

For example, selecting `xplan` automatically adds `multi-agent` (its dependency), which adds `startup-dashboard` (multi-agent's dependency).

### Step 7: Module config prompts

Each module can define `configPrompts` in its `module.json`. The installer asks these questions and stores answers for template expansion. See [Configuration - Module configuration prompts](configuration.md#module-configuration-prompts) for the full list.

### Step 8: Preview

Shows a complete list of files that will be created or overwritten, grouped by module. This is the last chance to review before changes are made.

### Step 9: Confirm

A single yes/no gate. Answering no exits without making changes.

### Step 10: Backup

Creates a timestamped backup of existing `~/.claude/` contents to `~/.claude/backups/ccgm-YYYYMMDD-HHMMSS/`. Only backs up files that CCGM will overwrite.

### Step 11: Install

Processes each file according to its type:

| File type | Behavior |
|-----------|----------|
| **copy** (default) | Copies the file to the target location. Template variables are expanded via `sed`. |
| **link** | Creates a symlink to the source file in the CCGM repo. Only available with `--link` flag. |
| **merge** | Deep-merges JSON into the existing `settings.json` using `jq`. Arrays like `allow` and `deny` are deduplicated. Hook arrays are concatenated. |

Also writes `~/.claude/.ccgm.env` with all collected configuration values.

### Step 12: Manifest

Writes `~/.claude/.ccgm-manifest.json` recording:
- Version, timestamp, preset name
- Scope and link mode
- List of installed modules and files
- Backup paths
- Path to the CCGM repository (`ccgmRoot`)

This manifest is used by `update.sh` and `uninstall.sh` to know what was installed.

### Step 13: Verification

Checks that all installed files exist on disk, scans for unexpanded `__PLACEHOLDER__` tokens (indicating a template expansion failure), and validates `settings.json` as valid JSON via `jq`.

### Step 14: Shell alias

Optionally adds `alias ccgm="claude /startup"` to `~/.zshrc` or `~/.bashrc`. Detects existing aliases to avoid duplicates.

### Step 15: Next steps

Displays a summary with instructions to restart Claude Code and begin using the installed modules.

## Settings merge

The settings merge (`lib/merge.sh`) deserves special attention because `settings.json` is shared between CCGM modules.

When multiple modules contribute to `settings.json` (via `settings.partial.json` files with `"merge": true`), the installer deep-merges them using a custom `jq` function:

- **`allow` and `deny` arrays**: Entries are concatenated and deduplicated with `unique`
- **`hooks` object**: Hook event arrays (PreToolUse, PostToolUse, etc.) are concatenated
- **`enabledPlugins`**: Deep-merged
- **Other keys**: Standard JSON merge (later values override earlier)

This means each module can add its own permissions and hooks without overwriting what other modules installed.

## Updating

```bash
cd /path/to/ccgm
./update.sh
```

The updater performs these steps:

1. **Fetch** - runs `git fetch origin` to check for upstream changes
2. **Compare** - shows the commit log between your local HEAD and `origin/main`
3. **Categorize** - groups changed files by type (modules, presets, installer, other)
4. **Pull** - offers to `git pull --ff-only` to update the local repo
5. **Re-install** - offers to re-run the installer using the same preset, scope, and link mode recorded in the manifest
6. **Drift check** - compares installed files against source files to detect local modifications (for non-template, non-merge files)

## Uninstalling

```bash
cd /path/to/ccgm
./uninstall.sh
```

The uninstaller:

1. Reads `.ccgm-manifest.json` to find the exact files that were installed
2. Creates a safety backup before removing anything
3. Removes each file (handles both regular files and symlinks)
4. Removes `.ccgm-manifest.json` and `.ccgm.env`
5. Cleans up empty `rules/`, `commands/`, and `hooks/` directories
6. Offers to restore from the safety backup if you change your mind

Only CCGM-installed files are removed. Personal files you created in `~/.claude/` are untouched.

## Installer library

The installer is split into library files in `lib/`:

| File | Purpose |
|------|---------|
| `lib/ui.sh` | Pure-bash ANSI TUI with colored output, menus, and progress indicators. No external dependencies. |
| `lib/modules.sh` | Module discovery (scans `modules/` for `module.json` files), dependency resolution (topological sort), and preset loading. |
| `lib/template.sh` | Template variable expansion via `sed`. Handles macOS and Linux `sed` differences. |
| `lib/merge.sh` | Deep JSON merge for `settings.json` using `jq`. Special handling for arrays and hook objects. |
| `lib/backup.sh` | Timestamped backup and restore of `~/.claude/` contents. |

## Non-interactive mode

Set environment variables to skip all prompts:

```bash
CCGM_NON_INTERACTIVE=1 \
  CCGM_USERNAME="github-user" \
  CCGM_CODE_DIR="$HOME/code" \
  CCGM_TIMEZONE="America/New_York" \
  ./start.sh --preset standard
```

| Variable | Description | Default |
|----------|-------------|---------|
| `CCGM_NON_INTERACTIVE` | Set to `1` to skip all prompts | - |
| `CCGM_USERNAME` | GitHub username | auto-detected via `gh` |
| `CCGM_CODE_DIR` | Code workspace directory | `~/code` |
| `CCGM_TIMEZONE` | Timezone | auto-detected |

All module config prompts use their default values in non-interactive mode.
