---
description: Log initialization - create today's log without full session startup
allowed-tools: Agent
---

# /log-init - Log Initialization

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: log initialization

Pass the agent all workflow instructions below.

After the agent completes, relay its brief status line to the user exactly as received. Then wait for the user's next instruction.

---

## Workflow Instructions

Initialize session logging only. Faster than /startup - no git status, no issue check, no release check.

### 1. Derive Agent Identity

```bash
# Agent identity from directory name (supports both workspace and flat clone models)
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

# Repo name from git remote
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
echo "Repo: ${REPO_NAME}"

# Today's date
TODAY=$(date +%Y%m%d)
echo "Date: ${TODAY}"
```

### 2. Pull Log Repo

```bash
LOG_REPO="$HOME/code/{log-repo-name}"
cd "$LOG_REPO" && git pull --rebase 2>/dev/null | tail -1
```

Check for today's log file:

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

If today's log exists, read it briefly (last 20 lines only) for minimal context. If not, note the most recent log date for reference.

### 3. Freshness Check

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

### 4. Create Today's Log (if needed)

**IMPORTANT: Parallel execution safety** - Run `mkdir -p` as its own step, never grouped with git commands in the same parallel call.

```bash
mkdir -p "$LOG_DIR"
```

If today's log does not exist, create it:

```markdown
# {agent-id} - {YYYYMMDD} - {repo-name}

## Session Start
- **Time**: {HH:MM}
- **Branch**: `{current-branch}`
- **State**: {Clean / dirty / in-progress on #XX}
```

To get current branch:
```bash
git branch --show-current
```

### 5. Output Status

Check for sibling sessions in the same repo (other live Claude CLI sessions):

```bash
python3 ~/.claude/lib/agent_sessions.py --repo "$REPO_NAME" --exclude-cwd "$PWD" --text 2>/dev/null
```

If the command is unavailable or returns nothing, skip silently.

Print the log line, then optionally a sessions line if siblings exist:

```
Log: {agent-id} @ {log-file-path} [new | existing]
Sessions: {agent-id} (branch: {branch}, up {uptime}) | ...
```

The Sessions line is only shown when at least one sibling session exists. Format each sibling compactly: `{agent_id or pid} (branch: {branch}, up {uptime})`. If agent_id is unknown, use `pid:{pid}`.

Example with siblings:
```
Log: agent-0 @ ~/code/{log-repo-name}/my-repo/20260404/agent-0.md [new]
Sessions: agent-w0-c1 (branch: 44-feature, up 45m) | agent-w0-c3 (branch: main, up 2h)
```

Example without siblings (single line, unchanged):
```
Log: agent-0 @ ~/code/{log-repo-name}/my-repo/20260404/agent-0.md [existing]
```

That is all. No dashboard, no recommendations, no issue list.
