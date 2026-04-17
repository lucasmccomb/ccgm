# Contributing to CCGM

Thanks for your interest in contributing to CCGM. This guide covers how modules work, how to create new ones, and how to submit changes.

## How Modules Work

Each module is a self-contained directory under `modules/` with a `module.json` manifest and one or more content files. The installer reads the manifest to know what to install, where to put it, and what configuration to prompt for.

Modules install files into `~/.claude/` (global scope) or `.claude/` (project scope). The target location is determined by the `target` field in each file entry.

### Module Directory Structure

```
modules/{name}/
├── module.json          # Required: manifest with metadata, files, dependencies
├── README.md            # Required: documentation with manual install instructions
├── rules/               # Rule files (.md) - loaded automatically by Claude Code
│   └── {name}.md
├── commands/            # Command files (.md) - available as /command-name
│   └── {command}.md
├── agents/              # Reusable subagent prompts (.md) - invoked by commands/skills
│   └── {agent}.md
├── hooks/               # Hook scripts (.py) - triggered by Claude Code events
│   └── {hook}.py
├── settings.base.json   # Settings template (merged into settings.json)
├── settings.partial.json # Partial settings (merged into settings.json)
└── *.md                 # Additional documentation files
```

Not every module has all subdirectories. A simple module might only have `module.json`, `README.md`, and a single rule file.

## Creating a New Module

### 1. Create the module directory

```bash
mkdir -p modules/{your-module-name}
```

Use lowercase with hyphens for the directory name.

### 2. Create module.json

Every module needs a `module.json` manifest. Here is the full schema:

```json
{
  "name": "your-module-name",
  "displayName": "Your Module Name",
  "description": "One-line description of what the module does.",
  "category": "core",
  "scope": ["global", "project"],
  "dependencies": [],
  "files": {
    "rules/your-module.md": {
      "target": "rules/your-module.md",
      "type": "rule",
      "template": false
    }
  },
  "tags": ["relevant", "tags"],
  "configPrompts": []
}
```

### 3. Add content files

Create the files referenced in `module.json`. Place them in subdirectories that match the target location:

- `rules/*.md` for rule files
- `commands/*.md` for slash commands
- `agents/*.md` for reusable subagent prompts
- `hooks/*.py` for event hooks

### When to use `agents/`

Use `agents/` for reusable subagent definitions that are invoked by multiple commands or skills (for example, a `code-reviewer` or `adversarial-reviewer` prompt that several review pipelines share). Keep one-off prompts inline in the command or skill that uses them — promote to `agents/` only when the second caller appears.

### 4. Write a README.md

Every module must have a README.md that explains:

- What the module does
- What files it installs
- Manual installation instructions (copy commands)
- Dependencies, if any
- Template variables, if any

Look at `modules/autonomy/README.md` for a minimal example and `modules/hooks/README.md` for a full-featured example.

### 5. Add to relevant presets

If your module is broadly useful, add its name to the appropriate preset arrays in `presets/`:

- `minimal.json` - Only essential modules
- `standard.json` - Modules most users will want
- `full.json` - All modules (your module should always be here)
- `team.json` - Modules useful for team workflows

### 6. Run tests

```bash
# Validate all module manifests
bash tests/test-modules.sh

# Check for personal data leaks
bash tests/test-no-personal-data.sh
```

## module.json Schema Reference

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Module identifier, matches directory name. Lowercase with hyphens. |
| `displayName` | string | yes | Human-readable name shown during installation. |
| `description` | string | yes | One-line description of what the module provides. |
| `category` | string | yes | Module category (see categories below). |
| `scope` | string[] | yes | Where the module can be installed: `"global"`, `"project"`, or both. |
| `dependencies` | string[] | yes | Module names that must be installed first. Use `[]` for no dependencies. |
| `files` | object | yes | Map of source paths to file descriptors (see below). |
| `tags` | string[] | yes | Searchable tags for discovery. |
| `configPrompts` | object[] | yes | Configuration questions asked during installation. Use `[]` for none. |

### Categories

| Category | Description |
|----------|-------------|
| `core` | Foundational modules that most users will want |
| `commands` | Slash command collections |
| `workflow` | Development workflow automation |
| `patterns` | Coding patterns, standards, and anti-patterns |
| `tech-specific` | Rules for specific technologies (Cloudflare, Supabase, etc.) |

