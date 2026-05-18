# /cpm — Commit, PR, Merge

One-shot workflow: commit all changes, create a PR, merge it, close the issue, and rebase on main.

## Usage

```
/cpm
```

No arguments needed. Derives the issue number from the current branch name (expects `{issue-number}-{description}` format).

## Instructions

Execute the following steps sequentially. Do NOT skip steps or proceed if a step fails.

### Phase 1: Pre-flight

1. Run `git status` to confirm there are changes to commit.
2. Run `git diff --stat` to see what changed.
3. Extract the issue number from the current branch name (the leading digits before the first `-`).
4. Run `git log --oneline -5` to check recent commit style.

If there are no changes and no unpushed commits, stop and report "Nothing to commit or push."

### Phase 2: Commit

1. Stage all changed files with `git add` (prefer specific files over `git add -A`; never stage `.env` or credential files).
2. Create a commit with message format: `{issue-number}: {concise description of changes}`
3. Do NOT add any Co-Authored-By trailers or AI attribution.

### Phase 3: Push & Create PR

1. Push the branch: `git push -u origin HEAD`
2. Check for a PR template at `.github/PULL_REQUEST_TEMPLATE.md` or `pull_request_template.md` in the repo root.
3. Create the PR using `gh pr create`:
   - Title: `{issue-number}: {concise description}`
   - Body: Use the PR template if found, otherwise use Summary + Test Plan format
   - Include `Closes #{issue-number}` in the body
4. Capture the PR URL.

### Phase 4: Merge

1. Merge with admin bypass so you do not wait on GitHub Actions:
   `gh pr merge --squash --delete-branch --admin`
2. Confirm the merge succeeded.

Local pre-push verification is the source of truth. Remote Actions stall, run out of budget, and queue — those are not reasons to block a merge. `--admin` bypasses the BLOCKED state caused by "checks pending" or "no required reviewer present" when you are the repo admin. It does NOT force-merge through an actually-FAILED check; a FAILURE check (not PENDING) means local verification missed something — stop and investigate, do not retry with `--admin`.

### Phase 5: Close Issue

1. The issue should auto-close from "Closes #N" in the PR body.
2. Verify with `gh issue view {issue-number} --json state`.
3. If still open, close it manually: `gh issue close {issue-number}`

### Phase 6: Return to Main

1. `git checkout main`
2. `git pull origin main --ff-only`
3. If `--ff-only` fails (local main diverged), fall back to `git fetch origin && git reset --hard origin/main`
4. Confirm clean state with `git status`.

### Phase 7: Report

Output a summary in this format:

```
## Completed

- **Issue**: #{issue-number} — {issue title}
- **PR**: {PR URL} (merged)
- **Commit**: {short SHA} — {commit message}
- **Branch**: Deleted `{branch-name}`, now on `main`
- **Status**: Clean, up to date with origin/main
```

## Error Handling

- If `gh pr merge --admin` fails for a real reason — merge conflict, missing PR, you are not the admin in this repo, a check in FAILURE state — report and stop. Do not retry the same command; investigate the cause.
- A FAILURE check (not PENDING) is the one signal that should block a merge. Pre-push verification should have caught it. If a remote check disagrees with local, investigate before merging.
- If `git pull --ff-only` fails, fall back to `git fetch origin && git reset --hard origin/main`.
- If any step fails, stop and report what succeeded and what failed.
