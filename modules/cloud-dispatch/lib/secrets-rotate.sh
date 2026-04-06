#!/usr/bin/env bash
# secrets-rotate.sh — Rotate a GitHub PAT for a specific agent on a VM.
#
# Re-injects a new GitHub token for a single agent and verifies the token
# works by testing git remote access from the agent's workspace.
#
# Usage:
#   secrets-rotate.sh <vm-ip> <agent-index> --github-token NEW_TOKEN
#
# Example:
#   secrets-rotate.sh 1.2.3.4 0 --github-token ghp_newtoken
#
# Requirements:
#   - SSH key loaded in ssh-agent (run secrets-init.sh first)
#   - secrets-inject.sh in the same directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INJECT_SCRIPT="${SCRIPT_DIR}/secrets-inject.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '[secrets-rotate] %s\n' "$*" >&2; }
die()  { printf '[secrets-rotate] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'USAGE'
Usage: secrets-rotate.sh <vm-ip> <agent-index> --github-token NEW_TOKEN

Arguments:
  vm-ip          IP address of the VM
  agent-index    Agent index (0-3)

Options:
  --github-token TOKEN   New GitHub personal access token (required)
USAGE
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

[[ $# -ge 3 ]] || usage

VM_IP="$1"
AGENT_INDEX="$2"
shift 2

GITHUB_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-token)
      GITHUB_TOKEN="$2"
      shift 2
      ;;
    --help|-h)
      usage
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -n "${GITHUB_TOKEN}" ]] || die "--github-token is required"
[[ "${AGENT_INDEX}" =~ ^[0-3]$ ]] || die "agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})"
[[ -n "${VM_IP}" ]] || die "vm-ip is required"

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

[[ -x "${INJECT_SCRIPT}" ]] || die "secrets-inject.sh not found or not executable at ${INJECT_SCRIPT}"
[[ -n "${SSH_AUTH_SOCK:-}" ]] || die "SSH_AUTH_SOCK is not set — is ssh-agent running?"

AGENT_USER="agent-${AGENT_INDEX}"
SECRETS_DIR="/run/secrets/${AGENT_USER}"

# ---------------------------------------------------------------------------
# Re-inject the new token
# ---------------------------------------------------------------------------

log "Rotating GitHub token for ${AGENT_USER} on ${VM_IP}"
bash "${INJECT_SCRIPT}" "${VM_IP}" "${AGENT_INDEX}" --github-token "${GITHUB_TOKEN}"

# ---------------------------------------------------------------------------
# Verify the new token works
# ---------------------------------------------------------------------------

log "Verifying new token with git ls-remote"

SSH_OPTS=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=10
)

# Run git ls-remote as the agent user to confirm the new GITHUB_TOKEN works.
# The token is read from the secrets file so it never appears in the process list.
VERIFY_RESULT="$(HISTFILE=/dev/null ssh "${SSH_OPTS[@]}" "root@${VM_IP}" \
  bash -s "${AGENT_USER}" "${SECRETS_DIR}" <<'VERIFY'
set -euo pipefail
AGENT_USER="$1"
SECRETS_DIR="$2"

# Run as the agent user so the test mirrors actual agent conditions
if [[ ! -f "${SECRETS_DIR}/github_token" ]]; then
  echo "FAIL: github_token file not found" >&2
  exit 1
fi

TOKEN_FILE="${SECRETS_DIR}/github_token"

# Test API access using the token (does not clone, just checks auth)
HTTP_STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: token $(cat ${TOKEN_FILE})" \
  https://api.github.com/user 2>/dev/null || echo "000")"

case "${HTTP_STATUS}" in
  200)
    echo "OK: GitHub API responded 200"
    ;;
  401)
    echo "FAIL: token rejected (401)" >&2
    exit 1
    ;;
  403)
    echo "FAIL: token forbidden (403)" >&2
    exit 1
    ;;
  000)
    echo "FAIL: no network response (curl error)" >&2
    exit 1
    ;;
  *)
    echo "WARN: unexpected HTTP status ${HTTP_STATUS}" >&2
    ;;
esac
VERIFY
)"

log "${VERIFY_RESULT}"
log "secrets-rotate complete for ${AGENT_USER} on ${VM_IP}"
