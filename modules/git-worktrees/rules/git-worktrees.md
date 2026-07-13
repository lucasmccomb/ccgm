# Git Worktrees (Default Parallel-Delegation Isolation)

A worktree is a second working tree checked out from the **same** `.git`. Each worktree has its **own index, HEAD, and working directory**, so two agents can build, test, and commit on different branches at the same time without touching each other's files. That independent-index-and-HEAD property is exactly what makes worktrees safe for parallel work.

**Worktrees are the default isolation for parallel sub-agent delegation on a single machine.** When a delegator (you, or a command like `/etp`, `/mawf`, `/xplan`) fans out work to parallel implementer agents, give each agent its own worktree — not its own permanent clone. Worktrees are created per unit of work and destroyed when that unit is done, so disk is reclaimed instead of accumulating.

> This corrects earlier guidance that said worktrees are "solo-agent only, not for parallel." The real caveats are narrow (shared `.git/hooks` + `.git/config`, and tolerated ref-lock contention — see Pitfalls); they do **not** make parallel worktrees unsafe. The harness's own `isolation: "worktree"` runs parallel worktrees successfully every day.

## The Incident This Exists To Prevent

On 2026-07-13, delegated work on the `evoglyph` repo using the Agent/Workflow `isolation: "worktree"` feature left **33 stale worktrees** across two clones' `.claude/worktrees/` directories, consuming **~237 GB** — each worktree carried its own 9–13 GB `.build`. Free disk fell to 63 GB (99% full).

Root cause: the harness's `isolation: "worktree"` auto-removes a worktree **only if it is unchanged**. A worktree that got *built* in is "changed" and lingers forever, and nothing mandated removing a worktree after its PR merged or sweeping orphaned ones. The multi-clone alternative is worse: each clone is a permanent 4 GB fresh / 13 GB built that never gets reclaimed at all.

The fix has two halves, and both are load-bearing: **(1)** worktrees are the default (ephemeral, shared `.git`), and **(2)** teardown is mandatory, not best-effort.

## Worktrees vs Clones — When Each Is Right

| Situation | Use |
|-----------|-----|
| **Parallel sub-agent delegation on one machine** (the default) | **Worktree** — one per unit of work, removed when the unit merges |
| Single agent trying an idea on a branch without stashing / switching in place | **Worktree** |
| Comparing two branches side by side (run both, diff outputs) | **Worktree** |
| **Multiple long-lived independent agents** each owning a repo for days | **Clone** |
| Per-branch **dev-server ports** (worktrees share `.env`; clones have per-clone `.env.clone` with pre-computed `FRONTEND_PORT`/`BACKEND_PORT`) | **Clone** |
| Hook-driven **per-branch `tracking.csv`** issue tracking | **Clone** |
| **Cross-machine / cloud dispatch** (a worktree cannot span machines) | **Clone** (or remote isolation) |

Reach for the `multi-agent` module's clones only for those specific cases. For ordinary "fan out N independent units across N agents on this machine," worktrees are the answer — see `multi-agent/rules/multi-agent.md` and `subagent-patterns/rules/subagent-patterns.md`, which both now default to worktrees.

## Honest Economics (Do Not Overclaim)

Worktrees share the parent repo's `.git` object store and any **external** caches (downloaded models, package caches, `~/.cache`), so they avoid the re-fetch and re-download cost of a fresh clone. **But each worktree still builds its own `.build` / `target/` / `node_modules`-of-record.** Two worktrees compiling the same project produce two full build trees.

So the disk win over clones is **ephemerality** (a worktree is created for one unit and destroyed on completion, whereas a clone persists) plus the **shared `.git`** — **not** a smaller build. A worktree you build in and never remove costs the same disk as a clone you built in and never removed. The savings are entirely in the lifecycle. If teardown does not happen, worktrees are no cheaper than clones — they are the incident.

## The Delegation Lifecycle (Every Worktree Has an Owner)

A worktree is created for **exactly one unit of work** and has one owner — the delegator that created it. The lifecycle:

