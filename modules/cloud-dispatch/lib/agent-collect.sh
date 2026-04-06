#!/usr/bin/env bash
# agent-collect.sh — Collect run results from one or all Claude Code agents.
#
# Usage:
#   agent-collect.sh --all [--json] [--log-lines N]
#   agent-collect.sh <vm-ip> <agent-index> [--json] [--log-lines N]
#
# Output:
#   Formatted summary table (or JSON with --json) containing:
#     - Agent status (from ~/status)
#     - PR URL (from run.log or gh CLI)
#     - Branch name and last commit
#     - Exit status
#     - Last N lines of run.log (default: 20)
#
# Requires:
#   - hcloud CLI (when --all is used)
#   - SSH key in ~/.ssh/ccgm-dispatch-session or $SSH_KEY_PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

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
LOG_LINES=20

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
      log_error "Unknown option: $1"
      exit 1
      ;;
    *)
      if [[ -z "${VM_IP}" ]]; then
        VM_IP="$1"
      elif [[ -z "${AGENT_INDEX}" ]]; then
        AGENT_INDEX="$1"
      else
        log_error "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ "${COLLECT_ALL}" == "false" ]]; then
  if [[ -z "${VM_IP}" || -z "${AGENT_INDEX}" ]]; then
    log_error "Provide --all or both <vm-ip> and <agent-index>"
    exit 1
  fi
  if ! [[ "${AGENT_INDEX}" =~ ^[0-3]$ ]]; then
    log_error "agent-index must be 0, 1, 2, or 3 (got: ${AGENT_INDEX})"
    exit 1
  fi
fi

if ! [[ "${LOG_LINES}" =~ ^[0-9]+$ ]]; then
  log_error "--log-lines must be a positive integer (got: ${LOG_LINES})"
  exit 1
fi

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
if [[ "${COLLECT_ALL}" == "true" ]]; then
  require_cmd hcloud
  if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
    log_error "HCLOUD_TOKEN is not set."
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ssh_root_quiet() {
  local ip="$1"; shift
  # shellcheck disable=SC2206
  read -ra _opts <<< "$(ssh_opts)"
  # SC2029: expansion on client side is intentional
  # shellcheck disable=SC2029
  ssh "${_opts[@]}" "root@${ip}" "$@" 2>/dev/null
}

json_escape() {
  printf '%s' "$1" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null \
    || printf '"%s"' "$1"
}

