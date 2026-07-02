#!/usr/bin/env bash
# CCGM dreaming — daily chain wrapper (Epic 6).
#
# Full nightly chain (plan.md §5 Epic 6):
#   1. bin/dream-analyze.sh    (Epic 3) — mine + map/reduce -> proposals
#   2. bin/dream-digest.sh     (Epic 3) — render today's digest
#   3. bin/dream-reconcile.sh  (Epic 8) — read-only auto-memory reconciliation.
#      Does not exist yet; run_step's "missing -> skip, return 0" makes this
#      a harmless no-op until Epic 8 lands it (mirrors autoheal-daily.sh's
#      own "steps that land in later epics" tolerance).
#   4. auto-apply              — opt-in, config- AND eval-gated (see below).
#   5. retention                — gzip >30d, delete >60d (mirrors
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
# tells this wrapper which day the digest/auto-apply/retention steps are
# "for", so `--force-day 2026-01-01` produces a fully self-consistent run
# for that single day end to end.
#
# Env overrides (tests):
#   CCGM_DREAMING_DIR          default ~/.claude/dreaming
#   CCGM_DREAMING_LOGS_DIR     default ~/.claude/logs
#   CCGM_DREAMING_TODAY        default $(date -u +%Y-%m-%d); overridden by
#                               --force-day when given
#   CCGM_DREAMING_BIN_DIR      default to dirname of this script
#   CCGM_DREAMING_EVAL_SCRIPT  default ${CCGM_DREAMING_BIN_DIR}/dream-eval.sh
#                               (Epic 7); override to test the auto-apply
#                               fail-closed gate independent of whether
#                               that file exists in this checkout

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
# Step 4: opt-in, config- AND eval-gated auto-apply.
#
# Two independent gates must BOTH pass before anything is applied:
#   (a) config gate: ~/.claude/dreaming/config.json's `auto_apply_counters`
#       must be true (default false — auto-apply stays off until a human
#       opts in).
#   (b) eval gate: `bin/dream-eval.sh --gate` must exit 0. dream-eval.sh is
#       Epic 7's deliverable and does not exist in this branch yet — a
#       missing eval harness FAILS CLOSED (no auto-apply this run) rather
#       than being treated as "no gate configured, proceed anyway". This is
#       the same fail-closed posture modules/autoheal/bin/autoheal-auto-apply.sh
#       uses for its own missing-evaluator case.
#
# Per plan.md Epic 6 / sec-5, the per-proposal STRUCTURAL predicate (kind ==
# learning_verify AND confidence >= 9 AND status == pending — NEVER
# learning_add/supersede/deprecate/contradict at any confidence) lives in
# apply_dream_proposal.py's run_auto_apply(), not here — this function's job
# is only the two gates above, then a single CLI invocation for the day.
#
# Always returns 0: an auto-apply stand-down (disabled, gate missing, gate
# red) is a successful, expected outcome, never a chain failure (mirrors
# autoheal-auto-apply.sh's own "Exit codes: 0 always" contract).
# ---------------------------------------------------------------------

run_auto_apply_step() {
    local cfg="${DREAMING_DIR}/config.json"
    local enabled="false"
    if [ -f "${cfg}" ]; then
        enabled="$(python3 -c "
import json, sys
try:
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('false')
    sys.exit(0)
print('true' if isinstance(cfg, dict) and bool(cfg.get('auto_apply_counters', False)) else 'false')
" "${cfg}" 2>/dev/null || echo false)"
    fi

    if [ "${enabled}" != "true" ]; then
        log "auto-apply: auto_apply_counters=false (default off); skipping ${TODAY}"
        return 0
    fi

    # CCGM_DREAMING_EVAL_SCRIPT lets tests (and any future alternate
    # deployment layout) point this at a controlled path independent of
    # BIN_DIR, so the fail-closed-when-missing behavior stays testable
    # regardless of whether Epic 7 has landed the real dream-eval.sh in
    # this checkout yet.
    local eval_script="${CCGM_DREAMING_EVAL_SCRIPT:-${BIN_DIR}/dream-eval.sh}"
    if [ ! -f "${eval_script}" ]; then
        log "auto-apply: ${eval_script} missing (Epic 7 not yet installed); failing closed -- no auto-apply this run"
        return 0
    fi

    local gate_out gate_rc
    gate_out="$(bash "${eval_script}" --gate 2>&1)"
    gate_rc=$?
    if [ "${gate_rc}" -ne 0 ]; then
        log "auto-apply: dream-eval.sh --gate exit=${gate_rc}; failing closed (${gate_out})"
        return 0
    fi

    log "auto-apply: eval gate passed; running apply_dream_proposal.py auto-apply for ${TODAY}"
    local apply_out apply_rc
    apply_out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" auto-apply --day "${TODAY}" 2>&1)"
    apply_rc=$?
    printf '%s\n' "${apply_out}" >>"${DAILY_LOG}"
    if [ "${apply_rc}" -ne 0 ]; then
        log "auto-apply: apply_dream_proposal.py exit=${apply_rc} (see log for details)"
    else
        log "auto-apply: done (${apply_out})"
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

steps_total=$((steps_total + 1))
run_step "digest" "${BIN_DIR}/dream-digest.sh" "${TODAY}" || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_step "reconcile" "${BIN_DIR}/dream-reconcile.sh" || steps_failed=$((steps_failed + 1))

# Auto-apply and retention always return 0 (see comments above) — their own
# internal stand-down/failure reasons are logged, never surfaced as a chain
# step failure.
steps_total=$((steps_total + 1))
run_auto_apply_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_retention_step || steps_failed=$((steps_failed + 1))

log "dream-daily done (failed=${steps_failed}/${steps_total})"

# Exit 0 unless EVERY step failed — a faulty individual step should not
# trigger a whole-job launchd cooldown (mirrors autoheal-daily.sh).
if [ "${steps_failed}" -eq "${steps_total}" ] && [ "${steps_total}" -gt 0 ]; then
    exit 1
fi
exit 0
