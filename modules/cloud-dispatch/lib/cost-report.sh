#!/usr/bin/env bash
# cost-report.sh — Generate cost reports for CCGM cloud-dispatch sessions.
#
# Usage:
#   cost-report.sh session [--json]
#   cost-report.sh monthly [--json]
#
# Subcommands:
#   session   Report for the current or last completed session.
#   monthly   Report for the current calendar month.
#
# Flags:
#   --json    Output machine-readable JSON instead of formatted text.
#
# Reads from:
#   /tmp/ccgm-budget.json         Current or last session data
#   /tmp/ccgm-budget-monthly.json Monthly session log
#
# Requires: jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BUDGET_FILE="${CCGM_BUDGET_FILE:-/tmp/ccgm-budget.json}"
MONTHLY_FILE="${CCGM_MONTHLY_FILE:-/tmp/ccgm-budget-monthly.json}"
MONTHLY_BUDGET_USD="${CCGM_MONTHLY_BUDGET:-2000}"
CLAUDE_MAX_USD="${CCGM_CLAUDE_MAX_USD:-200}"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: $0 <session|monthly> [--json]" >&2
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

SUBCOMMAND="$1"
shift

JSON_OUTPUT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    *)
      log_error "Unknown argument: $1"
      usage
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
require_cmd jq

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# month_label — "Month YYYY" format for display
month_label() {
  date -u +"%B %Y"
}

# current_month — YYYY-MM
current_month() {
  date -u +"%Y-%m"
}

# safe_jq <filter> <file> <default> — run jq filter and return default on failure
safe_jq() {
  local filter="$1"
  local file="$2"
  local default="${3:-0}"
  jq -r "${filter}" "${file}" 2>/dev/null || echo "${default}"
}

# py_calc <expr> — evaluate a Python arithmetic expression and print result
py_calc() {
  python3 -c "print(round(${1}, 2))" 2>/dev/null || echo "0"
}

# duration_label <hours_float> — convert decimal hours to human-readable string
duration_label() {
  python3 -c "
h = float('${1}')
hours = int(h)
mins = int((h - hours) * 60)
if hours > 0:
    print(f'{hours}h {mins}m')
else:
    print(f'{mins}m')
" 2>/dev/null || echo "${1}h"
}

# ---------------------------------------------------------------------------
# Compute session-level stats from a session JSON object
# Returns a JSON object with derived fields
# ---------------------------------------------------------------------------
session_stats() {
  local session_json="$1"

  # Extract base fields
  local sid started_at stopped_at vm_count vm_hours_total cost
  sid=$(echo "${session_json}"           | jq -r '.session_id // "unknown"')
  started_at=$(echo "${session_json}"    | jq -r '.started_at // ""')
  stopped_at=$(echo "${session_json}"    | jq -r '.stopped_at // ""')
  vm_count=$(echo "${session_json}"      | jq '.vms | length')
  vm_hours_total=$(echo "${session_json}" | jq '.vm_hours_total // 0')
  cost=$(echo "${session_json}"          | jq '.estimated_cost_usd // 0')

  # Compute wall-clock duration
  local duration_hours="0"
  if [[ -n "${started_at}" && -n "${stopped_at}" ]]; then
    duration_hours=$(python3 -c "
from datetime import datetime, timezone
def parse(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))
try:
    s = parse('${started_at}')
    e = parse('${stopped_at}')
    print(round((e - s).total_seconds() / 3600, 3))
except Exception:
    print(0)
" 2>/dev/null || echo "0")
  fi

  # VM breakdown
  local vm_breakdown
  vm_breakdown=$(echo "${session_json}" | jq -c '[.vms[] | {name: .name, type: .type, hourly_rate: .hourly_rate}]')

  jq -n \
    --arg sid "${sid}" \
    --arg started_at "${started_at}" \
    --arg stopped_at "${stopped_at}" \
    --argjson vm_count "${vm_count}" \
    --argjson vm_hours "${vm_hours_total}" \
    --argjson cost "${cost}" \
    --argjson duration "${duration_hours}" \
    --argjson vms "${vm_breakdown}" \
    '{
      session_id: $sid,
      started_at: $started_at,
      stopped_at: $stopped_at,
      vm_count: $vm_count,
      vm_hours_total: $vm_hours,
      estimated_cost_usd: $cost,
      duration_hours: $duration,
      vms: $vms
    }'
}

