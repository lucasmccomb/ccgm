#!/usr/bin/env bash
# CCGM dreaming — daily chain wrapper (Epic 6; chain order revised by the
# optimistic-memory plan.md Epic 3).
#
# Full nightly chain (plan.md §5 Epic 3/6):
#   0. breaker-check               — active mode only: resume a suspended
#      circuit breaker after N quiet nights with no content anomaly, before
#      and independent of the eval gate (#1098 item 2.2).
#   1. bin/dream-analyze.sh       (Epic 3) — mine + map/reduce -> proposals
#   2. eval-refresh                — OFF by default (`eval_refresh_enabled`
#      must be true; #1098 item 0.1). When opted in: weekly, live eval
#      refresh under a hard total-cost stop so dream-eval.sh --gate's 7-day
#      freshness bound stays met (fix (b) for adrev-opt-001). Runs BEFORE
#      optimistic-integrate so a freshly-refreshed result is available to
#      the SAME night's gate check.
#   3. optimistic-integrate        — opt-in, config- AND eval-gated, and
#      paused on a night the analyze step failed (see below). Every night it
#      does not integrate records one infra or content anomaly. The full
#      per-op-kind posture engine
#      (apply_dream_proposal.run_optimistic_integrate) -- supersedes the
#      retired verify-only auto-apply step. Runs BEFORE digest so the
#      digest reports tonight's batch while its dwell window is still
#      entirely ahead of it (the pre-Epic-3 order ran auto-apply AFTER
#      digest, which meant a batch was never reported until its own dwell
#      had already expired).
#   3b. expire-pending             — active mode only, whatever the gate said:
#      pending proposals older than 48h are discarded `expired` (#1098 2.3).
#      With integration off or in shadow nothing is discarded.
#   4. bin/dream-digest.sh        (Epic 3) — render today's digest
#   5. bin/dream-reconcile.sh     (Epic 8) — read-only auto-memory reconciliation.
#      Does not exist yet; run_step's "missing -> skip, return 0" makes this
#      a harmless no-op until Epic 8 lands it (mirrors autoheal-daily.sh's
#      own "steps that land in later epics" tolerance).
#   6. scorecard                   — Sundays only (UTC): bin/dream-scorecard.sh
#      writes scorecards/<date>.md (#1098 item 1.3).
#   7. retention                   — gzip >30d, delete >60d (mirrors
#      modules/autoheal/bin/autoheal-retention.sh, scoped to dreaming's dirs).
#      A proposals file with pending rows is deleted only in active mode,
#      after its rows are audited `expired`; otherwise it is kept.
#   EXIT trap (always, even after a crash or SIGTERM): lib/health.py rewrites
#      state/health.json from scratch (#1098 item 1.1), so a broken chain
#      announces itself in the next session via hooks/dreaming-health.py.
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

