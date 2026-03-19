---
description: Stage all changes and commit with conventional format
allowed-tools: Bash, Read, Glob, Grep
---

# /commit - Stage and Commit Changes

Stage all current changes and create a commit with conventional format.

## Input

```
$ARGUMENTS
```

## Instructions

### 1. Verify There Are Changes to Commit

```bash
git status --short
```

If no changes exist, report that there is nothing to commit and stop.

### 2. Understand the Context

Gather context to write a good commit message:

```bash
# Current branch name (often contains issue number)
git branch --show-current

# What has changed
git diff --stat
git diff --cached --stat

# Recent commits for style reference
git log --oneline -5
```

### 3. Extract Issue Number

Derive the issue number from the branch name. Convention: branches are named `{issue-number}-{description}`.

```bash
BRANCH=$(git branch --show-current)
ISSUE_NUM=$(echo "$BRANCH" | grep -oE '^[0-9]+')
```

If no issue number is found in the branch name and `$ARGUMENTS` contains an issue number, use that instead. If neither source has an issue number, proceed without one.

### 4. Run Verification

Before committing, run the project's verification suite to ensure nothing is broken:

```bash
# Check for common verification commands (adapt to project)
# Look for package.json scripts
cat package.json 2>/dev/null | grep -E '"(lint|type-check|test:run|test|build)"'
```

Run available checks:
- Linting (if available)
- Type checking (if TypeScript project)
- Tests (if available)
- Build (if available)

If any check fails, fix the issue before proceeding. Do not commit broken code.

### 5. Stage All Changes

```bash
git add -A
```

Review what is staged:

```bash
git diff --cached --stat
```

### 6. Create the Commit

Format: `{issue_number}: {brief description}`

If an issue number was found:
```bash
git commit -m "{issue_number}: {brief description of changes}"
```

If no issue number:
```bash
git commit -m "{brief description of changes}"
```

Rules for the commit message:
- Keep the first line under 72 characters
- Use imperative mood ("Add feature" not "Added feature")
- Be specific about what changed
- Do not include any AI attribution or co-author trailers
- If `$ARGUMENTS` contains a specific message, use it (but still prepend the issue number)

### 7. Confirm Success

```bash
git log --oneline -1
```

Report the commit hash and message to the user.