# ---------------------------------------------------------------------------
# Subcommand: session
# ---------------------------------------------------------------------------
cmd_session() {
  local session_json

  if [[ -f "${BUDGET_FILE}" ]]; then
    # Active session
    session_json=$(cat "${BUDGET_FILE}")
    local is_active=true

    # For active sessions, compute running cost from current time
    local now_ts
    now_ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local running_cost
    running_cost=$(echo "${session_json}" | jq --arg now "${now_ts}" '
      [.vms[] |
        ((($now | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime) -
          (.started_at | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime)) / 3600) * .hourly_rate
      ] | add // 0
    ' 2>/dev/null || echo "0")

    session_json=$(echo "${session_json}" | jq --argjson cost "${running_cost}" '.estimated_cost_usd = $cost')
  elif [[ -f "${MONTHLY_FILE}" ]]; then
    # Use last completed session
    session_json=$(jq '.sessions[-1]' "${MONTHLY_FILE}" 2>/dev/null || echo "null")
    if [[ "${session_json}" == "null" ]]; then
      log_warn "No session data found."
      exit 0
    fi
    local is_active=false
  else
    log_warn "No session data found. Run 'budget-track.sh start' to begin tracking."
    exit 0
  fi

  local stats
  stats=$(session_stats "${session_json}")

  if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "${stats}"
    return
  fi

  # Human-readable output
  local sid vm_count vm_hours cost duration
  sid=$(echo "${stats}"      | jq -r '.session_id')
  vm_count=$(echo "${stats}" | jq '.vm_count')
  vm_hours=$(echo "${stats}" | jq '.vm_hours_total')
  cost=$(echo "${stats}"     | jq '.estimated_cost_usd')
  duration=$(echo "${stats}" | jq '.duration_hours')

  local duration_str
  duration_str=$(duration_label "${duration}")

  echo "=== CCGM Cloud Dispatch - Session Report ==="
  printf "Session ID:    %s\n" "${sid}"

  if [[ "${is_active}" == "true" ]]; then
    printf "Status:        ACTIVE (running)\n"
  else
    printf "Status:        Completed\n"
  fi

  printf "Duration:      %s\n" "${duration_str}"
  printf "VMs active:    %s\n" "${vm_count}"
  printf "VM-hours:      %.2f\n" "${vm_hours}"
  printf "Session cost:  \$%.2f\n" "${cost}"

  # VM breakdown
  local vm_entries
  vm_entries=$(echo "${stats}" | jq -r '.vms[] | "  \(.name) (\(.type)): \$\(.hourly_rate)/hr"')
  if [[ -n "${vm_entries}" ]]; then
    echo ""
    echo "VM Breakdown:"
    echo "${vm_entries}"
  fi
}

# ---------------------------------------------------------------------------
# Subcommand: monthly
# ---------------------------------------------------------------------------
cmd_monthly() {
  if [[ ! -f "${MONTHLY_FILE}" ]]; then
    log_warn "No monthly data found at ${MONTHLY_FILE}."
    exit 0
  fi

  # Aggregate session stats
  local session_count avg_duration_hours total_vm_hours total_vm_cost
  session_count=$(jq '.sessions | length' "${MONTHLY_FILE}")
  total_vm_hours=$(jq '[.sessions[].vm_hours_total // 0] | add // 0' "${MONTHLY_FILE}")
  total_vm_cost=$(jq '[.sessions[].estimated_cost_usd // 0] | add // 0' "${MONTHLY_FILE}")

  if [[ "${session_count}" -gt 0 ]]; then
    avg_duration_hours=$(python3 -c "print(round(${total_vm_hours} / ${session_count}, 2))" 2>/dev/null || echo "0")
  else
    avg_duration_hours="0"
  fi

  # Count total issues dispatched (sum of VM counts across sessions as proxy)
  local issues_dispatched
  issues_dispatched=$(jq '[.sessions[] | (.vms | length)] | add // 0' "${MONTHLY_FILE}")

  # Total cost including Claude subscription
  local total_cost
  total_cost=$(py_calc "${total_vm_cost} + ${CLAUDE_MAX_USD}")

  # Budget utilization
  local budget_remaining budget_pct_used
  budget_remaining=$(py_calc "${MONTHLY_BUDGET_USD} - ${total_cost}")
  budget_pct_used=$(python3 -c "print(round(${total_cost} / ${MONTHLY_BUDGET_USD} * 100, 1))" 2>/dev/null || echo "0")

  # Cost per issue
  local cost_per_issue="N/A"
  if [[ "${issues_dispatched}" -gt 0 ]]; then
    cost_per_issue=$(python3 -c "print(f'\${round(${total_vm_cost} / ${issues_dispatched}, 2)}')" 2>/dev/null || echo "N/A")
  fi

  # Month-end projection based on days elapsed
  local month_days_total month_days_elapsed projected_cost
  month_days_total=$(python3 -c "
from datetime import datetime, timezone
import calendar
now = datetime.now(timezone.utc)
print(calendar.monthrange(now.year, now.month)[1])
" 2>/dev/null || echo "30")

  month_days_elapsed=$(python3 -c "
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
print(max(1, now.day))
" 2>/dev/null || echo "1")

  projected_cost=$(python3 -c "
print(round(${total_cost} / ${month_days_elapsed} * ${month_days_total}, 2))
" 2>/dev/null || echo "0")

  # Per-session type breakdown (by server type)
  local type_breakdown
  type_breakdown=$(jq -r '
    [.sessions[].vms[]] |
    group_by(.type) |
    map({type: .[0].type, count: length, rate: .[0].hourly_rate}) |
    .[] |
    "  \(.type): \(.count) VM-slot(s) @ $\(.rate)/hr"
  ' "${MONTHLY_FILE}" 2>/dev/null || true)

  if [[ "${JSON_OUTPUT}" == "true" ]]; then
    jq -n \
      --arg month "$(current_month)" \
      --argjson sessions "${session_count}" \
      --argjson issues "${issues_dispatched}" \
      --argjson vm_hours "${total_vm_hours}" \
      --argjson vm_cost "${total_vm_cost}" \
      --argjson claude_cost "${CLAUDE_MAX_USD}" \
      --argjson total "${total_cost}" \
      --argjson remaining "${budget_remaining}" \
      --argjson budget "${MONTHLY_BUDGET_USD}" \
      --argjson projected "${projected_cost}" \
      --argjson pct "${budget_pct_used}" \
      '{
        month: $month,
        session_count: $sessions,
        issues_dispatched: $issues,
        vm_hours_total: $vm_hours,
        vm_cost_usd: $vm_cost,
        claude_subscription_usd: $claude_cost,
        total_cost_usd: $total,
        budget_usd: $budget,
        budget_remaining_usd: $remaining,
        budget_pct_used: $pct,
        projected_month_end_usd: $projected
      }'
    return
  fi

  # Human-readable output
  local month_lbl
  month_lbl=$(month_label)

  echo "=== CCGM Cloud Dispatch - Cost Report ==="
  printf "Month:                  %s\n" "${month_lbl}"
  printf "Sessions:               %s\n" "${session_count}"
  printf "Issues dispatched:      %s\n" "${issues_dispatched}"
  printf "Total VM-hours:         %.1f\n" "${total_vm_hours}"

  if [[ "${session_count}" -gt 0 ]]; then
    local avg_str
    avg_str=$(duration_label "${avg_duration_hours}")
    printf "Avg session duration:   %s\n" "${avg_str}"
  fi

  echo ""
  printf "Total VM cost:          \$%.2f\n" "${total_vm_cost}"
  printf "Claude Max subscription:\$%.2f\n" "${CLAUDE_MAX_USD}"
  printf "Estimated total:        \$%.2f\n" "${total_cost}"
  echo ""
  printf "Budget:                 \$%s\n" "${MONTHLY_BUDGET_USD}"
  printf "Budget used:            %.1f%%\n" "${budget_pct_used}"
  printf "Budget remaining:       \$%.2f\n" "${budget_remaining}"
  printf "Projected month-end:    \$%.2f\n" "${projected_cost}"

  if [[ "${cost_per_issue}" != "N/A" ]]; then
    echo ""
    printf "Cost per issue (VM):    %s\n" "${cost_per_issue}"
  fi

  if [[ -n "${type_breakdown}" ]]; then
    echo ""
    echo "VM Type Usage:"
    echo "${type_breakdown}"
  fi

  # Budget warning
  if python3 -c "exit(0 if ${budget_pct_used} >= 80 else 1)" 2>/dev/null; then
    echo ""
    log_warn "Budget utilization is ${budget_pct_used}%. Consider reviewing dispatch frequency."
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${SUBCOMMAND}" in
  session) cmd_session ;;
  monthly) cmd_monthly ;;
  *)
    log_error "Unknown subcommand: ${SUBCOMMAND}"
    usage
    ;;
esac
