#!/usr/bin/env bash
# Test suite for the /autoheal-apply slash command spec.
#
# The command itself is documented in modules/autoheal/commands/autoheal-apply.md
# and is implemented in two halves:
#
#   - LIST mode: the agent runs `lib/ledger.py ready`, which prints the ledger
#     rows waiting for a decision (ready, plus snoozed rows whose snooze
#     ended), whatever their age. This test runs that command.
#
#   - APPLY mode: routes through lib/apply-proposal.py — the gate test
#     (test-auto-apply-gate.sh) covers that path end-to-end. This test
#     only spot-checks that the CLI exposes the documented usage.
#
# Run: bash modules/autoheal/tests/test-autoheal-apply-command.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"
COMMAND_DOC="${MODULE_ROOT}/commands/autoheal-apply.md"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1"
    local expected="$2"
    local label="$3"
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected: ${expected}"
        echo "  actual:   ${actual}"
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            PASS=$((PASS + 1))
            ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
    esac
}

# ---------------------------------------------------------------------
# Test 1: the command doc names the expected subcommands. A regression
# in the command surface would silently break the agent that follows the
# spec, so we pin the wording.
# ---------------------------------------------------------------------

[ -f "${COMMAND_DOC}" ] && PASS=$((PASS + 1)) || {
    FAIL=$((FAIL + 1))
    echo "FAIL: command doc exists at ${COMMAND_DOC}"
}

doc_content=$(cat "${COMMAND_DOC}" 2>/dev/null || echo "")
assert_contains "${doc_content}" "/autoheal-apply" \
    "doc: top-level command name present"
assert_contains "${doc_content}" "/autoheal-apply list" \
    "doc: list subcommand documented"
assert_contains "${doc_content}" "/autoheal-apply <proposal-id>" \
    "doc: apply-by-id subcommand documented"
assert_contains "${doc_content}" "lib/apply-proposal.py" \
    "doc: routes through the shared apply library"
assert_contains "${doc_content}" "autoheal/{proposal-id}" \
    "doc: names the manual-apply branch shape"
assert_contains "${doc_content}" "tests/test-modules.sh" \
    "doc: test-gate references test-modules.sh"
assert_contains "${doc_content}" "tests/test-no-personal-data.sh" \
    "doc: test-gate references test-no-personal-data.sh"

# ---------------------------------------------------------------------
# Test 2: the CLI exposes the documented usage string and rejects bad
# source labels. We do not run the apply itself here (the gate test
# covers that); we only confirm the CLI surface matches the doc.
# ---------------------------------------------------------------------

usage=$(python3 "${APPLY_LIB}" 2>&1 || true)
assert_contains "${usage}" "apply-proposal.py" "cli: usage names the script"
assert_contains "${usage}" "permission-fix|auto-apply" \
    "cli: usage names the two source labels"

bad_source=$(python3 "${APPLY_LIB}" prop_x notarealsource 2>&1 || true)
assert_contains "${bad_source}" "source must be" \
    "cli: rejects unknown source labels"

# ---------------------------------------------------------------------
# Test 3: LIST mode reads the whole ledger: a 30-day-old ready row appears;
# applied, rejected, legacy and still-snoozed rows do not.
# ---------------------------------------------------------------------

LEDGER_DIR="$(mktemp -d -t autoheal_list_ledger.XXXXXX)"
trap 'rm -rf "${LEDGER_DIR}"' EXIT
LEDGER_FILE="${LEDGER_DIR}/proposals.jsonl"

python3 - "${LEDGER_FILE}" <<'PY'
import datetime as dt, json, sys
def ago(n): return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).isoformat()
base = {"kind": "rule_insert", "confidence": 9, "breadth_score": 1, "occurrence_count": 2}
rows = [
    {**base, "id": "prop_new", "state": "ready", "title": "add A", "generated_at": ago(0)},
    {**base, "id": "prop_old", "state": "ready", "title": "add B", "generated_at": ago(30)},
    {**base, "id": "prop_snoozed", "state": "snoozed", "snoozed_until": "2099-01-01T00:00:00Z", "generated_at": ago(1)},
    {**base, "id": "prop_wake", "state": "snoozed", "snoozed_until": "2000-01-01T00:00:00Z", "generated_at": ago(40)},
    {**base, "id": "prop_applied", "state": "applied", "generated_at": ago(2)},
    {**base, "id": "prop_rejected", "state": "rejected", "generated_at": ago(2)},
    {**base, "id": "prop_legacy", "state": "legacy", "generated_at": ago(60)},
    {**base, "id": "prop_dropped", "state": "dropped", "generated_at": ago(2)},
]
open(sys.argv[1], "w").write("".join(json.dumps(r) + "\n" for r in rows))
PY

list_output="$(CCGM_AUTOHEAL_LEDGER="${LEDGER_FILE}" python3 "${MODULE_ROOT}/lib/ledger.py" ready | python3 -c '
import json, sys
print(" ".join(sorted(json.loads(l)["id"] for l in sys.stdin)))')"
assert_eq "${list_output}" "prop_new prop_old prop_wake" \
    "list: ready rows of any age and expired snoozes; nothing applied, rejected, legacy, dropped or still snoozed"

echo ""
echo "test-autoheal-apply-command.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
