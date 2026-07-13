---
description: Create a new git worktree for feature work with gitignore verification and project setup
allowed-tools: Bash, Read, Edit, Write
---

# /worktree-start - Start a New Worktree

Creates an isolated git worktree so feature work does not disturb the main checkout. This is the **hands-on** single-worktree creator (you, working a branch directly).

For **parallel sub-agent delegation**, you usually do not run this by hand — the delegating command (`/etp`, `/mawf`, `/xplan`) or the Agent/Workflow `isolation: "worktree"` option creates one worktree per unit automatically, and removes it when the unit merges. Worktrees are the default isolation for that; see `git-worktrees.md`. Reach for a permanent clone only for long-lived independent agents, per-branch dev-server ports, per-branch `tracking.csv`, or cross-machine dispatch.

Whichever path creates the worktree, its lifecycle ends the same way: removed when its PR merges, with `/worktree-sweep` as the orphan backstop.

## Usage

```
/worktree-start <branch-name> [base-branch]
```

- `branch-name` (required): the new branch to create in the worktree
- `base-branch` (optional, default: `origin/main`): branch to fork from

## Workflow

### Phase 1: Pre-Flight Checks

1. **Confirm repo root**: run `git rev-parse --show-toplevel`. If this fails, stop and report: "not inside a git repository."

2. **Fetch latest**: `git fetch origin`. Do this every time - never assume the local `origin/main` ref is current.

3. **Check for existing worktree on this branch**: `git worktree list --porcelain | grep -A2 "branch refs/heads/<branch-name>"`. If one exists, show its path and ask the user whether to reuse it, pick a different name, or remove the existing worktree first.

4. **Check branch uniqueness**: `git branch --list <branch-name>`. If the branch already exists and the user did not pass `[existing-branch]` as the base, ask whether they meant to check out the existing branch in a worktree.

5. **Verify the worktree parent is gitignored**: the canonical location is `.claude/worktrees/`. Check `git check-ignore .claude/worktrees` — if it exits 0, the path is already ignored (the harness usually gitignores `.claude/`) and there is nothing to do. If not, add it:

   ```bash
   echo ".claude/worktrees/" >> .gitignore
   git add .gitignore
   git commit -m "chore: ignore .claude/worktrees directory"
   ```

   Do this BEFORE creating the worktree. Creating a worktree under a non-gitignored path risks committing the entire worktree back into the repo on a careless `git add .`.

### Phase 2: Create the Worktree

Choose the directory:

- Canonical: `<repo-root>/.claude/worktrees/<branch-name>/` — the same tree the harness's `isolation: "worktree"` uses, so `/worktree-sweep` reclaims everything from one place.
- Fallback if `.claude/worktrees/` gitignore cannot be added: `~/code/worktrees/<repo-name>-<branch-name>/` (create this directory first, mkdir -p).

Create the worktree:

```bash
# New branch off base-branch (default: origin/main)
git worktree add -b <branch-name> .claude/worktrees/<branch-name> <base-branch>
```

If the branch already exists and the user confirmed reuse:

```bash
git worktree add .claude/worktrees/<branch-name> <branch-name>
```

### Phase 3: Project Setup (Auto-Detect)

Inside the new worktree, detect project type and run the appropriate install / build command. Check for these files in order and run the matching command:

| File present | Command |
|--------------|---------|
| `pnpm-lock.yaml` | `pnpm install` |
| `yarn.lock` | `yarn install` |
| `package-lock.json` | `npm install` |
| `package.json` (no lockfile) | `npm install` |
| `Cargo.toml` | `cargo build` |
| `requirements.txt` | `pip install -r requirements.txt` |
| `Gemfile` | `bundle install` |
| `go.mod` | `go mod download` |

Run only the FIRST match. If the project uses a lockfile, respect it. If the install fails, stop and report the error - do not proceed to baseline checks.

### Phase 4: Copy Non-Tracked Local Config

Worktrees do not inherit `.env` or other gitignored local config. Offer to copy them from the main checkout. Locate the main checkout root robustly (do not hard-code `../../` — the depth depends on the worktree path):

```bash
ROOT="$(git rev-parse --git-common-dir)/.."   # main checkout root, from anywhere inside the worktree
cp "$ROOT/.env"       .env       2>/dev/null || true
cp "$ROOT/.env.local" .env.local 2>/dev/null || true
```

Only copy files that are gitignored. Never copy a file that could be committed back.

### Phase 5: Baseline Test Run

Run the project's test command once to confirm the baseline is green before feature work starts. Auto-detect:

| File present | Test command |
|--------------|--------------|
| `package.json` with `"test"` script | `pnpm test` / `npm test` (match the install command) |
| `Cargo.toml` | `cargo test` |
| `pytest.ini` / `pyproject.toml` with pytest | `pytest` |
| `Gemfile` with rspec | `bundle exec rspec` |
| `go.mod` | `go test ./...` |

If the baseline test run fails:
- Do NOT start feature work
- Report the failure to the user
- Ask whether to proceed anyway (accepting that later failures will be hard to attribute) or investigate

If the project has no test command, skip this phase and note it in the report.

### Phase 6: Report

Report to the user:

- Worktree path: absolute path
- Branch name
- Base branch (ref and SHA)
- Install / build status
- Baseline test status (pass / fail / skipped)
- `cd` command to enter the worktree

Do not claim success if any phase failed.

## Safety Notes

- Never run `rm -rf` on a worktree directory directly - use `git worktree remove`
- Never `mv` a worktree - use `git worktree move`
- Never create worktrees inside other worktrees - they cannot share a parent
- A locked worktree (`.git/worktrees/<name>/locked` present) requires `git worktree unlock` before removal
