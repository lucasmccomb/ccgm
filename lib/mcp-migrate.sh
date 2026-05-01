#!/usr/bin/env bash
# Migrate ~/.claude/mcp.json (legacy, unread by current Claude Code) to ~/.claude.json
# via the `claude mcp add-json --scope user` CLI.
#
# Idempotent: entries that already exist (per `claude mcp get`) are skipped.
# Backs up the legacy file with a .migrated.bak suffix on success.

set -euo pipefail

LEGACY_FILE="${1:-${HOME}/.claude/mcp.json}"

c_red=$'\033[0;31m'
c_grn=$'\033[0;32m'
c_ylw=$'\033[0;33m'
c_dim=$'\033[2m'
c_rst=$'\033[0m'

log_info()  { printf '%s\n' "$*"; }
log_ok()    { printf '%s%s%s\n' "$c_grn" "$*" "$c_rst"; }
log_warn()  { printf '%s%s%s\n' "$c_ylw" "$*" "$c_rst"; }
log_err()   { printf '%s%s%s\n' "$c_red" "$*" "$c_rst" >&2; }

if ! command -v claude &>/dev/null; then
  log_err "ERROR: 'claude' CLI not found on PATH; install Claude Code first."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  log_err "ERROR: 'jq' required for MCP migration."
  exit 1
fi

if [ ! -f "$LEGACY_FILE" ]; then
  log_info "${c_dim}No legacy MCP file at $LEGACY_FILE - nothing to migrate.${c_rst}"
  exit 0
fi

if ! jq empty "$LEGACY_FILE" 2>/dev/null; then
  log_err "ERROR: $LEGACY_FILE is not valid JSON; aborting."
  exit 1
fi

server_count=$(jq -r '.mcpServers // {} | length' "$LEGACY_FILE")
if [ "$server_count" -eq 0 ]; then
  log_info "${c_dim}$LEGACY_FILE has no mcpServers entries - nothing to migrate.${c_rst}"
  exit 0
fi

log_info "Found $server_count server entries in $LEGACY_FILE"
log_info ""

migrated=0
skipped=0
failed=0
failed_names=()

# Resolve ${VAR} references against the current environment.
# Only substitutes simple ${NAME} forms; leaves $NAME or unset references alone
# (claude mcp will record the literal, which the user can fix later).
expand_env_refs() {
  local input="$1"
  python3 -c '
import os, re, sys
def repl(m):
    name = m.group(1)
    return os.environ.get(name, m.group(0))
text = sys.stdin.read()
print(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, text), end="")
' <<< "$input"
}

while IFS= read -r name; do
  [ -z "$name" ] && continue

  if claude mcp get "$name" &>/dev/null; then
    log_info "${c_dim}skip${c_rst}     $name (already registered)"
    skipped=$((skipped + 1))
    continue
  fi

  raw=$(jq -c --arg n "$name" '.mcpServers[$n]' "$LEGACY_FILE")

  # Add a "type" field if the legacy entry omits it. Heuristic: url -> sse, command -> stdio.
  shaped=$(jq -c '
    if has("type") then .
    elif has("url") then .type = "sse"
    elif has("command") then .type = "stdio"
    else .
    end' <<< "$raw")

  expanded=$(expand_env_refs "$shaped")

  if claude mcp add-json --scope user "$name" "$expanded" >/dev/null 2>&1; then
    log_ok "migrate  $name"
    migrated=$((migrated + 1))
  else
    log_err "FAILED   $name"
    log_err "         payload: $expanded"
    failed=$((failed + 1))
    failed_names+=("$name")
  fi
done < <(jq -r '.mcpServers // {} | keys[]' "$LEGACY_FILE")

log_info ""
log_info "Summary: ${c_grn}${migrated} migrated${c_rst}, ${c_dim}${skipped} skipped${c_rst}, ${c_red}${failed} failed${c_rst}"

if [ "$failed" -eq 0 ]; then
  backup="${LEGACY_FILE}.migrated.bak"
  mv "$LEGACY_FILE" "$backup"
  log_info ""
  log_ok "Legacy file moved to: $backup"
  log_info "Verify with 'claude mcp list', then delete the backup when satisfied."
else
  log_info ""
  log_warn "Legacy file kept in place because ${failed} entries failed to migrate."
  log_warn "Failed: ${failed_names[*]}"
  log_warn "Re-run after resolving, or migrate those entries by hand:"
  log_warn "  claude mcp add-json --scope user <name> '<json>'"
  exit 1
fi