# Bound a command's wall-clock (composite-eligibility plan.md §5 E3 / §9.3).
# The optimistic-integrate step re-verifies transcripts at apply time, so a
# pathologically large transcript could hang it under launchd; `timeout 600`
# caps it. The default SIGTERM is caught by run_optimistic_integrate's
# SIGTERM-safe handler (commit-what-it-has + record a timeout anomaly).
# POSIX-clean + portable: prefer coreutils `timeout`, then macOS/brew
# `gtimeout`; if neither exists, run the command directly (no bound rather
# than a hard failure) so the step is never broken by a missing utility.
_run_with_timeout() {
    local secs="$1"; shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "${secs}" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "${secs}" "$@"
    else
        "$@"
    fi
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
# the two would let the new engine -- and its eval-refresh API
# spend -- silently activate on a machine that only ever opted into the
# OLD verify-only auto-apply step, without the operator ever seeing or
# confirming the migration.
# Both new steps below (eval-refresh, optimistic-integrate) share this one
# gate so they turn on and off together.
# ---------------------------------------------------------------------

_optimistic_integration_mode() {
    local cfg="${DREAMING_DIR}/config.json"
    if [ ! -f "${cfg}" ]; then
        echo off
        return
    fi
    # rollout_mode.py is the one resolver: a persisted boolean reads as
    # active/off, "shadow" is shadow, anything else fails closed to off.
    python3 "${MODULE_ROOT}/lib/rollout_mode.py" "${cfg}" 2>/dev/null || echo off
}

# True iff the mode is "active". Shadow integrates nothing, so the steps that
# spend money or write the store (eval-refresh, a real integrate) key on this.
_optimistic_integration_active() {
    if [ "$(_optimistic_integration_mode)" = "active" ]; then
        echo true
    else
        echo false
    fi
}

# ---------------------------------------------------------------------
# Step 2: weekly, cost-capped eval refresh (fix (b) for adrev-opt-001).
#
# Gated on _optimistic_integration_active() only -- the preconditions that
# actually decide whether a refresh RUNS (eval_refresh_enabled, default
# false; results-file age, API key presence, its own
# eval_refresh_cost_cap_usd budget) live in
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
# Step 0: breaker resume check (#1098 item 2.2). Runs first, before analyze
# and independent of the eval gate: a suspended breaker resumes after N quiet
# nights (default 7) with no CONTENT anomaly, even on a night the gate is
# paused. Resuming only clears content anomalies; integration still needs
# tonight's gate to be open. Active mode only (shadow never writes breaker
# state). Always returns 0.
# ---------------------------------------------------------------------

run_breaker_check_step() {
    if [ "$(_optimistic_integration_active)" != "true" ]; then
        return 0
    fi
    local out rc
    out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" breaker-check 2>&1)"
    rc=$?
    log "breaker-check: exit=${rc} ${out}"
    return 0
}

# ---------------------------------------------------------------------
# Step 3: opt-in, config- AND eval-gated optimistic auto-integration.
#
# Two independent gates must BOTH pass before anything is applied:
#   (a) config gate: _optimistic_integration_mode() above (default off).
#   (b) eval gate: `bin/dream-eval.sh --gate` prints
#       {"gate": "open"|"closed"|"paused", "code", "reason", "since"} and
#       exits 0 / 1 / 3 (#1098 item 2.1). Integration runs only on open.
#
# Every night that does not integrate records ONE anomaly through
# `apply_dream_proposal.py record-anomaly`, and its class decides what the
# breaker does with it (#1098 item 2.2, lib/breaker.py):
#   * infra (pauses tonight, never counts toward a trip):
#       eval_gate_paused  -- the gate said paused (missing, stale, broken or
#                            budget-aborted results)
#       harness_failure   -- the eval script is missing, crashed, or printed
#                            something other than the documented JSON
#       analyze_failed    -- tonight's analyze step exited non-zero, so
#                            tonight's proposals are not trustworthy
#   * content (counts toward a trip; a trip reverts implicated batches):
#       eval_regression --since <last green run> -- the gate said closed.
#       With no batch integrated since the last green run it is recorded
#       as eval_regression_unattributed, which is infra.
#
# Shadow mode runs the same gates but records nothing: an anomaly would move
# the live breaker. Always returns 0 (a stand-down is an expected outcome).
# ---------------------------------------------------------------------

_record_anomaly() {
    local out rc
    out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" record-anomaly "$@" 2>&1)"
    rc=$?
    printf '%s\n' "${out}" >>"${DAILY_LOG}"
    log "optimistic-integrate: recorded anomaly $* (exit=${rc})"
}

# Prints "<gate>|<code>|<since>" from the gate's JSON (its last stdout
# line), or nothing when the output is not the documented shape.
_parse_gate_json() {
    printf '%s\n' "$1" | python3 -c '
import json, sys
lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
try:
    d = json.loads(lines[-1])
except (IndexError, ValueError):
    sys.exit(0)
if isinstance(d, dict) and d.get("gate") in ("open", "closed", "paused"):
    print("|".join([d["gate"], str(d.get("code") or ""), str(d.get("since") or "")]))
' 2>/dev/null
}

run_optimistic_integrate_step() {
    local mode shadow_flag=""
    mode="$(_optimistic_integration_mode)"
    if [ "${mode}" = "off" ]; then
        log "optimistic-integrate: optimistic_integration.enabled=false (default off); skipping ${TODAY}"
        return 0
    fi
    if [ "${mode}" = "shadow" ]; then
        shadow_flag="--shadow"
    fi

    # CCGM_DREAMING_EVAL_SCRIPT lets tests point this at a controlled path.
    local eval_script="${CCGM_DREAMING_EVAL_SCRIPT:-${BIN_DIR}/dream-eval.sh}"
    local gate="paused" code="" since="" reason_args=()
    if [ ! -f "${eval_script}" ]; then
        log "optimistic-integrate: ${eval_script} missing (Epic 7 not yet installed); gate paused (harness_failure); failing closed -- no integration this run"
        reason_args=(--reason harness_failure)
    else
        local gate_out gate_rc parsed
        gate_out="$(bash "${eval_script}" --gate 2>&1)"
        gate_rc=$?
        parsed="$(_parse_gate_json "${gate_out}")"
        if [ -n "${parsed}" ]; then
            IFS='|' read -r gate code since <<<"${parsed}"
            # The exit code must agree with the JSON; a mismatch is a broken
            # gate, never a content verdict.
            case "${gate}:${gate_rc}" in
                open:0|closed:1|paused:3) ;;
                *) gate="paused"; code="harness_failure" ;;
            esac
        elif [ "${gate_rc}" -eq 0 ]; then
            gate="open"  # a gate that exits 0 without JSON (test stubs)
        else
            gate="paused"; code="harness_failure"  # crashed or printed something else
        fi

        case "${gate}" in
            open)
                if [ -n "${ANALYZE_RC}" ] && [ "${ANALYZE_RC}" -ne 0 ]; then
                    log "optimistic-integrate: eval gate open but the analyze step failed (exit=${ANALYZE_RC}); gate paused (analyze_failed); failing closed -- no integration this run"
                    gate="paused"
                    reason_args=(--reason analyze_failed)
                fi
                ;;
            closed)
                log "optimistic-integrate: dream-eval.sh --gate exit=${gate_rc}; gate closed (${code}); failing closed -- no integration this run (${gate_out})"
                reason_args=(--reason eval_regression)
                if [ -n "${since}" ]; then
                    reason_args+=(--since "${since}")
                fi
                ;;
            paused)
                log "optimistic-integrate: dream-eval.sh --gate exit=${gate_rc}; gate paused (${code}); failing closed -- no integration this run (${gate_out})"
                if [ "${code}" = "harness_failure" ]; then
                    reason_args=(--reason harness_failure)
                else
                    reason_args=(--reason eval_gate_paused)
                fi
                ;;
        esac
    fi

    if [ "${gate}" != "open" ]; then
        if [ "${mode}" = "shadow" ]; then
            log "optimistic-integrate: shadow mode; no anomaly recorded, nothing decided this run"
            return 0
        fi
        _record_anomaly "${reason_args[@]}"
        return 0
    fi

    log "optimistic-integrate: eval gate open; running apply_dream_proposal.py optimistic-integrate for ${TODAY}"
    local integrate_out integrate_rc
    # timeout 600 bounds the apply-time re-verification cost (plan.md §5 E3);
    # a fired timeout SIGTERMs the process, which its SIGTERM-safe handler turns
    # into a clean commit-what-it-has + a recorded timeout anomaly (never a
    # dirty tree). Exit-tolerance is preserved: this step always returns 0.
    integrate_out="$(_run_with_timeout 600 python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" optimistic-integrate --day "${TODAY}" ${shadow_flag} 2>&1)"
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
# Step 3b: expiry sweep (#1098 item 2.3). Active mode only, whatever the gate
# said tonight: a pending proposal older than pending_max_age_hours (48) is
# discarded `expired`, so no backlog forms behind a paused gate or a
# suspended breaker. Off and shadow hold everything. Always returns 0.
# ---------------------------------------------------------------------

