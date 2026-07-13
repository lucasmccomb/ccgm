# git-worktrees

Git worktrees as the **default isolation for parallel sub-agent delegation on one machine**, with enforced teardown so worktrees never silently fill the disk.

## What This Module Does

A worktree is a second working tree from the same `.git`, with its own index and HEAD. That independence is what makes parallel agents safe: each builds, tests, and commits on its own branch without touching the others. When a delegator (you, `/etp`, `/mawf`, `/xplan`, or the Agent/Workflow `isolation: "worktree"` option) fans work out to parallel implementers, each gets its own worktree — created per unit of work and destroyed when that unit merges — instead of a permanent extra clone.

Key capabilities:

- **Default parallel-delegation isolation**: one ephemeral worktree per unit of work, sharing the parent `.git`.
- **`/worktree-start`**: create a worktree hands-on, with gitignore verification and project-setup auto-detection.
- **`/worktree-finish`**: finish one worktree via a four-option gate (merge locally / push + PR / keep / discard).
- **`/worktree-sweep`**: repo-wide safe janitor — remove clean worktrees, preserve anything with unsaved work, prune stale metadata. The enforced-teardown backstop.

## Why It Exists

On 2026-07-13, delegated work using `isolation: "worktree"` left 33 stale worktrees consuming ~237 GB on one repo. The harness auto-removes a worktree only if it is *unchanged*; a built-in worktree lingers forever, and nothing mandated cleaning them up. This module makes worktrees the default (ephemeral, shared `.git`) **and** makes teardown load-bearing (mandatory per-unit removal + `/worktree-sweep` orphan backstop). See `rules/git-worktrees.md` for the full lifecycle and removal-safety rule.

## Worktrees vs Multi-Agent Clones

| Situation | Use |
|-----------|-----|
| Parallel sub-agent delegation on one machine (the default) | **Worktree** — one per unit, removed on merge |
| Single agent trying an idea / comparing two branches | **Worktree** |
| Multiple long-lived independent agents owning a repo for days | **Clone** (`multi-agent` module) |
| Per-branch dev-server ports (worktrees share `.env`) | **Clone** |
| Hook-driven per-branch `tracking.csv` | **Clone** |
| Cross-machine / cloud dispatch | **Clone** / remote isolation |

Worktrees share `.git` objects and external caches, but **each still builds its own `.build`** — the disk win over clones is ephemerality and the shared `.git`, not a smaller build. That win only materializes if teardown actually happens, which is why `/worktree-sweep` exists.

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/git-worktrees.md` | rule | Default-isolation framing, delegation lifecycle, honest economics, removal-safety rule, pitfalls |
| `commands/worktree-start.md` | command | `/worktree-start {branch-name}` |
| `commands/worktree-finish.md` | command | `/worktree-finish` — four-option gate for one worktree |
| `commands/worktree-sweep.md` | command | `/worktree-sweep` — safe repo-wide orphan janitor |
| `lib/worktree-sweep.sh` | lib | Deterministic sweep implementation (classify → non-force remove → prune → report) |

## Dependencies

None. The module is self-contained.

## Manual Installation

```bash
# Rule
mkdir -p ~/.claude/rules
cp rules/git-worktrees.md ~/.claude/rules/git-worktrees.md

# Commands
mkdir -p ~/.claude/commands
cp commands/worktree-start.md  ~/.claude/commands/worktree-start.md
cp commands/worktree-finish.md ~/.claude/commands/worktree-finish.md
cp commands/worktree-sweep.md  ~/.claude/commands/worktree-sweep.md

# Lib
mkdir -p ~/.claude/lib
cp lib/worktree-sweep.sh ~/.claude/lib/worktree-sweep.sh
chmod +x ~/.claude/lib/worktree-sweep.sh
```
