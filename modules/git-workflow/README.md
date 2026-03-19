# git-workflow

Git workflow rules: sync before history changes, rebase by default, post-merge cleanup, PR template detection, no AI attribution in commits.

## What It Does

This module installs a rules file that instructs Claude to:

- Never add AI attribution (Co-Authored-By, "Generated with Claude Code") to commits or PRs
- Check for and use PR templates when creating pull requests
- Always sync with remote before running history-altering git commands
- Use rebase by default when updating feature branches from main
- Return to a clean main branch state after PR merges

## Manual Installation

Copy `rules/git-workflow.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/git-workflow.md ~/.claude/rules/git-workflow.md

# Project-level
cp rules/git-workflow.md .claude/rules/git-workflow.md
```

## Files

| File | Description |
|------|-------------|
| `rules/git-workflow.md` | Rule file with git workflow conventions |