run_expire_step() {
    if [ "$(_optimistic_integration_active)" != "true" ]; then
        log "expire-pending: optimistic integration not active; holding every pending proposal"
        return 0
    fi
    local out rc
    out="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" expire-pending 2>&1)"
    rc=$?
    log "expire-pending: exit=${rc} ${out}"
    return 0
}

# ---------------------------------------------------------------------
# Step 5: retention sweep — gzip >30d, delete >60d.
#
# A proposals file is deleted only through `retention-check` (#1098 2.3): in
# active mode its pending rows are audited `expired` first; in off or shadow
# mode a file that still holds a pending row is kept.
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

    local held=0 expired=0
    for sub in "${subdirs[@]}"; do
        local dir="${DREAMING_DIR}/${sub}"
        [ -d "${dir}" ] || continue
        while IFS= read -r path; do
            [ -z "${path}" ] && continue
            if [ "${sub}" = "proposals" ]; then
                # Never delete a pending proposal unrecorded (#1098 2.3): in
                # active mode its rows are audited `expired` first; off and
                # shadow keep the file.
                local check verdict
                check="$(python3 "${MODULE_ROOT}/lib/apply_dream_proposal.py" retention-check "${path}" 2>>"${DAILY_LOG}")"
                verdict="$(printf '%s\n' "${check}" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read().strip().splitlines()[-1])
