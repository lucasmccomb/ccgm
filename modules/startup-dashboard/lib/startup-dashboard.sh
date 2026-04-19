#!/usr/bin/env bash
# startup-dashboard.sh - Run gather and emit formatted dashboard.
# Replaces the model-delegated formatting step of /startup (#335).
# Called directly by /startup; no Agent tool dispatch, no model tokens for formatting.

set -u

GATHER_SCRIPT="${CCGM_GATHER_SCRIPT:-$HOME/.claude/lib/startup-gather.sh}"

if [ ! -f "$GATHER_SCRIPT" ]; then
  echo "startup-dashboard: gather script not found at $GATHER_SCRIPT" >&2
  exit 1
fi

GATHER=$(bash "$GATHER_SCRIPT" 2>/dev/null)
if [ -z "$GATHER" ]; then
  echo "startup-dashboard: gather produced no output" >&2
  exit 1
fi

# ---- Section extraction ----
section() {
  local name="$1"
  printf '%s\n' "$GATHER" | awk -v marker="=== $name ===" '
    $0 == marker { inside = 1; next }
    /^=== / && inside { exit }
    inside { print }
  '
}

kv() {
  local name="$1" key="$2"
  section "$name" | awk -F: -v k="$key" '$1 == k { sub(/^[^:]*:/, ""); print; exit }'
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

indent() {
  awk 'NF { print "  " $0 } !NF { print }'
}

# ---- Extract fields ----
AGENT_ID=$(kv IDENTITY agent_id)
REPO=$(kv IDENTITY repo)
DATE=$(kv IDENTITY date)
IS_WORKSPACE_ROOT=$(kv IDENTITY is_workspace_root)

GIT_SECTION=$(section GIT)
if printf '%s' "$GIT_SECTION" | grep -q '^NOT_A_GIT_REPO$'; then
  BRANCH="(not a git repo)"
  SYNC=""
  AHEAD_BEHIND=""
  GIT_STATUS_BODY=""
else
  BRANCH=$(printf '%s\n' "$GIT_SECTION" | awk -F: '$1 == "branch" { sub(/^[^:]*:/, ""); print; exit }')
  SYNC=$(printf '%s\n' "$GIT_SECTION" | awk -F: '$1 == "sync" { sub(/^[^:]*:/, ""); print; exit }')
  AHEAD_BEHIND=$(printf '%s\n' "$GIT_SECTION" | awk -F: '$1 == "ahead_behind" { sub(/^[^:]*:/, ""); print; exit }')
  GIT_STATUS_BODY=$(printf '%s\n' "$GIT_SECTION" | awk '
    /^---STATUS---$/ { inside = 1; next }
    /^---COMMITS---$/ { inside = 0 }
    inside { print }
  ')
fi

CLONES_BODY=$(section CLONES)
PRS_BODY=$(section PRS)
TRACKING_BODY=$(section TRACKING)
SESSIONS_BODY=$(section SESSIONS)
SIBLINGS_BODY=$(section SIBLINGS)
ORPHANS_BODY=$(section ORPHANS)
RECENT_BODY=$(section RECENT_ACTIVITY)
RECENT_MERGES_BODY=$(section RECENT_MERGES)
CANDIDATE_ISSUES_BODY=$(section CANDIDATE_ISSUES)

RELEASE_CURRENT=$(kv RELEASE current)
RELEASE_LATEST=$(kv RELEASE latest)
UPDATE_AVAILABLE=0
if printf '%s\n' "$GATHER" | grep -q '^UPDATE_AVAILABLE$'; then
  UPDATE_AVAILABLE=1
fi

# ---- Summaries ----

if [ "$BRANCH" = "(not a git repo)" ]; then
  STATUS_LABEL="n/a"
  SYNC_LABEL="n/a"
elif [ -n "$(trim "$GIT_STATUS_BODY")" ]; then
  STATUS_LABEL="dirty"
else
  STATUS_LABEL="clean"
fi

if [ "$BRANCH" != "(not a git repo)" ]; then
  AB_TRIMMED=$(trim "$AHEAD_BEHIND")
  case "$AB_TRIMMED" in
    "0	0"|"0 0"|"")
      SYNC_LABEL="up to date"
      ;;
    *)
      BEHIND=$(printf '%s' "$AB_TRIMMED" | awk '{print $1}')
      AHEAD=$(printf '%s' "$AB_TRIMMED" | awk '{print $2}')
      SYNC_LABEL="ahead ${AHEAD:-0}, behind ${BEHIND:-0}"
      ;;
  esac
fi

# Parse CLONES body to find dirty clones (workspace mode).
DIRTY_CLONES=""
if [ "$IS_WORKSPACE_ROOT" = "true" ] && [ -n "$(trim "$CLONES_BODY")" ]; then
  while IFS=$'\t' read -r clone branch status sync; do
    [ -z "$clone" ] && continue
    case "$status" in
      dirty*) DIRTY_CLONES="${DIRTY_CLONES:+$DIRTY_CLONES, }${clone}" ;;
    esac
  done <<EOF
$CLONES_BODY
EOF
fi

# PR count for header
PR_COUNT=0
if [ -n "$(trim "$PRS_BODY")" ] && [ "$(trim "$PRS_BODY")" != "none" ]; then
  PR_COUNT=$(printf '%s\n' "$PRS_BODY" | grep -cE '^[0-9]+' || true)
  [ -z "$PR_COUNT" ] && PR_COUNT=0
fi

