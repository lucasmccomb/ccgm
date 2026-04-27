# common-mistakes

8 battle-tested anti-patterns to avoid, learned from real-world Claude Code sessions.

## What It Does

This module installs a rules file that teaches Claude to avoid these common mistakes:

1. **Shallow Directory Exploration** - Missing nested structures in monorepos
2. **Dependency Blindness** - Branching without checking open PRs
3. **ESLint Fast Refresh Violations** - Mixing component and non-component exports
4. **Suggesting Already-Tried Solutions** - Repeating what the user already attempted
5. **Premature Solutions** - Proposing fixes without understanding the full codebase
6. **Git Multi-Clone Issues** - Forgetting to branch from origin/main in multi-clone setups
7. **Cloudflare Pages vs Workers** - Choosing the wrong product for the use case
8. **Missing Git Integration** - Creating Cloudflare Pages without Git integration at inception (cannot be added later)

## Manual Installation

Copy `rules/common-mistakes.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/common-mistakes.md ~/.claude/rules/common-mistakes.md

# Project-level
cp rules/common-mistakes.md .claude/rules/common-mistakes.md
```

## Files

| File | Description |
|------|-------------|
| `rules/common-mistakes.md` | Rule file with 8 anti-patterns and their prevention strategies |
