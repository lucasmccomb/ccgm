#!/usr/bin/env bash
# common.sh - Shared utilities for CCGM cloud-dispatch VM lifecycle scripts
# Source this file from all other cloud-dispatch scripts.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Server type for agent VMs (CCX63: 48 vCPU, 192 GB RAM)
CCGM_SERVER_TYPE="${CCGM_SERVER_TYPE:-ccx63}"

# Datacenter locations, in round-robin order for VM placement
# exported so sourcing scripts see it without shellcheck SC2034 false-positives
export CCGM_LOCATIONS=("fsn1" "nbg1" "hel1")

# Snapshot label selector used to find the latest golden image
export CCGM_IMAGE_LABEL="${CCGM_IMAGE_LABEL:-purpose=ccgm-agent}"

# SSH key name as stored in Hetzner (set by Terraform)
export CCGM_SSH_KEY_NAME="${CCGM_SSH_KEY_NAME:-ccgm-dispatch-key}"

# Firewall name as created by Terraform
export CCGM_FIREWALL_NAME="${CCGM_FIREWALL_NAME:-ccgm-dispatch-firewall}"

# VM name prefix and pattern
export CCGM_VM_PREFIX="ccgm-agent"
export CCGM_VM_PATTERN="ccgm-agent-*"

# Number of agent users per VM
export CCGM_AGENTS_PER_VM=4

# SSH identity file for dispatch connections
export CCGM_SSH_KEY="${CCGM_SSH_KEY:-${HOME}/.ssh/ccgm-dispatch-session}"

# ControlMaster socket directory
export CCGM_SSH_CTL_DIR="/tmp"

# Minimum free disk space (GB) required for a VM to be healthy
export CCGM_MIN_DISK_GB=20

# Minimum free memory (MB) per agent slot for a VM to be healthy
export CCGM_MIN_MEM_MB_PER_AGENT=4096

# ---------------------------------------------------------------------------
# Color output helpers
# ---------------------------------------------------------------------------

# Detect whether we have a terminal that supports color
if [[ -t 1 ]] && [[ "${TERM:-}" != "dumb" ]]; then
  _COLOR_RESET=$'\033[0m'
  _COLOR_RED=$'\033[0;31m'
  _COLOR_GREEN=$'\033[0;32m'
  _COLOR_YELLOW=$'\033[0;33m'
  _COLOR_CYAN=$'\033[0;36m'
  _COLOR_BOLD=$'\033[1m'
else
  _COLOR_RESET=''
  _COLOR_RED=''
  _COLOR_GREEN=''
  _COLOR_YELLOW=''
  _COLOR_CYAN=''
  _COLOR_BOLD=''
fi

# ---------------------------------------------------------------------------
# Logging utilities
# ---------------------------------------------------------------------------

log_info() {
  echo "${_COLOR_CYAN}[INFO]${_COLOR_RESET}  $(date '+%Y-%m-%dT%H:%M:%S') $*" >&2
}

log_success() {
  echo "${_COLOR_GREEN}[OK]${_COLOR_RESET}    $(date '+%Y-%m-%dT%H:%M:%S') $*" >&2
}

log_warn() {
  echo "${_COLOR_YELLOW}[WARN]${_COLOR_RESET}  $(date '+%Y-%m-%dT%H:%M:%S') $*" >&2
}

log_error() {
  echo "${_COLOR_RED}[ERROR]${_COLOR_RESET} $(date '+%Y-%m-%dT%H:%M:%S') $*" >&2
}

# ---------------------------------------------------------------------------
# Prerequisite check
# ---------------------------------------------------------------------------

# require_cmd <command> - exits with error if <command> is not found in PATH
require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log_error "Required command not found: ${cmd}"
    log_error "Install it and retry."
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# VM naming convention
# ---------------------------------------------------------------------------

# vm_name <location> <index>
# Returns a deterministic VM name: ccgm-agent-<location>-<index>
# e.g. vm_name fsn1 0 -> ccgm-agent-fsn1-0
vm_name() {
  local location="$1"
  local index="$2"
  echo "${CCGM_VM_PREFIX}-${location}-${index}"
}

# ---------------------------------------------------------------------------
# SSH configuration
# ---------------------------------------------------------------------------

