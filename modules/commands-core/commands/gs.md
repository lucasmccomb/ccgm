---
description: Show git status and project overview
allowed-tools: Agent
---

# /gs - Git Status Dashboard

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: git status dashboard

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its dashboard output to the user exactly as received.

---

## Workflow Instructions

Display a comprehensive overview of the current repository state, including branch info, working directory status, sync status, and suggested next actions.

Arguments: $ARGUMENTS

### 1. Branch and Remote Info

```bash
# Current branch
BRANCH=$(git branch --show-current)

# Remote tracking branch
git rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo "No upstream tracking branch"

# Fetch latest (non-blocking, just to check ahead/behind)
git fetch origin 2>/dev/null
```

### 2. Working Directory Status

```bash
git status --short
```

Categorize and summarize:
- Staged changes (ready to commit)
- Unstaged changes (modified but not staged)
- Untracked files
- Conflicted files (if any)

### 3. Sync Status

```bash
# Ahead/behind main
git rev-list --left-right --count origin/main...HEAD 2>/dev/null

# Ahead/behind tracking branch
git rev-list --left-right --count @{upstream}...HEAD 2>/dev/null
```

Report:
- Commits ahead of main
- Commits behind main
- Commits ahead of remote tracking branch (unpushed)
- Commits behind remote tracking branch (needs pull)

### 4. Recent Commits

```bash
git log --oneline -5
```

### 5. Open Pull Requests

```bash
gh pr list --state open --limit 10 2>/dev/null
```

If any PRs are from the current branch, highlight them.

### 6. Uncommitted Changes Summary

If there are uncommitted changes, provide a brief summary:

```bash
git diff --stat
git diff --cached --stat
```

### 7. Recommended Next Action

Based on the gathered state, suggest the most logical next action:

| State | Recommendation |
|-------|---------------|
| Uncommitted changes on feature branch | Run `/commit` to commit your changes |
| Committed changes, no PR | Run `/pr` to push and create a pull request |
| On main with no changes | Create a feature branch or run `/ghi` |
| Behind main on feature branch | Run `git fetch origin && git rebase origin/main` |
| PR open and CI passing | Run `gh pr merge --squash --delete-branch` |
| Merge conflicts | Resolve conflicts, then `git rebase --continue` |
| Clean state on main | Ready for new work |

### 8. Display Dashboard

Present the information in a clean, scannable format:

```
Repository: {repo-name}
Branch: {branch} -> {tracking-branch}
Status: {clean / N files changed}

Sync:
  Main: {N ahead, N behind}
  Remote: {N unpushed, N to pull}

Recent Commits:
  {hash} {message}
  {hash} {message}
  ...

Open PRs:
  #{number} {title} ({branch})
  ...

Changes:
  {staged/unstaged/untracked summary}

Suggested: {recommended next action}
```
