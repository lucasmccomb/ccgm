#!/usr/bin/env bash
# recovery.sh — Failure recovery for CCGM cloud-dispatch agents.
#
# Usage:
#   recovery.sh check
#   recovery.sh retry <vm-ip> <agent-index>
#   recovery.sh retry-all
#
# Subcommands:
#   check              Scan all agents for failures and classify them.
#   retry <ip> <idx>   Re-dispatch a specific failed agent.
#   retry-all          Retry all agents currently classified as failed.
#
# Failure classifications:
#   rate-limited  Agent hit Claude API rate limits
#   crashed       Agent process died unexpectedly (tmux gone, no status file)
#   timeout       Auto-shutdown killed the agent (AGENT_TIMEOUT status)
#   error         Agent completed but with errors (AGENT_ERROR status)
#   success       Agent completed successfully (AGENT_DONE status, PR created)
#   running       Agent is still running
#   unknown       Cannot determine state
#
# Requires: hcloud, jq, SSH key at ~/.ssh/ccgm-dispatch-session

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RETRY_LOG="${CCGM_RETRY_LOG:-/tmp/ccgm-recovery.json}"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: $0 check" >&2
  echo "       $0 retry <vm-ip> <agent-index>" >&2
  echo "       $0 retry-all" >&2
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

SUBCOMMAND="$1"
shift

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
require_cmd jq

# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------
ssh_root_quiet() {
  local ip="$1"; shift
  # shellcheck disable=SC2206
  read -ra _opts <<< "$(ssh_opts)"
  # SC2029: expansion is intentional - building command on client side
  # shellcheck disable=SC2029
  ssh "${_opts[@]}" "root@${ip}" "$@" 2>/dev/null
}