# ssh_config_snippet - prints an SSH config Host block for ccgm-agent-* VMs.
# Append this to ~/.ssh/config or write to a dedicated include file.
ssh_config_snippet() {
  cat <<'EOF'
Host ccgm-agent-*
  User root
  IdentityFile ~/.ssh/ccgm-dispatch-session
  StrictHostKeyChecking accept-new
  ControlMaster auto
  ControlPath /tmp/ccgm-ssh-%r@%h:%p
  ControlPersist 600
  ServerAliveInterval 30
  ServerAliveCountMax 3
  BatchMode yes
  ConnectTimeout 10
EOF
}

# ssh_opts - common SSH options array, suitable for use with ssh/scp.
# Usage: ssh "${ssh_opts[@]}" root@<ip> <command>
ssh_opts() {
  echo \
    -i "${CCGM_SSH_KEY}" \
    -o StrictHostKeyChecking=accept-new \
    -o ControlMaster=auto \
    -o "ControlPath=${CCGM_SSH_CTL_DIR}/ccgm-ssh-%r@%h:%p" \
    -o ControlPersist=600 \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o BatchMode=yes \
    -o ConnectTimeout=10
}

# ---------------------------------------------------------------------------
# Hetzner helpers
# ---------------------------------------------------------------------------

# latest_image_id - returns the snapshot ID of the most recent ccgm-agent image.
# Selects by label type=ccgm-agent, sorted by created date descending.
latest_image_id() {
  hcloud image list \
    --type snapshot \
    --selector "${CCGM_IMAGE_LABEL}" \
    --output json \
    | python3 -c "
import json, sys
images = json.load(sys.stdin)
if not images:
    print('', end='')
    sys.exit(0)
images.sort(key=lambda x: x.get('created', ''), reverse=True)
print(images[0]['id'])
"
}

# wait_for_vm_running <vm-name> [timeout_secs]
# Polls hcloud until the VM is in 'running' state or timeout is reached.
wait_for_vm_running() {
  local name="$1"
  local timeout="${2:-120}"
  local elapsed=0
  local interval=5

  log_info "Waiting for ${name} to reach 'running' state (timeout ${timeout}s)..."
  while [[ ${elapsed} -lt ${timeout} ]]; do
    local status
    status=$(hcloud server describe "${name}" --output json 2>/dev/null \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" \
      || echo "unknown")

    if [[ "${status}" == "running" ]]; then
      log_success "${name} is running."
      return 0
    fi
    sleep "${interval}"
    elapsed=$(( elapsed + interval ))
  done

  log_error "${name} did not reach 'running' within ${timeout}s (last status: ${status:-unknown})."
  return 1
}

# wait_for_ssh <ip> [timeout_secs]
# Retries SSH connection until it succeeds or timeout is reached.
wait_for_ssh() {
  local ip="$1"
  local timeout="${2:-120}"
  local elapsed=0
  local interval=5

  log_info "Waiting for SSH on ${ip} (timeout ${timeout}s)..."
  while [[ ${elapsed} -lt ${timeout} ]]; do
    # ssh_opts returns space-separated options; read into array to avoid word splitting
    # shellcheck disable=SC2206
    read -ra _ssh_wait_opts <<< "$(ssh_opts)"
    if ssh "${_ssh_wait_opts[@]}" "root@${ip}" "true" 2>/dev/null; then
      log_success "SSH is reachable on ${ip}."
      return 0
    fi
    sleep "${interval}"
    elapsed=$(( elapsed + interval ))
  done

  log_error "SSH on ${ip} did not become reachable within ${timeout}s."
  return 1
}

# vm_ip <vm-name> - prints the public IPv4 address of a named VM.
vm_ip() {
  local name="$1"
  hcloud server describe "${name}" --output json \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
nets = d.get('public_net', {})
ipv4 = nets.get('ipv4', {})
print(ipv4.get('ip', ''))
"
}

# ---------------------------------------------------------------------------
# Trap / cleanup registration
# ---------------------------------------------------------------------------

# cleanup_fns is an array of function names to call on EXIT.
# Use register_cleanup to add entries.
declare -a _cleanup_fns=()

register_cleanup() {
  _cleanup_fns+=("$1")
}

_run_cleanup() {
  for fn in "${_cleanup_fns[@]+"${_cleanup_fns[@]}"}"; do
    "${fn}" || true
  done
}

trap '_run_cleanup' EXIT
