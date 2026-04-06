#!/usr/bin/env bash
# agent-stop.sh — Stop one or all running Claude Code agent tmux sessions.
#
# Usage:
#   agent-stop.sh --all
#   agent-stop.sh <vm-ip> <agent-index>
#
# For each target agent:
#   1. Kills the tmux session named agent-N on the VM
#   2. Writes AGENT_STOPPED to ~/status
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

STOP_ALL=false
VM_IP=""
AGENT_INDEX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      STOP_ALL=true
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

if [[ "${STOP_ALL}" == "false" ]]; then
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
if [[ "${STOP_ALL}" == "true" ]]; then
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

stop_one() {
  local ip="$1"
  local idx="$2"
  local agent_user="agent-${idx}"
  local agent_home="/home/${agent_user}"
  local status_file="${agent_home}/status"

  log_info "Stopping ${agent_user} on ${ip}"

  # Kill the tmux session (ignore errors if not running)
  ssh_root_quiet "${ip}" "su - ${agent_user} -c 'tmux kill-session -t ${agent_user} 2>/dev/null || true'"

  # Write stopped status
  ssh_root_quiet "${ip}" "echo AGENT_STOPPED > '${status_file}' && chown '${agent_user}:${agent_user}' '${status_file}'"

  log_success "Stopped ${agent_user} on ${ip}"
}

# ---------------------------------------------------------------------------
# Single agent
# ---------------------------------------------------------------------------
if [[ "${STOP_ALL}" == "false" ]]; then
  stop_one "${VM_IP}" "${AGENT_INDEX}"
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

STOPPED=0

for vm_name in "${VM_NAMES[@]}"; do
  ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
  for idx in $(seq 0 $(( CCGM_AGENTS_PER_VM - 1 ))); do
    stop_one "${ip}" "${idx}"
    STOPPED=$(( STOPPED + 1 ))
  done
done

log_info "Stopped ${STOPPED} agent session(s)."