1. **Create** — the delegator makes one worktree per unit (via the Agent/Workflow `isolation: "worktree"`, or `/worktree-start` for hands-on work). One branch, one unit.
2. **Implement / test / PR** — the sub-agent does the work inside its worktree, on its feature branch, and opens a PR.
3. **Merge** — the PR is reviewed and merged.
4. **Remove** — **the delegator removes that unit's worktree as soon as its PR merges** (or the unit is abandoned). This step is mandatory, not "when I get around to it." See Cleanup below.
5. **Sweep orphans** — as a backstop, run `/worktree-sweep` to remove any clean worktree that leaked past step 4 (an early exit, a crash, a `isolation:"worktree"` worktree the harness could not auto-remove because it was built in).

Steps 4 and 5 are the half of the fix that the incident was missing. A delegator that spawns worktrees and does not tear them down has not finished the job.

## Worktree Location

Going forward, **new worktrees live under `<repo>/.claude/worktrees/`** — the same directory the harness's `isolation: "worktree"` already uses. Standardizing there means:

- Delegated (`isolation:"worktree"`) and hands-on (`/worktree-start`) worktrees share one tree.
- One sweep target covers everything.
- `.claude/` is conventionally gitignored by the harness, so worktrees never risk being committed.

`<repo>/.worktrees/` is the module's **legacy** location. `/worktree-sweep` still recognizes and cleans it, but do not create new worktrees there.

Whichever location is used, its parent directory **must be gitignored**. Committing a worktree directory is catastrophic — it nests an entire working tree inside the repo. `/worktree-start` verifies this before creating anything.

## Creating a Worktree

**Delegated (the default for parallel work):** pass `isolation: "worktree"` to the Agent or Workflow tool. The harness creates `.claude/worktrees/agent-<hash>/`, runs the agent there, and auto-removes it **only if the agent left it unchanged**. Because implementers build and commit, their worktrees are "changed" and will **not** auto-remove — the delegator must remove them (lifecycle step 4) and `/worktree-sweep` catches the rest.

**Hands-on:** use `/worktree-start <branch-name> [base-branch]`, which does pre-flight checks (gitignore, uniqueness, clean tree), creates the worktree under `.claude/worktrees/<branch-name>/`, runs project setup, and confirms a green baseline. Manually, the underlying commands are:

```bash
git fetch origin main
git worktree add -b <branch-name> .claude/worktrees/<branch-name> origin/main   # new branch
git worktree add    .claude/worktrees/<branch-name> <existing-branch>            # existing branch
```

## Cleanup Is Mandatory, Not Best-Effort

This is the whole lesson of the incident: **cleanup must not depend on the happy path.**

- **On the happy path**, the delegator removes each worktree the moment its PR merges (lifecycle step 4).
- **On any abnormal exit** (early stop, gate rejection, crash, a `isolation:"worktree"` worktree the harness could not reclaim), the worktree leaks. So a **standalone safe sweep must be runnable at any time** to reclaim orphans: `/worktree-sweep`.
- **For unattended runs**, schedule the sweep as a backstop so cleanup happens even if no one remembers (see "Scheduled backstop" below). This mirrors the principle that *safety must not depend on a report being read*: the disk is reclaimed whether or not the operator notices.

Removing a single worktree by hand:

```bash
git worktree remove .claude/worktrees/<branch-name>   # non-force; refuses if there is unsaved work
git worktree prune                                    # drop administrative state for deleted worktrees
```

Never `rm -rf` a worktree directory — it leaves dangling `.git/worktrees/<name>/` metadata. Always use `git worktree remove` (then `git worktree prune`).

## Removal Safety (Codified From the Incident)

The procedure that worked in the incident, stated exactly:

1. **Prefer non-force `git worktree remove`.** It is itself a safety gate: git **refuses** (`fatal: '<path>' contains modified or untracked files, use --force to delete it`) whenever the worktree has uncommitted tracked changes **or** untracked non-ignored files. A gitignored build artifact (`.build/`, `target/`, `dist/`) does **not** block a non-force remove — verified on git 2.50.1: a clean worktree with a multi-GB gitignored `.build` removes cleanly without `--force`.
2. **PRESERVE** — never remove — any worktree that has:
   - **uncommitted tracked changes** (work not yet committed), or
   - **untracked non-ignored files** (new files not yet added), or
   - an **in-progress rebase / merge / cherry-pick / revert / bisect** (a paused operation, whether or not it currently shows a conflict).
