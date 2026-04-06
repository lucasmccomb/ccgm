---
description: One-shot commit, create PR, and merge workflow
allowed-tools: Agent
---

# /cpm - Commit, PR, and Merge

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: sonnet
- **description**: cpm git workflow

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its final report to the user exactly as received.

---

## Workflow Instructions

A one-shot workflow that commits current changes, creates a PR, and merges it. Designed for repos where you merge your own PRs (solo developer or self-merge workflow).

Arguments: $ARGUMENTS

### 1. Pre-Flight Checks

```bash
# Verify we have changes
git status --short

# Verify we are on a feature branch, not main
BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "ERROR: Cannot run /cpm from main/master. Create a feature branch first."
  exit 1
fi
```

If no changes exist and no commits ahead of main, report that there is nothing to do.

### 2. Extract Issue Number

```bash
BRANCH=$(git branch --show-current)
ISSUE_NUM=$(echo "$BRANCH" | grep -oE '^[0-9]+')
```

If arguments contain an issue number, prefer that. If neither source has one, proceed without it.

### 3. Run Verification

Run the project's full verification suite:

```bash
# Detect and run available checks
npm run lint 2>/dev/null
npm run type-check 2>/dev/null
npm run test:run 2>/dev/null || npm test 2>/dev/null
npm run build 2>/dev/null
```

All checks must pass. Fix failures before proceeding. Do not skip verification.

### 4. Commit (if uncommitted changes exist)

```bash
git add -A
git diff --cached --stat
```

If there are staged changes:

```bash
git commit -m "{issue_number}: {brief description}"
```

Rules:
- Imperative mood
- Under 72 characters
- No AI attribution
- If arguments include a message, use it (prepend issue number)

### 5. Rebase on Main

```bash
git fetch origin
git rebase origin/main
```

Resolve conflicts if any arise.

### 6. Push

```bash
git push -u origin "$BRANCH"
```

Or if rebased and remote branch exists:

```bash
git push --force-with-lease -u origin "$BRANCH"
```

### 7. Create PR

Check for a PR template first:

```bash
ls pull_request_template.md PULL_REQUEST_TEMPLATE.md .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md 2>/dev/null
```

Create the PR:

```bash
gh pr create \
  --title "{issue_number}: {description}" \
  --body "## Summary

{Summary of what this PR does}

## Changes

{Key changes}

## Test Plan

{How it was verified}

## Issue

Closes #{issue_number}"
```

### 8. Merge the PR

Wait briefly for any fast CI checks, then merge:

```bash
gh pr merge --squash --delete-branch
```

If merge fails (CI required, review required), report the blocker and stop. The user may need to adjust repo settings or wait for CI.

### 9. Close the Issue

If the PR body included `Closes #N`, GitHub auto-closes the issue on merge. Verify:

```bash
gh issue view "$ISSUE_NUM" --json state --jq '.state' 2>/dev/null
```

If still open, close manually:

```bash
gh issue close "$ISSUE_NUM" --comment "Completed via PR merge"
```

Note: Tracking status is updated automatically by the PostToolUse hook. The hook sets status to "closed" on `gh issue close` and "merged" on `gh pr merge`. No manual label management needed.

### 10. Return to Main

```bash
git checkout main
git pull origin main --ff-only
```

### 11. Report Result

Display:
- Commit hash and message
- PR number and URL
- Merge status
- Issue close status
- Current state (on main, clean working directory)
