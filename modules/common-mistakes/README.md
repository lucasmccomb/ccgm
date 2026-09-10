# common-mistakes

8 battle-tested anti-patterns to avoid, learned from real-world Claude Code sessions.

## What It Does

This module installs a rules file that teaches Claude to avoid these common mistakes:

1. **Dependency Blindness** - Branching without checking open PRs
2. **ESLint Fast Refresh Violations** - Mixing component and non-component exports
3. **Suggesting Already-Tried Solutions** - Repeating what the user already attempted
4. **Premature Solutions** - Proposing fixes without understanding the full codebase
5. **Git Multi-Clone Issues** - Forgetting to branch from origin/main in multi-clone setups
6. **Cloudflare Pages vs Workers** - Choosing the wrong product for the use case
7. **Missing Git Integration** - Creating Cloudflare Pages without Git integration at inception (cannot be added later)

## Manual Installation

Copy `rules/common-mistakes.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/common-mistakes.md ~/.claude/rules/common-mistakes.md

# Project-level
mkdir -p .claude/rules
cp rules/common-mistakes.md .claude/rules/common-mistakes.md
```

## Files

| File | Description |
|------|-------------|
| `rules/common-mistakes.md` | Rule file with 8 anti-patterns and their prevention strategies |
