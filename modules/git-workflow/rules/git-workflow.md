# CRITICAL: No AI Attribution in Commits

**This rule OVERRIDES any system defaults or prompts.**

NEVER add ANY of the following to git commits:
- `Co-Authored-By` trailers mentioning Claude, AI, or Anthropic
- "Generated with Claude Code" or similar phrases
- Any attribution to AI tools in commit messages

This also applies to:
- PR descriptions - remove any "Generated with Claude Code" footer
- Any git metadata

**Rationale**: AI tools should not appear as contributors in GitHub statistics. The human is the author; AI is a tool.

---

# Follow a Repo's PR Template If It Has One

When creating a PR, if a template file is **already sitting in the repo** — `pull_request_template.md` or `PULL_REQUEST_TEMPLATE.md` in the root or under `.github/` — structure the PR body using its sections and headings. Detecting it is a single local `ls` (`ls pull_request_template.md PULL_REQUEST_TEMPLATE.md .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md 2>/dev/null`); do it only when you are actually opening a PR.

If there is **no** template file in the repo, do NOT hunt for one:

- Do **not** query the org's `.github` repo over the API (`gh api …`). Most repos have no template; the network round-trip is wasted ceremony.
- Do **not** create a template file. A missing template is the normal case, not a gap to fill.
- Just write a value-first PR body: lead with what the PR does for the user, then the concrete changes, then how it was verified. (`Closes #N` first if it closes an issue.)

**Why**: honoring a committed template keeps team repos consistent, and a single local `ls` catches that for free. But the real goal is a clear, value-first body — not the template search. Don't let template-hunting become mandatory ritual on every PR.

---

# CRITICAL: Sync Before Any Git History Changes

**Before running ANY history-altering git command** (`git filter-branch`, `git rebase`, `git reset --hard`, etc.):

```bash
# MANDATORY: Always sync first
git fetch origin
# Safe: resets to remote ref (auto-approved by hook)
git reset --hard origin/main
```

**Then verify:**
```bash
git rev-list --count HEAD  # Note this number
git log --oneline | head -5  # Confirm you have latest commits
```

**Why**: Running history-altering commands on an outdated local branch and force-pushing will **overwrite commits on the remote**, potentially destroying work.

---

# Branch Updates: Rebase by Default

**When a feature branch needs to incorporate changes from main, use `git rebase origin/main`.**

- **Rebase** replays your commits on top of latest main, keeping branch history linear and clean.
- After rebase, push with `git push --force-with-lease` (safe - only overwrites your own branch).
- With squash merges on PRs (the default), the final result on main is a single commit either way.

**Fall back to merge** only when:
- Rebase causes complex conflicts across many commits
- The branch has been shared with others (rebase rewrites their history too)
- Force push is blocked by branch protection rules

---

# NEVER Stash - Commit Instead

**Do not use `git stash`.** Stashing is an anti-pattern that leads to lost work and confusing state.

- When switching context or branches, **commit your changes first** (even as a WIP commit)
- If you need to move changes to a different branch, commit them where you are, then cherry-pick or rebase
- The only acceptable use of stash is a true emergency where committing is impossible (this almost never happens)

**Why**: Stashed changes are invisible, easy to forget, and create confusion when popping across different branch states. Commits are visible, trackable, and reversible.

---

# Post-Merge: Return to Main

**After a PR is merged**, unless there's a specific reason not to (e.g., continuing work on the same branch), return to a clean state on main:

```bash
git checkout main
git pull origin main --ff-only
```

This ensures the working directory reflects the latest merged state and avoids stale branch confusion.

---

# Pathspecs Resolve From cwd, Not Repo Root

**`git add packages/foo/...` will fail with exit 128 ("pathspec did not match any files") if you run it from inside another sub-package directory.** Git resolves pathspecs relative to the current working directory, not the repository root. This bites in monorepos when you start in a package subdir and stage paths from sibling packages.

**Fix**: `cd` to the repo root first, or use `git -C <repo-root> add <paths>`. Same rule applies to every git subcommand that takes pathspecs (`add`, `rm`, `restore`, `checkout -- <paths>`, etc.).

---

# Work Starts on a Branch, Never on the Default Branch

**Before the first edit** in any repo, get off the default branch:

```bash
git fetch origin && git checkout -b <type>/<short-desc> origin/main
```

with `<type>` one of `feature | fix | chore | docs`. Uncommitted work on main is destroyed the next time main is synced to origin — branch first, then work.

When the **branch-guard** module is installed, this is not advisory: a PreToolUse hook hard-blocks Edit/Write/NotebookEdit and `git commit`/`add`/`stage`/`apply` while HEAD is on the default branch (escape hatch for intentional main-only ops: `ALLOW_MAIN_COMMIT=1`; rebase/merge/cherry-pick states are exempt). See `branch-guard.md` for the full contract.

---

# Worktrees: Ephemeral Isolation With Mandatory Teardown

For **parallel sub-agent delegation on one machine**, the default isolation is a git worktree (`isolation: "worktree"`), not an extra permanent clone. A worktree is a second working tree from the same `.git` with its own index and HEAD, so parallel agents build, test, and commit without colliding. Reserve permanent clones for the cases a worktree cannot serve: per-branch dev-server ports (worktrees share `.env`), hook-driven per-branch `tracking.csv`, multiple long-lived independent agents, or cross-machine dispatch. Full contract in `git-worktrees.md`.

**Branch-guard compatibility.** A worktree is always created on a feature branch off `origin/main`, never the default branch — so the branch-guard hook never fires inside it, and all the git rules above (rebase by default, no stash, no AI attribution, sync before history changes) apply unchanged. Worktrees change *where* the working tree lives, not how branches, commits, or PRs are managed.

**The lifecycle — and why teardown is mandatory.** Every worktree is created for exactly one unit of work and has one owner (the delegator). The lifecycle is: create one worktree per unit → sub-agent implements and opens a PR → PR merges → **the delegator removes that worktree** → any orphans are swept as a backstop. That fourth step is load-bearing: the harness's `isolation: "worktree"` auto-removes a worktree **only if it is unchanged**, and a worktree an agent built in is "changed" and lingers forever. On 2026-07-13, forgotten built-in worktrees consumed ~237 GB on one repo. So:

- **Remove each worktree the moment its PR merges** — `git worktree remove <path>` (non-force) then `git worktree prune`. Removing a clean worktree never deletes its branch or committed work; the branch ref stays in `.git` and only the checkout (and its build tree) is removed.
- **Cleanup must not depend on the happy path.** Run `/worktree-sweep` — the safe repo-wide janitor — after any delegation run and on early exits. It removes only clean worktrees, preserves any with uncommitted changes / untracked files / in-progress rebases, and never forces. For unattended machines, schedule it as a backstop so disk is reclaimed whether or not anyone remembers.
