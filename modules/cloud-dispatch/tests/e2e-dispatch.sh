#!/usr/bin/env bash
# E2E test for the cloud-dispatch module.
#
# This test validates the full dispatch pipeline end-to-end against real
# Hetzner Cloud infrastructure.
#
# COST WARNING: This test creates REAL VMs and costs REAL money (~$2-3 for a
# full run). Always run with --dry-run first to preview what will happen.
#
# Prerequisites:
#   - HCLOUD_TOKEN set to a valid Hetzner Cloud API token
#   - hcloud CLI installed (brew install hcloud)
#   - gh CLI installed and authenticated (brew install gh)
#   - jq installed (brew install jq)
#   - ssh-agent running with SSH_AUTH_SOCK set
#   - Golden image built (cd packer && packer build agent-image.pkr.hcl)
#
# Usage:
#   bash tests/e2e-dispatch.sh              # Full run with cleanup
#   bash tests/e2e-dispatch.sh --dry-run    # Preview steps without executing
#   bash tests/e2e-dispatch.sh --skip-cleanup  # Leave VMs running after test
#
# Environment variables:
#   E2E_TEST_REPO   GitHub repo to use (default: lucasmccomb/ccgm)
#   E2E_VM_COUNT    Number of VMs to create (default: 1)
#   E2E_MAX_TURNS   Max agent turns before stopping (default: 10)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

TEST_REPO="${E2E_TEST_REPO:-lucasmccomb/ccgm}"
VM_COUNT="${E2E_VM_COUNT:-1}"
MAX_TURNS="${E2E_MAX_TURNS:-10}"

DRY_RUN=false
SKIP_CLEANUP=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true;      shift ;;
    --skip-cleanup) SKIP_CLEANUP=true; shift ;;
    --repo)         TEST_REPO="$2";    shift 2 ;;
    --vm-count)     VM_COUNT="$2";     shift 2 ;;
    --max-turns)    MAX_TURNS="$2";    shift 2 ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -30
      exit 0
      ;;
    *)
      log_error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Cleanup tracking
# ---------------------------------------------------------------------------

TEST_ISSUE=""

cleanup_test_resources() {
  if [[ "${SKIP_CLEANUP}" == "true" ]]; then
    log_warn "Skipping cleanup (--skip-cleanup). Remember to run vm-destroy.sh --all --force manually!"
    return 0
  fi

  log_info "Cleaning up test resources..."

  bash "${SCRIPT_DIR}/lib/agent-stop.sh" --all 2>/dev/null || true
  bash "${SCRIPT_DIR}/lib/secrets-cleanup.sh" 2>/dev/null || true
  bash "${SCRIPT_DIR}/lib/vm-destroy.sh" --all --force 2>/dev/null || true

  if [[ -n "${TEST_ISSUE}" ]]; then
    gh issue close "${TEST_ISSUE}" \
      --repo "${TEST_REPO}" \
      --comment "E2E test complete - closing automatically" \
      2>/dev/null || true
    log_info "Closed test issue #${TEST_ISSUE}"
  fi

  log_success "Cleanup complete"
}

register_cleanup cleanup_test_resources

# ---------------------------------------------------------------------------
# Test header
# ---------------------------------------------------------------------------

echo ""
echo "${_COLOR_BOLD}=== Cloud Dispatch E2E Test ===${_COLOR_RESET}"
echo ""
log_info "Repo:       ${TEST_REPO}"
log_info "VM count:   ${VM_COUNT}"
log_info "Max turns:  ${MAX_TURNS}"
log_info "Dry run:    ${DRY_RUN}"
echo ""

if [[ "${DRY_RUN}" == "true" ]]; then
  log_warn "DRY RUN MODE: steps will be printed but not executed"
  echo ""
fi

# ---------------------------------------------------------------------------
# Helper: run or print a command depending on --dry-run
# ---------------------------------------------------------------------------

run_step() {
  local description="$1"
  shift
  log_info "${description}"
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "  [dry-run] would run: $*"
    return 0
  fi
  "$@"
}

# ---------------------------------------------------------------------------
# Step 1: Validate prerequisites
# ---------------------------------------------------------------------------

log_info "Step 1: Checking prerequisites..."

require_cmd hcloud
require_cmd gh
require_cmd jq
require_cmd ssh
require_cmd ssh-add

if [[ -z "${HCLOUD_TOKEN:-}" ]]; then
  log_error "HCLOUD_TOKEN is not set. Export it before running this test."
  exit 1
fi

if [[ -z "${SSH_AUTH_SOCK:-}" ]]; then
  log_error "SSH_AUTH_SOCK is not set. Start ssh-agent and retry."
  exit 1
fi

if ! hcloud server-type list >/dev/null 2>&1; then
  log_error "hcloud CLI cannot reach the Hetzner API. Check HCLOUD_TOKEN."
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  log_error "gh CLI is not authenticated. Run: gh auth login"
  exit 1
