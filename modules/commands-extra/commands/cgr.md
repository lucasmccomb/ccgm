---
description: Clear conversation and rebase on the default branch for a fresh start
allowed-tools: Bash
---

# /cgr - Clear + Git Rebase

Start fresh by clearing the conversation context and rebasing on the latest default branch. Use this between tasks to get a clean slate.

## Input

```
$ARGUMENTS
```

## Instructions

### 1. Signal Fresh Start

Tell the user you are clearing context and starting fresh. Forget all previous conversation context - treat everything from this point as a brand new session.

### 2. Detect Default Branch

```bash
# Try remote HEAD first, fall back to common names
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')

if [ -z "$DEFAULT_BRANCH" ]; then
  for candidate in main master; do
    if git rev-parse --verify "origin/$candidate" >/dev/null 2>&1; then
      DEFAULT_BRANCH="$candidate"
      break
    fi
  done
fi

if [ -z "$DEFAULT_BRANCH" ]; then
  echo "ERROR: Could not detect default branch"
  exit 1
fi

echo "Default branch: $DEFAULT_BRANCH"
```

### 3. Stash Uncommitted Changes (if any)

```bash
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Stashing uncommitted changes..."
  git stash push -m "cgr-auto-stash-$(date +%s)"
fi
```

### 4. Checkout and Rebase

```bash
git checkout "$DEFAULT_BRANCH"
git fetch origin "$DEFAULT_BRANCH"
git rebase "origin/$DEFAULT_BRANCH"
```

### 5. Report Status

```bash
echo ""
echo "--- Fresh Start ---"
echo "Branch: $(git branch --show-current)"
echo "Commit: $(git log --oneline -1)"
echo "Status: $(git status --short | wc -l | tr -d ' ') files changed"
echo ""
echo "Ready for new work."
```

Display the status to the user and ask what they would like to work on next.
