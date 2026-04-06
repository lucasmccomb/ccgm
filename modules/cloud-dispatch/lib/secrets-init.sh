#!/usr/bin/env bash
# secrets-init.sh — Initialize session SSH credentials for cloud-dispatch.
#
# Generates a per-session ed25519 SSH keypair, loads it into macOS ssh-agent,
# and registers the public key with Hetzner Cloud. Session metadata is written
# to /tmp/ccgm-session.json for use by secrets-cleanup.sh.
#
# Usage: secrets-init.sh
#
# Requirements:
#   - hcloud CLI authenticated (HCLOUD_TOKEN env or hcloud context)
#   - macOS ssh-agent running (SSH_AUTH_SOCK set)
#   - jq installed

set -euo pipefail

SESSION_FILE="/tmp/ccgm-session.json"
TMPKEY="/tmp/ccgm-session-key-$$"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '[secrets-init] %s\n' "$*" >&2; }
die()  { printf '[secrets-init] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup_tmpkey() {
  rm -f "${TMPKEY}" "${TMPKEY}.pub" 2>/dev/null || true
}
trap cleanup_tmpkey EXIT

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

command -v hcloud >/dev/null 2>&1 || die "hcloud CLI not found in PATH"
command -v ssh-add >/dev/null 2>&1 || die "ssh-add not found in PATH"
command -v ssh-keygen >/dev/null 2>&1 || die "ssh-keygen not found in PATH"
command -v jq >/dev/null 2>&1 || die "jq not found in PATH"

[[ -n "${SSH_AUTH_SOCK:-}" ]] || die "SSH_AUTH_SOCK is not set — is ssh-agent running?"

if [[ -f "${SESSION_FILE}" ]]; then
  log "WARNING: session file already exists at ${SESSION_FILE}"
  log "Run secrets-cleanup.sh first to revoke the previous session."
  exit 1
fi

# ---------------------------------------------------------------------------
# Generate session keypair
# ---------------------------------------------------------------------------

SESSION_TS="$(date +%s)"
KEY_NAME="ccgm-session-${SESSION_TS}"

log "Generating ed25519 session keypair (${KEY_NAME})"
# -N "" means no passphrase so the key can be used by automation without prompting.
ssh-keygen -t ed25519 -f "${TMPKEY}" -N "" -C "${KEY_NAME}" -q

log "Adding private key to ssh-agent"
ssh-add "${TMPKEY}"

# Public key is safe to keep until Hetzner upload completes; trap removes both.
PUBKEY_CONTENT="$(cat "${TMPKEY}.pub")"

# ---------------------------------------------------------------------------
# Register public key with Hetzner
# ---------------------------------------------------------------------------

log "Uploading public key to Hetzner Cloud as '${KEY_NAME}'"
HCLOUD_OUTPUT="$(hcloud ssh-key create --name "${KEY_NAME}" --public-key "${PUBKEY_CONTENT}" --output json 2>/dev/null)"
HCLOUD_KEY_ID="$(printf '%s' "${HCLOUD_OUTPUT}" | jq -r '.ssh_key.id // .id')"
HCLOUD_FINGERPRINT="$(printf '%s' "${HCLOUD_OUTPUT}" | jq -r '.ssh_key.fingerprint // .fingerprint')"

[[ -n "${HCLOUD_KEY_ID}" && "${HCLOUD_KEY_ID}" != "null" ]] \
  || die "Failed to parse key ID from hcloud output"

log "Hetzner SSH key registered: ID=${HCLOUD_KEY_ID} fingerprint=${HCLOUD_FINGERPRINT}"

# ---------------------------------------------------------------------------
# Write session metadata
# ---------------------------------------------------------------------------

jq -n \
  --arg key_name "${KEY_NAME}" \
  --arg key_id "${HCLOUD_KEY_ID}" \
  --arg fingerprint "${HCLOUD_FINGERPRINT}" \
  --arg timestamp "${SESSION_TS}" \
  '{
    key_name:    $key_name,
    key_id:      $key_id,
    fingerprint: $fingerprint,
    timestamp:   $timestamp
  }' > "${SESSION_FILE}"

chmod 0600 "${SESSION_FILE}"

log "Session metadata written to ${SESSION_FILE}"
log "secrets-init complete"
log ""
log "  Key name:    ${KEY_NAME}"
log "  Key ID:      ${HCLOUD_KEY_ID}"
log "  Fingerprint: ${HCLOUD_FINGERPRINT}"
log ""
log "Run secrets-cleanup.sh to revoke this session when done."
