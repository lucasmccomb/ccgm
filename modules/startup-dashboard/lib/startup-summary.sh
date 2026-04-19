#!/usr/bin/env bash
# startup-summary.sh - Intelligent summary for /startup.
# Pipeline: startup-gather.sh → claude -p (sonnet) → markdown summary.
# Falls back to the deterministic startup-dashboard.sh whenever the model
# pipeline is unavailable or produces empty output.
#
# Usage: bash startup-summary.sh [--raw]
#   --raw : skip the model pipeline, emit the deterministic dashboard directly.

set -u

GATHER_SCRIPT="${CCGM_GATHER_SCRIPT:-$HOME/.claude/lib/startup-gather.sh}"
DASHBOARD_SCRIPT="${CCGM_DASHBOARD_SCRIPT:-$HOME/.claude/lib/startup-dashboard.sh}"
PROMPT_FILE="${CCGM_SUMMARY_PROMPT:-$HOME/.claude/lib/startup-summary-prompt.md}"
SUMMARY_MODEL="${CCGM_SUMMARY_MODEL:-sonnet}"

run_dashboard() {
  if [ -x "$(command -v bash)" ] && [ -f "$DASHBOARD_SCRIPT" ]; then
    bash "$DASHBOARD_SCRIPT"
  else
    echo "startup-summary: dashboard fallback unavailable" >&2
    return 1
  fi
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

# Claude -p reads the prompt from stdin when no prompt argv is given.
# Combine the summary instructions with the gather output as one stream.
SUMMARY=$(cat "$PROMPT_FILE" "$TMPGATHER" 2>/dev/null \
  | claude --model "$SUMMARY_MODEL" --no-session-persistence -p 2>/dev/null)

if [ -z "$SUMMARY" ]; then
  echo "startup-summary: model pipeline returned empty; falling back to dashboard" >&2
  run_dashboard
  exit $?
fi

printf '%s\n' "$SUMMARY"
