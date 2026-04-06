#!/usr/bin/env bash
# xplan-status-gather.sh - Parallel data gathering for /xplan-status
# Usage: xplan-status-gather.sh <project-name> <github-user>
# Runs issue, PR, and clone state checks concurrently.

PROJECT="$1"
GH_USER="$2"

if [ -z "$PROJECT" ] || [ -z "$GH_USER" ]; then
  echo "ERROR: Usage: xplan-status-gather.sh <project-name> <github-user>"
  exit 1
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# --- Parallel jobs ---

# 1. Open issues
(
  gh issue list --state open --repo "${GH_USER}/${PROJECT}" --limit 50 2>/dev/null || echo "none"
) > "$TMPDIR/issues" &

# 2. Open PRs
(
  gh pr list --state open --repo "${GH_USER}/${PROJECT}" 2>/dev/null || echo "none"
) > "$TMPDIR/prs" &

# 3. Clone states (auto-detect workspace vs flat model)
(
  WORKSPACES_DIR="$HOME/code/${PROJECT}-workspaces"
  REPOS_DIR="$HOME/code/${PROJECT}-repos"

  if [ -d "$WORKSPACES_DIR" ]; then
    for dir in "$WORKSPACES_DIR"/${PROJECT}-w*/${PROJECT}-w*-c*/; do
      [ -d "$dir" ] || continue
      CLONE=$(basename "$dir")
      BRANCH=$(git -C "$dir" branch --show-current 2>/dev/null || echo "unknown")
      STATUS=$(git -C "$dir" status --short 2>/dev/null)
      echo "${CLONE}|${BRANCH}|${STATUS}"
    done
  elif [ -d "$REPOS_DIR" ]; then
    for dir in "$REPOS_DIR"/${PROJECT}-[0-9]*/; do
      [ -d "$dir" ] || continue
      CLONE=$(basename "$dir")
      BRANCH=$(git -C "$dir" branch --show-current 2>/dev/null || echo "unknown")
      STATUS=$(git -C "$dir" status --short 2>/dev/null)
      echo "${CLONE}|${BRANCH}|${STATUS}"
    done
  else
    echo "no_clones_found"
  fi
) > "$TMPDIR/clones" &

# 4. Tracking dashboard
(
  python3 ~/.claude/lib/agent_tracking.py list --repo "$PROJECT" 2>/dev/null || echo "unavailable"
) > "$TMPDIR/tracking" &

wait

# --- Output ---
cat <<GATHER_EOF
=== PROJECT ===
name:${PROJECT}
user:${GH_USER}

=== ISSUES ===
$(cat "$TMPDIR/issues")

=== PRS ===
$(cat "$TMPDIR/prs")

=== CLONES ===
$(cat "$TMPDIR/clones")

=== TRACKING ===
$(cat "$TMPDIR/tracking")
GATHER_EOF
