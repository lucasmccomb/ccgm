#!/usr/bin/env bash
# vm-health.sh - Health check CCGM agent VMs.
#
# Usage:
#   vm-health.sh                  Check all ccgm-agent-* VMs
#   vm-health.sh --all            Same as above
#   vm-health.sh <vm-name> [...]  Check specific VM(s) by name
#
# Per-VM checks:
#   - SSH reachability (timeout 10s)
#   - `claude --version` returns successfully
#   - Free disk space > 20 GB
#   - Free memory > 4 GB per agent slot (CCGM_AGENTS_PER_VM slots)
#   - Agent users exist (agent-0 through agent-3)
#   - iptables rules active (non-empty ruleset)
#
# Reports HEALTHY / DEGRADED / UNREACHABLE per VM.
# Exit code: 0 if all VMs are HEALTHY, 1 if any DEGRADED or UNREACHABLE.
#
# Environment:
#   HCLOUD_TOKEN  Hetzner Cloud API token (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

declare -a TARGET_NAMES=()
CHECK_ALL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      CHECK_ALL=true; shift ;;
    --*)
      log_error "Unknown option: $1"; exit 1 ;;
    *)
      TARGET_NAMES+=("$1"); shift ;;
  esac
done

# Default: check all if no targets specified
if [[ ${#TARGET_NAMES[@]} -eq 0 ]]; then
  CHECK_ALL=true
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

require_cmd hcloud
require_cmd ssh
require_cmd python3

if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
  log_error "HCLOUD_TOKEN is not set. Export it before running this script."
  exit 1
fi

# ---------------------------------------------------------------------------
# Resolve target list
# ---------------------------------------------------------------------------

if [[ "${CHECK_ALL}" == "true" ]]; then
  log_info "Discovering ccgm-agent-* VMs..."
  mapfile -t TARGET_NAMES < <(
    hcloud server list --output json \
      | python3 -c "
import json, sys, fnmatch
servers = json.load(sys.stdin)
for s in sorted(servers, key=lambda x: x['name']):
    if fnmatch.fnmatch(s['name'], '${CCGM_VM_PATTERN}'):
        print(s['name'])
" \
    || true
  )

  if [[ ${#TARGET_NAMES[@]} -eq 0 ]]; then
    log_info "No ccgm-agent-* VMs found."
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Health check helpers
# ---------------------------------------------------------------------------

# Run a remote command on a VM, capturing output. Returns the exit code.
_remote() {
  local ip="$1"
  shift
  # shellcheck disable=SC2206
  read -ra opts <<< "$(ssh_opts)"
  ssh "${opts[@]}" -o ConnectTimeout=10 "root@${ip}" "$@" 2>/dev/null
}

# check_ssh <ip> - returns 0 if SSH is reachable within 10s
check_ssh() {
  local ip="$1"
  # shellcheck disable=SC2206
  read -ra opts <<< "$(ssh_opts)"
  ssh "${opts[@]}" -o ConnectTimeout=10 "root@${ip}" "true" 2>/dev/null
}

# check_claude <ip> - returns 0 if `claude --version` succeeds
check_claude() {
  _remote "$1" "claude --version" >/dev/null 2>&1
}

# check_disk <ip> - returns 0 if free space on / exceeds CCGM_MIN_DISK_GB
check_disk() {
  local ip="$1"
  local free_kb
  free_kb="$(_remote "${ip}" "df -k / | awk 'NR==2{print \$4}'")" || return 1
  local free_gb=$(( free_kb / 1024 / 1024 ))
  [[ "${free_gb}" -ge "${CCGM_MIN_DISK_GB}" ]]
}

# check_memory <ip> - returns 0 if free memory satisfies per-agent requirement
check_memory() {
  local ip="$1"
  local free_mb
  free_mb="$(_remote "${ip}" "free -m | awk '/^Mem:/{print \$7}'")" || return 1
  local required_mb=$(( CCGM_MIN_MEM_MB_PER_AGENT * CCGM_AGENTS_PER_VM ))
  [[ "${free_mb}" -ge "${required_mb}" ]]
}

# check_agent_users <ip> - returns 0 if agent-0 through agent-N-1 all exist
check_agent_users() {
  local ip="$1"
  local script=""
  for (( u=0; u<CCGM_AGENTS_PER_VM; u++ )); do
    script+="id agent-${u} >/dev/null 2>&1 || exit 1; "
  done
  _remote "${ip}" "bash -c '${script}exit 0'" >/dev/null 2>&1
}

# check_iptables <ip> - returns 0 if iptables has at least one non-default chain rule
check_iptables() {
  local ip="$1"
  local rule_count
  rule_count="$(_remote "${ip}" "iptables -L -n | grep -c '^[A-Z]' || true")" 2>/dev/null || return 1
  [[ "${rule_count}" -gt 3 ]]
}

# ---------------------------------------------------------------------------
# Run health checks on each VM
# ---------------------------------------------------------------------------

declare -a HEALTHY_NAMES=()
declare -a DEGRADED_NAMES=()
declare -a UNREACHABLE_NAMES=()

echo ""
echo "${_COLOR_BOLD}==== CCGM Agent VM Health Check ====${_COLOR_RESET}"
echo ""

for name in "${TARGET_NAMES[@]}"; do
  ip="$(vm_ip "${name}" 2>/dev/null || true)"
  if [[ -z "${ip}" ]]; then
    log_warn "${name}: could not resolve IP (VM may not exist)."
    UNREACHABLE_NAMES+=("${name}")
    printf "  %-32s  %s\n" "${name}" "${_COLOR_RED}UNREACHABLE${_COLOR_RESET} (no IP)"
    continue
  fi

  # SSH reachability is a hard requirement
  if ! check_ssh "${ip}" 2>/dev/null; then
    UNREACHABLE_NAMES+=("${name}")
    printf "  %-32s  %s\n" "${name}" "${_COLOR_RED}UNREACHABLE${_COLOR_RESET} (SSH timeout)"
    continue
  fi

  declare -a failures=()

  check_claude "${ip}"   || failures+=("claude-not-found")
  check_disk "${ip}"     || failures+=("low-disk (<${CCGM_MIN_DISK_GB}GB)")
  check_memory "${ip}"   || failures+=("low-memory (<$(( CCGM_MIN_MEM_MB_PER_AGENT * CCGM_AGENTS_PER_VM ))MB free)")
  check_agent_users "${ip}" || failures+=("missing-agent-users")
  check_iptables "${ip}" || failures+=("iptables-inactive")

  if [[ ${#failures[@]} -eq 0 ]]; then
    HEALTHY_NAMES+=("${name}")
    printf "  %-32s  %s\n" "${name}" "${_COLOR_GREEN}HEALTHY${_COLOR_RESET}"
  else
    DEGRADED_NAMES+=("${name}")
    printf "  %-32s  %s  [%s]\n" \
      "${name}" \
      "${_COLOR_YELLOW}DEGRADED${_COLOR_RESET}" \
      "${failures[*]}"
  fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "${_COLOR_BOLD}Summary:${_COLOR_RESET}"
echo "  Healthy:     ${#HEALTHY_NAMES[@]}"
echo "  Degraded:    ${#DEGRADED_NAMES[@]}"
echo "  Unreachable: ${#UNREACHABLE_NAMES[@]}"
echo "  Total:       ${#TARGET_NAMES[@]}"
echo ""

if [[ ${#DEGRADED_NAMES[@]} -gt 0 ]] || [[ ${#UNREACHABLE_NAMES[@]} -gt 0 ]]; then
  exit 1
fi
