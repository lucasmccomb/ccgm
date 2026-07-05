#!/usr/bin/env bash
# CCGM dreaming — daily chain wrapper (Epic 6; chain order revised by the
# optimistic-memory plan.md Epic 3).
#
# Full nightly chain (plan.md §5 Epic 3/6):
#   1. bin/dream-analyze.sh       (Epic 3) — mine + map/reduce -> proposals
#   2. eval-refresh                — opt-in, weekly, cost-capped live eval
#      refresh so dream-eval.sh --gate's 14-day freshness bound stays met
#      without manual intervention (fix (b) for adrev-opt-001). Runs BEFORE
#      optimistic-integrate so a freshly-refreshed result is available to
#      the SAME night's gate check.
#   3. optimistic-integrate        — opt-in, config- AND eval-gated (see
#      below). The full per-op-kind posture engine
#      (apply_dream_proposal.run_optimistic_integrate) -- supersedes the
#      retired verify-only auto-apply step. Runs BEFORE digest so the
#      digest reports tonight's batch while its dwell window is still
#      entirely ahead of it (the pre-Epic-3 order ran auto-apply AFTER
#      digest, which meant a batch was never reported until its own dwell
#      had already expired).
#   4. bin/dream-digest.sh        (Epic 3) — render today's digest
#   5. bin/dream-reconcile.sh     (Epic 8) — read-only auto-memory reconciliation.
#      Does not exist yet; run_step's "missing -> skip, return 0" makes this
#      a harmless no-op until Epic 8 lands it (mirrors autoheal-daily.sh's
#      own "steps that land in later epics" tolerance).
#   6. retention                   — gzip >30d, delete >60d (mirrors
#      modules/autoheal/bin/autoheal-retention.sh, scoped to dreaming's dirs).
#
# Each step is exit-tolerant: a failure of one step does not kill the rest.
# The wrapper exits 0 unless EVERY step failed (mirrors autoheal-daily.sh's
# launchd-friendly contract: a faulty individual step should not trigger a
# whole-job launchd cooldown).
#
# Usage:
#   dream-daily.sh [--offline DIR] [--force-day YYYY-MM-DD] [--slugs A,B,C]
#                  [--projects-root DIR] [--dry-run]
#
# All flags are forwarded VERBATIM to dream-analyze.sh, which already owns
# this exact surface (bin/dream-analyze.sh --help). --force-day additionally
# tells this wrapper which day the digest/optimistic-integrate/eval-refresh/
# retention steps are "for", so `--force-day 2026-01-01` produces a fully
# self-consistent run for that single day end to end.
#
# Env overrides (tests):
#   CCGM_DREAMING_DIR          default ~/.claude/dreaming
#   CCGM_DREAMING_LOGS_DIR     default ~/.claude/logs
#   CCGM_DREAMING_TODAY        default $(date -u +%Y-%m-%d); overridden by
#                               --force-day when given
#   CCGM_DREAMING_BIN_DIR      default to dirname of this script
#   CCGM_DREAMING_EVAL_SCRIPT  default ${CCGM_DREAMING_BIN_DIR}/dream-eval.sh
#                               (Epic 7); override to test the optimistic-
#                               integrate fail-closed gate independent of
#                               whether that file exists in this checkout
#   CCGM_DREAMING_EVAL_REFRESH_SCRIPT  override for the live eval harness
#                               the eval-refresh step invokes (tests only --
#                               see apply_dream_proposal.py's
#                               _eval_script_path())

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_DIR="${CCGM_DREAMING_BIN_DIR:-${SCRIPT_DIR}}"
DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
LOGS_DIR="${CCGM_DREAMING_LOGS_DIR:-${HOME}/.claude/logs}"

# ---------------------------------------------------------------------
# Extract --force-day (or --force-day=VALUE) from the forwarded argv so
# the digest/auto-apply/retention steps know which day this run is for.
# Everything in "$@" is still forwarded to dream-analyze.sh unchanged.
# ---------------------------------------------------------------------

FORCE_DAY=""
ARGS=("$@")
i=0
while [ "${i}" -lt "${#ARGS[@]}" ]; do
    arg="${ARGS[$i]}"
    case "${arg}" in
        --force-day)
            i=$((i + 1))
            FORCE_DAY="${ARGS[$i]:-}"
            ;;
        --force-day=*)
            FORCE_DAY="${arg#--force-day=}"
            ;;
    esac
    i=$((i + 1))
