#!/usr/bin/env bash
# startup-summary.sh - Intelligent summary for /startup.
#
# Fallback chain (each step runs only if the previous failed or was empty):
#   1. macOS Keychain → direct Anthropic API call (cheap, ~$0.015/run)
#   2. claude -p subprocess (loads CLI harness, ~$0.16/run, no setup needed)
#   3. Deterministic startup-dashboard.sh (no model tokens)
#
# To enable the cheap path, store your API key in Keychain once:
#   security add-generic-password -s ccgm-anthropic-api-key -a "$USER" -w <sk-ant-...>
# The script never exports ANTHROPIC_API_KEY to the parent shell, so new
# `claude` sessions continue to use Max / subscription auth.
#
# Usage: bash startup-summary.sh [--raw]
#   --raw : skip the model pipeline, emit the deterministic dashboard directly.

set -u

GATHER_SCRIPT="${CCGM_GATHER_SCRIPT:-$HOME/.claude/lib/startup-gather.sh}"
DASHBOARD_SCRIPT="${CCGM_DASHBOARD_SCRIPT:-$HOME/.claude/lib/startup-dashboard.sh}"
PROMPT_FILE="${CCGM_SUMMARY_PROMPT:-$HOME/.claude/lib/startup-summary-prompt.md}"
SUMMARY_MODEL="${CCGM_SUMMARY_MODEL:-sonnet}"
SUMMARY_MODEL_API="${CCGM_SUMMARY_MODEL_API:-claude-sonnet-4-6}"
KEYCHAIN_SERVICE="${CCGM_KEYCHAIN_SERVICE:-ccgm-anthropic-api-key}"

run_dashboard() {
  if [ -x "$(command -v bash)" ] && [ -f "$DASHBOARD_SCRIPT" ]; then
    bash "$DASHBOARD_SCRIPT"
  else
    echo "startup-summary: dashboard fallback unavailable" >&2
    return 1
  fi
}

# Try the cheap path: Keychain lookup → direct Anthropic API via curl.
# Returns the summary on stdout if successful; empty stdout on any failure.
# Never exports ANTHROPIC_API_KEY to the parent shell.
try_direct_api() {
  command -v security >/dev/null 2>&1 || return 1
  command -v curl >/dev/null 2>&1 || return 1
  command -v jq >/dev/null 2>&1 || return 1

  local api_key
  api_key=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null) || return 1
  [ -z "$api_key" ] && return 1

  local prompt_content
  prompt_content=$(cat "$PROMPT_FILE" "$1" 2>/dev/null)
  [ -z "$prompt_content" ] && return 1

  local payload
  payload=$(jq -nc \
    --arg m "$SUMMARY_MODEL_API" \
    --arg p "$prompt_content" \
    '{model: $m, max_tokens: 1500, messages: [{role: "user", content: $p}]}' 2>/dev/null) || return 1

  local response
  response=$(printf '%s' "$payload" | curl -sS --max-time 30 \
    https://api.anthropic.com/v1/messages \
    -H "x-api-key: $api_key" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d @- 2>/dev/null) || return 1

  [ -z "$response" ] && return 1

  local text
  text=$(printf '%s' "$response" | jq -r '.content[0].text // empty' 2>/dev/null)
  [ -z "$text" ] && return 1

  printf '%s' "$text"
}

# --raw skips the model pipeline entirely.
if [ "${1:-}" = "--raw" ]; then
  exec bash "$DASHBOARD_SCRIPT"
fi

# If any input is missing, fall back to the dashboard.
if ! command -v claude >/dev/null 2>&1; then
  run_dashboard
  exit $?
fi
if [ ! -f "$GATHER_SCRIPT" ] || [ ! -f "$PROMPT_FILE" ]; then
  run_dashboard
  exit $?
fi

TMPGATHER=$(mktemp -t ccgm-startup-gather.XXXXXX)
trap "rm -f $TMPGATHER" EXIT

bash "$GATHER_SCRIPT" > "$TMPGATHER" 2>/dev/null
if [ ! -s "$TMPGATHER" ]; then
  run_dashboard
  exit $?
fi

# Path 1: Keychain → direct Anthropic API (cheap).
SUMMARY=$(try_direct_api "$TMPGATHER")

# Path 2: claude -p subprocess (loads CLI harness, no setup required).
if [ -z "$SUMMARY" ]; then
  SUMMARY=$(cat "$PROMPT_FILE" "$TMPGATHER" 2>/dev/null \
    | claude --model "$SUMMARY_MODEL" --no-session-persistence -p 2>/dev/null)
fi

# Path 3: deterministic dashboard fallback.
if [ -z "$SUMMARY" ]; then
  echo "startup-summary: model pipeline returned empty; falling back to dashboard" >&2
  run_dashboard
  exit $?
fi

printf '%s\n' "$SUMMARY"