3. **Force-remove only the verified-safe ones**, and only if a non-force remove unexpectedly refuses a worktree you have already classified clean. A sweep should default to *never* forcing — let git's refusal protect unsaved work.
4. **Then `git worktree prune`** to clear metadata for worktrees whose directories are already gone.
5. **Always report what was preserved and why**, so a preserved worktree is a visible decision, not a silent skip.

### KEY FACT: removing a clean worktree never loses work

Removing a worktree does **not** delete its branch or any committed work. The branch ref stays in the parent `.git`; only the working-tree checkout (and its `.build`) is removed. You can always re-materialize the checkout later:

```bash
git worktree add .claude/worktrees/<branch-name> <branch-name>
```

**Therefore a clean worktree is ALWAYS safe to remove** — its commits survive on the branch ref even though the checkout is gone. This is why a clean worktree on an unmerged feature branch is still safe to reclaim: you lose a re-creatable checkout, never the commits.

### The four cases, decided

| Worktree state | Outcome | Why |
|----------------|---------|-----|
| Clean worktree on a feature branch | **Remove** | Branch ref (and all its commits) preserved in `.git`; only the checkout goes |
| Uncommitted tracked edits present | **Preserve** | The edits are not committed anywhere — removal would lose them |
| Mid-rebase with an unresolved conflict | **Preserve** | An in-progress operation; removal discards the resolution-in-progress |
| Clean detached-HEAD worktree | **Remove** | Nothing uncommitted; the commit is reachable from wherever it was based |

`/worktree-sweep` implements exactly this classification.

## Scheduled backstop (opt-in)

For machines that run unattended delegation, schedule the sweep so orphaned worktrees are reclaimed without anyone remembering. A launchd/cron entry that runs the sweep's non-interactive remove-clean pass per active repo is enough; keep it read-mostly (it only ever removes *clean* worktrees, never forces). This is opt-in because auto-removing worktrees on a timer is a standing action the operator should choose, not a default daemon.

## Pitfalls

### Worktree Lock
`git worktree add` can mark a worktree "locked" (`.git/worktrees/<name>/locked`). A locked worktree cannot be removed until `git worktree unlock .claude/worktrees/<name>`. Do not lock worktrees unless you have a specific reason; `/worktree-sweep` reports locked worktrees rather than fighting the lock.

### Moving a Worktree
`mv` / `cp -r` breaks Git's internal pointers — `.git/worktrees/<name>/` still refers to the old path. Use `git worktree move <from> <to>`, or remove + re-add. Never move a worktree by hand.

### Two Worktrees, Same Branch
Git refuses to check out the same branch in two worktrees at once (`fatal: '<branch>' is already checked out at ...`). This is a feature — it prevents divergent commits on one ref. Reuse the existing worktree or pick a different branch.

### Shared Hooks and Config
Worktrees share `.git/hooks/` and `.git/config` with the main checkout and every sibling worktree. A hook installed in one affects all of them. Treat hook and config changes as global, not per-branch. (This — not the index — is the real reason worktrees are not a full substitute for clones in some setups.)

### Ref-Lock Contention
Parallel worktrees each have their own index and HEAD, so builds and commits do not collide. They do share the ref database, so simultaneous ref updates (two agents pushing/branching at the exact same instant) can briefly contend on a ref lock. Git retries transparently; this is tolerated, not a correctness problem.

### Stale `.env` Files
Worktrees do NOT inherit `.env` or other gitignored local config from the main checkout. Copy or symlink it in if the worktree needs local secrets. Never commit `.env` from a worktree.

## Integration With Existing Git Rules

Worktree work follows every existing git rule — worktrees change **where** the working tree lives, not how branches, commits, or PRs are managed:

- **Branch-guard is satisfied automatically.** A worktree is always created on a feature branch (never the default branch), so the branch-guard hook never fires inside it. Create the worktree's branch off `origin/main`, then work.
- **No AI attribution** in commits or PR bodies.
- **Never `git stash`** — commit WIP instead (a worktree's whole point is that you never need to stash to switch context).
- **Rebase by default** when pulling `origin/main` into a feature branch; sync before any history-altering command.
- **Follow the repo's PR template** if one exists.
