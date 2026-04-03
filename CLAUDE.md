# CLAUDE.md - CCGM Repository

Instructions for Claude Code when working on the CCGM (Claude Code God Mode) repository itself.

## What This Repo Is

CCGM is a modular Claude Code configuration system. It contains 27 modules that users can selectively install to configure Claude Code's behavior, hooks, commands, and permissions.

## Repository Structure

```
ccgm/
├── start.sh            # Main entry point (bash)
├── update.sh           # Check for upstream changes
├── uninstall.sh        # Clean removal
├── lib/                # Installer utilities
│   ├── ui.sh           # TUI (gum + bash fallback)
│   ├── template.sh     # __PLACEHOLDER__ expansion
│   ├── merge.sh        # settings.json merge via jq
│   ├── modules.sh      # Module discovery + deps
│   └── backup.sh       # Backup/restore
├── modules/            # 15 self-contained modules
│   └── {name}/
│       ├── module.json # Manifest
│       ├── README.md   # Module docs
│       └── ...         # Content files
├── presets/            # Named module collections
│   ├── minimal.json
│   ├── standard.json
│   ├── full.json
│   └── team.json
└── tests/              # Test scripts
```

## Key Rules

### No Personal Data

This is a public repo. NEVER commit:
- GitHub usernames (e.g., specific user handles)
- Personal directory paths (e.g., /Users/specific-user)
- Service project IDs (Supabase refs, API endpoints)
- Personal repo names

Run the verification check before committing:
```bash
bash tests/test-no-personal-data.sh
```

### Module Development

Each module is self-contained in `modules/{name}/`:
- `module.json` defines metadata, files, dependencies, and config prompts
- Content files go in subdirectories matching their target location (rules/, commands/, hooks/)
- Rule files (rules/*.md) use generic language, NOT template variables
- Config files (hooks, settings) may use `__PLACEHOLDER__` template variables

### Template Variables

Used only in config files (not rule files):
- `__HOME__` - User's home directory
- `__USERNAME__` - GitHub username
- `__CODE_DIR__` - Code workspace directory
- `__LOG_REPO__` - Agent log repo name
- `__TIMEZONE__` - User's timezone
- `__DEFAULT_MODE__` - Permission default mode (ask/dontAsk)

### Testing

Before submitting changes:
```bash
# Validate all modules
bash tests/test-modules.sh

# Check for personal data leaks
bash tests/test-no-personal-data.sh

# Test installer (in temp directory)
bash tests/test-installer.sh
```

### Adding a New Module

1. Create `modules/{name}/` directory
2. Create `module.json` following the schema in existing modules
3. Add content files in appropriate subdirectories
4. Create `README.md` with manual installation instructions
5. Add to relevant presets in `presets/`
6. Run tests

## Commit Message Format

```
#{issue_number}: {description}
```

## Branch Workflow

Feature branches from main. PRs with squash merge.
