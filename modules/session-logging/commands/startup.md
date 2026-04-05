---
description: Session startup - check logs, git status, open issues, and orient
allowed-tools: Agent
---

# /startup - Session Startup

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: session startup

Pass the agent all workflow instructions below.

After the agent completes, relay its session summary dashboard to the user exactly as received. Then wait for the user's next instruction.

---

## Workflow Instructions

Initialize a new session by checking logs, git status, open issues, and establishing context.

### 1. Derive Agent Identity

```bash
WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')
if [ -n "$WC_MATCH" ]; then
  AGENT_ID="agent-${WC_MATCH}"
elif [ -f .env.clone ] && grep -q 'AGENT_ID=' .env.clone 2>/dev/null; then
  AGENT_ID=$(grep 'AGENT_ID=' .env.clone | cut -d= -f2)
else
  AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' || echo "0")
  AGENT_ID="agent-${AGENT_NUM}"
fi
echo "Agent: ${AGENT_ID}"

REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
echo "Repo: ${REPO_NAME}"

TODAY=$(date +%Y%m%d)
echo "Date: ${TODAY}"
```

### 2. Session Log Check

```bash
LOG_REPO="$HOME/code/{log-repo-name}"
cd "$LOG_REPO" && git pull --rebase 2>/dev/null | tail -1
```

```bash
LOG_DIR="${LOG_REPO}/${REPO_NAME}/${TODAY}"
LOG_FILE="${LOG_DIR}/${AGENT_ID}.md"

if [ -f "$LOG_FILE" ]; then
  echo "status:existing"
else
  echo "status:new"
  find "${LOG_REPO}/${REPO_NAME}" -name "${AGENT_ID}.md" -type f | sort | tail -1
fi
```

If today's log exists, read it. If not, read the most recent log for this agent.

**Cross-agent awareness**: List other agents' logs from today (filenames + last `## ` heading only - do NOT read full files):

```bash
for f in "${LOG_REPO}/${REPO_NAME}/${TODAY}"/*.md; do
  [ "$f" = "$LOG_FILE" ] && continue
  [ -f "$f" ] && echo "$(basename $f): $(grep '^## ' "$f" | tail -1)"
done
```

### 3. Live Session Discovery

```bash
python3 ~/.claude/lib/agent_sessions.py --text --exclude-cwd "$PWD" 2>/dev/null
```

Cross-reference with tracking.csv claims to annotate LIVE vs IDLE. If script unavailable, skip silently.

### 4. Freshness Check

If the log repo has uncommitted changes older than 1 hour, auto-commit and push:

```bash
cd "$LOG_REPO"
LAST_COMMIT=$(git log -1 --format="%ct" 2>/dev/null || echo "0")
NOW=$(date +%s)
DIFF_MINUTES=$(( (NOW - LAST_COMMIT) / 60 ))

if [ "$DIFF_MINUTES" -gt 60 ]; then
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "${AGENT_ID}: auto-sync" && git pull --rebase && git push
  fi
fi
```

### 5. Create Today's Log (if needed)

**Parallel safety**: Run `mkdir -p` as its own step, never grouped with git commands.

```bash
mkdir -p "$LOG_DIR"
```

If today's log does not exist, create it with a Session Start entry including time, branch (`git branch --show-current`), and state (clean/dirty/in-progress).

### 6. Git Status Check & Sync

First verify you are in a git repository:
```bash
git rev-parse --is-inside-work-tree 2>/dev/null || echo "NOT_A_GIT_REPO"
```

If NOT in a git repo, skip all git operations and note in the dashboard. Otherwise:

```bash
cd {project-dir}
BRANCH=$(git branch --show-current)
echo "Branch: $BRANCH"
git fetch origin
git pull origin "$BRANCH" --ff-only 2>/dev/null || echo "Branch diverged - rebase may be needed"
git rev-list --left-right --count origin/main...HEAD 2>/dev/null
git status --short
git log --oneline -5
```

Never use `git reset --hard` (blocked by hook). Use `git rebase origin/{base}` if diverged.

### 7. Open Pull Requests

```bash
gh pr list --state open --limit 10 2>/dev/null
```

### 8. Tracking Dashboard

```bash
cd ~/code/{log-repo-name} && git pull --rebase 2>/dev/null
python3 ~/.claude/lib/agent_tracking.py list --repo "$REPO_NAME"
python3 ~/.claude/lib/agent_tracking.py gc --repo "$REPO_NAME"
```

Shows active claims, stale claims, and unclaimed issues.

### 9. Dependency Check

For multi-clone repos, check sibling branches:

```bash
WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')
if [ -n "$WC_MATCH" ]; then
  WORKSPACE_DIR=$(dirname "$PWD")
  for dir in "${WORKSPACE_DIR}"/*-c[0-9]*/; do
    [ -d "$dir" ] && [ "$dir" != "$PWD/" ] && \
      echo "$(basename $dir): $(git -C $dir branch --show-current 2>/dev/null)"
  done
else
  REPOS_DIR=$(dirname "$PWD")
  REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
  for dir in "${REPOS_DIR}/${REPO_BASE}"-[0-9]*; do
    [ -d "$dir" ] && [ "$dir" != "$PWD" ] && \
      echo "$(basename $dir): $(git -C $dir branch --show-current 2>/dev/null)"
  done
fi
```

### 10. Orphaned Process Check

```bash
python3 ~/.claude/hooks/orphan-process-check.py 2>/dev/null
```

Include warning in dashboard if output exists. Otherwise skip.

### 11. Release Check

```bash
CURRENT=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
LATEST=$(npm view @anthropic-ai/claude-code version 2>/dev/null)
echo "Current: ${CURRENT} | Latest: ${LATEST}"
[ "$CURRENT" != "$LATEST" ] && [ -n "$LATEST" ] && echo "UPDATE_AVAILABLE"
```

If update available, add to dashboard: `Update: v{CURRENT} -> v{LATEST} (npm i -g @anthropic-ai/claude-code@latest)`
If current matches latest, skip silently. Do NOT fetch or read changelogs.

### 12. Present Session Summary

Display a concise dashboard:

```
Session: {agent-id} - {repo-name} - {date}
Branch: {current-branch}
Status: {clean/dirty}
Sync: {N ahead, N behind main}

Previous Session:
  {Summary of last log entry or "No previous session found"}

Cross-Agent Activity:
  {Sibling filenames + last heading, or "No other agent activity"}

Open PRs: {count}
  {list if any}

Tracking:
  {Active claims, unclaimed issues from tracking dashboard}

Recommended: {suggested next action based on state}
```

**STOP after presenting the dashboard.** Do not continue work or execute tasks. Wait for the user's instruction.

| State | Recommendation |
|-------|---------------|
| PR open from previous session | Report PR URL and CI status |
| In-progress issue | Report issue and branch |
| Uncommitted changes | Report what's uncommitted |
| No active work | Report available issues |
| All issues done | Ask what to work on next |
| Update available | Suggest upgrading first |
