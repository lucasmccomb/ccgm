#!/usr/bin/env bash
# secrets-inject-all.sh — Inject credentials into all agents across all running VMs.
#
# Discovers running ccgm-agent-* Hetzner VMs, then calls secrets-inject.sh for
# each agent (0-3) on each VM. Reports per-agent success/failure.
#
# Usage:
#   secrets-inject-all.sh --github-token TOKEN [--claude-auth TOKEN]
#
# Requirements:
#   - hcloud CLI authenticated
#   - SSH key loaded in ssh-agent (run secrets-init.sh first)
#   - secrets-inject.sh in the same directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INJECT_SCRIPT="${SCRIPT_DIR}/secrets-inject.sh"
AGENT_COUNT=4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf '[secrets-inject-all] %s\n' "$*" >&2; }
die()  { printf '[secrets-inject-all] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'USAGE'
Usage: secrets-inject-all.sh --github-token TOKEN [--claude-auth TOKEN]

Options:
  --github-token TOKEN   GitHub personal access token (required)
  --claude-auth TOKEN    Claude authentication token (optional)
USAGE
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

[[ $# -ge 1 ]] || usage

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
    --help|-h)
      usage
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -n "${GITHUB_TOKEN}" ]] || die "--github-token is required"

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

command -v hcloud >/dev/null 2>&1 || die "hcloud CLI not found in PATH"
[[ -x "${INJECT_SCRIPT}" ]] || die "secrets-inject.sh not found or not executable at ${INJECT_SCRIPT}"
[[ -n "${SSH_AUTH_SOCK:-}" ]] || die "SSH_AUTH_SOCK is not set — is ssh-agent running?"

# ---------------------------------------------------------------------------
# Discover running VMs
# ---------------------------------------------------------------------------

log "Discovering running ccgm-agent-* VMs"

# hcloud server list outputs name, status, public IP etc.
# Filter for VMs named ccgm-agent-* that are in 'running' status.
RUNNING_VMS="$(hcloud server list --selector 'ccgm-role=agent' --output columns=name,public_net 2>/dev/null \
  | tail -n +2 \
  | awk '{print $1, $2}' \
  || true)"

# Fallback: list by name prefix if no label selector works
if [[ -z "${RUNNING_VMS}" ]]; then
  log "Label selector returned no results; falling back to name-prefix discovery"
  RUNNING_VMS="$(hcloud server list --output json 2>/dev/null \
    | jq -r '.[] | select(.name | startswith("ccgm-agent")) | select(.status == "running") | "\(.name) \(.public_net.ipv4.ip)"' \
    || true)"
fi

if [[ -z "${RUNNING_VMS}" ]]; then
  log "No running ccgm-agent-* VMs found."
  exit 0
fi

VM_COUNT="$(printf '%s\n' "${RUNNING_VMS}" | grep -c . || true)"
log "Found ${VM_COUNT} VM(s)"

# ---------------------------------------------------------------------------
# Inject secrets into each VM / agent combination
# ---------------------------------------------------------------------------

PASS=0
FAIL=0
FAIL_DETAILS=()

while IFS=' ' read -r vm_name vm_ip; do
  [[ -z "${vm_name}" ]] && continue
  log "Processing VM: ${vm_name} (${vm_ip})"

  for i in $(seq 0 $((AGENT_COUNT - 1))); do
    INJECT_ARGS=("${vm_ip}" "${i}" "--github-token" "${GITHUB_TOKEN}")
    [[ -n "${CLAUDE_AUTH}" ]] && INJECT_ARGS+=("--claude-auth" "${CLAUDE_AUTH}")

    if bash "${INJECT_SCRIPT}" "${INJECT_ARGS[@]}" 2>&1; then
      PASS=$(( PASS + 1 ))
      log "  agent-${i}: OK"
    else
      FAIL=$(( FAIL + 1 ))
      FAIL_DETAILS+=("${vm_name}/agent-${i}")
      log "  agent-${i}: FAILED"
    fi
  done
done <<< "${RUNNING_VMS}"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

TOTAL=$(( PASS + FAIL ))
log ""
log "Injection complete: ${PASS}/${TOTAL} agents succeeded"

if [[ "${FAIL}" -gt 0 ]]; then
  log "Failed agents:"
  for detail in "${FAIL_DETAILS[@]}"; do
    log "  - ${detail}"
  done
  exit 1
fi
