#!/usr/bin/env bash
# startup-gather.sh - Parallel data gathering for /startup command
# Runs all independent checks concurrently and outputs structured sections.
# Called by the /startup agent; not meant to be run manually.

PROJECT_DIR="$PWD"
LOG_REPO="$HOME/code/__LOG_REPO__"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Identity (synchronous - everything depends on these) ---

WC_MATCH=$(basename "$PWD" | grep -oE 'w[0-9]+-c[0-9]+$' 2>/dev/null || true)
if [ -n "$WC_MATCH" ]; then
  AGENT_ID="agent-${WC_MATCH}"
elif [ -f .env.clone ] && grep -q 'AGENT_ID=' .env.clone 2>/dev/null; then
  AGENT_ID=$(grep 'AGENT_ID=' .env.clone | cut -d= -f2)
else
  AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' 2>/dev/null || echo "0")
  AGENT_ID="agent-${AGENT_NUM}"
fi

REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename 2>/dev/null | sed 's/\.git$//' || echo "unknown")
TODAY=$(date +%Y%m%d)
NOW_TIME=$(date +%H:%M)

# --- Log repo sync (sequential - needed before log checks) ---

LOG_SYNC="ok"
if [ -d "$LOG_REPO" ]; then
  cd "$LOG_REPO" 2>/dev/null
  git pull --rebase 2>/dev/null || LOG_SYNC="failed"
else
  LOG_SYNC="missing"
fi

LOG_DIR="${LOG_REPO}/${REPO_NAME}/${TODAY}"
LOG_FILE="${LOG_DIR}/${AGENT_ID}.md"

# Log file status
if [ -f "$LOG_FILE" ]; then
  LOG_STATUS="existing"
  PREV_LOG="$LOG_FILE"
else
  LOG_STATUS="new"
  PREV_LOG=$(find "${LOG_REPO}/${REPO_NAME}" -name "${AGENT_ID}.md" -type f 2>/dev/null | sort | tail -1)
  [ -z "$PREV_LOG" ] && PREV_LOG="none"
fi

# Cross-agent: filenames + last ## heading only
: > "$TMPDIR/cross"
if [ -d "$LOG_DIR" ]; then
  for f in "$LOG_DIR"/*.md; do
    [ "$f" = "$LOG_FILE" ] && continue
    [ -f "$f" ] || continue
    HEADING=$(grep '^## ' "$f" 2>/dev/null | tail -1 || echo "(no heading)")
    echo "$(basename "$f"): $HEADING" >> "$TMPDIR/cross"
  done
fi

# Previous log tail (last 20 lines)
if [ "$PREV_LOG" != "none" ] && [ -f "$PREV_LOG" ]; then
  tail -20 "$PREV_LOG" > "$TMPDIR/prev-log" 2>/dev/null
else
  echo "none" > "$TMPDIR/prev-log"
fi

# --- Parallel jobs (all independent) ---

# 1. Git status + sync
(
  cd "$PROJECT_DIR"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "NOT_A_GIT_REPO"
    exit 0
  fi
  BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
  echo "branch:$BRANCH"
  git fetch origin 2>/dev/null
  if git pull origin "$BRANCH" --ff-only 2>/dev/null; then
    echo "sync:ok"
  else
    echo "sync:diverged"
  fi
  AB=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "? ?")
  echo "ahead_behind:$AB"
  echo "---STATUS---"
  git status --short 2>/dev/null
  echo "---COMMITS---"
  git log --oneline -5 2>/dev/null
) > "$TMPDIR/git" 2>/dev/null &

# 2. Open PRs
(
  cd "$PROJECT_DIR"
  gh pr list --state open --limit 10 2>/dev/null || echo "none"
) > "$TMPDIR/prs" 2>/dev/null &

# 3. Tracking dashboard
(
  python3 ~/.claude/lib/agent_tracking.py list --repo "$REPO_NAME" 2>/dev/null || echo "unavailable"
  echo "---GC---"
  python3 ~/.claude/lib/agent_tracking.py gc --repo "$REPO_NAME" 2>/dev/null || true
) > "$TMPDIR/tracking" 2>/dev/null &

# 4. Live sessions
(
  python3 ~/.claude/lib/agent_sessions.py --text --exclude-cwd "$PROJECT_DIR" 2>/dev/null || true
) > "$TMPDIR/sessions" 2>/dev/null &

# 5. Sibling branches
(
  cd "$PROJECT_DIR"
  WC=$(basename "$PWD" | grep -oE 'w[0-9]+-c[0-9]+$' 2>/dev/null || true)
  if [ -n "$WC" ]; then
    WS_DIR=$(dirname "$PWD")
    for dir in "$WS_DIR"/*-c[0-9]*/; do
      [ -d "$dir" ] && [ "$dir" != "$PWD/" ] && \
        echo "$(basename "$dir"): $(git -C "$dir" branch --show-current 2>/dev/null)"
    done
  else
    REPOS_DIR=$(dirname "$PWD")
    REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
    for dir in "$REPOS_DIR/${REPO_BASE}"-[0-9]*; do
      [ -d "$dir" ] && [ "$dir" != "$PWD" ] && \
        echo "$(basename "$dir"): $(git -C "$dir" branch --show-current 2>/dev/null)"
    done
  fi
) > "$TMPDIR/siblings" 2>/dev/null &

