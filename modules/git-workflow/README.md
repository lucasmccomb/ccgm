# git-workflow

Git workflow rules: sync before history changes, rebase by default, post-merge cleanup, follow a repo's PR template if it has one (local check only), no AI attribution in commits.

## What It Does

This module installs a rules file that instructs Claude to:

- Never add AI attribution (Co-Authored-By, "Generated with Claude Code") to commits or PRs
- Follow a repo's PR template when one is present (a single local check); otherwise write a value-first body without hunting the org's `.github` repo or creating a template
- Always sync with remote before running history-altering git commands
- Use rebase by default when updating feature branches from main
- Return to a clean main branch state after PR merges
- Run pathspec-bearing git commands from the repo root (or `git -C`), not from a sub-package directory

## Manual Installation

Copy `rules/git-workflow.md` into your Claude configuration:

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/git-workflow.md ~/.claude/rules/git-workflow.md

# Project-level
mkdir -p .claude/rules
cp rules/git-workflow.md .claude/rules/git-workflow.md
```

## Files

| File | Description |
|------|-------------|
| `rules/git-workflow.md` | Rule file with git workflow conventions |