# Recent merge count
MERGE_COUNT=0
if [ -n "$(trim "$RECENT_MERGES_BODY")" ]; then
  MERGE_COUNT=$(printf '%s\n' "$RECENT_MERGES_BODY" | grep -c . || true)
  [ -z "$MERGE_COUNT" ] && MERGE_COUNT=0
fi

# First candidate issue (if any)
FIRST_CANDIDATE=""
if [ -n "$(trim "$CANDIDATE_ISSUES_BODY")" ]; then
  FIRST_CANDIDATE=$(printf '%s\n' "$CANDIDATE_ISSUES_BODY" | head -1)
fi

# Recommendation priority:
# 1. Open PRs (review/merge)
# 2. Dirty working tree (in-clone) or dirty clones (workspace mode)
# 3. Unclaimed open issue
# 4. Fallback
NEXT="What would you like to work on?"
if [ "$PR_COUNT" -gt 0 ] 2>/dev/null; then
  NEXT="Review ${PR_COUNT} open PR(s)"
elif [ "$STATUS_LABEL" = "dirty" ]; then
  NEXT="Review uncommitted changes or continue previous work"
elif [ -n "$DIRTY_CLONES" ]; then
  NEXT="Uncommitted changes in: ${DIRTY_CLONES}"
elif [ -n "$FIRST_CANDIDATE" ]; then
  # Render as "Pick up <first candidate>"
  NEXT="Pick up $(printf '%s' "$FIRST_CANDIDATE" | awk -F'\t' '{printf "%s: %s", $1, $2}')"
fi

# ---- Emit dashboard ----

REPO_DISPLAY="$REPO"
[ -z "$REPO_DISPLAY" ] && REPO_DISPLAY="(no repo)"
if [ "$IS_WORKSPACE_ROOT" = "true" ] && [ "$REPO_DISPLAY" != "(no repo)" ] && [ "$REPO_DISPLAY" != "unknown" ]; then
  REPO_DISPLAY="${REPO_DISPLAY} (workspace)"
fi

if [ ${#DATE} -eq 8 ]; then
  DATE_PRETTY="${DATE:0:4}-${DATE:4:2}-${DATE:6:2}"
else
  DATE_PRETTY="$DATE"
fi

printf '%s  ·  %s  ·  %s\n' "$AGENT_ID" "$REPO_DISPLAY" "$DATE_PRETTY"

# Header line differs by mode. In workspace mode, the Clones section carries the
# per-clone detail, so the header just summarizes repo-level state.
if [ "$IS_WORKSPACE_ROOT" = "true" ]; then
  CLONE_COUNT=0
  if [ -n "$(trim "$CLONES_BODY")" ]; then
    CLONE_COUNT=$(printf '%s\n' "$CLONES_BODY" | grep -c . || true)
  fi
  printf 'Workspace  %s clone(s)\n' "${CLONE_COUNT:-0}"
else
  printf 'Branch    %-30s  Status  %-8s  Sync  %s\n' "$BRANCH" "$STATUS_LABEL" "$SYNC_LABEL"
fi

emit_section() {
  local label="$1" body="$2"
  local trimmed
  trimmed=$(trim "$body")
  [ -z "$trimmed" ] && return 0
  [ "$trimmed" = "none" ] && return 0
  [ "$trimmed" = "(unknown repo - tracking unavailable)" ] && return 0
  [ "$trimmed" = "(coordinator workspace - tracking shown by individual clones)" ] && return 0
  printf '\n%s\n' "$label"
  printf '%s\n' "$body" | indent
}

# Clones table (workspace mode only)
if [ "$IS_WORKSPACE_ROOT" = "true" ] && [ -n "$(trim "$CLONES_BODY")" ]; then
  printf '\nClones\n'
  printf '%s\n' "$CLONES_BODY" | awk -F'\t' '{printf "  %-4s  %-36s  %-12s  %s\n", $1, $2, $3, $4}'
fi

emit_section "Live Sessions" "$SESSIONS_BODY"

if [ "$PR_COUNT" -gt 0 ] 2>/dev/null; then
  printf '\nOpen PRs (%s)\n' "$PR_COUNT"
  printf '%s\n' "$PRS_BODY" | indent
fi

# Recent merges (last 48h)
if [ "$MERGE_COUNT" -gt 0 ] 2>/dev/null; then
  printf '\nMerged (last 48h, %s)\n' "$MERGE_COUNT"
  printf '%s\n' "$RECENT_MERGES_BODY" | awk -F'\t' '{
    # Shorten mergedAt YYYY-MM-DDThh:mm:ssZ -> MM-DD hh:mm
    t = $2
    date = substr(t, 6, 5)
    time = substr(t, 12, 5)
    printf "  %s  %s %s  %s  %s\n", $1, date, time, $3, $4
  }'
fi

emit_section "Tracking" "$TRACKING_BODY"
emit_section "Recent Activity" "$RECENT_BODY"
emit_section "Siblings" "$SIBLINGS_BODY"

ORPHANS_TRIMMED=$(trim "$ORPHANS_BODY")
if [ -n "$ORPHANS_TRIMMED" ]; then
  printf '\nOrphans\n'
  printf '%s\n' "$ORPHANS_BODY" | indent
fi

if [ "$UPDATE_AVAILABLE" = "1" ]; then
  printf '\nUpdate    v%s -> v%s   (npm i -g @anthropic-ai/claude-code@latest)\n' \
    "$(trim "$RELEASE_CURRENT")" "$(trim "$RELEASE_LATEST")"
fi

printf '\nNext  %s\n' "$NEXT"
