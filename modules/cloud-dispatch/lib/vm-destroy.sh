#!/usr/bin/env bash
# vm-destroy.sh - Terminate CCGM agent VMs.
#
# Usage:
#   vm-destroy.sh --all [--force]
#   vm-destroy.sh [--force] <vm-name> [<vm-name>...]
#
# Options:
#   --all    Destroy all VMs matching the ccgm-agent-* pattern
#   --force  Skip confirmation prompt
#
# After destruction, removes SSH known_hosts entries and ControlMaster sockets
# for each destroyed VM.
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

DESTROY_ALL=false
FORCE=false
declare -a TARGET_NAMES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      DESTROY_ALL=true; shift ;;
    --force)
      FORCE=true; shift ;;
    --*)
      log_error "Unknown option: $1"; exit 1 ;;
    *)
      TARGET_NAMES+=("$1"); shift ;;
  esac
done

if [[ "${DESTROY_ALL}" == "false" ]] && [[ ${#TARGET_NAMES[@]} -eq 0 ]]; then
  echo "Usage: $0 --all [--force]" >&2
  echo "       $0 [--force] <vm-name> [<vm-name>...]" >&2
  exit 1
fi

if [[ "${DESTROY_ALL}" == "true" ]] && [[ ${#TARGET_NAMES[@]} -gt 0 ]]; then
  log_error "--all and explicit VM names are mutually exclusive."
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

# ---------------------------------------------------------------------------
# Resolve targets
# ---------------------------------------------------------------------------

if [[ "${DESTROY_ALL}" == "true" ]]; then
  log_info "Listing all VMs matching pattern '${CCGM_VM_PATTERN}'..."
  mapfile -t TARGET_NAMES < <(
    hcloud server list --output json \
      | python3 -c "
import json, sys, fnmatch
servers = json.load(sys.stdin)
pattern = '${CCGM_VM_PATTERN}'
for s in servers:
    if fnmatch.fnmatch(s['name'], pattern):
        print(s['name'])
" \
    || true
  )

  if [[ ${#TARGET_NAMES[@]} -eq 0 ]]; then
    log_info "No VMs matching '${CCGM_VM_PATTERN}' found. Nothing to destroy."
    exit 0
  fi
fi

log_info "Targets: ${TARGET_NAMES[*]}"

# ---------------------------------------------------------------------------
# Collect IPs before deletion (needed for known_hosts cleanup)
# ---------------------------------------------------------------------------

declare -A VM_IPS=()

for name in "${TARGET_NAMES[@]}"; do
  ip="$(vm_ip "${name}" 2>/dev/null || true)"
  if [[ -n "${ip}" ]]; then
    VM_IPS["${name}"]="${ip}"
  else
    log_warn "Could not resolve IP for ${name}; known_hosts cleanup may be incomplete."
  fi
done

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

if [[ "${FORCE}" == "false" ]]; then
  echo ""
  echo "${_COLOR_YELLOW}The following VMs will be permanently destroyed:${_COLOR_RESET}"
  for name in "${TARGET_NAMES[@]}"; do
    ip="${VM_IPS[${name}]:-unknown}"
    printf "  %-30s  %s\n" "${name}" "${ip}"
  done
  echo ""
  read -r -p "Type 'yes' to confirm: " CONFIRM
  if [[ "${CONFIRM}" != "yes" ]]; then
    log_info "Aborted."
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Destroy VMs
# ---------------------------------------------------------------------------

declare -a DESTROYED_NAMES=()
declare -a FAILED_NAMES=()

for name in "${TARGET_NAMES[@]}"; do
  log_info "Destroying ${name}..."
  if hcloud server delete "${name}" 2>/dev/null; then
    DESTROYED_NAMES+=("${name}")
    log_success "Destroyed ${name}."
  else
    FAILED_NAMES+=("${name}")
    log_error "Failed to destroy ${name}."
  fi
done

# ---------------------------------------------------------------------------
# Clean up SSH artifacts
# ---------------------------------------------------------------------------

for name in "${DESTROYED_NAMES[@]}"; do
  ip="${VM_IPS[${name}]:-}"

  # Remove known_hosts entry for the IP
  if [[ -n "${ip}" ]] && [[ -f "${HOME}/.ssh/known_hosts" ]]; then
    ssh-keygen -R "${ip}" >/dev/null 2>&1 || true
    log_info "Removed ${ip} from ~/.ssh/known_hosts."
  fi

  # Remove ControlMaster socket files matching this VM
  if [[ -n "${ip}" ]]; then
    # Socket path pattern: /tmp/ccgm-ssh-root@<ip>:<port>
    find "${CCGM_SSH_CTL_DIR}" -maxdepth 1 -name "ccgm-ssh-root@${ip}:*" -exec rm -f {} \; 2>/dev/null || true
  fi

  # Also clean by name-based socket pattern if present
  find "${CCGM_SSH_CTL_DIR}" -maxdepth 1 -name "ccgm-ssh-*${name}*" -exec rm -f {} \; 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "${_COLOR_BOLD}==== VM Destroy Summary ====${_COLOR_RESET}"
echo ""

if [[ ${#DESTROYED_NAMES[@]} -gt 0 ]]; then
  echo "${_COLOR_GREEN}Destroyed:${_COLOR_RESET}"
  for name in "${DESTROYED_NAMES[@]}"; do
    printf "  %s\n" "${name}"
  done
fi

if [[ ${#FAILED_NAMES[@]} -gt 0 ]]; then
  echo ""
  echo "${_COLOR_RED}Failed to destroy:${_COLOR_RESET}"
  for name in "${FAILED_NAMES[@]}"; do
    printf "  %s\n" "${name}"
  done
  exit 1
fi

echo ""
