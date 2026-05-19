#!/usr/bin/env bash
# Test the privilege-escalation filter in autoheal-analyze.sh (Epic 6).
#
# The gate rejects any proposal with `breadth_score >= 8 AND
# confidence < 9` (plan.md §1.2 insight #7, §5 Epic 6 step 7).
# Calibration mode relaxes the breadth threshold to 10 (so 9 is still
# accepted) — see analyzer-prompt.md.
#
# Strategy: build two fixture API responses, one with a violating
# proposal and one with a compliant one. Run the analyzer with each as
# the fixture and assert the proposals/{today}.jsonl + rejection log
# reflect the gate decision.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"

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
            echo "  actual (first 400): ${haystack:0:400}"
            ;;
    esac
}

write_events() {
    local file="$1"
    mkdir -p "$(dirname "${file}")"
    python3 - "${file}" <<'PY'
import datetime as dt
import json
import sys

path = sys.argv[1]
now = dt.datetime.now(dt.timezone.utc).isoformat()
with open(path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "kind": "permission_request",
        "timestamp": now,
        "session_id": "s-1",
        "tool_name": "Bash",
        "redacted_command": "git diff --staged",
        "cwd": "/tmp/repo",
    }) + "\n")
PY
}

make_fixture() {
    # Generate a fixture API response whose content[0].text is a
    # JSON-encoded proposals envelope. Args: out_path confidence breadth.
    local out="$1"
    local confidence="$2"
    local breadth="$3"
    local id_label="$4"
    python3 - "${out}" "${confidence}" "${breadth}" "${id_label}" <<'PY'
import json
import sys

out, confidence, breadth, label = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]

proposal = {
    "id": f"prop_{label}",
    "kind": "settings_allow_add",
    "title": f"Synthetic proposal {label}",
    "rationale": f"Test fixture for the privilege gate; confidence={confidence}, breadth_score={breadth}.",
    "confidence": confidence,
    "breadth_score": breadth,
    "occurrence_count": 2,
    "session_ids": ["s-aaa", "s-bbb"],
    "proposed_diff_target": "modules/settings/settings.partial.json",
    "proposed_diff": f"+ Bash(synthetic-{label})",
    "fingerprint": "0" * 64,
    "originating_clone": "ccgm-w1-c0",
    "generated_at": "2026-05-18T08:00:00+00:00",
}

text = json.dumps({"proposals": [proposal]})

response = {
    "id": f"msg_{label}",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "usage": {"input_tokens": 100, "output_tokens": 100},
    "content": [{"type": "text", "text": text}],
}

with open(out, "w", encoding="utf-8") as fh:
    json.dump(response, fh)
PY
}

run_analyzer() {
    local home="$1"
    local fixture="$2"
    local today="$3"
    local extra_env_calibration="${4:-}"

    # We want the analyzer to NOT be in calibration mode for the main
    # tests so the gate fires at breadth>=8. Bump last-analyzed's mtime
    # far back in time (well beyond the 7-day calibration window).
    if [ "${extra_env_calibration}" = "post-calibration" ]; then
        mkdir -p "${home}/autoheal"
        echo "2020-01-01" > "${home}/autoheal/last-analyzed"
        # mtime 30 days ago
        if command -v touch >/dev/null 2>&1; then
            # macOS BSD touch accepts -t YYYYMMDDhhmm
            touch -t 202001010000 "${home}/autoheal/last-analyzed" 2>/dev/null || true
        fi
    fi

    env \
        HOME="${home}" \
        CCGM_AUTOHEAL_DIR="${home}/autoheal" \
        CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${fixture}" \
        CCGM_AUTOHEAL_TODAY="${today}" \
        CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-c0" \
        ANTHROPIC_API_KEY="x" \
        bash "${ANALYZER}" \
            >"${home}/run.out" 2>"${home}/run.err"
    return $?
}

YESTERDAY=$(python3 -c "import datetime as dt; print((dt.date.today()-dt.timedelta(days=1)).isoformat())")
TODAY=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")

# -----------------------------------------------------------------
# Test A — violating proposal (breadth=9, confidence=8) rejected.
# -----------------------------------------------------------------

A_HOME=$(mktemp -d -t pe_test_a.XXXXXX)
trap 'rm -rf "${A_HOME}"' EXIT
write_events "${A_HOME}/autoheal/events/${YESTERDAY}.jsonl"
A_FIX="${A_HOME}/violating.json"
make_fixture "${A_FIX}" 8 9 "violating"

run_analyzer "${A_HOME}" "${A_FIX}" "${TODAY}" "post-calibration"
RC=$?
assert_eq "${RC}" "0" "violating: analyzer exits 0"

