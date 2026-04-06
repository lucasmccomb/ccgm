#!/usr/bin/env bash
# agent-status.sh — Report the status of one or all Claude Code agents.
#
# Usage:
#   agent-status.sh --all
#   agent-status.sh <vm-ip> <agent-index>
#
# Output per agent:
#   VM: ccgm-agent-fsn1-0 | Agent: agent-0 | Status: running | Issue: #42
#   Last log: "Creating PR for branch 42-habit-streaks..."
#   Duration: 23m
#
# Requires:
#   - hcloud CLI (when --all is used)
#   - SSH key in ~/.ssh/ccgm-dispatch-session or $SSH_KEY_PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 --all" >&2
  echo "       $0 <vm-ip> <agent-index>" >&2
  exit 1
fi

STATUS_ALL=false
VM_IP=""
AGENT_INDEX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      STATUS_ALL=true
      shift
      ;;
    -*)
      log_error "Unknown option: $1"
      exit 1
      ;;
    *)
      if [[ -z "${VM_IP}" ]]; then
        VM_IP="$1"
      elif [[ -z "${AGENT_INDEX}" ]]; then
        AGENT_INDEX="$1"
      else
        log_error "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ "${STATUS_ALL}" == "false" ]]; then
  if [[ -z "${VM_IP}" || -z "${AGENT_INDEX}" ]]; then
    log_error "Provide --all or both <vm-ip> and <agent-index>"
    exit 1
  fi
  if ! [[ "${AGENT_INDEX}" =~ ^[0-3]$ ]]; then
    log_error "agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
if [[ "${STATUS_ALL}" == "true" ]]; then
  require_cmd hcloud
  if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
    log_error "HCLOUD_TOKEN is not set."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ssh_root_quiet() {
  local ip="$1"; shift
  # shellcheck disable=SC2206
  read -ra _opts <<< "$(ssh_opts)"
  # SC2029: expansion on client side is intentional
  # shellcheck disable=SC2029
  ssh "${_opts[@]}" "root@${ip}" "$@" 2>/dev/null
}

# status_one <vm-ip> <vm-name> <agent-index>
status_one() {
  local ip="$1"
  local name="$2"
  local idx="$3"
  local agent_user="agent-${idx}"
  local agent_home="/home/${agent_user}"
  local assignment_file="${agent_home}/assignment.json"
  local status_file="${agent_home}/status"
  local run_log="${agent_home}/run.log"

  # --- assignment ---
  local issue_number="" issue_title="" assigned_at=""
  if ssh_root_quiet "${ip}" "test -f '${assignment_file}'"; then
    local raw_assignment
    raw_assignment=$(ssh_root_quiet "${ip}" "cat '${assignment_file}'" || echo "{}")
    issue_number=$(echo "${raw_assignment}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_number',''))" 2>/dev/null || true)
    issue_title=$(echo "${raw_assignment}"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_title',''))"  2>/dev/null || true)
    assigned_at=$(echo "${raw_assignment}"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('assigned_at',''))"  2>/dev/null || true)
  fi

  # --- tmux / status ---
  local agent_state="no-session"
  if ssh_root_quiet "${ip}" "su - ${agent_user} -c 'tmux has-session -t ${agent_user} 2>/dev/null'"; then
    agent_state="running"
  elif ssh_root_quiet "${ip}" "test -f '${status_file}'"; then
    agent_state=$(ssh_root_quiet "${ip}" "cat '${status_file}'" 2>/dev/null | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]' || echo "unknown")
  fi

  # --- last log line ---
  local last_log_line=""
  if ssh_root_quiet "${ip}" "test -f '${run_log}'"; then
    last_log_line=$(ssh_root_quiet "${ip}" "tail -1 '${run_log}'" 2>/dev/null | tr -d '\r' || true)
  fi

  # --- PR URL ---
  local pr_url=""
  if ssh_root_quiet "${ip}" "test -f '${run_log}'"; then
    pr_url=$(ssh_root_quiet "${ip}" "grep -oE 'https://github.com/[^/]+/[^/]+/pull/[0-9]+' '${run_log}' | tail -1" 2>/dev/null || true)
  fi

  # --- duration ---
  local duration=""
  if [[ -n "${assigned_at}" ]]; then
    duration=$(python3 - "${assigned_at}" <<'PYEOF'
import sys
from datetime import datetime, timezone
try:
    assigned = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    total = int((now - assigned).total_seconds())
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h > 0:
        print(f"{h}h {m}m")
    else:
        print(f"{m}m")
except Exception:
    print("")
PYEOF
    )
  fi

  # --- output ---
  printf "VM: %-24s | Agent: %-8s | Status: %-14s | Issue: %s\n" \
    "${name}" "${agent_user}" "${agent_state}" "${issue_number:-(none)}"

  if [[ -n "${issue_title}" ]]; then
    printf "  Title:    %s\n" "${issue_title}"
  fi
  if [[ -n "${last_log_line}" ]]; then
    printf "  Last log: %s\n" "${last_log_line}"
  fi
  if [[ -n "${pr_url}" ]]; then
    printf "  PR:       %s\n" "${pr_url}"
  fi
  if [[ -n "${duration}" ]]; then
    printf "  Duration: %s\n" "${duration}"
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Single agent
# ---------------------------------------------------------------------------
if [[ "${STATUS_ALL}" == "false" ]]; then
  # Resolve VM name from IP (best effort)
  VM_NAME="${VM_IP}"
  if command -v hcloud &>/dev/null && [[ -n "${HCLOUD_TOKEN:-}" ]]; then
    VM_NAME=$(hcloud server list --output columns=name,ipv4 2>/dev/null \
      | awk -v ip="${VM_IP}" '$2==ip {print $1}' || echo "${VM_IP}")
  fi
  status_one "${VM_IP}" "${VM_NAME}" "${AGENT_INDEX}"
  exit 0
fi

# ---------------------------------------------------------------------------
# All agents across all running VMs
# ---------------------------------------------------------------------------
mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status \
  | awk '$2=="running" && /ccgm-agent/ {print $1}' \
  | sort)

if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
  log_warn "No running ccgm-agent-* VMs found."
  exit 0
fi

for vm_name in "${VM_NAMES[@]}"; do
  ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
  for idx in $(seq 0 $(( CCGM_AGENTS_PER_VM - 1 ))); do
    status_one "${ip}" "${vm_name}" "${idx}"
  done
done
