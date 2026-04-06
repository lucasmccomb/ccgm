#!/usr/bin/env bash
# agent-launch.sh — Launch a single Claude Code agent in a tmux session on a VM.
#
# Usage:
#   agent-launch.sh <vm-ip> <agent-index> [--max-turns N] [--prompt PROMPT]
#
# Arguments:
#   vm-ip          Public IP of the Hetzner Cloud VM
#   agent-index    0-3, selects agent-N user on the VM
#   --max-turns    Maximum turns before Claude stops (default: 200)
#   --prompt       Override default Claude prompt
#
# The agent's assignment is read from /home/agent-N/assignment.json on the VM.
# The tmux session is named agent-N and output is appended to ~/run.log.
# On completion, ~/status is set to AGENT_DONE (or AGENT_ERROR on failure).
#
# Requires:
#   - SSH key in ~/.ssh/ccgm-dispatch-session or $SSH_KEY_PATH
#   - assignment.json already written (run workspace-assign.sh first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <vm-ip> <agent-index> [--max-turns N] [--prompt PROMPT]" >&2
  exit 1
fi

VM_IP="$1"
AGENT_INDEX="$2"
shift 2

MAX_TURNS=200
CUSTOM_PROMPT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-turns)
      MAX_TURNS="$2"
      shift 2
      ;;
    --prompt)
      CUSTOM_PROMPT="$2"
      shift 2
      ;;
    *)
      log_error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! [[ "${AGENT_INDEX}" =~ ^[0-3]$ ]]; then
  log_error "agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})"
  exit 1
fi

if ! [[ "${MAX_TURNS}" =~ ^[0-9]+$ ]]; then
  log_error "--max-turns must be a positive integer (got: ${MAX_TURNS})"
  exit 1
fi

AGENT_USER="agent-${AGENT_INDEX}"
AGENT_HOME="/home/${AGENT_USER}"
ASSIGNMENT_FILE="${AGENT_HOME}/assignment.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ssh_root() {
  # shellcheck disable=SC2206
  read -ra _opts <<< "$(ssh_opts)"
  # SC2029: expansion on client side is intentional (remote command args are built locally)
  # shellcheck disable=SC2029
  ssh "${_opts[@]}" "root@${VM_IP}" "$@"
}

# ---------------------------------------------------------------------------
# Step 1: Verify assignment.json exists
# ---------------------------------------------------------------------------
log_info "Checking assignment for ${AGENT_USER} on ${VM_IP}"

if ! ssh_root "test -f '${ASSIGNMENT_FILE}'" 2>/dev/null; then
  log_error "No assignment.json found at ${ASSIGNMENT_FILE}. Run workspace-assign.sh first."
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Read assignment fields
# ---------------------------------------------------------------------------
ASSIGNMENT=$(ssh_root "cat '${ASSIGNMENT_FILE}'" 2>/dev/null)

ISSUE_NUMBER=$(echo "${ASSIGNMENT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_number',''))" 2>/dev/null || true)
ISSUE_TITLE=$(echo "${ASSIGNMENT}"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_title',''))"  2>/dev/null || true)
REPO=$(echo "${ASSIGNMENT}"         | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('repo',''))"         2>/dev/null || true)
BRANCH=$(echo "${ASSIGNMENT}"       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('branch',''))"       2>/dev/null || true)

if [[ -z "${ISSUE_NUMBER}" || -z "${REPO}" ]]; then
  log_error "assignment.json is missing required fields (issue_number, repo)."
  exit 1
fi

REPO_NAME=$(basename "${REPO}")
WORKSPACE_DIR="${AGENT_HOME}/workspace/${REPO_NAME}"

# ---------------------------------------------------------------------------
# Step 3: Build the Claude prompt
# ---------------------------------------------------------------------------
if [[ -n "${CUSTOM_PROMPT}" ]]; then
  PROMPT="${CUSTOM_PROMPT}"
else
  PROMPT="You are an autonomous Claude Code agent. Work on GitHub issue #${ISSUE_NUMBER}: ${ISSUE_TITLE}. \
Create a branch named ${BRANCH}, implement the changes with tests, and create a PR that closes #${ISSUE_NUMBER}. \
Follow the repo's CLAUDE.md instructions. Commit with message format: #${ISSUE_NUMBER}: description."
fi

# ---------------------------------------------------------------------------
# Step 4: Kill any existing session with the same name
# ---------------------------------------------------------------------------
log_info "Launching tmux session '${AGENT_USER}' on ${VM_IP}"

# Silently kill a stale session if present
ssh_root "su - ${AGENT_USER} -c 'tmux kill-session -t ${AGENT_USER} 2>/dev/null || true'" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 5: Build the inner shell command
#
# The command runs as agent-N inside tmux. It:
#   1. Sources the injected secrets env file
#   2. cd's into the workspace clone
#   3. Runs claude in print mode
#   4. Writes AGENT_DONE (or AGENT_ERROR) to ~/status
# ---------------------------------------------------------------------------

# Single-quote the prompt for safe embedding in the outer double-quoted string.
# We use printf %q which escapes for bash, then wrap in single quotes for the
# su -c argument.
ESCAPED_PROMPT=$(printf '%s' "${PROMPT}" | sed "s/'/'\\\\''/g")

INNER_CMD="source /run/secrets/${AGENT_USER}/env 2>/dev/null || true; \
cd '${WORKSPACE_DIR}'; \
claude -p '${ESCAPED_PROMPT}' --dangerously-skip-permissions --max-turns ${MAX_TURNS} \
  >> ~/run.log 2>&1 \
  && echo AGENT_DONE > ~/status \
  || echo AGENT_ERROR > ~/status"

# Wrap inner command for su -c (needs single outer quotes)
SU_CMD="tmux new-session -d -s ${AGENT_USER} 'bash -lc $(printf '%q' "${INNER_CMD}")'"

ssh_root "su - ${AGENT_USER} -c $(printf '%q' "${SU_CMD}")"

# ---------------------------------------------------------------------------
# Step 6: Verify the session was created
# ---------------------------------------------------------------------------
if ssh_root "su - ${AGENT_USER} -c 'tmux has-session -t ${AGENT_USER} 2>/dev/null'" 2>/dev/null; then
  log_success "Session '${AGENT_USER}' is running on ${VM_IP}"
  echo "    Agent:  ${AGENT_USER}@${VM_IP}"
  echo "    Issue:  #${ISSUE_NUMBER} - ${ISSUE_TITLE}"
  echo "    Branch: ${BRANCH}"
  echo "    Repo:   ${REPO}"
else
  log_error "tmux session '${AGENT_USER}' did not start on ${VM_IP}"
  exit 1
fi
