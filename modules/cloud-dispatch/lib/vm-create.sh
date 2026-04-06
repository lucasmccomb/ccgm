#!/usr/bin/env bash
# vm-create.sh - Create CCGM agent VMs from the golden image snapshot.
#
# Usage:
#   vm-create.sh [count] [--type TYPE] [--image IMAGE_ID]
#
# Arguments:
#   count        Number of VMs to create (default: 3)
#
# Options:
#   --type TYPE       Server type (default: ccx63)
#   --image IMAGE_ID  Snapshot ID to use (default: latest ccgm-agent snapshot)
#
# Environment:
#   HCLOUD_TOKEN  Hetzner Cloud API token (required)
#
# VMs are named ccgm-agent-<location>-<index> and spread round-robin across
# the configured datacenter locations (fsn1, nbg1, hel1 by default).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

COUNT=3
SERVER_TYPE="${CCGM_SERVER_TYPE}"
IMAGE_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --type)
      SERVER_TYPE="$2"; shift 2 ;;
    --image)
      IMAGE_ID="$2"; shift 2 ;;
    --*)
      log_error "Unknown option: $1"; exit 1 ;;
    *)
      COUNT="$1"; shift ;;
  esac
done

if ! [[ "${COUNT}" =~ ^[0-9]+$ ]] || [[ "${COUNT}" -lt 1 ]]; then
  log_error "count must be a positive integer, got: ${COUNT}"
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

# Resolve image ID if not provided
if [[ -z "${IMAGE_ID}" ]]; then
  log_info "Resolving latest ccgm-agent snapshot..."
  IMAGE_ID="$(latest_image_id)"
  if [[ -z "${IMAGE_ID}" ]]; then
    log_error "No snapshot found matching label '${CCGM_IMAGE_LABEL}'."
    log_error "Build the golden image first with: packer build packer/agent-image.pkr.hcl"
    exit 1
  fi
  log_info "Using snapshot ID: ${IMAGE_ID}"
fi

# Resolve SSH key and firewall IDs from Hetzner
log_info "Resolving SSH key '${CCGM_SSH_KEY_NAME}'..."
SSH_KEY_ID="$(hcloud ssh-key describe "${CCGM_SSH_KEY_NAME}" --output json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")"

log_info "Resolving firewall '${CCGM_FIREWALL_NAME}'..."
FIREWALL_ID="$(hcloud firewall describe "${CCGM_FIREWALL_NAME}" --output json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")"

# ---------------------------------------------------------------------------
# Create VMs
# ---------------------------------------------------------------------------

log_info "Creating ${COUNT} VM(s) with type=${SERVER_TYPE}, image=${IMAGE_ID}..."

declare -a CREATED_NAMES=()
declare -a FAILED_NAMES=()

for (( i=0; i<COUNT; i++ )); do
  location="${CCGM_LOCATIONS[$(( i % ${#CCGM_LOCATIONS[@]} ))]}"
  name="$(vm_name "${location}" "${i}")"

  log_info "Creating ${name} in ${location}..."

  if hcloud server create \
    --name "${name}" \
    --type "${SERVER_TYPE}" \
    --image "${IMAGE_ID}" \
    --location "${location}" \
    --ssh-key "${SSH_KEY_ID}" \
    --firewall "${FIREWALL_ID}" \
    --output json >/dev/null 2>&1; then
    CREATED_NAMES+=("${name}")
    log_success "Created ${name}."
  else
    FAILED_NAMES+=("${name}")
    log_error "Failed to create ${name}."
  fi
done

if [[ ${#FAILED_NAMES[@]} -gt 0 ]]; then
  log_warn "Some VMs failed to create: ${FAILED_NAMES[*]}"
fi

if [[ ${#CREATED_NAMES[@]} -eq 0 ]]; then
  log_error "No VMs were created successfully."
  exit 1
fi

# ---------------------------------------------------------------------------
# Wait for VMs to be running and SSH-reachable
# ---------------------------------------------------------------------------

declare -a READY_NAMES=()
declare -a UNREADY_NAMES=()

for name in "${CREATED_NAMES[@]}"; do
  if wait_for_vm_running "${name}" 120; then
    ip="$(vm_ip "${name}")"
    if wait_for_ssh "${ip}" 120; then
      READY_NAMES+=("${name}")
    else
      UNREADY_NAMES+=("${name}")
      log_warn "${name} (${ip}): VM running but SSH unreachable."
    fi
  else
    UNREADY_NAMES+=("${name}")
    log_warn "${name}: did not reach running state in time."
  fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "${_COLOR_BOLD}==== VM Create Summary ====${_COLOR_RESET}"
echo ""

if [[ ${#READY_NAMES[@]} -gt 0 ]]; then
  echo "${_COLOR_GREEN}Ready:${_COLOR_RESET}"
  for name in "${READY_NAMES[@]}"; do
    ip="$(vm_ip "${name}")"
    location="$(hcloud server describe "${name}" --output json \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['datacenter']['location']['name'])")"
    printf "  %-30s  %-15s  %s\n" "${name}" "${ip}" "${location}"
  done
fi

if [[ ${#UNREADY_NAMES[@]} -gt 0 ]]; then
  echo ""
  echo "${_COLOR_YELLOW}Not ready (manual intervention may be needed):${_COLOR_RESET}"
  for name in "${UNREADY_NAMES[@]}"; do
    printf "  %s\n" "${name}"
  done
fi

if [[ ${#FAILED_NAMES[@]} -gt 0 ]]; then
  echo ""
  echo "${_COLOR_RED}Failed to create:${_COLOR_RESET}"
  for name in "${FAILED_NAMES[@]}"; do
    printf "  %s\n" "${name}"
  done
fi

echo ""

if [[ ${#UNREADY_NAMES[@]} -gt 0 ]] || [[ ${#FAILED_NAMES[@]} -gt 0 ]]; then
  exit 1
fi
