# Git Workflow

## No AI Attribution in Commits

Never add `Co-Authored-By` trailers naming Claude, AI, or Anthropic, "Generated with Claude Code" lines, or any other AI attribution to commit messages, PR descriptions, or git metadata. The human is the author; AI is a tool that should not appear in contributor statistics. The CCGM settings module turns Claude Code's own attribution off (`attribution.commit` and `attribution.pr` empty, `sessionUrl` false), so the harness will not ask for it either.

## Follow a Repo's PR Template If It Has One

When opening a PR, check locally for `pull_request_template.md` or `PULL_REQUEST_TEMPLATE.md` in the root or under `.github/` and structure the body on its sections. If there is none, do not query the org's `.github` repo and do not create one; write a value-first body: what the PR does for the user, the concrete changes, how it was verified, with `Closes #N` first when it closes an issue. Plain words, active voice, no achievement language; `writing-system.md` has the standard.

## Sync Before Any History Change

Before `git filter-branch`, `git rebase`, `git reset --hard`, or any other history-altering command:

```bash
git fetch origin
git reset --hard origin/main
git rev-list --count HEAD
git log --oneline | head -5
```

Rewriting history on an outdated local branch and force-pushing overwrites commits on the remote.

## Branch Updates: Rebase by Default

Bring a feature branch up to date with `git rebase origin/main`, then `git push --force-with-lease`. Fall back to merge only when rebase causes complex conflicts across many commits, the branch is shared with others, or branch protection blocks force pushes. With squash merges the result on main is one commit either way.

## Never Stash

Commit instead, as a WIP commit if needed, then cherry-pick or rebase to move changes between branches. Stashed changes are invisible, easy to forget, and confusing to pop across branch states.

## Post-Merge: Return to Main

After a PR merges, unless work continues on the same branch:

```bash
git checkout main
git pull origin main --ff-only
```

## Pathspecs Resolve From cwd

`git add packages/foo/...` fails with exit 128 ("pathspec did not match any files") when run from inside another sub-package. Git resolves pathspecs relative to the current directory, so `cd` to the repo root or use `git -C <repo-root> add <paths>`; the same applies to `rm`, `restore`, and `checkout -- <paths>`.

## Work Starts on a Branch

Before the first edit in any repo:

```bash
git fetch origin && git checkout -b <type>/<short-desc> origin/main
```

with `<type>` one of `feature | fix | chore | docs`. Uncommitted work on main is destroyed the next time main is synced. With the branch-guard module installed, a PreToolUse hook enforces this (see `branch-guard.md`).

## Worktrees

For parallel sub-agent delegation on one machine, the default isolation is a git worktree (`isolation: "worktree"`), always created on a feature branch off `origin/main`, so every rule above applies unchanged. Remove each worktree the moment its PR merges (`git worktree remove <path>` then `git worktree prune`, or `bash ~/.claude/lib/worktree-sweep.sh --worktree <path>`) and run `/worktree-sweep` after any delegation run; a worktree an agent built in does not auto-remove. Reserve permanent clones for per-branch dev-server ports, hook-driven per-branch `tracking.csv`, long-lived independent agents, or cross-machine dispatch. The `git-worktrees` skill has the full lifecycle.
