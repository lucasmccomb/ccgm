#!/usr/bin/env bash
# secrets-inject.sh — Inject credentials into a single agent on a VM.
#
# Writes secrets to the agent's tmpfs directory (/run/secrets/agent-N/) via SSH.
# Secrets are written using heredocs over the SSH connection so they never appear
# in process arguments (ps output). HISTFILE is disabled for all SSH sessions.
#
# Usage:
#   secrets-inject.sh <vm-ip> <agent-index> [--github-token TOKEN] [--claude-auth TOKEN]
#
# Example:
#   secrets-inject.sh 1.2.3.4 0 --github-token ghp_xxx --claude-auth sk-ant-xxx
#
# Requirements:
#   - SSH key for root access already loaded in ssh-agent (run secrets-init.sh first)

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '[secrets-inject] %s\n' "$*" >&2; }
die()  { printf '[secrets-inject] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'USAGE'
Usage: secrets-inject.sh <vm-ip> <agent-index> [options]

Options:
  --github-token TOKEN   GitHub personal access token
  --claude-auth TOKEN    Claude authentication token (API key or subscription token)

At least one of --github-token or --claude-auth must be provided.
USAGE
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

[[ $# -ge 2 ]] || usage

VM_IP="$1"
AGENT_INDEX="$2"
shift 2

GITHUB_TOKEN=""
CLAUDE_AUTH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-token)
      GITHUB_TOKEN="$2"
      shift 2
      ;;
    --claude-auth)
      CLAUDE_AUTH="$2"
      shift 2
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

# Validate inputs
[[ "${AGENT_INDEX}" =~ ^[0-3]$ ]] || die "agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})"
[[ -n "${VM_IP}" ]] || die "vm-ip is required"
[[ -n "${GITHUB_TOKEN}" || -n "${CLAUDE_AUTH}" ]] \
  || die "At least one of --github-token or --claude-auth must be provided"

AGENT_USER="agent-${AGENT_INDEX}"
SECRETS_DIR="/run/secrets/${AGENT_USER}"

# ---------------------------------------------------------------------------
# SSH helper — HISTFILE disabled for all sessions to prevent secret leakage
# ---------------------------------------------------------------------------

# Common SSH flags: batch mode, key-only auth, no stdin consumption.
SSH_OPTS=(
  -n
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=10
)

vm_exec() {
  HISTFILE=/dev/null ssh "${SSH_OPTS[@]}" "root@${VM_IP}" "$@"
}

# Variant that reads stdin (for piping secrets); -n flag must be omitted.
SSH_STDIN_OPTS=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=10
)

vm_exec_stdin() {
  HISTFILE=/dev/null ssh "${SSH_STDIN_OPTS[@]}" "root@${VM_IP}" "$@"
}

# ---------------------------------------------------------------------------
# Verify connectivity
# ---------------------------------------------------------------------------

log "Verifying SSH connectivity to ${VM_IP}"
vm_exec true || die "Cannot SSH to ${VM_IP} — check that secrets-init.sh has been run"

# ---------------------------------------------------------------------------
# Ensure secrets directory exists with correct permissions
# ---------------------------------------------------------------------------

log "Ensuring ${SECRETS_DIR} exists with correct permissions"

# Remote script body stored in a variable so it can be passed via stdin.
# Variables are expanded on the client side before sending — this is intentional
# for non-secret values like AGENT_USER and SECRETS_DIR.
SETUP_SCRIPT="$(cat <<SETUP
set -euo pipefail
if mountpoint -q /run 2>/dev/null; then
  FSTYPE=\"\$(findmnt -n -o FSTYPE /run 2>/dev/null || true)\"
  if [[ \"\${FSTYPE}\" != \"tmpfs\" ]]; then
    echo \"WARNING: /run is not tmpfs (found: \${FSTYPE})\" >&2
  fi
fi
mkdir -p '${SECRETS_DIR}'
chmod 0700 '${SECRETS_DIR}'
chown '${AGENT_USER}:${AGENT_USER}' '${SECRETS_DIR}'
SETUP
)"

printf '%s' "${SETUP_SCRIPT}" | vm_exec_stdin bash

# ---------------------------------------------------------------------------
# Inject secrets via stdin (never in command arguments)
# ---------------------------------------------------------------------------

inject_secret() {
  local filename="$1"
  local content="$2"
  local filepath="${SECRETS_DIR}/${filename}"

  log "  Writing ${filepath}"

  # The remote script reads the secret from stdin.
  # The secret is piped in and never appears in command arguments or ps output.
  # The remote script body is passed as a -c argument so stdin is free for the secret.
  local remote_script
  remote_script="$(cat <<RSCRIPT
set -euo pipefail
FILEPATH='${filepath}'
AGENT='${AGENT_USER}'
SECRET="\$(cat)"
printf '%s' "\${SECRET}" > "\${FILEPATH}"
chmod 0600 "\${FILEPATH}"
chown "\${AGENT}:\${AGENT}" "\${FILEPATH}"
RSCRIPT
)"

  printf '%s' "${content}" \
    | HISTFILE=/dev/null ssh "${SSH_STDIN_OPTS[@]}" "root@${VM_IP}" bash -c "${remote_script}"
}

