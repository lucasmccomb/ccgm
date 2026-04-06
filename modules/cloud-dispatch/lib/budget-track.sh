#!/usr/bin/env bash
# budget-track.sh — Track VM costs for CCGM cloud-dispatch sessions.
#
# Usage:
#   budget-track.sh start
#   budget-track.sh stop
#   budget-track.sh status
#   budget-track.sh report
#
# Subcommands:
#   start   Record session start time and active VM details to BUDGET_FILE.
#   stop    Finalize session cost and append to MONTHLY_FILE.
#   status  Print current session runtime and running cost estimate.
#   report  Print full cost report for the current month.
#
# State files:
#   /tmp/ccgm-budget.json         Current session data
#   /tmp/ccgm-budget-monthly.json Monthly session log (append-only array)
#
# Hourly rates (USD, approximate EUR->USD at 1.08):
#   CCX63: $0.58/hr  (48 vCPU, 192 GB)
#   CCX43: $0.28/hr  (16 vCPU,  64 GB)
#   CCX33: $0.20/hr  ( 8 vCPU,  32 GB)
#
# Requires: jq, hcloud (for start subcommand)

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

# Hourly rates by server type (USD)
declare -A HOURLY_RATES=(
  [ccx63]="0.58"
  [ccx43]="0.28"
  [ccx33]="0.20"
)
DEFAULT_RATE="0.58"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: $0 <start|stop|status|report>" >&2
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

SUBCOMMAND="$1"
shift

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

require_cmd jq

# hourly_rate <server-type> — print the USD/hr rate for a given server type
hourly_rate() {
  local stype
  stype=$(echo "$1" | tr '[:upper:]' '[:lower:]')
  echo "${HOURLY_RATES[$stype]:-${DEFAULT_RATE}}"
}

# now_iso — current UTC time in ISO 8601 format
now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# now_epoch — current time as Unix epoch seconds
now_epoch() {
  date +%s
}

# iso_to_epoch <iso-string> — convert ISO 8601 UTC string to epoch seconds
iso_to_epoch() {
  python3 -c "
from datetime import datetime, timezone
s = '$1'.replace('Z', '+00:00')
try:
    dt = datetime.fromisoformat(s)
    print(int(dt.timestamp()))
except Exception:
    print(0)
"
}

# elapsed_human <start_epoch> — return human-readable elapsed time
elapsed_human() {
  local start="$1"
  local now
  now=$(now_epoch)
  local total=$(( now - start ))
  local h=$(( total / 3600 ))
  local m=$(( (total % 3600) / 60 ))
  if [[ ${h} -gt 0 ]]; then
    echo "${h}h ${m}m"
  else
    echo "${m}m"
  fi
}

# session_id — generate a session ID from current timestamp
session_id() {
  date -u +"%Y%m%d-%H%M%S"
}

# current_month — YYYY-MM
current_month() {
  date -u +"%Y-%m"
}

# month_label — "Month YYYY" format for display
month_label() {
  date -u +"%B %Y"
}

# ---------------------------------------------------------------------------
# Subcommand: start
# ---------------------------------------------------------------------------
cmd_start() {
  require_cmd hcloud

  if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
    log_error "HCLOUD_TOKEN is not set. Cannot list VMs."
    exit 1
  fi

  log_info "Scanning for running ccgm-agent-* VMs..."

  # Collect VM details via hcloud
  local vm_json
  vm_json=$(hcloud server list --output json 2>/dev/null \
    | python3 -c "
import json, sys
servers = json.load(sys.stdin)
result = []
for s in servers:
    name = s.get('name', '')
    if not name.startswith('ccgm-agent'):
        continue
    if s.get('status', '') != 'running':
        continue
    stype = ''
    st = s.get('server_type', {})
    if st:
        stype = st.get('name', '')
    created = s.get('created', '')
    result.append({'name': name, 'type': stype, 'started_at': created})
print(json.dumps(result))
" 2>/dev/null || echo "[]")

  local sid
  sid=$(session_id)
  local ts
  ts=$(now_iso)

  # Build per-VM entries with hourly rates using jq
  local rate_map_json
  rate_map_json=$(jq -n \
    --argjson ccx63 "${HOURLY_RATES[ccx63]:-${DEFAULT_RATE}}" \
    --argjson ccx43 "${HOURLY_RATES[ccx43]:-${DEFAULT_RATE}}" \
    --argjson ccx33 "${HOURLY_RATES[ccx33]:-${DEFAULT_RATE}}" \
    '{ccx63: $ccx63, ccx43: $ccx43, ccx33: $ccx33}')

  local default_rate="${DEFAULT_RATE}"
  local vms_json
  vms_json=$(echo "${vm_json}" | jq \
    --argjson rates "${rate_map_json}" \
    --argjson default_rate "${default_rate}" \
    --arg fallback_ts "${ts}" \
    '[.[] | {
       name: .name,
       type: (.type | ascii_downcase),
       hourly_rate: ($rates[(.type | ascii_downcase)] // $default_rate),
       started_at: (if .started_at == "" or .started_at == null then $fallback_ts else .started_at end)
     }]' 2>/dev/null || echo "[]")

  jq -n \
    --arg sid "${sid}" \
    --arg ts "${ts}" \
    --argjson vms "${vms_json}" \
    '{
      session_id: $sid,
      started_at: $ts,
      vms: $vms,
      vm_hours_total: 0,
      estimated_cost_usd: 0
    }' > "${BUDGET_FILE}"

  local vm_count
  vm_count=$(jq '.vms | length' "${BUDGET_FILE}")
  log_success "Session ${sid} started. Tracking ${vm_count} VM(s)."
  echo "  Budget file: ${BUDGET_FILE}"
}

