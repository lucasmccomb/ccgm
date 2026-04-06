#!/usr/bin/env bash
# workspace-setup.sh — Set up an agent workspace on a Hetzner Cloud VM.
#
# Usage:
#   workspace-setup.sh <vm-ip> <agent-index> <repo-url> [--branch BRANCH]
#
# Arguments:
#   vm-ip         Public IP of the Hetzner Cloud VM
#   agent-index   0-3, selects agent-N user on the VM
#   repo-url      HTTPS URL of the target repo (e.g. https://github.com/owner/repo)
#   --branch      Optional branch to check out after clone (default: main)
#
# Requires:
#   - SSH access to the VM as root (key in ~/.ssh/id_ed25519 or SSH_KEY_PATH)
#   - /run/secrets/agent-N/github_token populated on the VM before this runs
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <vm-ip> <agent-index> <repo-url> [--branch BRANCH]" >&2
  exit 1
fi

VM_IP="$1"
AGENT_INDEX="$2"
REPO_URL="$3"
shift 3

BRANCH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# Validate agent index
if ! [[ "$AGENT_INDEX" =~ ^[0-3]$ ]]; then
  echo "Error: agent-index must be 0, 1, 2, or 3 (got: $AGENT_INDEX)" >&2
  exit 1
fi

AGENT_USER="agent-${AGENT_INDEX}"
AGENT_HOME="/home/${AGENT_USER}"
WORKSPACE_DIR="${AGENT_HOME}/workspace"
SECRETS_DIR="/run/secrets/${AGENT_USER}"
SSH_KEY="${SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519}"

# Extract repo name from URL (strip .git suffix if present)
REPO_NAME=$(basename "${REPO_URL}" .git)

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

echo "==> Setting up workspace for ${AGENT_USER} on ${VM_IP}"

# ---------------------------------------------------------------------------
# Step 1: Create workspace directory
# ---------------------------------------------------------------------------
echo "--> Creating workspace directory"
ssh_root "mkdir -p '${WORKSPACE_DIR}' && chown '${AGENT_USER}:${AGENT_USER}' '${WORKSPACE_DIR}'"

# ---------------------------------------------------------------------------
# Step 2: Clone the repo using the agent's GitHub token
# ---------------------------------------------------------------------------
echo "--> Cloning ${REPO_URL}"
CLONE_DIR="${WORKSPACE_DIR}/${REPO_NAME}"

# Build a token-authenticated URL from the plain HTTPS URL.
# The token is read on the VM from /run/secrets/agent-N/github_token — it
# never appears in the SSH command itself or in local shell variables.
CLONE_SCRIPT=$(cat <<'SCRIPT'
set -euo pipefail
AGENT_USER="__AGENT_USER__"
REPO_URL="__REPO_URL__"
CLONE_DIR="__CLONE_DIR__"
SECRETS_DIR="__SECRETS_DIR__"

TOKEN_FILE="${SECRETS_DIR}/github_token"
if [[ ! -f "${TOKEN_FILE}" ]]; then
  echo "Error: token file not found at ${TOKEN_FILE}" >&2
  exit 1
fi
GIT_TOKEN=$(cat "${TOKEN_FILE}")

# Inject token into HTTPS URL: https://<token>@github.com/owner/repo
AUTH_URL="${REPO_URL/https:\/\//https://${GIT_TOKEN}@}"

if [[ -d "${CLONE_DIR}/.git" ]]; then
  echo "Repo already cloned at ${CLONE_DIR}, skipping"
else
  git clone "${AUTH_URL}" "${CLONE_DIR}"
fi
SCRIPT
)

CLONE_SCRIPT="${CLONE_SCRIPT//__AGENT_USER__/$AGENT_USER}"
CLONE_SCRIPT="${CLONE_SCRIPT//__REPO_URL__/$REPO_URL}"
CLONE_SCRIPT="${CLONE_SCRIPT//__CLONE_DIR__/$CLONE_DIR}"
CLONE_SCRIPT="${CLONE_SCRIPT//__SECRETS_DIR__/$SECRETS_DIR}"

ssh_root "su - ${AGENT_USER} -c 'bash -s'" <<< "${CLONE_SCRIPT}"

# ---------------------------------------------------------------------------
# Step 3: Configure git identity for the agent
# ---------------------------------------------------------------------------
echo "--> Configuring git identity"
ssh_agent "git -C '${CLONE_DIR}' config user.name 'CCGM Agent ${AGENT_INDEX}'"
ssh_agent "git -C '${CLONE_DIR}' config user.email 'ccgm-agent-${AGENT_INDEX}@dispatch.local'"

# ---------------------------------------------------------------------------
# Step 4: Checkout branch (if specified)
# ---------------------------------------------------------------------------
if [[ -n "${BRANCH}" ]]; then
  echo "--> Checking out branch: ${BRANCH}"
  ssh_agent "git -C '${CLONE_DIR}' checkout '${BRANCH}'"
fi

# ---------------------------------------------------------------------------
# Step 5: Set up CCGM config (Claude Code settings for headless mode)
# ---------------------------------------------------------------------------
echo "--> Writing Claude Code settings"
CLAUDE_DIR="${AGENT_HOME}/.claude"
ssh_root "mkdir -p '${CLAUDE_DIR}' && chown '${AGENT_USER}:${AGENT_USER}' '${CLAUDE_DIR}'"

# Write settings.json enabling dangerously-skip-permissions for headless runs.
# See: https://docs.anthropic.com/en/docs/claude-code/settings
SETTINGS_JSON='{
  "permissions": {
    "allow": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    "deny": []
  },
  "dangerouslySkipPermissions": true
}'

ssh_root "printf '%s\n' '${SETTINGS_JSON}' > '${CLAUDE_DIR}/settings.json' && chown '${AGENT_USER}:${AGENT_USER}' '${CLAUDE_DIR}/settings.json'"

# Symlink global CCGM rules from /opt/ccgm if the directory exists on the VM
RULES_SYMLINK="${CLAUDE_DIR}/rules"
ssh_root "
if [[ -d /opt/ccgm/rules && ! -e '${RULES_SYMLINK}' ]]; then
  ln -s /opt/ccgm/rules '${RULES_SYMLINK}'
  chown -h '${AGENT_USER}:${AGENT_USER}' '${RULES_SYMLINK}'
  echo 'Symlinked /opt/ccgm/rules -> ${RULES_SYMLINK}'
else
  echo 'Skipping rules symlink (/opt/ccgm/rules not found or link already exists)'
fi
"

# ---------------------------------------------------------------------------
# Step 6: Verify
# ---------------------------------------------------------------------------
echo "--> Verifying workspace"
ssh_agent "git -C '${CLONE_DIR}' status"
ssh_agent "git -C '${CLONE_DIR}' config user.email"

echo "==> Workspace setup complete: ${AGENT_USER}@${VM_IP} -> ${CLONE_DIR}"
