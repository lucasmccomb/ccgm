#!/usr/bin/env bash
# workspace-cleanup.sh — Remove workspace artifacts from one or all agent users on a VM.
#
# Usage:
#   workspace-cleanup.sh <vm-ip> <agent-index>
#   workspace-cleanup.sh <vm-ip> --all
#
# Arguments:
#   vm-ip         Public IP of the Hetzner Cloud VM
#   agent-index   0-3, selects agent-N user to clean up
#   --all         Clean up all 4 agent users on the VM
#
# What is removed (per agent):
#   - /home/agent-N/workspace/    (repo clone)
#   - /home/agent-N/assignment.json
#   - /home/agent-N/run.log
#
# What is preserved:
#   - /home/agent-N/              (home directory)
#   - /home/agent-N/.gitconfig    (identity config, reused on next assignment)
#   - /home/agent-N/.claude/      (CCGM settings, reused on next assignment)
#   - /home/agent-N/.ssh/         (SSH config)
#   - /home/agent-N/.bashrc
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <vm-ip> <agent-index>" >&2
  echo "       $0 <vm-ip> --all" >&2
  exit 1
fi

VM_IP="$1"
AGENT_ARG="$2"
SSH_KEY="${SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519}"
AGENTS_PER_VM=4

# Build list of agent indexes to clean
declare -a AGENT_INDEXES
if [[ "${AGENT_ARG}" == "--all" ]]; then
  for i in $(seq 0 $(( AGENTS_PER_VM - 1 ))); do
    AGENT_INDEXES+=("$i")
  done
else
  if ! [[ "${AGENT_ARG}" =~ ^[0-3]$ ]]; then
    echo "Error: agent-index must be 0, 1, 2, or 3 (got: ${AGENT_ARG})" >&2
    exit 1
  fi
  AGENT_INDEXES=("${AGENT_ARG}")
fi

# ---------------------------------------------------------------------------
# Helper: run a command on the VM as root
# ---------------------------------------------------------------------------
ssh_root() {
  ssh -i "${SSH_KEY}" \
      -o StrictHostKeyChecking=accept-new \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      "root@${VM_IP}" "$@"
}

# ---------------------------------------------------------------------------
# Clean one agent
# ---------------------------------------------------------------------------
cleanup_one() {
  local agent_index="$1"
  local agent_user="agent-${agent_index}"
  local agent_home="/home/${agent_user}"
  local workspace_dir="${agent_home}/workspace"
  local assignment_file="${agent_home}/assignment.json"
  local run_log="${agent_home}/run.log"

  echo "==> Cleaning up ${agent_user}@${VM_IP}"

  # Stop any running agent process owned by this user before removing files
  local pids
  pids=$(ssh_root "pgrep -u '${agent_user}' -f 'claude' 2>/dev/null || true")
  if [[ -n "${pids}" ]]; then
    echo "--> Stopping running agent process(es): ${pids}"
    ssh_root "pkill -u '${agent_user}' -f 'claude' 2>/dev/null || true"
    # Give process a moment to terminate
    sleep 2
  fi

  # Remove workspace (repo clone)
  if ssh_root "test -d '${workspace_dir}'"; then
    echo "--> Removing workspace: ${workspace_dir}"
    ssh_root "rm -rf '${workspace_dir}'"
  else
    echo "--> Workspace not found, skipping: ${workspace_dir}"
  fi

  # Remove assignment.json
  if ssh_root "test -f '${assignment_file}'"; then
    echo "--> Removing assignment file: ${assignment_file}"
    ssh_root "rm -f '${assignment_file}'"
  else
    echo "--> Assignment file not found, skipping"
  fi

  # Remove run log
  if ssh_root "test -f '${run_log}'"; then
    echo "--> Removing run log: ${run_log}"
    ssh_root "rm -f '${run_log}'"
  else
    echo "--> Run log not found, skipping"
  fi

  echo "--> ${agent_user} cleaned up"
}

# ---------------------------------------------------------------------------
# Execute cleanup
# ---------------------------------------------------------------------------
for agent_index in "${AGENT_INDEXES[@]}"; do
  cleanup_one "${agent_index}"
done

echo ""
echo "==> Cleanup complete on ${VM_IP} (agents: ${AGENT_INDEXES[*]})"