### File Descriptor Fields

Each entry in the `files` object maps a source path (relative to the module directory) to a descriptor:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target` | string | yes | Destination path relative to the install root (`~/.claude/` or `.claude/`). |
| `type` | string | yes | File type: `rule`, `command`, `agent`, `hook`, `config`, or `doc`. |
| `template` | boolean | yes | Whether the file contains `__PLACEHOLDER__` template variables to expand. |
| `merge` | boolean | no | For `config` type only. If `true`, the file is merged into the target rather than replacing it. Used for settings partials. |

### File Types

| Type | Extension | Description |
|------|-----------|-------------|
| `rule` | `.md` | Markdown rules loaded by Claude Code at session start. Shapes behavior and decision-making. |
| `command` | `.md` | Markdown files that become slash commands in Claude Code. File name becomes the command name. |
| `agent` | `.md` | Reusable subagent prompts invoked by commands or skills via the Task tool. Installed to `~/.claude/agents/`. Use for prompts shared across two or more callers; keep one-off prompts inline. |
| `hook` | `.py` | Python scripts triggered by Claude Code events (PreToolUse, UserPromptSubmit, etc.). |
| `config` | `.json` | JSON configuration files (settings, partials). May be merged into existing files. |
| `doc` | `.md` | Documentation files installed alongside rules. Referenced by rules but not auto-loaded. |

### Config Prompts

Each entry in `configPrompts` defines a question asked during installation:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | yes | The template variable name (e.g., `__LOG_REPO__`) or a config key. |
| `prompt` | string | yes | The question shown to the user. |
| `default` | string | yes | Default value if the user presses Enter. |
| `options` | string[] | no | If provided, restricts answers to these values (shown as a select menu). |

## Template Variables

Template variables use `__DOUBLE_UNDERSCORE__` syntax and are expanded during installation. They are only used in files where `"template": true` in the file descriptor.

### When to Use Template Variables

- **Config files** (settings.json, hook scripts) that need user-specific paths or usernames
- **Never in rule files** - rules use generic language that works for anyone without substitution

### Available Variables

| Variable | Description | Prompted By |
|----------|-------------|-------------|
| `__HOME__` | User's home directory | Auto-detected |
| `__USERNAME__` | GitHub username | Prompted during install |
| `__CODE_DIR__` | Code workspace directory | Prompted during install |
| `__LOG_REPO__` | Agent log repo name | session-logging module |
| `__TIMEZONE__` | User's timezone | Auto-detected |
| `__DEFAULT_MODE__` | Permission default mode (ask/dontAsk) | settings module |

## Rule File Conventions

Rule files (`rules/*.md`) are the most common file type. Follow these conventions:

1. **Use generic language.** Rules must work for any user without template variable substitution. Write "your home directory" instead of a specific path.

2. **Be prescriptive.** Rules should clearly state what Claude should and should not do. Use imperative language.

3. **Include examples.** Show concrete examples of correct and incorrect behavior when helpful.

4. **Keep scope narrow.** Each rule file should cover one coherent topic. If a rule file grows beyond a few hundred lines, consider splitting it into a separate module.

5. **No personal data.** Never include specific usernames, paths, repo names, or API endpoints. Run `tests/test-no-personal-data.sh` to verify.

## Testing Your Module

### Validate module manifests

```bash
bash tests/test-modules.sh
```

This checks that every `module.json` is valid JSON, has required fields, references files that exist, and that dependencies point to real modules.

### Check for personal data

```bash
bash tests/test-no-personal-data.sh
```

This scans all files for personal data patterns (specific usernames, paths like `/Users/specific-name`, project IDs, etc.). The test must pass before your changes can be merged.

### Test the installer

```bash
bash tests/test-installer.sh
```

This runs the installer in a temporary directory to verify end-to-end behavior.

## Commit Message Format

All commits must follow this format:

```
#{issue_number}: {description}
```

Examples:

```
#12: Add Redis module with connection rules
#5: Fix template variable expansion in hooks
```

## Pull Request Process

1. Create a feature branch from `main` (e.g., `12-add-redis-module`).
2. Make your changes and ensure all tests pass.
3. Push and create a PR. PRs are squash-merged into `main`.
4. Reference the issue number in the PR description with `Closes #N`.

## Questions?

Open an issue on the repository if anything is unclear.
