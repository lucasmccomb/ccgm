#!/usr/bin/env bash
# autoheal-daily.sh
#
# Daily wrapper: runs the analyzer, digest, email, auto-apply, publish, and
# retention scripts in sequence. Each step is exit-tolerant — a failure of
# one step does not kill the rest. The wrapper exits non-zero when the
# analyze step fails (a dead analyzer must not look like a healthy job to
# launchd); a failure in a later step is recorded as "partial" and exits 0.
#
# Order (plan.md §5 Epic 7, Epic 11 §5, Epic 12 §5):
#   1. bin/autoheal-analyze.sh    (Epic 6)
#   2. bin/autoheal-digest.sh     (Epic 7)
#   3. bin/autoheal-email.sh      (Epic 7)
#   4. bin/autoheal-auto-apply.sh (Epic 11; stub OK)
#   5. bin/autoheal-publish.sh    (Epic 12; stub OK)
#   6. bin/autoheal-retention.sh  (Epic 12; stub OK)
#
# Missing/non-executable steps are logged and skipped, except the analyzer:
# a missing analyzer is recorded as exit 127 and fails the run. The wrapper
# aggregates each step's stdout/stderr into a per-day log under ~/.claude/logs.
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_LOGS_DIR   default ~/.claude/logs
#   CCGM_AUTOHEAL_TODAY      default $(date -u +%Y-%m-%d). UTC-keyed to
#                            match the event/proposal/digest file naming
#                            written by the hooks (issue #520).
#   CCGM_AUTOHEAL_BIN_DIR    default to dirname of this script
#   CCGM_AUTOHEAL_DIR        default ~/.claude/autoheal (health.json,
#                            last-run.json, cost.log)
#   CCGM_AUTOHEAL_CONFIG     default $CCGM_AUTOHEAL_DIR/config.json
#
# Heartbeat (#1099 3.4): an EXIT trap runs bin/autoheal-health.py as the last
# action, so every run, including a crash or a signal, leaves
# ~/.claude/autoheal/health.json. The helper decides the run status; the
# wrapper exits 1 when that status is "failed".
#
# Daily-cap stop: the analyzer exits 2 for a daily cost cap but also for an
# unsupported model, so the exit code alone is never read as a refusal. The
# analyzer records a deliberate refusal in last-run.json
# ({"date": ..., "outcome": "daily_cap_refused"}); the wrapper deletes that
# file before the analyze step, so only this run's record counts.
#
# Off switch: `paused: true` in the user config (or in the nearest per-repo
# .autoheal/config.json, which wins when it sets the key) makes the wrapper
# log "paused", write a health.json with status "paused", and exit 0 before
# any step runs. No step runs, so nothing is appended to cost.log and no API
# call is made.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${CCGM_AUTOHEAL_BIN_DIR:-${SCRIPT_DIR}}"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date -u +%Y-%m-%d)}"
AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${AUTOHEAL_DIR}/config.json}"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# hook_utils.py lives in the module tree, or under ~/.claude/lib once installed.
HOOK_LIB_DIR="${CCGM_AUTOHEAL_HOOK_LIB:-${SCRIPT_DIR}/../../hooks/lib:${HOME}/.claude/lib}"

mkdir -p "${LOGS_DIR}"
DAILY_LOG="${LOGS_DIR}/autoheal-daily-${TODAY}.log"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "${DAILY_LOG}"
}

# Space-separated "name=rc" for every step that ran; read by the heartbeat.
STEP_RCS=""

run_step() {
    local label="$1"
    local path="$2"
    local rc=0

    if [ ! -f "${path}" ]; then
        log "skip ${label}: ${path} not present"
        # A missing analyzer is the exit-127 failure this wrapper must report.
        if [ "${label}" = "analyze" ]; then
            STEP_RCS="${STEP_RCS} ${label}=127"
            return 127
        fi
        return 0
    fi
    if [ ! -x "${path}" ]; then
        # Run via bash even if not chmod +x, so a fresh checkout where
        # someone forgot the bit still works.
        log "run  ${label}: ${path} (via bash; not executable)"
        bash "${path}" >>"${DAILY_LOG}" 2>&1 || rc=$?
    else
        log "run  ${label}: ${path}"
        "${path}" >>"${DAILY_LOG}" 2>&1 || rc=$?
    fi
    STEP_RCS="${STEP_RCS} ${label}=${rc}"
    if [ "${rc}" -eq 0 ]; then
        log "ok   ${label}"
    else
        log "fail ${label}: exit=${rc}"
    fi
    return "${rc}"
}

