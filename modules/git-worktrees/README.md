# git-worktrees

Solo-agent worktree-based isolation for feature work. A lighter alternative to the multi-clone architecture when only a single agent is active.

## What This Module Does

Installs rules and commands that instruct Claude to use `git worktree` for parallel branch work in a single clone. Worktrees let you keep multiple branches checked out simultaneously in sibling directories without duplicating the entire repository.

Key capabilities:

- **Solo-agent isolation**: keep a feature branch's working tree separate from `main` without switching branches in place
- **`/worktree-start`**: create a new worktree with gitignore verification and project-setup auto-detection
- **`/worktree-finish`**: four-option finishing gate (merge locally / push + PR / keep / discard with typed confirmation)

## When to Use vs Multi-Agent Clones

| Situation | Use |
|-----------|-----|
| Single agent, wants to try an idea on a branch without stashing | **Worktree** (`/worktree-start`) |
| Single agent, wants to compare two branches side by side | **Worktree** |
| Multiple agents working on the same repo in parallel | **Multi-clone** (see `multi-agent` module) |
| Need isolated dev server ports per branch | **Multi-clone** (worktrees share `.env`) |
| Need per-branch `node_modules` only temporarily | **Worktree** (cheap, local-only) |

Worktrees are cheaper than clones (shared `.git`, no re-fetch) but lack the port-registry, tracking-CSV, and cross-agent log coordination that the `multi-agent` module provides. Use clones when coordination matters, worktrees when isolation alone is enough.

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/git-worktrees.md` | rule | When to use worktrees, creation/cleanup, pitfalls |
| `commands/worktree-start.md` | command | `/worktree-start {branch-name}` |
| `commands/worktree-finish.md` | command | `/worktree-finish` with four-option gate |

## Dependencies

None. The module is self-contained.

## Manual Installation

```bash
# Rule
mkdir -p ~/.claude/rules
cp rules/git-worktrees.md ~/.claude/rules/git-worktrees.md

# Commands
mkdir -p ~/.claude/commands
cp commands/worktree-start.md ~/.claude/commands/worktree-start.md
cp commands/worktree-finish.md ~/.claude/commands/worktree-finish.md
```
