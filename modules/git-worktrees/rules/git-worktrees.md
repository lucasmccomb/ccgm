# Git Worktrees (Solo-Agent Isolation)

Worktrees let a single agent keep multiple branches checked out at once in sibling directories, sharing one `.git` folder. They are the solo-agent equivalent of the multi-clone setup - lighter, no port registry, no cross-agent coordination.

## When to Use a Worktree

Use `git worktree` when:

- You are the only agent working on the repo right now
- You want to try a change on a new branch without switching or stashing in place
- You want to compare two branches side by side (run both, diff outputs)
- You want a clean test baseline that a destructive experiment cannot pollute

## When NOT to Use a Worktree (Use Clones Instead)

Reach for the `multi-agent` module's multi-clone architecture when:

- Multiple agents are running in parallel on the same repo (worktrees share the index and HEAD ref database - two simultaneous writers cause lock contention)
- You need per-branch dev server ports (worktrees share `.env`; clones have per-clone `.env.clone` with pre-computed `FRONTEND_PORT` / `BACKEND_PORT`)
- You need per-branch issue tracking via the hook-driven `tracking.csv`
- The work will span days and you want persistent per-branch session logs

See `multi-agent/rules/multi-agent.md` and `~/.claude/multi-agent-system.md` for the clone-based alternative.

## Directory Selection

Prefer project-local worktree directories over a global one.

- **Project-local (preferred)**: `<repo>/.worktrees/<branch-name>/`
  - Keeps worktrees next to the repo they belong to
  - Easier cleanup when the repo is archived
  - Requires `.worktrees/` to be gitignored
- **Global fallback**: `~/code/worktrees/<repo>-<branch-name>/`
  - Use only when the repo refuses to gitignore `.worktrees/` (e.g., enforced `.gitignore` policy)
  - Never commit files from a global worktree back without re-verifying paths

## Pre-Flight Checks (Before Creating a Worktree)

1. **Verify `.worktrees/` is gitignored** when using project-local. If not, add it to `.gitignore` in the same commit or before creating the worktree. Committing `.worktrees/` is catastrophic - it nests the entire working tree inside the repo.
2. **Verify the current working tree is clean** or has only tracked changes. Worktrees share the index with the main checkout; dirty state can confuse `git worktree add`.
3. **Verify the target branch does not already have a worktree**: `git worktree list` shows all existing worktrees.
4. **Verify the new branch name is unique**: `git branch --list {name}` must be empty unless you are deliberately re-checking out an existing branch.

## Creating a Worktree

```bash
# New branch off main
git fetch origin main
git worktree add -b <branch-name> .worktrees/<branch-name> origin/main

# Existing branch
git worktree add .worktrees/<branch-name> <existing-branch>
```

After creation, run project setup inside the worktree. Auto-detect based on files present:

- `package.json` + `pnpm-lock.yaml` -> `pnpm install`
- `package.json` + `package-lock.json` -> `npm install`
- `package.json` + `yarn.lock` -> `yarn install`
- `Cargo.toml` -> `cargo build`
- `requirements.txt` -> `pip install -r requirements.txt`
- `Gemfile` -> `bundle install`
- `go.mod` -> `go mod download`

Then verify a clean test baseline: run the project's test command once, confirm it exits 0, and only then hand off to feature work. A failing baseline makes later test failures ambiguous.

## Cleanup

When the branch is done (merged, abandoned, or paused), remove the worktree:

```bash
# Preferred - refuses if there are uncommitted changes
git worktree remove .worktrees/<branch-name>

# Force - use only after reviewing what would be lost
git worktree remove --force .worktrees/<branch-name>
```

After removal, prune stale administrative state:

```bash
git worktree prune
```

## Pitfalls

### Worktree Lock

`git worktree add` creates `.git/worktrees/<name>/` with a `locked` file if the worktree is marked as permanent. A locked worktree cannot be removed by `git worktree remove` without first running `git worktree unlock .worktrees/<name>`. Do not lock worktrees unless you have a specific reason.

### Moving a Worktree with Uncommitted Changes

`mv .worktrees/foo .worktrees/bar` breaks Git's internal pointers - the `.git/worktrees/foo/` metadata still refers to the old path. Instead:

```bash
git worktree move .worktrees/foo .worktrees/bar
```

Never `mv` or `cp -r` a worktree directory manually. Use `git worktree move` or remove + re-add.

### Two Worktrees, Same Branch

Git refuses to check out the same branch in two worktrees simultaneously. This is a feature, not a bug - it prevents divergent commits on the same branch ref. If you see `fatal: 'branch' is already checked out at ...`, either reuse the existing worktree or switch one of them to a different branch.

### Shared Hooks and Config

Worktrees share `.git/hooks/` and `.git/config` with the main checkout. A hook installed in one affects all worktrees. Treat hook changes as global, not per-branch.

### Stale `.env` Files

Worktrees do NOT copy `.env` from the main checkout. Symlink or copy it manually if the worktree needs local secrets. Never commit `.env` from a worktree - it is typically gitignored in the main checkout but a fresh worktree may not inherit that context if the gitignore rule is out of date.

## Integration with Existing Git Rules

Worktree feature work still follows the repo's git-workflow rules:

- Branch from `origin/main` (fetch first)
- Rebase by default when pulling main into a feature branch
- No AI attribution in commits or PRs
- Always sync before history-altering commands
- Never `git stash` - commit WIP instead

The only thing worktrees change is **where** the working tree lives, not how branches, commits, or PRs are managed.