# ---------------------------------------------------------------------------
# Heartbeat. Runs on every exit path. The helper prints the run status; a
# "failed" status turns a would-be exit 0 into exit 1. A helper that cannot
# run prints nothing, and the original exit code stands.
# ---------------------------------------------------------------------------

RUN_PAUSED=0
RUN_COMPLETE=0

write_heartbeat() {
    local rc=$?
    local status=""
    local args=(--dir "${AUTOHEAL_DIR}" --today "${TODAY}" --started "${STARTED_AT}" --steps "${STEP_RCS}")
    [ "${RUN_PAUSED}" = "1" ] && args+=(--paused)
    [ "${RUN_COMPLETE}" = "1" ] && args+=(--complete)
    status="$(python3 "${SCRIPT_DIR}/autoheal-health.py" "${args[@]}" 2>>"${DAILY_LOG}")" || status=""
    if [ "${status}" = "failed" ] && [ "${rc}" -eq 0 ]; then
        rc=1
    fi
    log "heartbeat: status=${status:-unknown} exit=${rc}"
    exit "${rc}"
}
trap write_heartbeat EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# ---------------------------------------------------------------------------
# Step list. Order matters; see plan.md §5 Epic 7 and the parent-merge order
# for Epic 12 (auto-apply runs BEFORE digest so the digest reflects applied
# state).
# ---------------------------------------------------------------------------

log "autoheal-daily start (${TODAY})"

# Preflight: honour `paused`. The user config is the base; a per-repo
# .autoheal/config.json found by walking up from the cwd overrides it
# (hook_utils.load_repo_config). Anything unreadable counts as not paused.
is_paused() {
    python3 - "${CONFIG_FILE}" "${HOOK_LIB_DIR}" <<'PY'
import json
import sys

config_path, hook_lib = sys.argv[1], sys.argv[2]
cfg = {}
try:
    with open(config_path, encoding="utf-8") as fh:
        loaded = json.load(fh)
    if isinstance(loaded, dict):
        cfg = loaded
except (OSError, ValueError):
    pass
try:
    sys.path[:0] = hook_lib.split(":")
    import hook_utils
    cfg = {**cfg, **hook_utils.load_repo_config()}
except Exception:
    pass
sys.exit(0 if cfg.get("paused") is True else 1)
PY
}

if is_paused; then
    log "paused (paused=true in ${CONFIG_FILE} or a per-repo override); skipping all steps"
    RUN_PAUSED=1
    exit 0
fi

# Step 1: analyzer (Epic 6). Clear last-run.json first so only a refusal the
# analyzer records during THIS run can excuse a non-zero exit.
rm -f "${AUTOHEAL_DIR}/last-run.json"
run_step "analyze"    "${BIN_DIR}/autoheal-analyze.sh"     || true

# Step 2: auto-apply (Epic 11). Runs AFTER analyzer so today's proposals
# exist and BEFORE digest so digest reflects the applied state.
run_step "auto-apply" "${BIN_DIR}/autoheal-auto-apply.sh"  || true

# Step 3: digest (Epic 7).
run_step "digest"     "${BIN_DIR}/autoheal-digest.sh"      || true

# Step 4: email (Epic 7).
run_step "email"      "${BIN_DIR}/autoheal-email.sh"       || true

# Step 5: publish (Epic 12).
run_step "publish"    "${BIN_DIR}/autoheal-publish.sh"     || true

# Step 6: retention (Epic 12).
run_step "retention"  "${BIN_DIR}/autoheal-retention.sh"   || true

RUN_COMPLETE=1
log "autoheal-daily done (steps: ${STEP_RCS# })"

# The exit code comes from the heartbeat trap: 1 when the analyze step failed
# without a recorded daily-cap refusal, 0 otherwise.
exit 0
