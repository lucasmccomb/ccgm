#!/usr/bin/env bash
# workspace-collect.sh — Collect results from agent workspaces.
#
# Usage:
#   workspace-collect.sh --all
#   workspace-collect.sh <vm-ip> <agent-index>
#
# Options:
#   --all         Collect from all running ccgm-agent-* VMs (all 4 agents each)
#   --json        Emit machine-readable JSON instead of formatted text
#   --log-lines N Number of log tail lines to include (default: 50)
#
# Requires:
#   - hcloud CLI (when --all is used)
#   - SSH key in ~/.ssh/id_ed25519 or $SSH_KEY_PATH
set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 --all [--json] [--log-lines N]" >&2
  echo "       $0 <vm-ip> <agent-index> [--json] [--log-lines N]" >&2
  exit 1
fi

COLLECT_ALL=false
VM_IP=""
AGENT_INDEX=""
JSON_OUTPUT=false
LOG_LINES=50

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      COLLECT_ALL=true
      shift
      ;;
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --log-lines)
      LOG_LINES="$2"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "${VM_IP}" ]]; then
        VM_IP="$1"
      elif [[ -z "${AGENT_INDEX}" ]]; then
        AGENT_INDEX="$1"
      else
        echo "Unexpected argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ "${COLLECT_ALL}" == "false" ]]; then
  if [[ -z "${VM_IP}" || -z "${AGENT_INDEX}" ]]; then
    echo "Error: provide --all or both <vm-ip> and <agent-index>" >&2
    exit 1
  fi
  if ! [[ "${AGENT_INDEX}" =~ ^[0-3]$ ]]; then
    echo "Error: agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})" >&2
    exit 1
  fi
fi

SSH_KEY="${SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519}"
AGENTS_PER_VM=4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ssh_root() {
  local ip="$1"; shift
  ssh -i "${SSH_KEY}" \
      -o StrictHostKeyChecking=accept-new \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      "root@${ip}" "$@" 2>/dev/null
}

