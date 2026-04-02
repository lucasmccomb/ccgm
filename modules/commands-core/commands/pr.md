---
description: Push branch and create a pull request that closes an issue
allowed-tools: Agent
---

# /pr - Push Branch and Create Pull Request

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: push and create PR

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its final report to the user exactly as received.

---

## Workflow Instructions

Push the current branch to the remote and create a PR that closes the associated issue.

Arguments: $ARGUMENTS

### 1. Pre-Flight Checks

Verify the working directory is clean:

```bash
git status --short
```

If there are uncommitted changes, warn the user and suggest running `/commit` first. Do not proceed with uncommitted changes.

### 2. Gather Context

```bash
# Current branch
BRANCH=$(git branch --show-current)

# Extract issue number from branch name
ISSUE_NUM=$(echo "$BRANCH" | grep -oE '^[0-9]+')

# Check we are not on main
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "ERROR: Cannot create PR from main/master branch"
  exit 1
fi

# Get commit history for this branch
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline -5
```

### 3. Run Verification

Run the project's full verification suite before pushing:

```bash
# Detect and run available checks
npm run lint 2>/dev/null
npm run type-check 2>/dev/null
npm run test:run 2>/dev/null || npm test 2>/dev/null
npm run build 2>/dev/null
```

All checks must pass. Fix any failures before proceeding.

### 4. Rebase on Main

Ensure the branch is up to date with the latest main:

```bash
git fetch origin
git rebase origin/main
```

If there are conflicts, resolve them. After resolving:

```bash
git rebase --continue
```

### 5. Push the Branch

```bash
git push -u origin "$BRANCH"
```

If the branch was rebased and already existed on the remote:

```bash
git push --force-with-lease -u origin "$BRANCH"
```

### 6. Check for PR Template

Look for a PR template in this order:

```bash
# 1. Repo root
ls pull_request_template.md PULL_REQUEST_TEMPLATE.md 2>/dev/null

# 2. .github directory
ls .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md 2>/dev/null

# 3. Organization .github repo (if applicable)
# gh api repos/{org}/.github/contents/.github/PULL_REQUEST_TEMPLATE.md 2>/dev/null
```

If a template is found, read it and structure the PR body using the template's sections and headings.

### 7. Create the Pull Request

Build the PR title and body:

- **Title**: `{issue_number}: {brief description}` (matching commit format)
- **Body**: Must include `Closes #{issue_number}` to auto-close on merge

If a PR template was found, fill in its sections. Otherwise use:

```bash
gh pr create \
  --title "{issue_number}: {description}" \
  --body "## Summary

{Summary of changes}

## Changes

{Key changes made}

## Test Plan

{How this was tested}

## Issue

Closes #{issue_number}"
```

### 8. Tracking Update

Note: Tracking status is updated automatically by the PostToolUse hook on `gh pr create` (sets status to "pr-created"). No manual label management needed.

### 9. Report Result

Display:
- PR URL
- PR number
- Issue it closes
- Any CI checks that are running