# 6. Orphan process check
(
  python3 ~/.claude/hooks/orphan-process-check.py 2>/dev/null || true
) > "$TMPDIR/orphans" 2>/dev/null &

# 7. Release check
(
  CURRENT=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  LATEST=$(npm view @anthropic-ai/claude-code version 2>/dev/null || echo "")
  echo "current:${CURRENT:-unknown}"
  echo "latest:${LATEST:-unknown}"
  if [ -n "$CURRENT" ] && [ -n "$LATEST" ] && [ "$CURRENT" != "$LATEST" ]; then
    echo "UPDATE_AVAILABLE"
  fi
) > "$TMPDIR/release" 2>/dev/null &

# 8. Log repo freshness (auto-sync if stale)
(
  cd "$LOG_REPO" 2>/dev/null || exit 0
  LAST_COMMIT=$(git log -1 --format="%ct" 2>/dev/null || echo "0")
  NOW=$(date +%s)
  DIFF=$(( (NOW - LAST_COMMIT) / 60 ))
  if [ "$DIFF" -gt 60 ]; then
    git add -A 2>/dev/null
    if ! git diff --cached --quiet 2>/dev/null; then
      git commit -m "${AGENT_ID}: auto-sync" 2>/dev/null && \
        git pull --rebase 2>/dev/null && \
        git push 2>/dev/null && echo "auto-synced" || echo "sync-failed"
    else
      echo "clean"
    fi
  else
    echo "fresh:${DIFF}min"
  fi
) > "$TMPDIR/freshness" 2>/dev/null &

# Wait for all background jobs
wait

# --- Structured output ---

cat <<GATHER_EOF
=== IDENTITY ===
agent_id:${AGENT_ID}
repo:${REPO_NAME}
date:${TODAY}
time:${NOW_TIME}
project_dir:${PROJECT_DIR}
log_repo:${LOG_REPO}

=== LOG ===
status:${LOG_STATUS}
file:${LOG_FILE}
dir:${LOG_DIR}
prev:${PREV_LOG}

=== PREV_LOG_TAIL ===
$(cat "$TMPDIR/prev-log")

=== CROSS_AGENT ===
$(cat "$TMPDIR/cross")

=== GIT ===
$(cat "$TMPDIR/git")

=== PRS ===
$(cat "$TMPDIR/prs")

=== TRACKING ===
$(cat "$TMPDIR/tracking")

=== SESSIONS ===
$(cat "$TMPDIR/sessions")

=== SIBLINGS ===
$(cat "$TMPDIR/siblings")

=== ORPHANS ===
$(cat "$TMPDIR/orphans")

=== RELEASE ===
$(cat "$TMPDIR/release")

=== FRESHNESS ===
$(cat "$TMPDIR/freshness")
GATHER_EOF
