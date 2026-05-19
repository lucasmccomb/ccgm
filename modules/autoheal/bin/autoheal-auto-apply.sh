#!/usr/bin/env bash
# autoheal-auto-apply.sh
#
# Epic 11: opt-in confidence-gated auto-apply.
#
# Reads today's proposals from ~/.claude/autoheal/proposals/{today}.jsonl,
# evaluates each against the strict auto-apply gate (plan.md §3.7), and
# routes qualifying proposals through lib/apply-proposal.py. The apply
# logic is shared with /permission-fix apply and /autoheal-apply <id>
# so the branch shape, commit format, and audit record stay identical
# across the three invocation paths.
#
# This script is chained at the end of autoheal-daily.sh (after the
# analyzer has written today's proposals, before the digest). It NEVER
# pushes to remote: it only commits to a feature branch named
# `autoheal/auto/{proposal-id}`. The user reviews the resulting diff and
# opens the PR by hand.
#
# Gate predicate (plan.md §3.7):
#   confidence            >= 9
#   breadth_score         <= 1
#   kind                  == "settings_allow_add"
#   proposed_diff_target  startswith("modules/settings/")
#   snoozed_until         is null
#   auto_apply_blocked    is false
#
# Every apply attempt — success OR failure — appends a record to
# ~/.claude/autoheal/applied/{today}.jsonl. Failures additionally write
# a stderr-tagged line to ~/.claude/logs/autoheal-auto-apply-{today}.log
# so the daily-wrapper log captures the reason without polluting the
# audit trail.
#
# Env overrides (tests):
#   CCGM_AUTOHEAL_CONFIG         default ~/.claude/autoheal/config.json
#   CCGM_AUTOHEAL_PROPOSALS_DIR  default ~/.claude/autoheal/proposals
#   CCGM_AUTOHEAL_APPLIED_DIR    default ~/.claude/autoheal/applied
#   CCGM_AUTOHEAL_LOGS_DIR       default ~/.claude/logs
#   CCGM_AUTOHEAL_TODAY          default $(date -u +%Y-%m-%d)
#   CCGM_AUTOHEAL_CLONE_ROOT     forwarded as CCGM_CLONE_ROOT to
#                                apply-proposal.py
#
# Exit codes:
#   0  always (per autoheal-daily.sh contract: a single failed proposal
#      should not crash the daily wrapper). Per-proposal failures are
#      logged but do not propagate.

set -u

# ---------------------------------------------------------------------
# Resolve module + path defaults.
# ---------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"

CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${HOME}/.claude/autoheal/config.json}"
PROPOSALS_DIR="${CCGM_AUTOHEAL_PROPOSALS_DIR:-${HOME}/.claude/autoheal/proposals}"
APPLIED_DIR="${CCGM_AUTOHEAL_APPLIED_DIR:-${HOME}/.claude/autoheal/applied}"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"

if [ -n "${CCGM_AUTOHEAL_TODAY:-}" ]; then
    TODAY="${CCGM_AUTOHEAL_TODAY}"
else
    TODAY="$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")"
fi

PROPOSALS_FILE="${PROPOSALS_DIR}/${TODAY}.jsonl"
APPLIED_FILE="${APPLIED_DIR}/${TODAY}.jsonl"
LOG_FILE="${LOGS_DIR}/autoheal-auto-apply-${TODAY}.log"

mkdir -p "${APPLIED_DIR}" "${LOGS_DIR}"

# Forward the autoheal-flavored clone-root override to apply-proposal.py,
# which reads CCGM_CLONE_ROOT. We never overwrite an explicit caller-set
# CCGM_CLONE_ROOT so manual invocations still work.
if [ -n "${CCGM_AUTOHEAL_CLONE_ROOT:-}" ] && [ -z "${CCGM_CLONE_ROOT:-}" ]; then
    export CCGM_CLONE_ROOT="${CCGM_AUTOHEAL_CLONE_ROOT}"
fi

# Pass through the env knobs apply-proposal.py honors. These are already
# exported in the daily-wrapper case, but re-exporting in tests keeps the
# script self-contained.
export CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}"
export CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}"
export CCGM_AUTOHEAL_TODAY="${TODAY}"

log() {
    # Append a tagged line to the per-day log AND echo to stderr so the
    # daily wrapper's aggregated log captures it too.
    local msg="$1"
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '[%s] %s\n' "${ts}" "${msg}" >>"${LOG_FILE}"
    printf '[%s] %s\n' "${ts}" "${msg}" >&2
}

# ---------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
    log "python3 not on PATH; auto-apply disabled this run"
    exit 0
fi

if [ ! -f "${APPLY_LIB}" ]; then
    log "apply-proposal.py missing at ${APPLY_LIB}; auto-apply disabled this run"
    exit 0
fi

# ---------------------------------------------------------------------
# Config gate: auto_apply_enabled must be true.
# ---------------------------------------------------------------------

auto_apply_enabled() {
    # Default false. We read with python so we do not depend on jq in the
    # daily-wrapper environment (jq IS present for digest, but the gate
    # script is the safer place to stay python-only).
    if [ ! -f "${CONFIG_FILE}" ]; then
        echo "false"
        return 0
    fi
    python3 - "${CONFIG_FILE}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, json.JSONDecodeError):
    print("false")
    sys.exit(0)

if not isinstance(cfg, dict):
    print("false")
    sys.exit(0)

print("true" if bool(cfg.get("auto_apply_enabled", False)) else "false")
PY
}

ENABLED="$(auto_apply_enabled)"
if [ "${ENABLED}" != "true" ]; then
    log "auto_apply_enabled=false (default off); skipping ${TODAY}"
    exit 0
