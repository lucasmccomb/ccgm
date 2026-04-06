#!/usr/bin/env bash
# secrets-cleanup.sh — Revoke session credentials and wipe VM secrets.
#
# Reads session metadata from /tmp/ccgm-session.json (written by secrets-init.sh),
# deletes the Hetzner SSH key, removes it from ssh-agent, and optionally wipes
# /run/secrets/ on all running VMs.
#
# Usage:
#   secrets-cleanup.sh [--wipe-vms]
#
# Options:
#   --wipe-vms   SSH into each running ccgm-agent-* VM and wipe /run/secrets/
#
# Requirements:
#   - hcloud CLI authenticated
#   - jq installed

set -euo pipefail

SESSION_FILE="/tmp/ccgm-session.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '[secrets-cleanup] %s\n' "$*" >&2; }
warn() { printf '[secrets-cleanup] WARN: %s\n' "$*" >&2; }
die()  { printf '[secrets-cleanup] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

WIPE_VMS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wipe-vms)
      WIPE_VMS=true
      shift
      ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

command -v hcloud >/dev/null 2>&1 || die "hcloud CLI not found in PATH"
command -v jq >/dev/null 2>&1 || die "jq not found in PATH"
command -v ssh-add >/dev/null 2>&1 || die "ssh-add not found in PATH"

# ---------------------------------------------------------------------------
# Read session metadata
# ---------------------------------------------------------------------------

if [[ ! -f "${SESSION_FILE}" ]]; then
  warn "Session file not found at ${SESSION_FILE} — nothing to clean up"
  exit 0
fi

KEY_ID="$(jq -r '.key_id' "${SESSION_FILE}")"
KEY_NAME="$(jq -r '.key_name' "${SESSION_FILE}")"
FINGERPRINT="$(jq -r '.fingerprint' "${SESSION_FILE}")"

[[ -n "${KEY_ID}" && "${KEY_ID}" != "null" ]] \
  || die "Could not read key_id from ${SESSION_FILE}"

log "Session: key_name=${KEY_NAME} key_id=${KEY_ID} fingerprint=${FINGERPRINT}"

# ---------------------------------------------------------------------------
# Remove key from ssh-agent
# ---------------------------------------------------------------------------

log "Removing session key from ssh-agent (fingerprint: ${FINGERPRINT})"
if ssh-add -l 2>/dev/null | grep -q "${FINGERPRINT}"; then
  ssh-add -d - 2>/dev/null <<< "" || {
    # ssh-add -d requires the public key or fingerprint; use -D as fallback
    # only if no other keys are loaded, to avoid revoking unrelated keys.
    LOADED_COUNT="$(ssh-add -l 2>/dev/null | grep -c . || true)"
    if [[ "${LOADED_COUNT}" -eq 1 ]]; then
      log "  Using ssh-add -D (only session key is loaded)"
      ssh-add -D
    else
      warn "  Could not remove specific key; ${LOADED_COUNT} keys loaded — manual cleanup may be needed"
    fi
  }
else
  log "  Key not found in ssh-agent (may have already been removed)"
fi

# ---------------------------------------------------------------------------
# Delete key from Hetzner
# ---------------------------------------------------------------------------

log "Deleting SSH key from Hetzner Cloud (ID: ${KEY_ID})"
if hcloud ssh-key describe "${KEY_ID}" &>/dev/null; then
  hcloud ssh-key delete "${KEY_ID}"
  log "  Deleted Hetzner SSH key ${KEY_NAME} (${KEY_ID})"
else
  log "  Key ID ${KEY_ID} not found in Hetzner — may have been deleted already"
fi

# ---------------------------------------------------------------------------
# Optional: wipe /run/secrets/ on all running VMs
# ---------------------------------------------------------------------------

if [[ "${WIPE_VMS}" == "true" ]]; then
  log "Discovering running ccgm-agent-* VMs for secret wipe"

  RUNNING_VMS="$(hcloud server list --output json 2>/dev/null \
    | jq -r '.[] | select(.name | startswith("ccgm-agent")) | select(.status == "running") | "\(.name) \(.public_net.ipv4.ip)"' \
    || true)"

  if [[ -z "${RUNNING_VMS}" ]]; then
    log "No running VMs found — nothing to wipe"
  else
    SSH_OPTS=(
      -o BatchMode=yes
      -o StrictHostKeyChecking=accept-new
      -o ConnectTimeout=10
    )

    while IFS=' ' read -r vm_name vm_ip; do
      [[ -z "${vm_name}" ]] && continue
      log "Wiping /run/secrets/ on ${vm_name} (${vm_ip})"

      if HISTFILE=/dev/null ssh -n "${SSH_OPTS[@]}" "root@${vm_ip}" \
          'find /run/secrets -mindepth 2 -type f -exec shred -u {} \; 2>/dev/null; echo "wiped"' 2>/dev/null; then
        log "  ${vm_name}: wiped"
      else
        warn "  ${vm_name}: wipe failed or VM unreachable"
      fi
    done <<< "${RUNNING_VMS}"
  fi
fi

# ---------------------------------------------------------------------------
# Remove session metadata file
# ---------------------------------------------------------------------------

log "Removing session metadata file ${SESSION_FILE}"
rm -f "${SESSION_FILE}"

log "secrets-cleanup complete"