collect_one() {
  local ip="$1"
  local vm_name="$2"
  local idx="$3"
  local agent_user="agent-${idx}"
  local agent_home="/home/${agent_user}"
  local assignment_file="${agent_home}/assignment.json"
  local status_file="${agent_home}/status"
  local run_log="${agent_home}/run.log"

  # --- assignment ---
  local issue_number="" issue_title="" repo="" branch=""
  if ssh_root_quiet "${ip}" "test -f '${assignment_file}'"; then
    local raw_assignment
    raw_assignment=$(ssh_root_quiet "${ip}" "cat '${assignment_file}'" || echo "{}")
    issue_number=$(echo "${raw_assignment}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_number',''))" 2>/dev/null || true)
    issue_title=$(echo "${raw_assignment}"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_title',''))"  2>/dev/null || true)
    repo=$(echo "${raw_assignment}"         | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('repo',''))"         2>/dev/null || true)
    branch=$(echo "${raw_assignment}"       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('branch',''))"       2>/dev/null || true)
  fi

  # --- status file ---
  local agent_status="unknown"
  if ssh_root_quiet "${ip}" "test -f '${status_file}'"; then
    agent_status=$(ssh_root_quiet "${ip}" "cat '${status_file}'" 2>/dev/null | tr -d '[:space:]' || echo "unknown")
  fi

  # --- git state ---
  local current_branch="" last_commit=""
  if [[ -n "${repo}" ]]; then
    local repo_name
    repo_name=$(basename "${repo}")
    local clone_dir="${agent_home}/workspace/${repo_name}"
    if ssh_root_quiet "${ip}" "test -d '${clone_dir}/.git'"; then
      current_branch=$(ssh_root_quiet "${ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} rev-parse --abbrev-ref HEAD'" \
        2>/dev/null || echo "")
      local sha msg
      sha=$(ssh_root_quiet "${ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} rev-parse --short HEAD'" \
        2>/dev/null || echo "")
      msg=$(ssh_root_quiet "${ip}" \
        "su - ${agent_user} -c 'git -C ${clone_dir} log -1 --pretty=%s'" \
        2>/dev/null || echo "")
      [[ -n "${sha}" ]] && last_commit="${sha} ${msg}"
    fi
  fi

  # --- PR URL ---
  local pr_url=""
  if [[ -n "${branch}" && -n "${repo}" ]]; then
    pr_url=$(ssh_root_quiet "${ip}" \
      "su - ${agent_user} -c 'gh pr list --repo ${repo} --head ${branch} --json url --jq .[0].url 2>/dev/null'" \
      2>/dev/null || true)
  fi
  if [[ -z "${pr_url}" ]]; then
    pr_url=$(ssh_root_quiet "${ip}" \
      "grep -oE 'https://github.com/[^/]+/[^/]+/pull/[0-9]+' '${run_log}' 2>/dev/null | tail -1" \
      2>/dev/null || true)
  fi

  # --- log tail ---
  local log_tail=""
  if ssh_root_quiet "${ip}" "test -f '${run_log}'"; then
    log_tail=$(ssh_root_quiet "${ip}" "tail -n ${LOG_LINES} '${run_log}'" 2>/dev/null || true)
  fi

  # ---------------------------------------------------------------------------
  # Output
  # ---------------------------------------------------------------------------
  if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{\n'
    printf '  "vm": %s,\n'            "$(json_escape "${vm_name}")"
    printf '  "agent": %s,\n'         "$(json_escape "${agent_user}")"
    printf '  "issue_number": %s,\n'  "${issue_number:-null}"
    printf '  "issue_title": %s,\n'   "$(json_escape "${issue_title}")"
    printf '  "repo": %s,\n'          "$(json_escape "${repo}")"
    printf '  "branch": %s,\n'        "$(json_escape "${branch}")"
    printf '  "current_branch": %s,\n' "$(json_escape "${current_branch}")"
    printf '  "last_commit": %s,\n'   "$(json_escape "${last_commit}")"
    printf '  "pr_url": %s,\n'        "$(json_escape "${pr_url}")"
    printf '  "status": %s,\n'        "$(json_escape "${agent_status}")"
    printf '  "log_tail": %s\n'       "$(json_escape "${log_tail}")"
    printf '}'
  else
    echo "--- ${vm_name} / ${agent_user} ---"
    printf "Status:       %s\n" "${agent_status}"
    if [[ -n "${issue_number}" ]]; then
      printf "Issue:        #%s - %s\n" "${issue_number}" "${issue_title}"
    else
      printf "Issue:        (no assignment)\n"
    fi
    printf "Repo:         %s\n" "${repo:-(none)}"
    printf "Branch:       %s\n" "${branch:-${current_branch:-(none)}}"
    if [[ -n "${last_commit}" ]]; then
      printf "Last commit:  %s\n" "${last_commit}"
    fi
    if [[ -n "${pr_url}" ]]; then
      printf "PR:           %s\n" "${pr_url}"
    fi
    if [[ -n "${log_tail}" ]]; then
      echo ""
      echo "Log (last ${LOG_LINES} lines):"
      while IFS= read -r line; do
        printf '  %s\n' "${line}"
      done <<< "${log_tail}"
    fi
    echo ""
  fi
}

# ---------------------------------------------------------------------------
# Single agent
# ---------------------------------------------------------------------------
if [[ "${COLLECT_ALL}" == "false" ]]; then
  VM_NAME="${VM_IP}"
  if command -v hcloud &>/dev/null && [[ -n "${HCLOUD_TOKEN:-}" ]]; then
    VM_NAME=$(hcloud server list --output columns=name,ipv4 2>/dev/null \
      | awk -v ip="${VM_IP}" '$2==ip {print $1}' || echo "${VM_IP}")
  fi
  collect_one "${VM_IP}" "${VM_NAME}" "${AGENT_INDEX}"
  exit 0
fi

# ---------------------------------------------------------------------------
# All agents across all running VMs
# ---------------------------------------------------------------------------
mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status \
  | awk '$2=="running" && /ccgm-agent/ {print $1}' \
  | sort)

if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
  log_warn "No running ccgm-agent-* VMs found."
  exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
  echo "["
  first_entry=true
fi

for vm_name in "${VM_NAMES[@]}"; do
  ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
  for idx in $(seq 0 $(( CCGM_AGENTS_PER_VM - 1 ))); do
    if [[ "${JSON_OUTPUT}" == "true" && "${first_entry}" != "true" ]]; then
      echo ","
    fi
    collect_one "${ip}" "${vm_name}" "${idx}"
    first_entry=false
  done
done

if [[ "${JSON_OUTPUT}" == "true" ]]; then
  echo ""
  echo "]"
fi
