#!/usr/bin/env bash
# agent-launch-all.sh — Launch all assigned agents across all running VMs with jitter.
#
# Usage:
#   agent-launch-all.sh [--jitter SECONDS] [--max-turns N] [--prompt PROMPT] [--dry-run]
#
# Options:
#   --jitter N    Random sleep max between agent launches in seconds (default: 90).
#                 Actual sleep is a random value between 60 and JITTER (min 60).
#                 Set to 0 to disable jitter.
#   --max-turns N Maximum turns per agent (default: 200)
#   --prompt P    Claude prompt override (passed to agent-launch.sh)
#   --dry-run     Print what would be launched without executing
#
# Jitter is critical: it staggers Claude API calls so all agents don't hit the
# rate limiter simultaneously.
#
# Requires:
#   - hcloud CLI installed and authenticated (HCLOUD_TOKEN set)
#   - agent-launch.sh in the same directory as this script
#   - SSH key in ~/.ssh/ccgm-dispatch-session or $SSH_KEY_PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MAX_TURNS=200
JITTER=90
CUSTOM_PROMPT=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jitter)
      JITTER="$2"
      shift 2
      ;;
    --max-turns)
      MAX_TURNS="$2"
      shift 2
      ;;
    --prompt)
      CUSTOM_PROMPT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      log_error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! [[ "${MAX_TURNS}" =~ ^[0-9]+$ ]]; then
  log_error "--max-turns must be a positive integer (got: ${MAX_TURNS})"
  exit 1
fi

if ! [[ "${JITTER}" =~ ^[0-9]+$ ]]; then
  log_error "--jitter must be a non-negative integer (got: ${JITTER})"
  exit 1
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
require_cmd hcloud
require_cmd python3

if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
  log_error "HCLOUD_TOKEN is not set. Export it before running this script."
  exit 1
fi

LAUNCH_SCRIPT="${SCRIPT_DIR}/agent-launch.sh"
if [[ ! -x "${LAUNCH_SCRIPT}" ]]; then
  log_error "agent-launch.sh not found or not executable at ${LAUNCH_SCRIPT}"
  exit 1
fi

# ---------------------------------------------------------------------------
# Discover running agent VMs
# ---------------------------------------------------------------------------
log_info "Discovering running ccgm-agent-* VMs..."

mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status \
  | awk '$2=="running" && /ccgm-agent/ {print $1}' \
  | sort)

if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
  log_error "No running ccgm-agent-* VMs found."
  exit 1
fi

log_info "Found ${#VM_NAMES[@]} VM(s): ${VM_NAMES[*]}"

# ---------------------------------------------------------------------------
# Build launch list: only slots that have an assignment.json
# ---------------------------------------------------------------------------
ssh_root() {
  local ip="$1"; shift
  # shellcheck disable=SC2206
  read -ra _opts <<< "$(ssh_opts)"
  # SC2029: expansion on client side is intentional
  # shellcheck disable=SC2029
  ssh "${_opts[@]}" "root@${ip}" "$@" 2>/dev/null
}

declare -a LAUNCH_VM_IPS
declare -a LAUNCH_VM_NAMES
declare -a LAUNCH_AGENT_INDEXES

log_info "Checking agent assignments..."

for vm_name in "${VM_NAMES[@]}"; do
  vm_ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
  for agent_index in $(seq 0 $(( CCGM_AGENTS_PER_VM - 1 ))); do
    agent_user="agent-${agent_index}"
    assignment_file="/home/${agent_user}/assignment.json"
    if ssh_root "${vm_ip}" "test -f '${assignment_file}'"; then
      LAUNCH_VM_IPS+=("${vm_ip}")
      LAUNCH_VM_NAMES+=("${vm_name}")
      LAUNCH_AGENT_INDEXES+=("${agent_index}")
      log_info "  ${vm_name} / ${agent_user} - has assignment"
    else
      log_warn "  ${vm_name} / ${agent_user} - no assignment, skipping"
    fi
  done
done

TOTAL="${#LAUNCH_VM_IPS[@]}"

if [[ "${TOTAL}" -eq 0 ]]; then
  log_warn "No agents have assignments. Run workspace-assign.sh (or workspace-setup-all.sh) first."
  exit 0
fi

log_info "Agents to launch: ${TOTAL}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo ""
  echo "Dry run - agents that would be launched:"
  for i in "${!LAUNCH_VM_IPS[@]}"; do
    printf "  %s / agent-%s\n" "${LAUNCH_VM_NAMES[$i]}" "${LAUNCH_AGENT_INDEXES[$i]}"
  done
  echo ""
  echo "(--dry-run: no changes made)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Launch agents with jitter between each
# ---------------------------------------------------------------------------
LAUNCHED=0
FAILED=0
START_TIME=$(date +%s)

for i in "${!LAUNCH_VM_IPS[@]}"; do
  vm_ip="${LAUNCH_VM_IPS[$i]}"
  vm_name="${LAUNCH_VM_NAMES[$i]}"
  agent_index="${LAUNCH_AGENT_INDEXES[$i]}"
  agent_user="agent-${agent_index}"

  log_info "[$(( i + 1 ))/${TOTAL}] Launching ${vm_name} / ${agent_user}"

  launch_args=("${vm_ip}" "${agent_index}" --max-turns "${MAX_TURNS}")
  if [[ -n "${CUSTOM_PROMPT}" ]]; then
    launch_args+=(--prompt "${CUSTOM_PROMPT}")
  fi

  if "${LAUNCH_SCRIPT}" "${launch_args[@]}"; then
    LAUNCHED=$(( LAUNCHED + 1 ))
  else
    log_error "Launch failed for ${vm_name} / ${agent_user}"
    FAILED=$(( FAILED + 1 ))
  fi

  # Jitter: sleep a random amount between 60s and JITTER (skip after last agent)
  if [[ "${JITTER}" -gt 0 && $(( i + 1 )) -lt "${TOTAL}" ]]; then
    if [[ "${JITTER}" -gt 60 ]]; then
      sleep_secs=$(( 60 + RANDOM % (JITTER - 60 + 1) ))
    else
      sleep_secs="${JITTER}"
    fi
    log_info "Jitter: sleeping ${sleep_secs}s before next launch..."
    sleep "${sleep_secs}"
  fi
done

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))

echo ""
log_info "Launch complete"
echo "  Total agents launched: ${LAUNCHED}"
if [[ "${FAILED}" -gt 0 ]]; then
  echo "  Failed:                ${FAILED}"
fi
echo "  Total elapsed:         ${ELAPSED}s"

[[ "${FAILED}" -eq 0 ]]