ssh_agent_quiet() {
  local ip="$1"
  local agent_user="$2"
  local cmd="$3"
  # SC2029: expansion is intentional
  # shellcheck disable=SC2029
  ssh_root_quiet "${ip}" "su - ${agent_user} -c $(printf '%q' "${cmd}")" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# classify_agent <vm-ip> <vm-name> <agent-index>
# Prints a JSON object describing the agent's failure state.
# ---------------------------------------------------------------------------
classify_agent() {
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
  if ssh_root_quiet "${ip}" "test -f '${assignment_file}'" 2>/dev/null; then
    local raw
    raw=$(ssh_root_quiet "${ip}" "cat '${assignment_file}'" || echo "{}")
    issue_number=$(echo "${raw}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_number',''))" 2>/dev/null || true)
    issue_title=$(echo "${raw}"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_title',''))"  2>/dev/null || true)
    repo=$(echo "${raw}"         | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('repo',''))"         2>/dev/null || true)
    branch=$(echo "${raw}"       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('branch',''))"       2>/dev/null || true)
  fi

  if [[ -z "${issue_number}" ]]; then
    # No assignment - skip this agent slot
    echo "null"
    return
  fi

  # --- tmux session state ---
  local tmux_running=false
  if ssh_root_quiet "${ip}" "su - ${agent_user} -c 'tmux has-session -t ${agent_user} 2>/dev/null'" 2>/dev/null; then
    tmux_running=true
  fi

  # --- status file ---
  local status_content=""
  if ssh_root_quiet "${ip}" "test -f '${status_file}'" 2>/dev/null; then
    status_content=$(ssh_root_quiet "${ip}" "cat '${status_file}'" 2>/dev/null | tr -d '[:space:]' || true)
  fi

  # --- log analysis for rate limits ---
  local rate_limited=false
  if ssh_root_quiet "${ip}" "test -f '${run_log}'" 2>/dev/null; then
    if ssh_root_quiet "${ip}" "grep -qiE 'rate.?limit|429|too many requests|overloaded' '${run_log}'" 2>/dev/null; then
      rate_limited=true
    fi
  fi

  # --- PR existence check ---
  local has_pr=false
  if [[ -n "${branch}" && -n "${repo}" ]]; then
    local pr_url
    pr_url=$(ssh_agent_quiet "${ip}" "${agent_user}" \
      "gh pr list --repo ${repo} --head ${branch} --json url --jq '.[0].url' 2>/dev/null" || true)
    [[ -n "${pr_url}" ]] && has_pr=true
  fi

  # --- git commits check ---
  local has_commits=false
  if [[ -n "${repo}" ]]; then
    local repo_name
    repo_name=$(basename "${repo}")
    local clone_dir="${agent_home}/workspace/${repo_name}"
    if ssh_root_quiet "${ip}" "test -d '${clone_dir}/.git'" 2>/dev/null; then
      local commit_count
      commit_count=$(ssh_agent_quiet "${ip}" "${agent_user}" \
        "git -C '${clone_dir}' rev-list --count HEAD ^origin/main 2>/dev/null" || echo "0")
      [[ "${commit_count:-0}" -gt 0 ]] && has_commits=true
    fi
  fi

  # --- classify ---
  local classification
  if [[ "${tmux_running}" == "true" ]]; then
    classification="running"
  elif [[ "${status_content}" == "AGENT_DONE" && "${has_pr}" == "true" ]]; then
    classification="success"
  elif [[ "${status_content}" == "AGENT_TIMEOUT" ]]; then
    classification="timeout"
  elif [[ "${rate_limited}" == "true" ]]; then
    classification="rate-limited"
  elif [[ "${status_content}" == "AGENT_ERROR" ]]; then
    classification="error"
  elif [[ "${tmux_running}" == "false" && -z "${status_content}" ]]; then
    classification="crashed"
  else
    classification="unknown"
  fi

  # Output JSON
  jq -n \
    --arg vm "${vm_name}" \
    --arg ip "${ip}" \
    --arg agent "${agent_user}" \
    --argjson idx "${idx}" \
    --arg issue "${issue_number}" \
    --arg title "${issue_title}" \
    --arg repo "${repo}" \
    --arg branch "${branch}" \
    --arg status "${status_content}" \
    --arg class "${classification}" \
    --argjson has_pr "${has_pr}" \
    --argjson has_commits "${has_commits}" \
    '{
      vm: $vm,
      ip: $ip,
      agent: $agent,
      agent_index: $idx,
      issue_number: $issue,
      issue_title: $title,
      repo: $repo,
      branch: $branch,
      status: $status,
      classification: $class,
      has_pr: $has_pr,
      has_commits: $has_commits
    }'
}

# ---------------------------------------------------------------------------
# Subcommand: check
# ---------------------------------------------------------------------------
cmd_check() {
  require_cmd hcloud

  if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
    log_error "HCLOUD_TOKEN is not set."
    exit 1
  fi

  mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status \
    | awk '$2=="running" && /ccgm-agent/ {print $1}' \
    | sort)

  if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
    log_warn "No running ccgm-agent-* VMs found."
    exit 0
  fi

  local results=()
  local total=0
  local running=0
  local success=0
  local failed=0

  for vm_name in "${VM_NAMES[@]}"; do
    local ip
    ip=$(hcloud server describe "${vm_name}" --output format='{{.PublicNet.IPv4.IP}}')
    for idx in $(seq 0 $(( CCGM_AGENTS_PER_VM - 1 ))); do
      log_info "Checking ${vm_name} agent-${idx}..."
      local result
      result=$(classify_agent "${ip}" "${vm_name}" "${idx}")
      if [[ "${result}" == "null" ]]; then
        continue
      fi
      results+=("${result}")
      total=$(( total + 1 ))

      local class
      class=$(echo "${result}" | jq -r '.classification')
      case "${class}" in
        running) running=$(( running + 1 )) ;;
        success) success=$(( success + 1 )) ;;
        *)       failed=$(( failed + 1 ))  ;;
      esac
    done
  done

  # Save results to retry log
  printf '[%s]' "$(IFS=','; echo "${results[*]}")" \
    | jq '.' > "${RETRY_LOG}" 2>/dev/null || true

  # Print summary
  echo ""
  echo "=== Agent Recovery Check ==="
  printf "Total agents: %s | Running: %s | Success: %s | Failed: %s\n\n" \
    "${total}" "${running}" "${success}" "${failed}"

  # Print per-agent status
  for result in "${results[@]}"; do
    local vm agent issue class has_pr has_commits
    vm=$(echo "${result}"          | jq -r '.vm')
    agent=$(echo "${result}"       | jq -r '.agent')
    issue=$(echo "${result}"       | jq -r '.issue_number')
    class=$(echo "${result}"       | jq -r '.classification')
    has_pr=$(echo "${result}"      | jq -r '.has_pr')
    has_commits=$(echo "${result}" | jq -r '.has_commits')

    local status_icon
    case "${class}" in
      success)      status_icon="${_COLOR_GREEN}[OK]${_COLOR_RESET}   " ;;
      running)      status_icon="${_COLOR_CYAN}[RUN]${_COLOR_RESET}  " ;;
      rate-limited) status_icon="${_COLOR_YELLOW}[RATE]${_COLOR_RESET} " ;;
      crashed)      status_icon="${_COLOR_RED}[CRASH]${_COLOR_RESET}" ;;
      timeout)      status_icon="${_COLOR_YELLOW}[TIME]${_COLOR_RESET} " ;;
      error)        status_icon="${_COLOR_RED}[ERR]${_COLOR_RESET}  " ;;
      *)            status_icon="[???]  " ;;
    esac

    printf "%s %-24s %-8s #%-6s %s" \
      "${status_icon}" "${vm}" "${agent}" "${issue}" "${class}"
    [[ "${has_commits}" == "true" ]] && printf " [has-commits]"
    [[ "${has_pr}" == "true" ]] && printf " [pr-created]"
    echo ""
  done

  echo ""
  if [[ ${failed} -gt 0 ]]; then
    echo "Run '$0 retry-all' to re-dispatch all failed agents."
  fi
}