fi

if [ ! -f "${PROPOSALS_FILE}" ]; then
    log "no proposals file for ${TODAY}; nothing to apply"
    exit 0
fi

# ---------------------------------------------------------------------
# Build the list of proposal ids that pass the gate.
#
# We do the gate evaluation in a single python pass so the predicate
# matches plan.md §3.7 exactly, with no shell-quoting ambiguity. The
# python prints one line per proposal: `<status>\t<id>\t<reason>`, where
# status is one of:
#   QUALIFY   passed the gate; auto-apply will run
#   SKIP      failed the gate; reason names the rejected field
#   BAD_ROW   malformed JSON or missing required field; skipped
# ---------------------------------------------------------------------

evaluate_gate() {
    python3 - "${PROPOSALS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]


def gate(p):
    # Predicate from plan.md §3.7. Return (ok, reason).
    if not isinstance(p, dict):
        return False, "not-a-dict"
    pid = p.get("id")
    if not isinstance(pid, str) or not pid:
        return False, "missing-id"
    try:
        c = int(p.get("confidence"))
    except (TypeError, ValueError):
        return False, "confidence-not-int"
    if c < 9:
        return False, f"confidence<{9} (got {c})"
    try:
        b = int(p.get("breadth_score"))
    except (TypeError, ValueError):
        return False, "breadth_score-not-int"
    if b > 1:
        return False, f"breadth_score>{1} (got {b})"
    kind = p.get("kind")
    if kind != "settings_allow_add":
        return False, f"kind!=settings_allow_add (got {kind!r})"
    target = p.get("proposed_diff_target") or ""
    if not isinstance(target, str) or not target.startswith("modules/settings/"):
        return False, f"target not under modules/settings/ (got {target!r})"
    if p.get("snoozed_until"):
        return False, "snoozed"
    if p.get("auto_apply_blocked"):
        return False, "auto_apply_blocked"
    return True, ""


total = 0
qualified = 0
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            sys.stdout.write("BAD_ROW\t-\tinvalid-json\n")
            continue
        ok, reason = gate(rec)
        if ok:
            qualified += 1
            sys.stdout.write(f"QUALIFY\t{rec['id']}\t-\n")
        else:
            pid = rec.get("id") if isinstance(rec, dict) else "-"
            sys.stdout.write(f"SKIP\t{pid or '-'}\t{reason}\n")

sys.stderr.write(f"evaluated={total} qualified={qualified}\n")
PY
}

GATE_OUTPUT="$(evaluate_gate 2>&1)"
# Separate the per-row tab-delimited rows from the trailing stderr counter.
ROWS="$(printf '%s\n' "${GATE_OUTPUT}" | grep -E '^(QUALIFY|SKIP|BAD_ROW)\t' || true)"

EVALUATED=0
QUALIFIED=0
APPLIED=0
FAILED=0

while IFS= read -r row; do
    [ -z "${row}" ] && continue
    EVALUATED=$((EVALUATED + 1))
    status="${row%%	*}"
    rest="${row#*	}"
    pid="${rest%%	*}"
    reason="${rest#*	}"
    case "${status}" in
        SKIP|BAD_ROW)
            log "skip ${pid}: ${reason}"
            ;;
        QUALIFY)
            QUALIFIED=$((QUALIFIED + 1))
            log "qualify ${pid}: routing to apply-proposal.py"

            # Run apply-proposal.py with source=auto-apply. The library
            # creates branch autoheal/auto/{pid}, applies the diff, runs
            # tests/test-modules.sh + tests/test-no-personal-data.sh, and
            # — on pass — commits with `#auto: apply autoheal proposal {pid}`
            # and appends to applied/{today}.jsonl. We capture stdout +
            # stderr into the per-day log so a tester sees both the diff
            # and the failure reason in one place.
            apply_out="$(python3 "${APPLY_LIB}" "${pid}" auto-apply 2>&1)"
            apply_rc=$?
            printf '%s\n' "${apply_out}" >>"${LOG_FILE}"

            if [ "${apply_rc}" -eq 0 ]; then
                APPLIED=$((APPLIED + 1))
                log "applied ${pid}: branch + commit created (review the PR)"
            else
                FAILED=$((FAILED + 1))
                # The library wrote NO applied record on failure (its
                # contract is "audit on success"). We add a failure-tagged
                # record so the audit log captures the attempt either way.
                python3 - "${APPLIED_FILE}" "${pid}" "${apply_out}" <<'PY'
import datetime
import json
import os
import sys

path = sys.argv[1]
pid = sys.argv[2]
err = sys.argv[3]

# Truncate the err blob so a 4MB test-output dump doesn't bloat the audit.
err_short = err[-2000:] if len(err) > 2000 else err

rec = {
    "id": f"app_{pid}_failed_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "proposal_id": pid,
    "method": "auto_apply",
    "branch": None,
    "commit_sha": None,
    "tests_passed": False,
    "rolled_back": True,
    "error": err_short,
}

parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
PY
                log "failed ${pid}: apply-proposal.py exit=${apply_rc} (see log for details)"
            fi
            ;;
        *)
            log "unknown gate row: ${row}"
            ;;
    esac
done <<< "${ROWS}"

# ---------------------------------------------------------------------
# Summary line. The daily wrapper aggregates stderr into its log so this
# is visible without parsing the per-day file.
# ---------------------------------------------------------------------

printf 'autoheal-auto-apply: evaluated=%d qualified=%d applied=%d failed=%d (today=%s)\n' \
    "${EVALUATED}" "${QUALIFIED}" "${APPLIED}" "${FAILED}" "${TODAY}" >&2

exit 0
