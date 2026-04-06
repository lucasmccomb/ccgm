#!/usr/bin/env bash
# workspace-setup-all.sh — Provision workspaces across all running agent VMs.
#
# Usage:
#   workspace-setup-all.sh <repo-url> --issues "42,43,44,45,46,47,48,49"
#
# Arguments:
#   repo-url     HTTPS URL of the target repo (e.g. https://github.com/owner/repo)
#   --issues     Comma-separated list of issue numbers to distribute
#   --titles     Optional: JSON file mapping issue numbers to titles
#                If omitted, titles are fetched from GitHub via gh CLI
#   --repo       GitHub repo in owner/repo format (derived from repo-url if omitted)
#   --max-turns  Maximum agent turns per assignment (default: 200)
#   --branch     Optional base branch for all workspaces (default: main)
#   --dry-run    Print the assignment plan without executing it
#
# Requires:
#   - Hetzner Cloud CLI (hcloud) installed and authenticated
#   - workspace-setup.sh and workspace-assign.sh in the same directory as this script
#   - SSH key in ~/.ssh/id_ed25519 or $SSH_KEY_PATH
#   - gh CLI authenticated (for fetching issue titles when --titles not provided)
#
# NOTE: If common.sh from Epic 3 is available in the same lib/ directory, source it
#       for shared SSH helpers. This script defines its own helpers as a fallback
#       since Epic 3 may not be merged when this runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common.sh if available (Epic 3 dependency — may not be merged yet)
if [[ -f "${SCRIPT_DIR}/common.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/common.sh"
fi

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <repo-url> --issues \"42,43,44\" [--titles FILE] [--repo OWNER/REPO] [--max-turns N] [--branch BRANCH] [--dry-run]" >&2
  exit 1
fi

REPO_URL="$1"
shift

ISSUES_CSV=""
TITLES_FILE=""
REPO_OVERRIDE=""
MAX_TURNS=200
BRANCH=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issues)
      ISSUES_CSV="$2"
      shift 2
      ;;
    --titles)
      TITLES_FILE="$2"
      shift 2
      ;;
    --repo)
      REPO_OVERRIDE="$2"
      shift 2
      ;;
    --max-turns)
      MAX_TURNS="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${ISSUES_CSV}" ]]; then
  echo "Error: --issues is required" >&2
  exit 1
fi

# Derive repo in owner/repo format from URL
if [[ -n "${REPO_OVERRIDE}" ]]; then
  REPO="${REPO_OVERRIDE}"
else
  # Strip https://github.com/ prefix and .git suffix
  REPO=$(echo "${REPO_URL}" | sed 's|https://github.com/||;s|\.git$||')
fi

# SSH_KEY is passed via SSH_KEY_PATH env to child scripts (workspace-setup.sh, workspace-assign.sh)
export SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519}"

# ---------------------------------------------------------------------------
# Parse issue list
# ---------------------------------------------------------------------------
IFS=',' read -ra ISSUE_LIST <<< "${ISSUES_CSV}"
ISSUE_COUNT="${#ISSUE_LIST[@]}"

# ---------------------------------------------------------------------------
# Fetch issue titles
# ---------------------------------------------------------------------------
declare -A ISSUE_TITLES

if [[ -n "${TITLES_FILE}" ]]; then
  # Load from JSON file: {"42": "feat: habit streaks", "43": "fix: login bug"}
  if ! command -v jq &>/dev/null; then
    echo "Error: jq is required when --titles is specified" >&2
    exit 1
  fi
  while IFS= read -r line; do
    num=$(echo "${line}" | jq -r '.key')
    title=$(echo "${line}" | jq -r '.value')
    ISSUE_TITLES["${num}"]="${title}"
  done < <(jq -r 'to_entries[] | {key, value} | @json' "${TITLES_FILE}")
else
  echo "==> Fetching issue titles from GitHub"
  if ! command -v gh &>/dev/null; then
    echo "Error: gh CLI is required to fetch issue titles. Install it or use --titles to provide them." >&2
    exit 1
  fi
  for issue_num in "${ISSUE_LIST[@]}"; do
    issue_num=$(echo "${issue_num}" | tr -d '[:space:]')
    title=$(gh issue view "${issue_num}" --repo "${REPO}" --json title --jq '.title' 2>/dev/null || echo "issue-${issue_num}")
    ISSUE_TITLES["${issue_num}"]="${title}"
  done
fi

# ---------------------------------------------------------------------------
# Discover running agent VMs via hcloud CLI
# ---------------------------------------------------------------------------
echo "==> Discovering running agent VMs"
if ! command -v hcloud &>/dev/null; then
  echo "Error: hcloud CLI is required. Install it from https://github.com/hetznercloud/cli" >&2
  exit 1
fi

# VMs created by the ccgm terraform config are named ccgm-agent-{location}-{n}
# List all running servers with the ccgm-agent prefix, sorted by name.
mapfile -t VM_NAMES < <(hcloud server list --output columns=name,status | awk '$2=="running" && /ccgm-agent/ {print $1}' | sort)