# ---------------------------------------------------------------------------
# retry_one <vm-ip> <agent-index>
# Re-dispatch a single failed agent, resuming from last commit if possible.
# ---------------------------------------------------------------------------
retry_one() {
  local ip="$1"
  local idx="$2"
  local agent_user="agent-${idx}"
  local agent_home="/home/${agent_user}"
  local assignment_file="${agent_home}/assignment.json"

  log_info "Preparing retry for ${agent_user}@${ip}"

  # Read assignment
  if ! ssh_root_quiet "${ip}" "test -f '${assignment_file}'" 2>/dev/null; then
    log_error "No assignment.json for ${agent_user}@${ip}. Cannot retry."
    return 1
  fi

  local raw
  raw=$(ssh_root_quiet "${ip}" "cat '${assignment_file}'" || echo "{}")
  local issue_number repo branch
  issue_number=$(echo "${raw}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issue_number',''))" 2>/dev/null || true)
  repo=$(echo "${raw}"         | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('repo',''))"         2>/dev/null || true)
  branch=$(echo "${raw}"       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('branch',''))"       2>/dev/null || true)

  if [[ -z "${issue_number}" || -z "${repo}" || -z "${branch}" ]]; then
    log_error "Incomplete assignment.json for ${agent_user}@${ip}."
    return 1
  fi

  local repo_name
  repo_name=$(basename "${repo}")
  local clone_dir="${agent_home}/workspace/${repo_name}"

  # Check if the branch has commits beyond origin/main
  local has_commits=false
  local commit_count
  commit_count=$(ssh_agent_quiet "${ip}" "${agent_user}" \
    "git -C '${clone_dir}' rev-list --count HEAD ^origin/main 2>/dev/null" || echo "0")
  [[ "${commit_count:-0}" -gt 0 ]] && has_commits=true

  # Choose prompt based on commit state
  local prompt
  if [[ "${has_commits}" == "true" ]]; then
    log_info "Branch has commits - resuming from checkpoint."
    prompt="You are resuming work on issue #${issue_number}. \
Check the current state of the branch '${branch}' and continue from where the previous agent left off. \
Review any existing commits, assess what remains to be done, and complete the implementation. \
Create a PR when complete that closes #${issue_number}."
  else
    log_info "No commits found - starting fresh."
    # Reset branch to origin/main
    ssh_agent_quiet "${ip}" "${agent_user}" \
      "git -C '${clone_dir}' checkout -B '${branch}' origin/main 2>/dev/null" || true
    prompt="You are an autonomous Claude Code agent. Work on GitHub issue #${issue_number}. \
Create a branch named ${branch}, implement the changes with tests, and create a PR that closes #${issue_number}. \
Follow the repo's CLAUDE.md instructions. Commit with message format: #${issue_number}: description."
  fi

  # Clear previous status and log (append retry marker)
  ssh_root_quiet "${ip}" "rm -f '${agent_home}/status'" || true
  ssh_root_quiet "${ip}" \
    "echo '--- RETRY $(date -u +"%Y-%m-%dT%H:%M:%SZ") ---' >> '${agent_home}/run.log'" || true

  # Re-launch via agent-launch.sh
  "${SCRIPT_DIR}/agent-launch.sh" "${ip}" "${idx}" --prompt "${prompt}"
}

# ---------------------------------------------------------------------------
# Subcommand: retry <vm-ip> <agent-index>
# ---------------------------------------------------------------------------
cmd_retry() {
  if [[ $# -lt 2 ]]; then
    echo "Usage: $0 retry <vm-ip> <agent-index>" >&2
    exit 1
  fi
  local ip="$1"
  local idx="$2"

  if ! [[ "${idx}" =~ ^[0-3]$ ]]; then
    log_error "agent-index must be 0, 1, 2, or 3 (got: ${idx})"
    exit 1
  fi

  retry_one "${ip}" "${idx}"
}

# ---------------------------------------------------------------------------
# Subcommand: retry-all
# ---------------------------------------------------------------------------
cmd_retry_all() {
  if [[ ! -f "${RETRY_LOG}" ]]; then
    log_warn "No recovery data found at ${RETRY_LOG}. Run 'check' first."
    exit 0
  fi

  local retry_count=0
  local skip_count=0

  # Read failed agents from the check results
  while IFS= read -r entry; do
    local class ip idx
    class=$(echo "${entry}" | jq -r '.classification')
    ip=$(echo "${entry}"    | jq -r '.ip')
    idx=$(echo "${entry}"   | jq -r '.agent_index')

    case "${class}" in
      success|running)
        skip_count=$(( skip_count + 1 ))
        log_info "Skipping agent-${idx}@${ip} (${class})"
        ;;
      *)
        log_info "Retrying agent-${idx}@${ip} (${class})"
        if retry_one "${ip}" "${idx}"; then
          retry_count=$(( retry_count + 1 ))
        else
          log_warn "Retry failed for agent-${idx}@${ip}"
        fi
        ;;
    esac
  done < <(jq -c '.[]' "${RETRY_LOG}" 2>/dev/null || true)

  echo ""
  log_success "Retry complete: ${retry_count} agent(s) re-dispatched, ${skip_count} skipped."
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${SUBCOMMAND}" in
  check)      cmd_check                ;;
  retry)      cmd_retry "$@"           ;;
  retry-all)  cmd_retry_all            ;;
  *)
    log_error "Unknown subcommand: ${SUBCOMMAND}"
    usage
    ;;
esac