done

if [ -n "${FORCE_DAY}" ]; then
    TODAY="${FORCE_DAY}"
elif [ -n "${CCGM_DREAMING_TODAY:-}" ]; then
    TODAY="${CCGM_DREAMING_TODAY}"
else
    TODAY="$(date -u +%Y-%m-%d)"
fi

mkdir -p "${LOGS_DIR}"
DAILY_LOG="${LOGS_DIR}/dreaming-daily-${TODAY}.log"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >>"${DAILY_LOG}"
}

run_step() {
    local label="$1"
    local path="$2"
    shift 2

    if [ ! -f "${path}" ]; then
        log "skip ${label}: ${path} not present"
        return 0
    fi

    log "run  ${label}: ${path} $*"
    if bash "${path}" "$@" >>"${DAILY_LOG}" 2>&1; then
        log "ok   ${label}"
        return 0
    else
        local rc=$?
        log "fail ${label}: exit=${rc}"
        return ${rc}
    fi
}

# ---------------------------------------------------------------------
# Shared config gate: is optimistic auto-integration active?
#
# True iff ONLY `optimistic_integration.enabled` is true -- enabled-only,
# no legacy bridge (review fix for #801, PR #810). The legacy
# `auto_apply_counters` flag is intentionally NOT read here: migrating a
# `true` legacy flag into `optimistic_integration.enabled` is Epic 8's job
# (memory-setup.sh offers optimistic mode as an explicit, logged opt-in
# prompt, plan.md §3.5), not an implicit OR-bridge in this gate. Bridging
# the two would let the new engine -- and its ~$2/night eval-refresh API
# spend -- silently activate on a machine that only ever opted into the
# OLD verify-only auto-apply step, without the operator ever seeing or
# confirming the migration.
# Both new steps below (eval-refresh, optimistic-integrate) share this one
# gate so they turn on and off together.
# ---------------------------------------------------------------------

_optimistic_integration_active() {
    local cfg="${DREAMING_DIR}/config.json"
    if [ ! -f "${cfg}" ]; then
        echo false
        return
    fi
    python3 -c "
import json, sys
try:
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('false')
    sys.exit(0)
if not isinstance(cfg, dict):
    print('false')
    sys.exit(0)
opt = cfg.get('optimistic_integration')
enabled = isinstance(opt, dict) and bool(opt.get('enabled', False))
print('true' if enabled else 'false')
" "${cfg}" 2>/dev/null || echo false
}

# ---------------------------------------------------------------------
# Step 2: weekly, cost-capped eval refresh (fix (b) for adrev-opt-001).
#
# Gated on _optimistic_integration_active() only -- the preconditions that
# actually decide whether a refresh RUNS (results-file age, API key
# presence, its own eval_refresh_cost_cap_usd budget) live in
# apply_dream_proposal.py's run_eval_refresh(), not here, so this step is
# a thin, always-safe wrapper: it never blocks the rest of the chain and
# never itself decides whether to spend money. Placed BEFORE
# optimistic-integrate so a freshly-refreshed result is available to the
# SAME night's --gate check.
#
# Always returns 0: any stand-down (inactive, too fresh, no key, cap
# exhausted) is a successful, expected outcome, never a chain failure.
# ---------------------------------------------------------------------

run_eval_refresh_step() {
    if [ "$(_optimistic_integration_active)" != "true" ]; then
        log "eval-refresh: optimistic integration inactive; skipping ${TODAY}"
        return 0
    fi

    log "eval-refresh: running apply_dream_proposal.py eval-refresh for ${TODAY}"
    local refresh_out refresh_rc
    refresh_out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" eval-refresh --day "${TODAY}" 2>&1)"
    refresh_rc=$?
    printf '%s\n' "${refresh_out}" >>"${DAILY_LOG}"
    log "eval-refresh: exit=${refresh_rc} (${refresh_out})"
    return 0
}