# Collect data for one agent and emit a result block
collect_one() {
  local vm_ip="$1"
  local agent_index="$2"
  local agent_user="agent-${agent_index}"
  local agent_home="/home/${agent_user}"
  local assignment_file="${agent_home}/assignment.json"
  local run_log="${agent_home}/run.log"

  # --- assignment ---
  local issue_number="" issue_title="" repo="" branch="" assigned_at=""
  if ssh_root "${vm_ip}" "test -f '${assignment_file}'" 2>/dev/null; then
    local assignment
    assignment=$(ssh_root "${vm_ip}" "cat '${assignment_file}'" 2>/dev/null || echo "{}")
    issue_number=$(echo "${assignment}" | grep -o '"issue_number":[^,}]*' | sed 's/"issue_number"://' | tr -d ' "')
    issue_title=$(echo "${assignment}" | grep -o '"issue_title":"[^"]*"' | sed 's/"issue_title":"//;s/"$//')
    repo=$(echo "${assignment}" | grep -o '"repo":"[^"]*"' | sed 's/"repo":"//;s/"$//')
    branch=$(echo "${assignment}" | grep -o '"branch":"[^"]*"' | sed 's/"branch":"//;s/"$//')
    assigned_at=$(echo "${assignment}" | grep -o '"assigned_at":"[^"]*"' | sed 's/"assigned_at":"//;s/"$//')
  fi

  # --- git state ---
  local current_branch="" last_commit_sha="" last_commit_msg=""
  local workspace_dir="${agent_home}/workspace"

  if [[ -n "${repo}" ]]; then
    local repo_name
    repo_name=$(basename "${repo}")
    local clone_dir="${workspace_dir}/${repo_name}"
    if ssh_root "${vm_ip}" "test -d '${clone_dir}/.git'" 2>/dev/null; then
      current_branch=$(ssh_root "${vm_ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} rev-parse --abbrev-ref HEAD'" 2>/dev/null || echo "unknown")
      last_commit_sha=$(ssh_root "${vm_ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} rev-parse --short HEAD'" 2>/dev/null || echo "unknown")
      last_commit_msg=$(ssh_root "${vm_ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} log -1 --pretty=%s'" 2>/dev/null || echo "")
    fi
  fi

  # --- PR detection ---
  local pr_url=""
  if [[ -n "${branch}" && -n "${repo}" ]]; then
    # Check gh CLI on the VM, or fall back to grepping the run log
    pr_url=$(ssh_root "${vm_ip}" \
      "su - ${agent_user} -c 'gh pr list --repo ${repo} --head ${branch} --json url --jq .[0].url 2>/dev/null'" \
      2>/dev/null || true)
    if [[ -z "${pr_url}" && -f "${run_log}" ]]; then
      pr_url=$(ssh_root "${vm_ip}" "grep -oE 'https://github.com/[^ ]*/pull/[0-9]+' '${run_log}' | tail -1" 2>/dev/null || true)
    fi
  fi

  # --- agent process status ---
  local agent_pid="" agent_status="unknown"
  agent_pid=$(ssh_root "${vm_ip}" \
    "pgrep -u ${agent_user} -f 'claude' | head -1" 2>/dev/null || true)
  if [[ -n "${agent_pid}" ]]; then
    agent_status="running"
  elif [[ -f "${run_log}" ]]; then
    # Check last exit code if logged
    local last_exit
    last_exit=$(ssh_root "${vm_ip}" "tail -1 '${run_log}'" 2>/dev/null || true)
    if echo "${last_exit}" | grep -qi "exit.*0\|completed\|success"; then
      agent_status="completed"
    elif echo "${last_exit}" | grep -qi "exit\|error\|fail"; then
      agent_status="failed"
    else
      agent_status="idle"
    fi
  fi

  # --- run log tail ---
  local log_tail=""
  if ssh_root "${vm_ip}" "test -f '${run_log}'" 2>/dev/null; then
    log_tail=$(ssh_root "${vm_ip}" "tail -n ${LOG_LINES} '${run_log}'" 2>/dev/null || true)
  fi

  # --- VM name (best effort) ---
  local vm_name=""
  if command -v hcloud &>/dev/null; then
    vm_name=$(hcloud server list --output columns=name,ipv4 2>/dev/null \
      | awk -v ip="${vm_ip}" '$2==ip {print $1}' || true)
  fi
  [[ -z "${vm_name}" ]] && vm_name="${vm_ip}"

  # ---------------------------------------------------------------------------
  # Output
  # ---------------------------------------------------------------------------
  if [[ "${JSON_OUTPUT}" == "true" ]]; then
    # Escape strings for JSON (basic escaping)
    json_escape() { printf '%s' "$1" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "$1"; }
    printf '{\n'
    printf '  "vm": %s,\n'            "$(json_escape "${vm_name}")"
    printf '  "agent": %s,\n'         "$(json_escape "${agent_user}")"
    printf '  "issue_number": %s,\n'  "${issue_number:-null}"
    printf '  "issue_title": %s,\n'   "$(json_escape "${issue_title}")"
    printf '  "repo": %s,\n'          "$(json_escape "${repo}")"
    printf '  "branch": %s,\n'        "$(json_escape "${branch}")"
    printf '  "current_branch": %s,\n' "$(json_escape "${current_branch}")"
    printf '  "last_commit": %s,\n'   "$(json_escape "${last_commit_sha} ${last_commit_msg}")"
    printf '  "pr_url": %s,\n'        "$(json_escape "${pr_url}")"
    printf '  "status": %s,\n'        "$(json_escape "${agent_status}")"
    printf '  "assigned_at": %s\n'    "$(json_escape "${assigned_at}")"
    printf '}\n'
  else
    echo "---"
    printf "Agent:       %s / %s\n" "${vm_name}" "${agent_user}"
    if [[ -n "${issue_number}" ]]; then
      printf "Issue:       #%s - %s\n" "${issue_number}" "${issue_title}"
      printf "Repo:        %s\n" "${repo}"
    else
      printf "Issue:       (no assignment)\n"
    fi
    printf "Branch:      %s\n" "${branch:-${current_branch:-(none)}}"
    printf "Status:      %s\n" "${agent_status}"
    if [[ -n "${pr_url}" ]]; then
      printf "PR:          %s\n" "${pr_url}"
    fi
    if [[ -n "${last_commit_sha}" && "${last_commit_sha}" != "unknown" ]]; then
      printf "Last commit: %s \"%s\"\n" "${last_commit_sha}" "${last_commit_msg}"
    fi
    if [[ -n "${assigned_at}" ]]; then
      printf "Assigned:    %s\n" "${assigned_at}"
    fi
    if [[ -n "${log_tail}" ]]; then
      echo ""
      echo "Log (last ${LOG_LINES} lines):"
      while IFS= read -r log_line; do printf '  %s\n' "${log_line}"; done <<< "${log_tail}"
    fi
    echo ""
  fi
}

# ---------------------------------------------------------------------------
# Single agent
# ---------------------------------------------------------------------------
if [[ "${COLLECT_ALL}" == "false" ]]; then
  collect_one "${VM_IP}" "${AGENT_INDEX}"
  exit 0
fi

# ---------------------------------------------------------------------------
# All agents across all running VMs
# ---------------------------------------------------------------------------
if ! command -v hcloud &>/dev/null; then
  echo "Error: hcloud CLI is required for --all mode" >&2
  exit 1
fi

mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status | awk '$2=="running" && /ccgm-agent/ {print $1}' | sort)

if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
  echo "No running ccgm-agent-* VMs found." >&2
  exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
  echo "["
  first=true
fi

for vm_name in "${VM_NAMES[@]}"; do
  vm_ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
  for agent_index in $(seq 0 $(( AGENTS_PER_VM - 1 ))); do
    if [[ "${JSON_OUTPUT}" == "true" && "${first}" != "true" ]]; then
      echo ","
    fi
    collect_one "${vm_ip}" "${agent_index}"
    first=false
  done
done

if [[ "${JSON_OUTPUT}" == "true" ]]; then
  echo "]"
fi
