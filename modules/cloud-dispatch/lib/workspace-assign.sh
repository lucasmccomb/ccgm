#!/usr/bin/env bash
# workspace-assign.sh — Assign a GitHub issue to an agent on a VM.
#
# Usage:
#   workspace-assign.sh <vm-ip> <agent-index> <issue-number> <issue-title> \
#     [--repo OWNER/REPO] [--max-turns N]
#
# Arguments:
#   vm-ip          Public IP of the Hetzner Cloud VM
#   agent-index    0-3, selects agent-N user on the VM
#   issue-number   GitHub issue number to assign
#   issue-title    Issue title (used to build the branch slug)
#   --repo         GitHub repo in owner/repo format (required)
#   --max-turns    Maximum agent turns before stopping (default: 200)
#
# Side effects:
#   - Writes /home/agent-N/assignment.json on the VM
#   - Creates a feature branch in /home/agent-N/workspace/<repo>
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 4 ]]; then
  echo "Usage: $0 <vm-ip> <agent-index> <issue-number> <issue-title> [--repo OWNER/REPO] [--max-turns N]" >&2
  exit 1
fi

VM_IP="$1"
AGENT_INDEX="$2"
ISSUE_NUMBER="$3"
ISSUE_TITLE="$4"
shift 4

REPO=""
MAX_TURNS=200
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="$2"
      shift 2
      ;;
    --max-turns)
      MAX_TURNS="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${REPO}" ]]; then
  echo "Error: --repo OWNER/REPO is required" >&2
  exit 1
fi

if ! [[ "$AGENT_INDEX" =~ ^[0-3]$ ]]; then
  echo "Error: agent-index must be 0, 1, 2, or 3 (got: $AGENT_INDEX)" >&2
  exit 1
fi

if ! [[ "$ISSUE_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Error: issue-number must be a positive integer (got: $ISSUE_NUMBER)" >&2
  exit 1
fi

if ! [[ "$MAX_TURNS" =~ ^[0-9]+$ ]]; then
  echo "Error: --max-turns must be a positive integer (got: $MAX_TURNS)" >&2
  exit 1
fi

AGENT_USER="agent-${AGENT_INDEX}"
AGENT_HOME="/home/${AGENT_USER}"
REPO_NAME=$(basename "${REPO}")
CLONE_DIR="${AGENT_HOME}/workspace/${REPO_NAME}"
SSH_KEY="${SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519}"

# Build branch slug: lowercase, replace spaces/non-alphanumeric with hyphens,
# trim leading/trailing hyphens, collapse repeated hyphens.
SLUG=$(echo "${ISSUE_TITLE}" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/[^a-z0-9]/-/g' \
  | sed 's/-\{2,\}/-/g' \
  | sed 's/^-//;s/-$//')
BRANCH_NAME="${ISSUE_NUMBER}-${SLUG}"

# ISO 8601 timestamp (UTC)
ASSIGNED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Helper: run a command on the VM as root
# ---------------------------------------------------------------------------
ssh_root() {
  ssh -i "${SSH_KEY}" \
      -o StrictHostKeyChecking=accept-new \
      -o BatchMode=yes \
      "root@${VM_IP}" "$@"
}

# ---------------------------------------------------------------------------
# Helper: run a command on the VM as agent-N (via root su)
# ---------------------------------------------------------------------------
ssh_agent() {
  local cmd="$1"
  ssh_root "su - ${AGENT_USER} -c $(printf '%q' "$cmd")"
}

echo "==> Assigning issue #${ISSUE_NUMBER} to ${AGENT_USER} on ${VM_IP}"

# ---------------------------------------------------------------------------
# Step 1: Verify the workspace clone exists before assigning
# ---------------------------------------------------------------------------
if ! ssh_root "test -d '${CLONE_DIR}/.git'"; then
  echo "Error: workspace not found at ${CLONE_DIR}. Run workspace-setup.sh first." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Write assignment.json
# ---------------------------------------------------------------------------
echo "--> Writing assignment.json"
ASSIGNMENT_FILE="${AGENT_HOME}/assignment.json"

ASSIGNMENT_JSON=$(cat <<JSON
{
  "issue_number": ${ISSUE_NUMBER},
  "issue_title": "${ISSUE_TITLE}",
  "repo": "${REPO}",
  "branch": "${BRANCH_NAME}",
  "max_turns": ${MAX_TURNS},
  "assigned_at": "${ASSIGNED_AT}"
}
JSON
)

ssh_root "printf '%s\n' '${ASSIGNMENT_JSON}' > '${ASSIGNMENT_FILE}' && chown '${AGENT_USER}:${AGENT_USER}' '${ASSIGNMENT_FILE}'"

# ---------------------------------------------------------------------------
# Step 3: Create the feature branch
# ---------------------------------------------------------------------------
echo "--> Creating branch ${BRANCH_NAME} from origin/main"
ssh_agent "git -C '${CLONE_DIR}' fetch origin"
ssh_agent "git -C '${CLONE_DIR}' checkout -b '${BRANCH_NAME}' origin/main"

# ---------------------------------------------------------------------------
# Step 4: Verify
# ---------------------------------------------------------------------------
echo "--> Verifying branch"
CURRENT_BRANCH=$(ssh_agent "git -C '${CLONE_DIR}' rev-parse --abbrev-ref HEAD")
if [[ "${CURRENT_BRANCH}" != "${BRANCH_NAME}" ]]; then
  echo "Error: expected branch ${BRANCH_NAME}, got ${CURRENT_BRANCH}" >&2
  exit 1
fi

echo "==> Assignment complete"
echo "    Agent:  ${AGENT_USER}@${VM_IP}"
echo "    Issue:  #${ISSUE_NUMBER} - ${ISSUE_TITLE}"
echo "    Branch: ${BRANCH_NAME}"
echo "    Repo:   ${REPO}"