A_PROPOSALS="${A_HOME}/autoheal/proposals/${TODAY}.jsonl"
if [ -f "${A_PROPOSALS}" ]; then
    A_SIZE=$(wc -c < "${A_PROPOSALS}" | tr -d ' ')
    assert_eq "${A_SIZE}" "0" "violating: no accepted proposals"
else
    PASS=$((PASS + 1))
fi

A_REJECTED="${A_HOME}/.claude/logs/autoheal-rejected-${TODAY}.log"
if [ -f "${A_REJECTED}" ]; then
    PASS=$((PASS + 1))
    A_BODY=$(cat "${A_REJECTED}")
    assert_contains "${A_BODY}" "privilege_gate" "violating: rejection reason logged"
    assert_contains "${A_BODY}" "prop_violating" "violating: proposal id in log"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: violating: rejection log not created at ${A_REJECTED}"
fi

# -----------------------------------------------------------------
# Test B — compliant proposal (breadth=2, confidence=9) accepted.
# -----------------------------------------------------------------

B_HOME=$(mktemp -d -t pe_test_b.XXXXXX)
write_events "${B_HOME}/autoheal/events/${YESTERDAY}.jsonl"
B_FIX="${B_HOME}/compliant.json"
make_fixture "${B_FIX}" 9 2 "compliant"

run_analyzer "${B_HOME}" "${B_FIX}" "${TODAY}" "post-calibration"
RC=$?
assert_eq "${RC}" "0" "compliant: analyzer exits 0"

B_PROPOSALS="${B_HOME}/autoheal/proposals/${TODAY}.jsonl"
if [ -f "${B_PROPOSALS}" ]; then
    LINES=$(wc -l < "${B_PROPOSALS}" | tr -d ' ')
    assert_eq "${LINES}" "1" "compliant: one proposal accepted"
    ID=$(python3 -c "import json; print(json.loads(open('${B_PROPOSALS}').readline())['id'])")
    assert_eq "${ID}" "prop_compliant" "compliant: proposal id preserved"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: compliant: proposals file not created"
fi

# Compliant case should NOT generate a rejection log entry (or if the
# file exists from earlier in the day, it should not contain this id).
B_REJECTED="${B_HOME}/.claude/logs/autoheal-rejected-${TODAY}.log"
if [ -f "${B_REJECTED}" ]; then
    B_BODY=$(cat "${B_REJECTED}")
    case "${B_BODY}" in
        *prop_compliant*)
            FAIL=$((FAIL + 1))
            echo "FAIL: compliant: should not be in rejection log"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
else
    PASS=$((PASS + 1))
fi

# -----------------------------------------------------------------
# Test C — edge case (breadth=8, confidence=9) accepted in steady.
# -----------------------------------------------------------------

C_HOME=$(mktemp -d -t pe_test_c.XXXXXX)
write_events "${C_HOME}/autoheal/events/${YESTERDAY}.jsonl"
C_FIX="${C_HOME}/edge.json"
make_fixture "${C_FIX}" 9 8 "edge"

run_analyzer "${C_HOME}" "${C_FIX}" "${TODAY}" "post-calibration"
RC=$?
assert_eq "${RC}" "0" "edge: analyzer exits 0"

C_PROPOSALS="${C_HOME}/autoheal/proposals/${TODAY}.jsonl"
if [ -f "${C_PROPOSALS}" ]; then
    LINES=$(wc -l < "${C_PROPOSALS}" | tr -d ' ')
    assert_eq "${LINES}" "1" "edge: breadth=8 confidence=9 accepted"
fi

# -----------------------------------------------------------------
# Test D — edge case (breadth=7, confidence=4) accepted: below
# breadth threshold so gate does not apply regardless of confidence.
# -----------------------------------------------------------------

D_HOME=$(mktemp -d -t pe_test_d.XXXXXX)
write_events "${D_HOME}/autoheal/events/${YESTERDAY}.jsonl"
D_FIX="${D_HOME}/low-breadth.json"
make_fixture "${D_FIX}" 4 7 "lowbreadth"

run_analyzer "${D_HOME}" "${D_FIX}" "${TODAY}" "post-calibration"
RC=$?
assert_eq "${RC}" "0" "low-breadth: analyzer exits 0"

D_PROPOSALS="${D_HOME}/autoheal/proposals/${TODAY}.jsonl"
if [ -f "${D_PROPOSALS}" ]; then
    LINES=$(wc -l < "${D_PROPOSALS}" | tr -d ' ')
    assert_eq "${LINES}" "1" "low-breadth: accepted (gate does not fire)"
fi

# Cleanup of trapped first dir is in EXIT; manual cleanup of the rest.
for d in "${B_HOME}" "${C_HOME}" "${D_HOME}"; do
    rm -rf "${d}"
done

# -----------------------------------------------------------------
# Summary.
# -----------------------------------------------------------------

echo ""
echo "test-privilege-escalation-filter.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
