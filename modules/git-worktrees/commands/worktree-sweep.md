---
description: Repo-wide safe worktree janitor - remove clean worktrees, preserve anything with unsaved work, prune stale metadata
allowed-tools: Bash, Read
---

# /worktree-sweep - Sweep Orphaned Worktrees

The backstop that keeps worktree isolation from silently filling the disk. It enumerates every worktree of the current repo, removes the **clean** ones with a non-force `git worktree remove`, preserves anything with unsaved work, prunes already-gone entries, and reports what it did. It is the orphan-sweep step of the worktree lifecycle (`git-worktrees.md`) — run it after a delegation run, or any time `git worktree list` looks crowded.

It exists because the harness's `isolation: "worktree"` auto-removes a worktree **only if it is unchanged** — a worktree an agent built in is "changed" and lingers forever. On 2026-07-13 that left 33 stale worktrees consuming ~237 GB on one repo. This command reclaims them safely.

## Usage

```
/worktree-sweep [--dry-run] [--conservative] [--all]
```

- **(no flags)** — report + remove every clean worktree in the managed locations. Safe by construction: a clean worktree's commits survive on its branch ref after removal (only the checkout and its build artifacts go), so nothing committed is ever lost.
- **`--dry-run`** — classify and show what *would* happen; remove nothing. Run this first if you want a preview.
- **`--conservative`** — additionally preserve clean worktrees whose branch has commits not yet on the origin default branch (keep in-progress-but-committed checkouts around). Removes only fully-merged, detached, or behind worktrees.
- **`--all`** — also sweep clean worktrees outside the two managed locations (`.claude/worktrees/`, `.worktrees/`). Off by default so a deliberately-placed worktree elsewhere is never touched.

## What It Does

Run the installed janitor and present its report to the user:

```bash
bash ~/.claude/lib/worktree-sweep.sh $ARGUMENTS
```

(When running from a CCGM checkout instead of an install, the script is at `modules/git-worktrees/lib/worktree-sweep.sh`.)

The script classifies each worktree (never the main checkout, never the one you are standing in):

| Classification | Action |
|----------------|--------|
| Uncommitted tracked changes, or untracked non-ignored files | **PRESERVE** |
| In-progress rebase / merge / cherry-pick / revert / bisect | **PRESERVE** |
| Locked | **PRESERVE** (report; run `git worktree unlock` if intended) |
| Clean, in a managed location | **REMOVE** (non-force) |
| Clean, outside managed locations | **SKIP** (unless `--all`) |
| Directory already gone (prunable) | **PRUNE** metadata |

It **never uses `--force`.** A non-force `git worktree remove` is itself a safety gate — git refuses on any modified-or-untracked worktree — so even if the classification missed something, git will not let the sweep destroy unsaved work. A gitignored build artifact (`.build/`, `target/`) does not block a clean removal.

## After the Sweep

Report the summary the script prints: how many worktrees were removed (and disk reclaimed), how many were preserved and why, and how many prunable entries were cleaned. For any removed worktree whose branch had commits not on the default branch, the report includes the exact `git worktree add ...` command to restore the checkout — the branch and its commits were never deleted.

## Related

- `git-worktrees.md` — the worktree lifecycle, removal-safety rule, and honest economics.
- `/worktree-finish` — finish **one** worktree interactively (merge / PR / keep / discard). Use `/worktree-sweep` for the many-at-once orphan cleanup.
