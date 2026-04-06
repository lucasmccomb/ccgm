#!/usr/bin/env bash
# gs-gather.sh - Parallel data gathering for /gs command
# Runs git status, PR, and session checks concurrently.

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Identity (synchronous) ---
BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
UPSTREAM=$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo "No upstream tracking branch")
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename 2>/dev/null | sed 's/\.git$//' || echo "unknown")

# --- Parallel jobs ---

# 1. Fetch + sync status
(
  git fetch origin 2>/dev/null
  AB_MAIN=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo "? ?")
  AB_UP=$(git rev-list --left-right --count @{upstream}...HEAD 2>/dev/null || echo "? ?")
  echo "main:$AB_MAIN"
  echo "upstream:$AB_UP"
) > "$TMPDIR/sync" 2>/dev/null &

# 2. Working directory status
(
  git status --short 2>/dev/null
) > "$TMPDIR/status" 2>/dev/null &

# 3. Recent commits
(
  git log --oneline -5 2>/dev/null
) > "$TMPDIR/log" 2>/dev/null &

# 4. Open PRs
(
  gh pr list --state open --limit 10 2>/dev/null || echo "none"
) > "$TMPDIR/prs" 2>/dev/null &

# 5. Sibling sessions
(
  python3 ~/.claude/lib/agent_sessions.py --repo "$REPO_NAME" --exclude-cwd "$PWD" --text 2>/dev/null || true
) > "$TMPDIR/sessions" 2>/dev/null &

# 6. Diff stats
(
  echo "---UNSTAGED---"
  git diff --stat 2>/dev/null
  echo "---STAGED---"
  git diff --cached --stat 2>/dev/null
) > "$TMPDIR/diff" 2>/dev/null &

wait

# --- Output ---
cat <<GATHER_EOF
=== REPO ===
name:${REPO_NAME}
branch:${BRANCH}
upstream:${UPSTREAM}

=== SYNC ===
$(cat "$TMPDIR/sync")

=== STATUS ===
$(cat "$TMPDIR/status")

=== LOG ===
$(cat "$TMPDIR/log")

=== PRS ===
$(cat "$TMPDIR/prs")

=== SESSIONS ===
$(cat "$TMPDIR/sessions")

=== DIFF ===
$(cat "$TMPDIR/diff")
GATHER_EOF
