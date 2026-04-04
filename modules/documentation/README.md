# Documentation Update

Provides the `/docupdate` slash command for comprehensive documentation auditing and updating. Works in any codebase type (npm, Cargo, Python, Ruby, Go, monorepo).

## Command

### `/docupdate [--scope <area>] [--dry-run]`

Spawns 4 parallel audit agents to find every gap between your documentation and actual codebase state, then applies targeted surgical fixes.

**What it audits:**
- README accuracy (packages, features, commands, setup steps, versions, internal links)
- Table of contents vs actual headings (anchor slugs, order, missing entries)
- Onboarding/setup flow (prerequisites, env vars, setup steps, documented scripts)
- Module and feature coverage (source dirs vs docs, undocumented new additions)

**Flags:**
- `--scope readme|toc|onboarding|all` - Limit to specific audit areas (default: all)
- `--dry-run` - Print the gap report without making any changes

**Usage:**
```
/docupdate                    # Full audit and fix
/docupdate --dry-run          # Report gaps without making changes
/docupdate --scope toc        # TOC only
/docupdate --scope readme     # README only
```

## Manual Installation

```bash
cp commands/docupdate.md ~/.claude/commands/docupdate.md
```

## How It Works

1. **Discover** - Detects project type and finds all documentation files
2. **Audit** - Runs 4 agents in parallel, each focused on one area
3. **Report** - Synthesizes findings into Critical / Missing / Stale / TOC / Minor categories
4. **Confirm** - Asks which fixes to apply
5. **Fix** - Makes targeted edits matching existing voice and formatting
6. **Summary** - Lists every file changed and any gaps left for manual review
