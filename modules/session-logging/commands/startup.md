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
LOG_FILE="${LOG_DIR}/${AGENT_ID}.md"

if [ -f "$LOG_FILE" ]; then
  echo "Today's log exists - reading for context"
else
  echo "No log for today yet"
  # Find most recent log for this agent
  find "${LOG_REPO}/${REPO_NAME}" -name "${AGENT_ID}.md" -type f | sort | tail -1
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
    git commit -m "${AGENT_ID}: auto-sync" && git pull --rebase && git push
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

**IMPORTANT: Parallel execution safety** - Log directory creation (`mkdir -p`) is
independent of git operations. Do NOT batch it in the same parallel tool call as git
sync commands. If a git command is denied by a hook, the entire parallel batch gets
cancelled, including the `mkdir -p`. Always run log directory creation as its own
separate step, not grouped with any git commands.

### 5. Git Status Check & Sync

**CRITICAL: Never use `git reset --hard`** - This command is blocked by the
auto-approve hook (deny pattern: `git reset --hard:*`). Using it will cause the
tool call to be denied, and if other commands are in the same parallel batch, they
will be cancelled too. Use safe alternatives instead.

```bash
# Return to the project directory
cd {project-dir}

# Current branch
BRANCH=$(git branch --show-current)
echo "Branch: $BRANCH"

# Fetch latest
git fetch origin

# Sync with remote (safe - fast-forward only, fails cleanly if diverged)
git pull origin "$BRANCH" --ff-only 2>/dev/null || echo "Branch diverged from remote - rebase may be needed"

# Ahead/behind the base branch (use main or development per project config)
git rev-list --left-right --count origin/main...HEAD 2>/dev/null

# Working directory status
git status --short

# Recent commits
git log --oneline -5
```

**If the branch has diverged** (pull --ff-only fails): use `git rebase origin/{base-branch}` to
get back in sync. Never use `git reset --hard`.

**Returning to the base branch after a merge**: Use `git checkout main && git pull origin main --ff-only`
(or `development` depending on the project). Do NOT use `git reset --hard origin/main`.

### 6. Open Pull Requests

```bash
gh pr list --state open --limit 10 2>/dev/null
```

Check for:
- PRs from this agent's previous session
- PRs from other agents that may affect your work
- PRs waiting for review or merge

### 7. Open Issues by Status

> **Note**: Label-based queries below are deprecated in favor of the tracking dashboard (step 7b). They are kept for backward compatibility with repos that haven't adopted the tracking CSV system yet.

```bash
# All open issues
gh issue list --state open --limit 30 2>/dev/null

# Issues assigned to this agent (multi-agent repos) [DEPRECATED - use tracking dashboard]
gh issue list --state open --label "${AGENT_ID}" 2>/dev/null

# In-progress issues [DEPRECATED - use tracking dashboard]
gh issue list --state open --label "in-progress" 2>/dev/null

# Blocked issues
gh issue list --state open --label "blocked" 2>/dev/null

# Human-agent issues (skip these)
gh issue list --state open --label "human-agent" 2>/dev/null
```

### 7b. Tracking Dashboard

Pull the latest log repo and check the tracking CSV for the current repo:

```bash
# Pull latest log repo
cd ~/code/{log-repo-name} && git pull --rebase 2>/dev/null
```

Display active claims, stale claims, and unclaimed issues:

```bash
# List all tracked issues for this repo (active claims, statuses)
python3 ~/.claude/lib/agent_tracking.py list --repo "$REPO_NAME"

# Garbage-collect stale claims (agents that abandoned work without updating)
python3 ~/.claude/lib/agent_tracking.py gc --repo "$REPO_NAME"
```

The tracking dashboard replaces label-based issue queries. It shows:
- **Active claims**: Which agent is working on which issue, with branch and status
- **Stale claims**: Claims from agents that haven't updated in a long time
- **Unclaimed issues**: Open issues not yet claimed by any agent

### 8. Dependency Check

For multi-clone repos, check what sibling agents are working on:

