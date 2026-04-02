---
description: Clear conversation, checkout default branch, rebase on latest origin
allowed-tools: Agent
---

# /cgr - Clear + Git Rebase

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: cgr git reset

Pass the agent all workflow instructions below.

After the agent completes, relay its confirmation to the user exactly as received. Then treat this as a fresh conversation start - do not carry over context from before the /cgr command.

---

## Workflow Instructions

Clear the conversation and reset to the default branch with latest origin. No arguments expected.

### 1. Detect Default Branch

```bash
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
if [ -z "$DEFAULT_BRANCH" ]; then
  # Fallback: check for main or master
  if git show-ref --verify --quiet refs/remotes/origin/main 2>/dev/null; then
    DEFAULT_BRANCH="main"
  elif git show-ref --verify --quiet refs/remotes/origin/master 2>/dev/null; then
    DEFAULT_BRANCH="master"
  fi
fi
echo "$DEFAULT_BRANCH"
```

If no default branch can be detected, stop and report the error.

### 2. Checkout and Rebase

```bash
git fetch origin
git checkout "$DEFAULT_BRANCH"
# Safe: resets to remote ref (auto-approved by hook)
git reset --hard "origin/$DEFAULT_BRANCH"
```

### 3. Confirm

Output a brief status:

```
On {default_branch} with latest from origin.
```

Then report the latest commit:

```bash
git log --oneline -1
```