fi

log_success "Step 1: Prerequisites OK"

# ---------------------------------------------------------------------------
# Step 2: Check for golden image
# ---------------------------------------------------------------------------

log_info "Step 2: Checking for golden image snapshot..."

if [[ "${DRY_RUN}" == "false" ]]; then
  IMAGE_ID="$(latest_image_id 2>/dev/null || true)"
  if [[ -z "${IMAGE_ID}" ]]; then
    log_error "No golden image found (label selector: ${CCGM_IMAGE_LABEL})."
    log_error "Build one first:"
    log_error "  cd ${SCRIPT_DIR}/packer && packer build agent-image.pkr.hcl"
    exit 1
  fi
  log_success "Step 2: Golden image found: ${IMAGE_ID}"
else
  log_info "  [dry-run] would check for snapshot with label ${CCGM_IMAGE_LABEL}"
fi

# ---------------------------------------------------------------------------
# Step 3: Create test VM(s)
# ---------------------------------------------------------------------------

run_step "Step 3: Creating ${VM_COUNT} test VM(s)..." \
  bash "${SCRIPT_DIR}/lib/vm-create.sh" "${VM_COUNT}"

# ---------------------------------------------------------------------------
# Step 4: Health check VM(s)
# ---------------------------------------------------------------------------

run_step "Step 4: Health checking VM(s)..." \
  bash "${SCRIPT_DIR}/lib/vm-health.sh" --all

# ---------------------------------------------------------------------------
# Step 5: Initialize session secrets
# ---------------------------------------------------------------------------

run_step "Step 5: Initializing session secrets..." \
  bash "${SCRIPT_DIR}/lib/secrets-init.sh"

# ---------------------------------------------------------------------------
# Step 6: Inject secrets
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN}" == "false" ]]; then
  log_info "Step 6: Injecting secrets into agents..."
  GITHUB_TOKEN="$(gh auth token)"
  bash "${SCRIPT_DIR}/lib/secrets-inject-all.sh" --github-token "${GITHUB_TOKEN}"
  log_success "Step 6: Secrets injected"
else
  log_info "  [dry-run] would run: secrets-inject-all.sh --github-token <token>"
fi

# ---------------------------------------------------------------------------
# Step 7: Create test issue and set up workspaces
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN}" == "false" ]]; then
  log_info "Step 7: Creating test GitHub issue..."
  TEST_ISSUE="$(gh issue create \
    --repo "${TEST_REPO}" \
    --title "E2E test: cloud-dispatch validation (safe to close)" \
    --body "Automated E2E test issue created by tests/e2e-dispatch.sh. Safe to close." \
    2>&1 | grep -oE '[0-9]+$')"

  if [[ -z "${TEST_ISSUE}" ]]; then
    log_error "Failed to create test issue on ${TEST_REPO}"
    exit 1
  fi
  log_info "Created test issue #${TEST_ISSUE} on ${TEST_REPO}"

  log_info "Step 7: Setting up workspace for issue #${TEST_ISSUE}..."
  bash "${SCRIPT_DIR}/lib/workspace-setup-all.sh" \
    "https://github.com/${TEST_REPO}.git" \
    --issues "${TEST_ISSUE}"
  log_success "Step 7: Workspace set up"
else
  log_info "  [dry-run] would create test issue on ${TEST_REPO}"
  log_info "  [dry-run] would run: workspace-setup-all.sh https://github.com/${TEST_REPO}.git --issues <number>"
fi

# ---------------------------------------------------------------------------
# Step 8: Launch agent(s)
# ---------------------------------------------------------------------------

run_step "Step 8: Launching test agent(s) (max-turns=${MAX_TURNS})..." \
  bash "${SCRIPT_DIR}/lib/agent-launch-all.sh" \
    --max-turns "${MAX_TURNS}" \
    --jitter 0

# ---------------------------------------------------------------------------
# Step 9: Wait and check status
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN}" == "false" ]]; then
  log_info "Step 9: Waiting 30s then checking agent status..."
  sleep 30
  bash "${SCRIPT_DIR}/lib/agent-status.sh" --all
  log_success "Step 9: Status check complete"
else
  log_info "  [dry-run] would wait 30s then run: agent-status.sh --all"
fi

# ---------------------------------------------------------------------------
# Step 10: Collect results
# ---------------------------------------------------------------------------

run_step "Step 10: Collecting results from agents..." \
  bash "${SCRIPT_DIR}/lib/workspace-collect.sh" --all

# ---------------------------------------------------------------------------
# Test complete
# ---------------------------------------------------------------------------

echo ""
log_success "=== E2E Test Complete ==="
echo ""

if [[ "${SKIP_CLEANUP}" == "true" ]]; then
  log_warn "VMs are still running. Destroy them when done:"
  log_warn "  bash ${SCRIPT_DIR}/lib/vm-destroy.sh --all --force"
fi