except (IndexError, ValueError):
    d = {}
print("delete" if d.get("delete") is True else "keep", int(d.get("expired") or 0))
' 2>/dev/null)"
                case "${verdict}" in
                    delete*) expired=$((expired + ${verdict#delete })) ;;
                    *) held=$((held + 1)); continue ;;
                esac
            fi
            if rm -f -- "${path}" 2>/dev/null; then
                deleted=$((deleted + 1))
            else
                errors=$((errors + 1))
            fi
        done < <(find "${dir}" -maxdepth 1 -type f -name '*.gz' -mtime "+${delete_days}" 2>/dev/null)
    done

    log "retention: gzipped=${gzipped} deleted=${deleted} expired=${expired} held=${held} errors=${errors} (gzip>${gzip_days}d, delete>${delete_days}d)"
    return 0
}

# ---------------------------------------------------------------------
# Weekly scorecard: Sundays (UTC), for the day this run is for.
# Always returns 0 -- a scorecard failure never fails the chain.
# ---------------------------------------------------------------------

run_scorecard_step() {
    local dow
    dow="$(python3 -c 'import datetime, sys; print(datetime.date.fromisoformat(sys.argv[1]).isoweekday())' "${TODAY}" 2>/dev/null)"
    if [ "${dow}" != "7" ]; then
        return 0
    fi
    run_step "scorecard" "${BIN_DIR}/dream-scorecard.sh" "${TODAY}" || true
    return 0
}

# ---------------------------------------------------------------------
# Health file (EXIT trap). Runs on normal exit, on `exit 1`, on a set -u
# abort, and on SIGTERM/SIGINT/SIGHUP (the signal traps turn the signal into
# an exit so the EXIT trap fires). Never changes the chain's exit status.
# ---------------------------------------------------------------------

ANALYZE_RC=""

write_health() {
    local rc=$?
    trap - EXIT
    local rc_args=()
    if [ -n "${ANALYZE_RC}" ]; then
        rc_args=(--analyze-rc "${ANALYZE_RC}")
    fi
    python3 "${MODULE_ROOT}/lib/health.py" --dreaming-dir "${DREAMING_DIR}" "${rc_args[@]+"${rc_args[@]}"}" >>"${DAILY_LOG}" 2>&1 || true
    exit "${rc}"
}

trap write_health EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

# ---------------------------------------------------------------------
# Chain.
# ---------------------------------------------------------------------

steps_total=0
steps_failed=0

log "dream-daily start (${TODAY})"

# Breaker resume check first: before analyze, and independent of the gate.
steps_total=$((steps_total + 1))
run_breaker_check_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_step "analyze" "${BIN_DIR}/dream-analyze.sh" "$@"
ANALYZE_RC=$?
if [ "${ANALYZE_RC}" -ne 0 ]; then
    steps_failed=$((steps_failed + 1))
fi

# breaker-check, eval-refresh, optimistic-integrate, and retention always return 0 (see
# comments above) -- their own internal stand-down/failure reasons are
# logged, never surfaced as a chain step failure.
steps_total=$((steps_total + 1))
run_eval_refresh_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_optimistic_integrate_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_expire_step || steps_failed=$((steps_failed + 1))

# digest runs AFTER optimistic-integrate (chain order revised by
# optimistic-memory plan.md Epic 3) so tonight's just-integrated batch is
# reported while its dwell window is still entirely ahead of it.
steps_total=$((steps_total + 1))
run_step "digest" "${BIN_DIR}/dream-digest.sh" "${TODAY}" || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_step "reconcile" "${BIN_DIR}/dream-reconcile.sh" || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_scorecard_step || steps_failed=$((steps_failed + 1))

steps_total=$((steps_total + 1))
run_retention_step || steps_failed=$((steps_failed + 1))

log "dream-daily done (failed=${steps_failed}/${steps_total})"

# Exit 0 unless EVERY step failed — a faulty individual step should not
# trigger a whole-job launchd cooldown (mirrors autoheal-daily.sh).
if [ "${steps_failed}" -eq "${steps_total}" ] && [ "${steps_total}" -gt 0 ]; then
    exit 1
fi
exit 0