# ---------------------------------------------------------------------
# Step 3: opt-in, config- AND eval-gated optimistic auto-integration.
# Supersedes the retired verify-only auto-apply step.
#
# Two independent gates must BOTH pass before anything is applied:
#   (a) config gate: _optimistic_integration_active() above (default false
#       -- optimistic integration stays off until a human opts in).
#   (b) eval gate: `bin/dream-eval.sh --gate` must exit 0. dream-eval.sh is
#       Epic 7's deliverable; a missing eval harness FAILS CLOSED (no
#       integration this run) rather than being treated as "no gate
#       configured, proceed anyway". This is the same fail-closed posture
#       modules/autoheal/bin/autoheal-auto-apply.sh uses for its own
#       missing-evaluator case, and the same posture the retired
#       run_auto_apply_step used.
#
# Per plan.md Epic 3, the full per-op-kind posture/cap/anomaly/breaker
# engine lives in apply_dream_proposal.py's run_optimistic_integrate(), not
# here -- this function's job is only the two gates above, then a single
# CLI invocation for the day.
#
# Red-gate-as-anomaly (review fix for #801, PR #810): plan.md §3.5 says the
# breaker trips on "batch-anomaly fire OR red eval gate" -- but a red
# `--gate` result short-circuits BEFORE `apply_dream_proposal.py
# optimistic-integrate` is ever invoked, so the breaker's own anomaly_log
# previously had zero memory of a red-gate streak. When gate (b) fails,
# this function now ALSO calls `apply_dream_proposal.py record-anomaly
# --reason red_eval_gate` before returning -- still fail-closed (no
# integration on a red gate; only the anomaly itself is recorded).
#
# Always returns 0: a stand-down (disabled, gate missing, gate red) is a
# successful, expected outcome, never a chain failure (mirrors
# autoheal-auto-apply.sh's own "Exit codes: 0 always" contract).
# ---------------------------------------------------------------------

run_optimistic_integrate_step() {
    if [ "$(_optimistic_integration_active)" != "true" ]; then
        log "optimistic-integrate: optimistic_integration.enabled=false (default off); skipping ${TODAY}"
        return 0
    fi

    # CCGM_DREAMING_EVAL_SCRIPT lets tests (and any future alternate
    # deployment layout) point this at a controlled path independent of
    # BIN_DIR, so the fail-closed-when-missing behavior stays testable
    # regardless of whether Epic 7 has landed the real dream-eval.sh in
    # this checkout yet.
    local eval_script="${CCGM_DREAMING_EVAL_SCRIPT:-${BIN_DIR}/dream-eval.sh}"
    if [ ! -f "${eval_script}" ]; then
        log "optimistic-integrate: ${eval_script} missing (Epic 7 not yet installed); failing closed -- no integration this run"
        return 0
    fi

    local gate_out gate_rc
    gate_out="$(bash "${eval_script}" --gate 2>&1)"
    gate_rc=$?
    if [ "${gate_rc}" -ne 0 ]; then
        log "optimistic-integrate: dream-eval.sh --gate exit=${gate_rc}; failing closed (${gate_out})"
        local anomaly_out anomaly_rc
        anomaly_out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" record-anomaly --reason red_eval_gate 2>&1)"
        anomaly_rc=$?
        printf '%s\n' "${anomaly_out}" >>"${DAILY_LOG}"
        log "optimistic-integrate: recorded red_eval_gate anomaly (exit=${anomaly_rc})"
        return 0
    fi

    log "optimistic-integrate: eval gate passed; running apply_dream_proposal.py optimistic-integrate for ${TODAY}"
    local integrate_out integrate_rc
    integrate_out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" optimistic-integrate --day "${TODAY}" 2>&1)"
    integrate_rc=$?
    printf '%s\n' "${integrate_out}" >>"${DAILY_LOG}"
    if [ "${integrate_rc}" -ne 0 ]; then
        log "optimistic-integrate: apply_dream_proposal.py exit=${integrate_rc} (see log for details)"
    else
        log "optimistic-integrate: done (${integrate_out})"
    fi
    return 0
}

# ---------------------------------------------------------------------
# Step 5: retention sweep — gzip >30d, delete >60d.
#
# Scoped to date-named, safely-sweepable artifacts only: proposals/*.jsonl,
# digests/*.md, state/runs/*.json. Deliberately EXCLUDES the perpetual,
# non-date-named state files this module depends on staying intact forever:
# state/last-dreamed.json (watermark), state/canary.json (durable incident
# marker), state/apply-audit.jsonl (audit trail), state/.apply.lock. An
# mtime-based sweep would never touch these anyway (they are continuously
# rewritten/appended, so their mtime never ages past the threshold) but the
# subdir list below never even considers them, for clarity.
# ---------------------------------------------------------------------