if [[ -n "${GITHUB_TOKEN}" ]]; then
  inject_secret "github_token" "${GITHUB_TOKEN}"
fi

if [[ -n "${CLAUDE_AUTH}" ]]; then
  inject_secret "claude_auth" "${CLAUDE_AUTH}"
fi

# ---------------------------------------------------------------------------
# Write env file that the agent sources at startup
# ---------------------------------------------------------------------------

log "  Writing ${SECRETS_DIR}/env"

ENV_SCRIPT="$(cat <<ENVSCRIPT
set -euo pipefail
ENV_FILE='${SECRETS_DIR}/env'
{
  printf '# Auto-generated by secrets-inject.sh -- do not edit\n'
  printf '# Source this file to load agent credentials into the current shell.\n'
  printf '\n'
ENVSCRIPT
)"

if [[ -n "${GITHUB_TOKEN}" ]]; then
  ENV_SCRIPT+="$(cat <<GITHUB
  printf 'export GITHUB_TOKEN="\$(cat ${SECRETS_DIR}/github_token)"\n'
GITHUB
)"
fi

if [[ -n "${CLAUDE_AUTH}" ]]; then
  ENV_SCRIPT+="$(cat <<CLAUDE
  printf 'export ANTHROPIC_API_KEY="\$(cat ${SECRETS_DIR}/claude_auth)"\n'
  printf '# Uncomment for subscription-mode auth:\n'
  printf '# export CLAUDE_AUTH_TOKEN="\$(cat ${SECRETS_DIR}/claude_auth)"\n'
CLAUDE
)"
fi

ENV_SCRIPT+="$(cat <<ENVEND
} > "\${ENV_FILE}"
chmod 0600 "\${ENV_FILE}"
chown '${AGENT_USER}:${AGENT_USER}' "\${ENV_FILE}"
ENVEND
)"

printf '%s' "${ENV_SCRIPT}" | vm_exec_stdin bash

# ---------------------------------------------------------------------------
# Verify injection
# ---------------------------------------------------------------------------

log "Verifying injection for ${AGENT_USER}"

# Build a list of expected secret files to verify
EXPECTED_FILES=()
[[ -n "${GITHUB_TOKEN}" ]] && EXPECTED_FILES+=("github_token")
[[ -n "${CLAUDE_AUTH}" ]]  && EXPECTED_FILES+=("claude_auth")
EXPECTED_FILES+=("env")

VERIFY_SCRIPT="$(cat <<VERIFYSCRIPT
set -euo pipefail
ALL_OK=true
AGENT_USER='${AGENT_USER}'
SECRETS_DIR='${SECRETS_DIR}'
VERIFYSCRIPT
)"

for f in "${EXPECTED_FILES[@]}"; do
  VERIFY_SCRIPT+="$(cat <<VFILE
fp="\${SECRETS_DIR}/${f}"
if [[ ! -f "\${fp}" ]]; then
  printf 'FAIL: %s does not exist\n' "\${fp}" >&2
  ALL_OK=false
else
  perms="\$(stat -c '%a' "\${fp}" 2>/dev/null || stat -f '%OLp' "\${fp}" 2>/dev/null)"
  owner="\$(stat -c '%U' "\${fp}" 2>/dev/null || stat -f '%Su' "\${fp}" 2>/dev/null)"
  if [[ "\${perms}" != "600" ]]; then
    printf 'FAIL: %s has permissions %s (expected 600)\n' "\${fp}" "\${perms}" >&2
    ALL_OK=false
  fi
  if [[ "\${owner}" != "\${AGENT_USER}" ]]; then
    printf 'FAIL: %s owned by %s (expected %s)\n' "\${fp}" "\${owner}" "\${AGENT_USER}" >&2
    ALL_OK=false
  fi
fi
VFILE
)"
done

VERIFY_SCRIPT+='
if [[ "${ALL_OK}" == "true" ]]; then
  printf "OK: all secrets verified\n" >&2
else
  exit 1
fi'

printf '%s' "${VERIFY_SCRIPT}" | vm_exec_stdin bash

log "secrets-inject complete for ${AGENT_USER} on ${VM_IP}"