if [[ ${#VM_NAMES[@]} -eq 0 ]]; then
  echo "Error: no running ccgm-agent-* VMs found. Create them with Terraform first." >&2
  exit 1
fi

echo "Found ${#VM_NAMES[@]} VM(s): ${VM_NAMES[*]}"

# ---------------------------------------------------------------------------
# Build assignment plan: distribute issues round-robin across agent slots
#
# Slot order: VM0-agent0, VM0-agent1, VM0-agent2, VM0-agent3,
#             VM1-agent0, VM1-agent1, ...
# ---------------------------------------------------------------------------
declare -a PLAN_VM_IPS
declare -a PLAN_AGENT_INDEXES
declare -a PLAN_ISSUE_NUMBERS
AGENTS_PER_VM=4

slot=0
for issue_num in "${ISSUE_LIST[@]}"; do
  issue_num=$(echo "${issue_num}" | tr -d '[:space:]')
  vm_index=$(( slot / AGENTS_PER_VM ))
  agent_index=$(( slot % AGENTS_PER_VM ))

  if [[ ${vm_index} -ge ${#VM_NAMES[@]} ]]; then
    echo "Warning: more issues (${ISSUE_COUNT}) than agent slots ($(( ${#VM_NAMES[@]} * AGENTS_PER_VM ))). Stopping at slot ${slot}." >&2
    break
  fi

  VM_NAME="${VM_NAMES[$vm_index]}"
  VM_IP=$(hcloud server describe "${VM_NAME}" --output format='{{.PublicNet.IPv4.IP}}')

  PLAN_VM_IPS+=("${VM_IP}")
  PLAN_AGENT_INDEXES+=("${agent_index}")
  PLAN_ISSUE_NUMBERS+=("${issue_num}")

  slot=$(( slot + 1 ))
done

# ---------------------------------------------------------------------------
# Print assignment plan
# ---------------------------------------------------------------------------
echo ""
echo "Assignment plan:"
echo "  Repo:      ${REPO}"
echo "  Issues:    ${ISSUE_COUNT}"
echo "  VMs:       ${#VM_NAMES[@]}"
echo ""
printf "  %-6s  %-8s  %-20s  %s\n" "Issue" "Agent" "VM" "Branch"
printf "  %-6s  %-8s  %-20s  %s\n" "------" "--------" "--------------------" "------"
for i in "${!PLAN_ISSUE_NUMBERS[@]}"; do
  num="${PLAN_ISSUE_NUMBERS[$i]}"
  title="${ISSUE_TITLES[$num]:-issue-${num}}"
  slug=$(echo "${title}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9]/-/g' \
    | sed 's/-\{2,\}/-/g' \
    | sed 's/^-//;s/-$//')
  branch="${num}-${slug}"
  printf "  %-6s  %-8s  %-20s  %s\n" "#${num}" "agent-${PLAN_AGENT_INDEXES[$i]}" "${PLAN_VM_IPS[$i]}" "${branch}"
done
echo ""

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "(--dry-run: no changes made)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Execute: setup workspace then assign issue for each slot
# ---------------------------------------------------------------------------
SETUP_SCRIPT="${SCRIPT_DIR}/workspace-setup.sh"
ASSIGN_SCRIPT="${SCRIPT_DIR}/workspace-assign.sh"

for script in "${SETUP_SCRIPT}" "${ASSIGN_SCRIPT}"; do
  if [[ ! -x "${script}" ]]; then
    echo "Error: ${script} not found or not executable" >&2
    exit 1
  fi
done

SUCCESS=0
FAILED=0

for i in "${!PLAN_ISSUE_NUMBERS[@]}"; do
  vm_ip="${PLAN_VM_IPS[$i]}"
  agent_index="${PLAN_AGENT_INDEXES[$i]}"
  issue_num="${PLAN_ISSUE_NUMBERS[$i]}"
  title="${ISSUE_TITLES[$issue_num]:-issue-${issue_num}}"

  echo "==> [${i}] Setting up ${vm_ip} agent-${agent_index} for issue #${issue_num}"

  setup_args=("${vm_ip}" "${agent_index}" "${REPO_URL}")
  if [[ -n "${BRANCH}" ]]; then
    setup_args+=(--branch "${BRANCH}")
  fi

  if "${SETUP_SCRIPT}" "${setup_args[@]}"; then
    if "${ASSIGN_SCRIPT}" "${vm_ip}" "${agent_index}" "${issue_num}" "${title}" \
        --repo "${REPO}" --max-turns "${MAX_TURNS}"; then
      SUCCESS=$(( SUCCESS + 1 ))
    else
      echo "Error: workspace-assign.sh failed for issue #${issue_num} on ${vm_ip} agent-${agent_index}" >&2
      FAILED=$(( FAILED + 1 ))
    fi
  else
    echo "Error: workspace-setup.sh failed for ${vm_ip} agent-${agent_index}" >&2
    FAILED=$(( FAILED + 1 ))
  fi
done

echo ""
echo "==> Setup complete: ${SUCCESS} succeeded, ${FAILED} failed"
[[ ${FAILED} -eq 0 ]]