# ---------------------------------------------------------------------------
# Subcommand: stop
# ---------------------------------------------------------------------------
cmd_stop() {
  if [[ ! -f "${BUDGET_FILE}" ]]; then
    log_error "No active session found at ${BUDGET_FILE}. Run 'start' first."
    exit 1
  fi

  local now_ts
  now_ts=$(now_iso)

  # Calculate total VM-hours and cost
  local total_hours total_cost
  total_hours=$(jq --arg now "${now_ts}" '
    [.vms[] |
      (($now | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime) -
       (.started_at | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime)) / 3600
    ] | add // 0
  ' "${BUDGET_FILE}" 2>/dev/null || echo "0")

  total_cost=$(jq --arg now "${now_ts}" '
    [.vms[] |
      ((($now | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime) -
        (.started_at | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime)) / 3600) * .hourly_rate
    ] | add // 0
  ' "${BUDGET_FILE}" 2>/dev/null || echo "0")

  # Update session file with final values
  local session_data
  session_data=$(jq \
    --arg stopped "${now_ts}" \
    --argjson hours "${total_hours}" \
    --argjson cost "${total_cost}" \
    '. + {stopped_at: $stopped, vm_hours_total: $hours, estimated_cost_usd: $cost}' \
    "${BUDGET_FILE}")

  # Append to monthly log
  local month
  month=$(current_month)

  if [[ ! -f "${MONTHLY_FILE}" ]]; then
    echo '{"sessions": []}' > "${MONTHLY_FILE}"
  fi

  jq --argjson entry "${session_data}" --arg month "${month}" \
    '.sessions += [$entry] | .last_updated = now | .month = $month' \
    "${MONTHLY_FILE}" > "${MONTHLY_FILE}.tmp" && mv "${MONTHLY_FILE}.tmp" "${MONTHLY_FILE}"

  # Print session summary
  local sid
  sid=$(jq -r '.session_id' "${BUDGET_FILE}")
  printf "\nSession %s complete.\n" "${sid}"
  printf "  VM-hours:  %.2f\n" "${total_hours}"
  printf "  Cost:      \$%.2f\n" "${total_cost}"
  printf "  Saved to:  %s\n\n" "${MONTHLY_FILE}"

  # Clean up session file
  rm -f "${BUDGET_FILE}"
}

# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------
cmd_status() {
  if [[ ! -f "${BUDGET_FILE}" ]]; then
    log_warn "No active session. Run 'start' to begin tracking."
    exit 0
  fi

  local started_at
  started_at=$(jq -r '.started_at' "${BUDGET_FILE}")
  local start_ep
  start_ep=$(iso_to_epoch "${started_at}")
  local elapsed
  elapsed=$(elapsed_human "${start_ep}")

  local vm_count
  vm_count=$(jq '.vms | length' "${BUDGET_FILE}")

  # Running cost: sum of (elapsed_hours * hourly_rate) per VM
  local now_ts
  now_ts=$(now_iso)
  local running_cost
  running_cost=$(jq --arg now "${now_ts}" '
    [.vms[] |
      ((($now | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime) -
        (.started_at | gsub("Z$";"") | strptime("%Y-%m-%dT%H:%M:%S") | mktime)) / 3600) * .hourly_rate
    ] | add // 0
  ' "${BUDGET_FILE}" 2>/dev/null || echo "0")

  local hourly_rate_total
  hourly_rate_total=$(jq '[.vms[].hourly_rate] | add // 0' "${BUDGET_FILE}")

  # Monthly stats
  local monthly_total="0"
  if [[ -f "${MONTHLY_FILE}" ]]; then
    monthly_total=$(jq '[.sessions[].estimated_cost_usd // 0] | add // 0' "${MONTHLY_FILE}" 2>/dev/null || echo "0")
  fi

  # Session-hours so far (for monthly projection)
  local month_seconds_elapsed
  month_seconds_elapsed=$(python3 -c "
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
import calendar
days_in_month = calendar.monthrange(now.year, now.month)[1]
day = now.day + now.hour/24.0
print(int(day / days_in_month * 86400 * days_in_month))
" 2>/dev/null || echo "1")

  local month_seconds_total
  month_seconds_total=$(python3 -c "
from datetime import datetime, timezone
import calendar
now = datetime.now(timezone.utc)
days_in_month = calendar.monthrange(now.year, now.month)[1]
print(days_in_month * 86400)
" 2>/dev/null || echo "2592000")

  local grand_total
  grand_total=$(python3 -c "print(round(${monthly_total} + ${running_cost}, 2))" 2>/dev/null || echo "${monthly_total}")

  local projected
  projected=$(python3 -c "
elapsed = ${month_seconds_elapsed}
total = ${month_seconds_total}
spent = ${grand_total}
if elapsed > 0:
    print(round(spent / elapsed * total, 2))
else:
    print(0)
" 2>/dev/null || echo "0")

  printf "Session: %s | VMs: %s | Rate: \$%.2f/hr | Session cost: \$%.2f\n" \
    "${elapsed}" "${vm_count}" "${hourly_rate_total}" "${running_cost}"
  printf "Monthly total: \$%.2f (est. \$%.2f/mo at current pace)\n" \
    "${grand_total}" "${projected}"
}

# ---------------------------------------------------------------------------
# Subcommand: report
# ---------------------------------------------------------------------------
cmd_report() {
  local month_label
  month_label=$(month_label)

  echo "=== CCGM Cloud Dispatch - Cost Report ==="
  echo "Month: ${month_label}"

  if [[ ! -f "${MONTHLY_FILE}" ]]; then
    echo "No session data found for this month."
    exit 0
  fi

  # Session stats
  local session_count total_vm_hours total_vm_cost issues_completed
  session_count=$(jq '.sessions | length' "${MONTHLY_FILE}")
  total_vm_hours=$(jq '[.sessions[].vm_hours_total // 0] | add // 0' "${MONTHLY_FILE}")
  total_vm_cost=$(jq '[.sessions[].estimated_cost_usd // 0] | add // 0' "${MONTHLY_FILE}")

  # Count issues (vms * agents * sessions as a proxy - sum vm counts per session)
  issues_completed=$(jq '[.sessions[] | (.vms | length)] | add // 0' "${MONTHLY_FILE}")

  local total_cost
  total_cost=$(python3 -c "print(round(${total_vm_cost} + ${CLAUDE_MAX_USD}, 2))" 2>/dev/null || echo "${total_vm_cost}")

  local budget_remaining
  budget_remaining=$(python3 -c "print(round(${MONTHLY_BUDGET_USD} - ${total_cost}, 2))" 2>/dev/null || echo "0")

  # Projection
  local month_seconds_total
  month_seconds_total=$(python3 -c "
from datetime import datetime, timezone
import calendar
now = datetime.now(timezone.utc)
days_in_month = calendar.monthrange(now.year, now.month)[1]
print(days_in_month * 86400)
" 2>/dev/null || echo "2592000")

  local month_seconds_elapsed
  month_seconds_elapsed=$(python3 -c "
from datetime import datetime, timezone
import calendar
now = datetime.now(timezone.utc)
days_in_month = calendar.monthrange(now.year, now.month)[1]
elapsed = (now.day - 1) * 86400 + now.hour * 3600 + now.minute * 60 + now.second
print(max(1, elapsed))
" 2>/dev/null || echo "86400")

  local projected
  projected=$(python3 -c "
elapsed = ${month_seconds_elapsed}
total = ${month_seconds_total}
spent = ${total_cost}
print(round(spent / elapsed * total, 2))
" 2>/dev/null || echo "0")

  printf "Sessions:               %s\n" "${session_count}"
  printf "Total VM-hours:         %.1f\n" "${total_vm_hours}"
  printf "Total VM cost:          \$%.2f\n" "${total_vm_cost}"
  printf "Claude Max subscription:\$%.2f\n" "${CLAUDE_MAX_USD}"
  printf "Estimated total:        \$%.2f\n" "${total_cost}"
  printf "Budget remaining:       \$%.2f (of \$%s)\n" "${budget_remaining}" "${MONTHLY_BUDGET_USD}"
  printf "Projected month-end:    \$%.2f\n" "${projected}"

  # Cost per issue (if any completed)
  if [[ "${issues_completed}" -gt 0 && $(python3 -c "print(1 if ${total_cost} > 0 else 0)") == "1" ]]; then
    local cost_per_issue
    cost_per_issue=$(python3 -c "print(round(${total_vm_cost} / ${issues_completed}, 2))" 2>/dev/null || echo "N/A")
    printf "Cost per issue (VM):    \$%s\n" "${cost_per_issue}"
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${SUBCOMMAND}" in
  start)  cmd_start  ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  report) cmd_report ;;
  *)
    log_error "Unknown subcommand: ${SUBCOMMAND}"
    usage
    ;;
esac
