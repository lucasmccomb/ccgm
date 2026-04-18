#!/usr/bin/env bash
# startup-dashboard.sh - Run gather, create log if needed, emit formatted dashboard.
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
# Print lines between "=== NAME ===" and the next "=== ... ===" (exclusive).
section() {
  local name="$1"
  printf '%s\n' "$GATHER" | awk -v marker="=== $name ===" '
    $0 == marker { inside = 1; next }
    /^=== / && inside { exit }
    inside { print }
  '
}

# Read a "key:value" from a section. Returns the value verbatim (everything after the first colon).
kv() {
  local name="$1" key="$2"
  section "$name" | awk -F: -v k="$key" '$1 == k { sub(/^[^:]*:/, ""); print; exit }'
}

# Trim leading/trailing whitespace.
trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# Indent every non-empty line by two spaces.
indent() {
  awk 'NF { print "  " $0 } !NF { print }'
}

# ---- Extract fields ----
AGENT_ID=$(kv IDENTITY agent_id)
REPO=$(kv IDENTITY repo)
DATE=$(kv IDENTITY date)
TIME=$(kv IDENTITY time)

LOG_STATUS=$(kv LOG status)
LOG_FILE=$(kv LOG file)
LOG_DIR=$(kv LOG dir)
PREV_LOG=$(kv LOG prev)

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

PRS_BODY=$(section PRS)
TRACKING_BODY=$(section TRACKING)
SESSIONS_BODY=$(section SESSIONS)
CROSS_AGENT_BODY=$(section CROSS_AGENT)
SIBLINGS_BODY=$(section SIBLINGS)
ORPHANS_BODY=$(section ORPHANS)
PREV_TAIL=$(section PREV_LOG_TAIL)

RELEASE_CURRENT=$(kv RELEASE current)
RELEASE_LATEST=$(kv RELEASE latest)
UPDATE_AVAILABLE=0
if printf '%s\n' "$GATHER" | grep -q '^UPDATE_AVAILABLE$'; then
  UPDATE_AVAILABLE=1
fi

# ---- Create today's log if missing ----
if [ "$LOG_STATUS" = "new" ] && [ -n "$LOG_DIR" ] && [ -n "$LOG_FILE" ]; then
  mkdir -p "$LOG_DIR"
  if [ ! -f "$LOG_FILE" ]; then
    STATE="clean"
    if [ -n "$(trim "$GIT_STATUS_BODY")" ]; then
      STATE="dirty"
    fi
    cat > "$LOG_FILE" <<LOGEOF
# ${AGENT_ID} - ${DATE} - ${REPO}

## Session Start
- **Time**: ${TIME}
- **Branch**: \`${BRANCH}\`
- **State**: ${STATE}
LOGEOF
  fi
fi

# ---- Summaries ----

# "Previous" one-liner: last meaningful "## " heading from PREV_LOG_TAIL.
# Skip the "Session Start" stub since it has no information content.
PREV_SUMMARY="No prior session found"
if [ -n "$(trim "$PREV_TAIL")" ] && [ "$(trim "$PREV_TAIL")" != "none" ]; then
  LAST_HEADING=$(printf '%s\n' "$PREV_TAIL" \
    | grep -E '^## ' \
    | grep -vE '^## Session Start$' \
    | tail -1 \
    | sed -E 's/^## //; s/[[:space:]]*#[a-z-]+$//')
  if [ -n "$LAST_HEADING" ]; then
    PREV_SUMMARY="$LAST_HEADING"
  elif printf '%s\n' "$PREV_TAIL" | grep -qE '^## Session Start$'; then
    PREV_SUMMARY="Session started, no updates logged yet"
  fi
fi

# Status label: clean/dirty/n-a
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

# PR count for header
PR_COUNT=0
if [ -n "$(trim "$PRS_BODY")" ] && [ "$(trim "$PRS_BODY")" != "none" ]; then
  PR_COUNT=$(printf '%s\n' "$PRS_BODY" | grep -cE '^[0-9]+' || true)
  [ -z "$PR_COUNT" ] && PR_COUNT=0
fi

# Recommendation
NEXT="What would you like to work on?"
if [ "$PR_COUNT" -gt 0 ] 2>/dev/null; then
  NEXT="Review ${PR_COUNT} open PR(s)"
elif [ "$STATUS_LABEL" = "dirty" ]; then
  NEXT="Review uncommitted changes or continue previous work"
elif printf '%s\n' "$PREV_TAIL" | grep -qE '#in-progress'; then
  NEXT="Continue in-progress work from previous session"
fi

# ---- Emit dashboard ----

REPO_DISPLAY="$REPO"
[ -z "$REPO_DISPLAY" ] && REPO_DISPLAY="(no repo)"

printf '**%s** | `%s` | %s\n' "$AGENT_ID" "$REPO_DISPLAY" "$DATE"
printf '**Branch:** `%s` | **Status:** %s | **Sync:** %s\n' "$BRANCH" "$STATUS_LABEL" "$SYNC_LABEL"
printf '**Previous** - %s\n' "$PREV_SUMMARY"

emit_section() {
  local label="$1" body="$2"
  local trimmed
  trimmed=$(trim "$body")
  [ -z "$trimmed" ] && return 0
  [ "$trimmed" = "none" ] && return 0
  [ "$trimmed" = "(coordinator workspace - tracking shown by individual clones)" ] && return 0
  printf '\n**%s**\n' "$label"
  printf '%s\n' "$body" | indent
}

emit_section "Live Sessions" "$SESSIONS_BODY"

if [ "$PR_COUNT" -gt 0 ] 2>/dev/null; then
  printf '\n**Open PRs** (%s)\n' "$PR_COUNT"
  printf '%s\n' "$PRS_BODY" | indent
fi

emit_section "Tracking" "$TRACKING_BODY"
emit_section "Cross-Agent" "$CROSS_AGENT_BODY"
emit_section "Siblings" "$SIBLINGS_BODY"

ORPHANS_TRIMMED=$(trim "$ORPHANS_BODY")
if [ -n "$ORPHANS_TRIMMED" ]; then
  printf '\n**Orphans**\n'
  printf '%s\n' "$ORPHANS_BODY" | indent
fi

if [ "$UPDATE_AVAILABLE" = "1" ]; then
  printf '\n**Update:** v%s -> v%s (`npm i -g @anthropic-ai/claude-code@latest`)\n' \
    "$(trim "$RELEASE_CURRENT")" "$(trim "$RELEASE_LATEST")"
fi

printf '\n**Next:** %s\n' "$NEXT"