run_retention_step() {
    local cfg="${DREAMING_DIR}/config.json"
    local gzip_days="${CCGM_DREAMING_RETENTION_GZIP:-}"
    local delete_days="${CCGM_DREAMING_RETENTION_DELETE:-}"

    if [ -z "${gzip_days}" ] || [ -z "${delete_days}" ]; then
        if [ -f "${cfg}" ]; then
            local cfg_out
            cfg_out="$(python3 -c "
import json, sys
try:
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    cfg = {}
if not isinstance(cfg, dict):
    cfg = {}
print(cfg.get('retention_gzip_days', 30))
print(cfg.get('retention_delete_days', 60))
" "${cfg}" 2>/dev/null)"
            if [ -z "${gzip_days}" ]; then
                gzip_days="$(printf '%s\n' "${cfg_out}" | sed -n '1p')"
            fi
            if [ -z "${delete_days}" ]; then
                delete_days="$(printf '%s\n' "${cfg_out}" | sed -n '2p')"
            fi
        fi
    fi

    case "${gzip_days}" in ''|*[!0-9]*) gzip_days=30 ;; esac
    case "${delete_days}" in ''|*[!0-9]*) delete_days=60 ;; esac

    local subdirs=(proposals digests state/runs)
    local gzipped=0 deleted=0 errors=0

    for sub in "${subdirs[@]}"; do
        local dir="${DREAMING_DIR}/${sub}"
        [ -d "${dir}" ] || continue
        while IFS= read -r path; do
            [ -z "${path}" ] && continue
            case "${path}" in *.gz) continue ;; esac
            if gzip -f -- "${path}" 2>/dev/null; then
                gzipped=$((gzipped + 1))
            else
                errors=$((errors + 1))
            fi
        done < <(find "${dir}" -maxdepth 1 -type f \( -name '*.jsonl' -o -name '*.md' -o -name '*.json' \) -mtime "+${gzip_days}" 2>/dev/null)
    done

    for sub in "${subdirs[@]}"; do
        local dir="${DREAMING_DIR}/${sub}"
        [ -d "${dir}" ] || continue
        while IFS= read -r path; do
            [ -z "${path}" ] && continue
            if rm -f -- "${path}" 2>/dev/null; then
                deleted=$((deleted + 1))
            else
                errors=$((errors + 1))
            fi
        done < <(find "${dir}" -maxdepth 1 -type f -name '*.gz' -mtime "+${delete_days}" 2>/dev/null)
    done

    log "retention: gzipped=${gzipped} deleted=${deleted} errors=${errors} (gzip>${gzip_days}d, delete>${delete_days}d)"
    return 0
}

# ---------------------------------------------------------------------
# Chain.
# ---------------------------------------------------------------------

steps_total=0
steps_failed=0

log "dream-daily start (${TODAY})"

steps_total=$((steps_total + 1))
run_step "analyze" "${BIN_DIR}/dream-analyze.sh" "$@" || steps_failed=$((steps_failed + 1))

# eval-refresh, optimistic-integrate, and retention always return 0 (see
# comments above) -- their own internal stand-down/failure reasons are
# logged, never surfaced as a chain step failure.
steps_total=$((steps_total + 1))
run_eval_refresh_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_optimistic_integrate_step || steps_failed=$((steps_failed + 1))

# digest runs AFTER optimistic-integrate (chain order revised by
# optimistic-memory plan.md Epic 3) so tonight's just-integrated batch is
# reported while its dwell window is still entirely ahead of it.
steps_total=$((steps_total + 1))
run_step "digest" "${BIN_DIR}/dream-digest.sh" "${TODAY}" || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_step "reconcile" "${BIN_DIR}/dream-reconcile.sh" || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_retention_step || steps_failed=$((steps_failed + 1))

log "dream-daily done (failed=${steps_failed}/${steps_total})"

# Exit 0 unless EVERY step failed — a faulty individual step should not
# trigger a whole-job launchd cooldown (mirrors autoheal-daily.sh).
if [ "${steps_failed}" -eq "${steps_total}" ] && [ "${steps_total}" -gt 0 ]; then
    exit 1
fi
exit 0
