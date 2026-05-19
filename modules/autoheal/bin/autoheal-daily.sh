#!/usr/bin/env bash
# autoheal-daily.sh
#
# Daily wrapper: runs the analyzer, digest, email, auto-apply, publish, and
# retention scripts in sequence. Each step is exit-tolerant — a failure of
# one step does not kill the rest. The wrapper exits 0 unless EVERY step
# failed.
#
# Order (plan.md §5 Epic 7, Epic 11 §5, Epic 12 §5):
#   1. bin/autoheal-analyze.sh    (Epic 6)
#   2. bin/autoheal-digest.sh     (Epic 7)
#   3. bin/autoheal-email.sh      (Epic 7)
#   4. bin/autoheal-auto-apply.sh (Epic 11; stub OK)
#   5. bin/autoheal-publish.sh    (Epic 12; stub OK)
#   6. bin/autoheal-retention.sh  (Epic 12; stub OK)
#
# Missing/non-executable steps are logged and skipped. The wrapper aggregates
# each step's stdout/stderr into a per-day log under ~/.claude/logs.
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_LOGS_DIR   default ~/.claude/logs
#   CCGM_AUTOHEAL_TODAY      default $(date +%Y-%m-%d)
#   CCGM_AUTOHEAL_BIN_DIR    default to dirname of this script

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${CCGM_AUTOHEAL_BIN_DIR:-${SCRIPT_DIR}}"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date +%Y-%m-%d)}"

mkdir -p "${LOGS_DIR}"
DAILY_LOG="${LOGS_DIR}/autoheal-daily-${TODAY}.log"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "${DAILY_LOG}"
}

run_step() {
    local label="$1"
    local path="$2"

    if [ ! -f "${path}" ]; then
        log "skip ${label}: ${path} not present"
        return 0
    fi
    if [ ! -x "${path}" ]; then
        # Run via bash even if not chmod +x, so a fresh checkout where
        # someone forgot the bit still works.
        log "run  ${label}: ${path} (via bash; not executable)"
        if bash "${path}" >>"${DAILY_LOG}" 2>&1; then
            log "ok   ${label}"
            return 0
        else
            local rc=$?
            log "fail ${label}: exit=${rc}"
            return ${rc}
        fi
    fi

    log "run  ${label}: ${path}"
    if "${path}" >>"${DAILY_LOG}" 2>&1; then
        log "ok   ${label}"
        return 0
    else
        local rc=$?
        log "fail ${label}: exit=${rc}"
        return ${rc}
    fi
}

# ---------------------------------------------------------------------------
# Step list. Order matters; see plan.md §5 Epic 7 and the parent-merge order
# for Epic 12 (auto-apply runs BEFORE digest so the digest reflects applied
# state).
# ---------------------------------------------------------------------------

steps_total=0
steps_failed=0

log "autoheal-daily start (${TODAY})"

# Step 1: analyzer (Epic 6).
steps_total=$((steps_total + 1))
run_step "analyze"    "${BIN_DIR}/autoheal-analyze.sh"     || steps_failed=$((steps_failed + 1))

# Step 2: auto-apply (Epic 11). Runs AFTER analyzer so today's proposals
# exist and BEFORE digest so digest reflects the applied state.
steps_total=$((steps_total + 1))
run_step "auto-apply" "${BIN_DIR}/autoheal-auto-apply.sh"  || steps_failed=$((steps_failed + 1))

# Step 3: digest (Epic 7).
steps_total=$((steps_total + 1))
run_step "digest"     "${BIN_DIR}/autoheal-digest.sh"      || steps_failed=$((steps_failed + 1))

# Step 4: email (Epic 7).
steps_total=$((steps_total + 1))
run_step "email"      "${BIN_DIR}/autoheal-email.sh"       || steps_failed=$((steps_failed + 1))

# Step 5: publish (Epic 12).
steps_total=$((steps_total + 1))
run_step "publish"    "${BIN_DIR}/autoheal-publish.sh"     || steps_failed=$((steps_failed + 1))

# Step 6: retention (Epic 12).
steps_total=$((steps_total + 1))
run_step "retention"  "${BIN_DIR}/autoheal-retention.sh"   || steps_failed=$((steps_failed + 1))

log "autoheal-daily done (failed=${steps_failed}/${steps_total})"

# Exit 0 unless EVERY step failed. If launchd sees a non-zero exit, it
# treats the job as faulty and may delay reschedule — we'd rather have a
# faulty individual step than a wholesale launchd cooldown.
if [ "${steps_failed}" -eq "${steps_total}" ] && [ "${steps_total}" -gt 0 ]; then
    exit 1
fi
exit 0
