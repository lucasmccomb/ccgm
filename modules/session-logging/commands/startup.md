---
description: Session startup - check logs, git status, open issues, and orient
allowed-tools: Bash, Read, Glob, Grep
---

# /startup - Session Startup

Initialize a new session by checking logs, git status, open issues, and establishing context.

## Input

```
$ARGUMENTS
```

## Instructions

### 1. Derive Agent Identity

```bash
# Agent number from directory name
AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' || echo "0")
echo "Agent: agent-${AGENT_NUM}"

# Repo name from git remote
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
echo "Repo: ${REPO_NAME}"

# Today's date
TODAY=$(date +%Y%m%d)
echo "Date: ${TODAY}"
```

### 2. Session Log Check

Pull the latest agent logs and read relevant context:

```bash
# Pull latest logs (adjust path to your log repo)
LOG_REPO="$HOME/code/{log-repo-name}"
cd "$LOG_REPO" && git pull --rebase 2>/dev/null
```

Check for today's log file:

```bash
LOG_DIR="${LOG_REPO}/${REPO_NAME}/${TODAY}"
LOG_FILE="${LOG_DIR}/agent-${AGENT_NUM}.md"

if [ -f "$LOG_FILE" ]; then
  echo "Today's log exists - reading for context"
else
  echo "No log for today yet"
  # Find most recent log for this agent
  find "${LOG_REPO}/${REPO_NAME}" -name "agent-${AGENT_NUM}.md" -type f | sort | tail -1
fi
```

If today's log exists, read it. If not, read the most recent log for this agent in the project directory.

**Cross-agent awareness**: Read other agents' logs from today to understand what they are working on:

```bash
ls "${LOG_REPO}/${REPO_NAME}/${TODAY}/" 2>/dev/null
```

Read other agents' files to check for:
- Issues they have claimed (avoid conflicts)
- Branches they created
- Blockers or decisions that affect your work

### 3. Freshness Check

If the log repo has uncommitted changes older than 1 hour, auto-commit and push:

```bash
cd "$LOG_REPO"
LAST_COMMIT=$(git log -1 --format="%ct" 2>/dev/null || echo "0")
NOW=$(date +%s)
DIFF_MINUTES=$(( (NOW - LAST_COMMIT) / 60 ))

if [ "$DIFF_MINUTES" -gt 60 ]; then
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "agent-${AGENT_NUM}: auto-sync" && git pull --rebase && git push
  fi
fi
```

### 4. Create Today's Log (if needed)

If today's log does not exist:

```bash
mkdir -p "$LOG_DIR"
```

Create the log file with a Session Start entry:

```markdown
# agent-N - YYYYMMDD - {repo-name}

## Session Start
- **Time**: HH:MM
- **Branch**: `{current-branch}`
- **State**: {Clean / dirty / in-progress on #XX}
```

### 5. Git Status Check

```bash
# Return to the project directory
cd {project-dir}

# Current branch
git branch --show-current

# Fetch latest
git fetch origin

# Ahead/behind main
git rev-list --left-right --count origin/main...HEAD 2>/dev/null

# Working directory status
git status --short

# Recent commits
git log --oneline -5
```

### 6. Open Pull Requests

```bash
gh pr list --state open --limit 10 2>/dev/null
```

Check for:
- PRs from this agent's previous session
- PRs from other agents that may affect your work
- PRs waiting for review or merge

### 7. Open Issues by Status

```bash
# All open issues
gh issue list --state open --limit 30 2>/dev/null

# Issues assigned to this agent (multi-agent repos)
gh issue list --state open --label "agent-${AGENT_NUM}" 2>/dev/null

# In-progress issues
gh issue list --state open --label "in-progress" 2>/dev/null

# Blocked issues
gh issue list --state open --label "blocked" 2>/dev/null

# Human-agent issues (skip these)
gh issue list --state open --label "human-agent" 2>/dev/null
```

### 8. Dependency Check

For multi-clone repos, check what sibling agents are working on:

```bash
# Check sibling clone branches
REPOS_DIR=$(dirname "$PWD")
REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
for dir in "${REPOS_DIR}/${REPO_BASE}"-[0-9]*; do
  if [ -d "$dir" ] && [ "$dir" != "$PWD" ]; then
    echo "$(basename $dir): $(git -C $dir branch --show-current 2>/dev/null)"
  fi
done
```

### 9. Present Session Summary

Display a concise dashboard:

```
Session: agent-{N} - {repo-name} - {date}
Branch: {current-branch}
Status: {clean/dirty}
Sync: {N ahead, N behind main}

Previous Session:
  {Summary of last log entry or "No previous session found"}

Cross-Agent Activity:
  {What other agents logged today, or "No other agent activity"}

Open PRs: {count}
  {list if any}

Open Issues: {count} ({N in-progress}, {N blocked}, {N human-agent})
  In-Progress: {list}
  Available: {list of unclaimed issues}

Recommended: {suggested next action based on state}
```

### 10. Suggested Next Actions

Based on the gathered state, recommend what to do:

| State | Recommendation |
|-------|---------------|
| PR open from previous session | Check CI status and merge if green |
| In-progress issue from previous session | Continue working on it |
| Uncommitted changes | Review and commit or stash |
| Behind main | Rebase on origin/main |
| No active work | Pick next available issue |
| All issues done | Ask what to work on next |
