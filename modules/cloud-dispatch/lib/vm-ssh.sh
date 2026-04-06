#!/usr/bin/env bash
# vm-ssh.sh - SSH into a CCGM agent VM.
#
# Usage:
#   vm-ssh.sh <vm-name> [command [args...]]
#
# If a command is provided, it is executed non-interactively and the script
# exits with its return code. If no command is given, an interactive shell
# session is opened.
#
# ControlMaster sockets are reused when available (see SSH config in common.sh).
#
# Environment:
#   HCLOUD_TOKEN  Hetzner Cloud API token (required to resolve the VM IP)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <vm-name> [command [args...]]" >&2
  exit 1
fi

VM_NAME="$1"
shift
REMOTE_CMD=("$@")

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
# Resolve IP
# ---------------------------------------------------------------------------

log_info "Resolving IP for ${VM_NAME}..."
VM_IP="$(vm_ip "${VM_NAME}")"

if [[ -z "${VM_IP}" ]]; then
  log_error "Could not resolve IP for VM '${VM_NAME}'. Is it running?"
  exit 1
fi

log_info "${VM_NAME} -> ${VM_IP}"

# ---------------------------------------------------------------------------
# Build SSH options array
# ---------------------------------------------------------------------------

# Using read -ra to split the opts string into an array
# shellcheck disable=SC2206
read -ra SSH_OPTS <<< "$(ssh_opts)"

# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------

if [[ ${#REMOTE_CMD[@]} -gt 0 ]]; then
  # Non-interactive: run command and exit
  exec ssh "${SSH_OPTS[@]}" "root@${VM_IP}" "${REMOTE_CMD[@]}"
else
  # Interactive session: allocate a TTY
  exec ssh -t "${SSH_OPTS[@]}" "root@${VM_IP}"
fi
