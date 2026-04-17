---
description: Finish a git worktree feature branch with a four-option gate (merge locally / push+PR / keep / discard)
allowed-tools: Bash, Read
---

# /worktree-finish - Finish a Worktree

Ends feature work in a worktree with an explicit four-option gate. Never silently merges, pushes, or discards - the user picks the outcome, and destructive options require typed confirmation.

## Usage

```
/worktree-finish [worktree-path]
```

- `worktree-path` (optional): path to the worktree. Defaults to the current directory if it is a worktree, otherwise asks.

## Workflow

### Phase 1: Detect Context

1. If `worktree-path` was passed, use it. Otherwise, run `git rev-parse --show-toplevel` to find the repo root and check `git worktree list` - if the current directory is a worktree, use it.

2. Verify this IS a worktree, not the main checkout:

   ```bash
   git rev-parse --git-common-dir   # .git of the main repo
   git rev-parse --git-dir          # .git-worktrees/<name> of this worktree
   ```

   If they are the same path, this is the main checkout - stop and report: "this is the main checkout, not a worktree; /worktree-finish is only for worktrees."

3. Gather state:
   - Current branch: `git rev-parse --abbrev-ref HEAD`
   - Upstream: `git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null`
   - Uncommitted changes: `git status --porcelain`
   - Unpushed commits: `git log @{u}..HEAD --oneline 2>/dev/null`
   - Merge base with `origin/main`: `git merge-base HEAD origin/main`
   - Commits ahead of main: `git log origin/main..HEAD --oneline`

### Phase 2: Preflight Warnings

Before showing options, surface any state the user should know about:

- Uncommitted changes: list them. Warn that options 1, 2, and 4 below require a clean tree or an intentional WIP commit.
- Unpushed commits: list count and titles.
- Branch not based on latest main: if `git merge-base HEAD origin/main` is not the tip of `origin/main`, suggest a rebase before merging or opening a PR.

### Phase 3: Present Four Options

Print this prompt to the user VERBATIM and wait for a numeric reply:

```
Finishing worktree: <path>
Branch: <branch>
Commits ahead of main: <N>
Uncommitted changes: <yes/no>

Choose an action:
  1) Merge locally into main (squash, then remove worktree)
  2) Push branch and open a PR (worktree stays until PR is merged)
  3) Keep the worktree as is (no action, just exit)
  4) Discard the worktree and branch (DESTRUCTIVE, requires typed confirmation)

Enter 1, 2, 3, or 4:
```

Do NOT pick an option on the user's behalf. If the reply is not `1`, `2`, `3`, or `4`, re-prompt.

### Phase 4: Execute the Chosen Option

#### Option 1: Merge Locally

1. Require a clean tree. If `git status --porcelain` is non-empty, stop and ask the user to commit or discard the changes first.
2. `cd` to the main checkout: `cd $(git rev-parse --git-common-dir)/..`
3. `git checkout main && git pull --ff-only origin main`
4. `git merge --squash <branch>`
5. Show the staged diff. Ask the user to confirm the squash commit message.
6. `git commit -m "<message>"`
7. Push: ask first. If confirmed, `git push origin main`.
8. Remove the worktree: `git worktree remove <path>`
9. Delete the branch: `git branch -D <branch>` (safe after squash merge).

#### Option 2: Push and Open PR

1. Require a clean tree (same check as option 1).
2. Check that `origin/main` is current: `git fetch origin`. If behind, offer to rebase first.
3. Push: `git push -u origin <branch>`
4. Create PR: `gh pr create` with title and body. Use the repo's PR template if one exists (check `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and repo root). Do not add AI attribution footers.
5. Report the PR URL.
6. Leave the worktree in place - the user will run `/worktree-finish` again after the PR is merged to clean up (or manually `git worktree remove`).

#### Option 3: Keep

No-op. Report:

```
Keeping worktree: <path>
Branch: <branch>
(Run /worktree-finish again when you are ready to merge, push, or discard.)
```

#### Option 4: Discard (Typed Confirmation Required)

1. Show what will be lost:
   - Branch and SHA
   - List of commits that exist only on this branch (`git log origin/main..HEAD --oneline`)
   - List of uncommitted changes (`git status --porcelain`)
2. Ask the user to type the EXACT branch name to confirm. Example:

   ```
   To confirm discard, type the branch name: <branch>
   ```

3. If the typed reply does not match the branch name exactly, abort and report: "Discard cancelled - typed name did not match."
4. If it matches:
   - `git worktree remove --force <path>`
   - `git branch -D <branch>`
   - If the branch was pushed, ask separately whether to delete the remote: `git push origin --delete <branch>`. This is a second typed confirmation.
5. Report: worktree and branch discarded.

### Phase 5: Final Report

Always report:

- Option chosen
- Actions taken (commits, pushes, removals)
- Any warnings the user should follow up on (e.g., unpushed commits when keeping, stale remote branches)

## Safety Notes

- Option 4 is the only destructive action and requires typed confirmation. Do not shortcut it.
- Never force-push to `main` from any option.
- Never `rm -rf` a worktree - always use `git worktree remove` (with `--force` only for option 4).
- If any phase fails, stop and report. Do not fall through to a different option silently.
