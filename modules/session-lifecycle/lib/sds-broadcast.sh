#!/usr/bin/env bash
# sds-broadcast.sh — deterministic sibling detection + session-event log writer
#
# Used by the /sds command to:
#   1. Detect sibling clones in the same workspace (workspace model only).
#   2. Append a session-event entry to ~/.claude/sessions/{repo}/events.jsonl
#      so future tools can query when each agent last cleanly shut down.
#
# This script does NOT directly notify siblings — the handoff file at
# ~/.claude/handoffs/{repo}/ does that via auto-startup.py on their next
# session. This script just gathers info and persists a structured event.
#
# Usage:
#   sds-broadcast.sh                 Detect + log
#   sds-broadcast.sh --dry-run       Detect only, no writes
#   sds-broadcast.sh --siblings-only Print sibling JSON only, no event log
#
# Output (stdout, JSON):
#   {
#     "agent": "agent-w0-c0",
#     "repo": "ccgm",
#     "workspace": "ccgm-w0",
#     "clone_path": "$HOME/code/.../ccgm-w0-c0",
#     "siblings": [
#       { "agent": "agent-w0-c1", "path": "...", "branch": "...", "dirty": true }
#     ],
#     "event_path": "$HOME/.claude/sessions/ccgm/events.jsonl",
#     "handoff_dir": "$HOME/.claude/handoffs/ccgm"
#   }

set -uo pipefail

DRY_RUN=0
SIBLINGS_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --siblings-only) SIBLINGS_ONLY=1 ;;
    *) echo "warn: unknown arg: $arg" >&2 ;;
  esac
done

# -----------------------------------------------------------------------------
# Identity
# -----------------------------------------------------------------------------

CWD="$(pwd)"
CLONE_PATH="$CWD"

# Read agent_id from .env.clone if present, else derive from directory name
AGENT_ID=""
if [ -f "$CWD/.env.clone" ]; then
  AGENT_ID="$(grep -E '^AGENT_ID=' "$CWD/.env.clone" 2>/dev/null | head -1 | cut -d= -f2)"
fi
if [ -z "$AGENT_ID" ]; then
  base="$(basename "$CWD")"
  if [[ "$base" =~ w([0-9]+)-c([0-9]+)$ ]]; then
    AGENT_ID="agent-w${BASH_REMATCH[1]}-c${BASH_REMATCH[2]}"
  elif [[ "$base" =~ -([0-9]+)$ ]]; then
    AGENT_ID="agent-${BASH_REMATCH[1]}"
  else
    AGENT_ID="agent-0"
  fi
fi

# Repo from git remote
REPO=""
if git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  url="$(git -C "$CWD" remote get-url origin 2>/dev/null || true)"
  if [ -n "$url" ]; then
    REPO="$(basename "$url")"
    REPO="${REPO%.git}"
  fi
fi
[ -z "$REPO" ] && REPO="$(basename "$CWD")"

# Workspace = parent dir if cwd basename matches the workspace pattern (w0-cN)
WORKSPACE=""
if [[ "$(basename "$CWD")" =~ w[0-9]+-c[0-9]+$ ]]; then
  WORKSPACE="$(basename "$(dirname "$CWD")")"
fi

# -----------------------------------------------------------------------------
# Sibling detection (workspace model only)
# -----------------------------------------------------------------------------

SIBLINGS_JSON="[]"
if [ -n "$WORKSPACE" ]; then
  ws_dir="$(dirname "$CWD")"
  parts=()
  while IFS= read -r -d '' sib; do
    [ "$sib" = "$CWD" ] && continue
    sib_base="$(basename "$sib")"
    if [[ "$sib_base" =~ w([0-9]+)-c([0-9]+)$ ]]; then
      sib_agent="agent-w${BASH_REMATCH[1]}-c${BASH_REMATCH[2]}"
    else
      continue
    fi
    sib_branch="$(git -C "$sib" branch --show-current 2>/dev/null || echo '')"
    sib_dirty="false"
    if [ -n "$(git -C "$sib" status --porcelain 2>/dev/null)" ]; then
      sib_dirty="true"
    fi
    sib_path_escaped="${sib//\"/\\\"}"
    sib_branch_escaped="${sib_branch//\"/\\\"}"
    parts+=("{\"agent\":\"$sib_agent\",\"path\":\"$sib_path_escaped\",\"branch\":\"$sib_branch_escaped\",\"dirty\":$sib_dirty}")
  done < <(find "$ws_dir" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)

  if [ ${#parts[@]} -gt 0 ]; then
    SIBLINGS_JSON="[$(IFS=,; echo "${parts[*]}")]"
  fi
fi

# -----------------------------------------------------------------------------
# Paths (handoff dir + session event log)
# -----------------------------------------------------------------------------

# Slugify repo name (filesystem-safe)
REPO_SLUG="$(echo "$REPO" | sed -E 's/[^A-Za-z0-9._-]+/-/g; s/^-+|-+$//g')"
[ -z "$REPO_SLUG" ] && REPO_SLUG="unknown"

HANDOFF_DIR="${HOME}/.claude/handoffs/${REPO_SLUG}"
SESSIONS_DIR="${HOME}/.claude/sessions/${REPO_SLUG}"
EVENT_PATH="${SESSIONS_DIR}/events.jsonl"

# -----------------------------------------------------------------------------
# Event log write (unless dry-run or siblings-only)
# -----------------------------------------------------------------------------

if [ "$DRY_RUN" -eq 0 ] && [ "$SIBLINGS_ONLY" -eq 0 ]; then
  mkdir -p "$SESSIONS_DIR"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  branch="$(git -C "$CWD" branch --show-current 2>/dev/null || echo '')"
  branch_escaped="${branch//\"/\\\"}"
  printf '{"ts":"%s","agent":"%s","repo":"%s","branch":"%s","event":"session-ended"}\n' \
    "$ts" "$AGENT_ID" "$REPO_SLUG" "$branch_escaped" >> "$EVENT_PATH"
fi

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

cat <<EOF
{
  "agent": "$AGENT_ID",
  "repo": "$REPO_SLUG",
  "workspace": "$WORKSPACE",
  "clone_path": "$CLONE_PATH",
  "siblings": $SIBLINGS_JSON,
  "event_path": "$EVENT_PATH",
  "handoff_dir": "$HANDOFF_DIR",
  "dry_run": $([ "$DRY_RUN" -eq 1 ] && echo true || echo false)
}
EOF