```bash
# Detect model and check sibling clones
WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')

if [ -n "$WC_MATCH" ]; then
  # Workspace model: check sibling clones within this workspace
  WORKSPACE_DIR=$(dirname "$PWD")
  for dir in "${WORKSPACE_DIR}"/*-c[0-9]*/; do
    [ -d "$dir" ] && [ "$dir" != "$PWD/" ] && \
      echo "$(basename $dir): $(git -C $dir branch --show-current 2>/dev/null)"
  done
else
  # Flat clone model: check sibling clones
  REPOS_DIR=$(dirname "$PWD")
  REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
  for dir in "${REPOS_DIR}/${REPO_BASE}"-[0-9]*; do
    if [ -d "$dir" ] && [ "$dir" != "$PWD" ]; then
      echo "$(basename $dir): $(git -C $dir branch --show-current 2>/dev/null)"
    fi
  done
fi
```

### 9. Present Session Summary

Display a concise dashboard:

```
Session: {agent-id} - {repo-name} - {date}
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

### 10. Claude Code Release Check

Check for new Claude Code releases and surface features worth integrating into our workflow.

```bash
# Get current version
CURRENT_VERSION=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
echo "Current Claude Code version: ${CURRENT_VERSION}"
```

Fetch the Claude Code changelog and compare against our last-reviewed version:

```bash
# Read the last-reviewed version from memory
LAST_REVIEWED_FILE="$HOME/.claude/projects/-Users-lem-code/memory/claude-code-releases.md"
if [ -f "$LAST_REVIEWED_FILE" ]; then
  LAST_REVIEWED=$(grep -oE 'last_reviewed: [0-9]+\.[0-9]+\.[0-9]+' "$LAST_REVIEWED_FILE" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
else
  LAST_REVIEWED="$CURRENT_VERSION"
fi
echo "Last reviewed version: ${LAST_REVIEWED}"
```

Use WebFetch to pull the changelog from `https://code.claude.com/docs/en/changelog` and extract all releases newer than `LAST_REVIEWED`.

For each new release, identify features in these categories:

| Category | What to flag |
|----------|-------------|
| **New tools/capabilities** | New tools, computer use, browser features, agent modes |
| **Settings/config changes** | New settings.json keys, permission options, env vars |
| **Workflow improvements** | New CLI flags, subagent features, MCP enhancements |
| **Performance** | Memory, startup time, or throughput improvements |
| **Breaking changes** | Deprecations, removed features, changed defaults |

**Present the release summary** as part of the session dashboard:

```
Claude Code Releases (since {LAST_REVIEWED}):
  Current: v{CURRENT_VERSION} | Latest: v{LATEST}
  {N} new releases with notable changes:

  v{X.Y.Z} ({date}):
    - {notable feature 1}
    - {notable feature 2}

  Recommended actions:
    - [ ] Update to latest: npm install -g @anthropic-ai/claude-code@latest
    - [ ] Enable {new feature} in settings.json
    - [ ] Update CLAUDE.md to use {new capability}
```

**After presenting**: Update the memory file with the latest reviewed version:

Write/update `~/.claude/projects/-Users-lem-code/memory/claude-code-releases.md` with:

```markdown
# Claude Code Release Tracking

last_reviewed: {LATEST_VERSION}
last_checked: {TODAY}

## Recent Notable Features
- {version}: {feature} - {status: integrated / pending / skipped}
```

**If current version is behind latest**: Flag the update prominently and recommend updating before starting work, since new features may affect the session.

**If no new releases since last check**: Skip this section silently (don't clutter the dashboard).

### 11. Suggested Next Actions

Based on the gathered state, recommend what to do:

| State | Recommendation |
|-------|---------------|
| PR open from previous session | Check CI status and merge if green |
| In-progress issue from previous session | Continue working on it |
| Uncommitted changes | Review and commit (do NOT stash) |
| Behind base branch | Sync with `git pull origin {branch} --ff-only` or `git rebase origin/{branch}` |
| No active work | Pick next available issue |
| All issues done | Ask what to work on next |
| Claude Code update available | Update first, then proceed |

**Sync safety reminder**: Never use `git reset --hard` to sync branches. Use
`git pull --ff-only` for clean fast-forwards, or `git rebase` when the branch has diverged.
