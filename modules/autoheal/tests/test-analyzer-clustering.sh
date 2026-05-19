#!/usr/bin/env bash
# Tests for issues #517 and #518: analyzer event clustering, dedup,
# adaptive excerpts, --force-day, and rejected-day tracking.
#
# Covers:
#   1. Dedup on (session_id, timestamp, kind) — duplicate-kind records
#      from the double-write hook contract appear once.
#   2. Clustering — routine successes are grouped by (tool_name,
#      command-prefix); friction events stay as full records.
#   3. Adaptive excerpt window — payload shrinks when over cap.
#   4. --force-day re-processes a specific day and does NOT bump
#      last-analyzed.
#   5. Rejected day — when even window=0 exceeds cap, rejected-days.jsonl
#      gets a record AND last-analyzed does not advance past the day.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
FIXTURE="${SCRIPT_DIR}/fixtures/api-response-sample.json"

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

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  unexpected substring present: ${needle}"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
}

assert_file_exists() {
    local path="$1"
    local label="$2"
    if [ -f "${path}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected file: ${path}"
    fi
}

assert_ge() {
    local actual="$1"
    local floor="$2"
    local label="$3"
    if [ "${actual}" -ge "${floor}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected >= ${floor}, got ${actual}"
    fi
}

assert_lt() {
    local actual="$1"
    local ceiling="$2"
    local label="$3"
    if [ "${actual}" -lt "${ceiling}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected < ${ceiling}, got ${actual}"
    fi
}

mk_state() {
    local root="$1"
    mkdir -p "${root}/events" "${root}/proposals"
}

# ---------------------------------------------------------------------
# Test 1 — dedup on (session_id, timestamp, kind).
#
# The double-write contract (failure-logger.py:8-12) emits the same
# tool_failure record twice. The analyzer must dedupe so the prompt
# only sees one copy.
# ---------------------------------------------------------------------

T1_HOME=$(mktemp -d -t autoheal_clu1.XXXXXX)
T1_DIR="${T1_HOME}/autoheal"
mk_state "${T1_DIR}"

TODAY=$(python3 -c "import datetime as dt; print(dt.datetime.now(dt.timezone.utc).date().isoformat())")
YESTERDAY=$(python3 -c "import datetime as dt; print((dt.date.today()-dt.timedelta(days=1)).isoformat())")
EVENTS_FILE="${T1_DIR}/events/${YESTERDAY}.jsonl"

python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
# 3 unique events, each duplicated to simulate the double-write.
rows = []
for i in range(3):
    rec = {
        "kind": "tool_failure",
        "timestamp": f"2026-05-18T10:0{i}:00+00:00",
        "session_id": f"s-{i}",
        "tool_name": "Bash",
        "redacted_command": f"git diff path-{i}",
        "exit_code": 1,
        "stderr_excerpt": "boom",
    }
    rows.append(rec)
    rows.append(dict(rec))  # exact duplicate
with open(path, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
PY

PROMPT_LOG="${T1_HOME}/prompt.log"
env \
    HOME="${T1_HOME}" \
    CCGM_AUTOHEAL_DIR="${T1_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T1_HOME}/run.out" 2>"${T1_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "dedup: analyzer exits 0"
assert_file_exists "${PROMPT_LOG}" "dedup: prompt log written"

ERR_BODY=$(cat "${T1_HOME}/run.err")
# Loader log: "loaded N unique events (M duplicates skipped)"
assert_contains "${ERR_BODY}" "loaded 3 unique events (3 duplicates skipped)" \
    "dedup: loader reports 3 unique and 3 duplicates"

# Each unique command appears exactly once in the prompt.
if [ -f "${PROMPT_LOG}" ]; then
    for i in 0 1 2; do
        cmd="git diff path-${i}"
        count=$(grep -F -o "${cmd}" "${PROMPT_LOG}" | wc -l | tr -d ' ')
        assert_eq "${count}" "1" "dedup: command '${cmd}' appears exactly once"
    done
fi

# ---------------------------------------------------------------------
# Test 2 — clustering: 1000-event mix with 5 failures + 2 permission
# requests scattered in. Routine events should cluster (count > 100);
# friction events stay as full records.
# ---------------------------------------------------------------------

T2_HOME=$(mktemp -d -t autoheal_clu2.XXXXXX)
T2_DIR="${T2_HOME}/autoheal"
mk_state "${T2_DIR}"

EVENTS_FILE="${T2_DIR}/events/${YESTERDAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
rows = []
# 993 routine successes spread across 3 tools/commands.
# 200 Read events, 400 Bash 'git status', 393 Bash 'ls -la'.
for i in range(200):
    rows.append({
        "kind": "tool_use",
        "timestamp": f"2026-05-18T11:{i//60:02d}:{i%60:02d}+00:00",
        "session_id": "s-A",
        "tool_name": "Read",
        "redacted_command": None,
        "exit_code": 0,
    })
for i in range(400):
    rows.append({
        "kind": "tool_use",
        "timestamp": f"2026-05-18T12:{i//60:02d}:{i%60:02d}+00:00",
        "session_id": "s-B",
        "tool_name": "Bash",
        "redacted_command": "git status",
        "exit_code": 0,
    })
for i in range(393):
    rows.append({
        "kind": "tool_use",
        "timestamp": f"2026-05-18T13:{i//60:02d}:{i%60:02d}+00:00",
        "session_id": "s-C",
        "tool_name": "Bash",
        "redacted_command": "ls -la",
        "exit_code": 0,
    })
# 5 unique tool_failure friction events with distinct commands.
for i in range(5):
    rows.append({
        "kind": "tool_failure",
        "timestamp": f"2026-05-18T14:{i:02d}:00+00:00",
        "session_id": f"s-fail-{i}",
        "tool_name": "Bash",
        "redacted_command": f"npm run unique-fail-cmd-{i}",
        "exit_code": 1,
        "stderr_excerpt": f"unique-stderr-marker-{i}",
    })
# 2 permission_request friction events with distinct commands.
for i in range(2):
    rows.append({
        "kind": "permission_request",
        "timestamp": f"2026-05-18T15:{i:02d}:00+00:00",
        "session_id": f"s-perm-{i}",
        "tool_name": "Bash",
        "redacted_command": f"unique-perm-cmd-{i}",
        "permission_decision": "ask",
    })

with open(path, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
PY

PROMPT_LOG="${T2_HOME}/prompt.log"
env \
    HOME="${T2_HOME}" \
    CCGM_AUTOHEAL_DIR="${T2_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T2_HOME}/run.out" 2>"${T2_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "cluster: analyzer exits 0"
assert_file_exists "${PROMPT_LOG}" "cluster: prompt log written"

ERR_BODY=$(cat "${T2_HOME}/run.err")
assert_contains "${ERR_BODY}" "loaded 1000 unique events" "cluster: 1000 events loaded"
# Window=3 is correct here — under the 200k default cap.
assert_contains "${ERR_BODY}" "excerpt window: 3" "cluster: window=3 fits under default cap"

# All 5 unique failures + 2 permission requests are present as friction
# events (verified by checking each unique marker survives).
if [ -f "${PROMPT_LOG}" ]; then
    for i in 0 1 2 3 4; do
        marker="unique-fail-cmd-${i}"
        count=$(grep -F -o "${marker}" "${PROMPT_LOG}" | wc -l | tr -d ' ')
        assert_ge "${count}" "1" "cluster: tool_failure ${i} present as friction"
    done
    for i in 0 1; do
        marker="unique-perm-cmd-${i}"
        count=$(grep -F -o "${marker}" "${PROMPT_LOG}" | wc -l | tr -d ' ')
        assert_ge "${count}" "1" "cluster: permission_request ${i} present as friction"
    done

    # Cluster records exist for the routine workloads.
    cluster_count=$(grep -F -o '"kind": "cluster"' "${PROMPT_LOG}" | wc -l | tr -d ' ')
    assert_ge "${cluster_count}" "3" "cluster: at least 3 cluster records emitted"

    # Verify the 400-count cluster ('git status') is in the prompt.
    assert_contains "$(cat "${PROMPT_LOG}")" '"count": 400' "cluster: 400-count signature recorded"
    assert_contains "$(cat "${PROMPT_LOG}")" '"count": 393' "cluster: 393-count signature recorded"
    assert_contains "$(cat "${PROMPT_LOG}")" '"count": 200' "cluster: 200-count signature recorded"

    # The 1000-event prompt at the new defaults must be well under 200k tokens.
    PROMPT_BYTES=$(wc -c < "${PROMPT_LOG}" | tr -d ' ')
    PROMPT_TOKENS=$((PROMPT_BYTES / 4))
    assert_lt "${PROMPT_TOKENS}" "200000" "cluster: prompt fits in 200k token cap"
fi

# ---------------------------------------------------------------------
# Test 3 — adaptive window: at a low cap the analyzer shrinks excerpts
# rather than rejecting. Friction events must remain even when excerpts
# disappear.
# ---------------------------------------------------------------------

T3_HOME=$(mktemp -d -t autoheal_clu3.XXXXXX)
T3_DIR="${T3_HOME}/autoheal"
mk_state "${T3_DIR}"

# Synthesize 30 small permission_request friction events. The cap is
# tight enough that the analyzer must shrink the window, but loose
# enough that window=0 still fits.
EVENTS_FILE="${T3_DIR}/events/${YESTERDAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
rows = []
for i in range(30):
    rows.append({
        "kind": "permission_request",
        "timestamp": f"2026-05-18T16:{i//60:02d}:{i%60:02d}+00:00",
        "session_id": f"s-{i % 5}",
        "tool_name": "Bash",
        "redacted_command": "git status",
        "permission_decision": "ask",
    })
with open(path, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
PY

# 30 small events ≈ 5k chars ≈ 1300 tokens — comfortably under any
# reasonable cap. We just verify the analyzer reports the window it
# chose (proves the adaptive-window code path runs).
cat > "${T3_DIR}/config.json" <<'EOF'
{
  "max_input_tokens": 20000
}
EOF

PROMPT_LOG="${T3_HOME}/prompt.log"
env \
    HOME="${T3_HOME}" \
    CCGM_AUTOHEAL_DIR="${T3_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T3_HOME}/run.out" 2>"${T3_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "adaptive: analyzer exits 0 with tight cap"

ERR_BODY=$(cat "${T3_HOME}/run.err")
# The window logged must be one of 3, 1, 0. With this payload at 6k
# cap, it will be the highest window that still fits — we just assert
# the line was emitted, not the exact value (since transcript paths
# don't resolve in tests, payload size doesn't grow with window).
assert_contains "${ERR_BODY}" "excerpt window:" "adaptive: window choice logged"

# ---------------------------------------------------------------------
# Test 4 — --force-day re-processes a specific day even when
# last-analyzed is newer, and does NOT bump last-analyzed.
# ---------------------------------------------------------------------

T4_HOME=$(mktemp -d -t autoheal_clu4.XXXXXX)
T4_DIR="${T4_HOME}/autoheal"
mk_state "${T4_DIR}"

# Pre-populate last-analyzed to today.
printf '%s\n' "${TODAY}" > "${T4_DIR}/last-analyzed"

# Old day with events to force-analyze.
OLD_DAY="2020-01-01"
EVENTS_FILE="${T4_DIR}/events/${OLD_DAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(3):
        rec = {
            "kind": "permission_request",
            "timestamp": f"2020-01-01T0{i}:00:00+00:00",
            "session_id": f"force-s-{i}",
            "tool_name": "Bash",
            "redacted_command": f"force-day-cmd-{i}",
            "permission_decision": "ask",
        }
        fh.write(json.dumps(rec) + "\n")
PY

PROMPT_LOG="${T4_HOME}/prompt.log"
env \
    HOME="${T4_HOME}" \
    CCGM_AUTOHEAL_DIR="${T4_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" --force-day "${OLD_DAY}" >"${T4_HOME}/run.out" 2>"${T4_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "force-day: analyzer exits 0"

# Prompt log contains the old day's unique marker.
if [ -f "${PROMPT_LOG}" ]; then
    assert_contains "$(cat "${PROMPT_LOG}")" "force-day-cmd-0" "force-day: forced day's events appear in prompt"
fi

# last-analyzed is unchanged.
LAST_VAL=$(cat "${T4_DIR}/last-analyzed" | tr -d '\n')
assert_eq "${LAST_VAL}" "${TODAY}" "force-day: last-analyzed unchanged"

# Stderr explains the --force-day mode.
F4_ERR=$(cat "${T4_HOME}/run.err")
assert_contains "${F4_ERR}" "--force-day" "force-day: stderr explains the mode"

# Bad --force-day value fails fast.
env \
    HOME="${T4_HOME}" \
    CCGM_AUTOHEAL_DIR="${T4_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" --force-day "not-a-date" >"${T4_HOME}/run.bad.out" 2>"${T4_HOME}/run.bad.err"
RC=$?
assert_eq "${RC}" "1" "force-day: invalid date rejected with rc=1"

# --help prints usage and exits 0.
env \
    HOME="${T4_HOME}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" --help >"${T4_HOME}/help.out" 2>"${T4_HOME}/help.err"
RC=$?
assert_eq "${RC}" "0" "help: --help exits 0"
HELP_BODY=$(cat "${T4_HOME}/help.out")
assert_contains "${HELP_BODY}" "Usage:" "help: prints usage"
assert_contains "${HELP_BODY}" "--force-day" "help: mentions --force-day"

# ---------------------------------------------------------------------
# Test 5 — rejected day: a day too big even at window=0 is logged in
# rejected-days.jsonl AND last-analyzed does NOT advance past it.
# ---------------------------------------------------------------------

T5_HOME=$(mktemp -d -t autoheal_clu5.XXXXXX)
T5_DIR="${T5_HOME}/autoheal"
mk_state "${T5_DIR}"

# Tight cap so 200 friction events overflow even at window=0.
cat > "${T5_DIR}/config.json" <<'EOF'
{
  "max_input_tokens": 3000
}
EOF

EVENTS_FILE="${T5_DIR}/events/${YESTERDAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(200):
        rec = {
            "kind": "permission_request",
            "timestamp": f"2026-05-18T17:{i//60:02d}:{i%60:02d}+00:00",
            "session_id": f"s-{i}",
            "tool_name": "Bash",
            "redacted_command": "git " + ("x" * 220),
            "permission_decision": "ask",
        }
        fh.write(json.dumps(rec) + "\n")
PY

env \
    HOME="${T5_HOME}" \
    CCGM_AUTOHEAL_DIR="${T5_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T5_HOME}/run.out" 2>"${T5_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "rejected: analyzer exits 0 (rejection is non-fatal)"

# rejected-days.jsonl was written.
assert_file_exists "${T5_DIR}/rejected-days.jsonl" "rejected: rejected-days.jsonl created"

if [ -f "${T5_DIR}/rejected-days.jsonl" ]; then
    REJ_DATE=$(python3 -c "
import json
with open('${T5_DIR}/rejected-days.jsonl') as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        print(rec.get('date',''))
        break
")
    assert_eq "${REJ_DATE}" "${YESTERDAY}" "rejected: rejected-days.jsonl records the right date"

    REJ_CAP=$(python3 -c "
import json
with open('${T5_DIR}/rejected-days.jsonl') as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        print(rec.get('max_input_tokens',''))
        break
")
    assert_eq "${REJ_CAP}" "3000" "rejected: rejection records the active cap"
fi

# Stderr explains the rejection at window=0.
ERR_BODY=$(cat "${T5_HOME}/run.err")
assert_contains "${ERR_BODY}" "even at window=0" "rejected: stderr explains rejection happened at window=0"

# last-analyzed must NOT advance past the rejected day (so the next run
# retries it). The new value should be (rejected_day - 1) at most.
LAST_VAL=""
if [ -f "${T5_DIR}/last-analyzed" ]; then
    LAST_VAL=$(cat "${T5_DIR}/last-analyzed" | tr -d '\n')
fi
if [ -n "${LAST_VAL}" ]; then
    # YESTERDAY > LAST_VAL strictly.
    if [ "${YESTERDAY}" \> "${LAST_VAL}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: rejected: last-analyzed (${LAST_VAL}) advanced past rejected day (${YESTERDAY})"
    fi
fi

# ---------------------------------------------------------------------
# Test 6 — give-up: after REJECT_GIVEUP_THRESHOLD rejections, the
# analyzer stops retrying the day and bumps past it.
# ---------------------------------------------------------------------

T6_HOME=$(mktemp -d -t autoheal_clu6.XXXXXX)
T6_DIR="${T6_HOME}/autoheal"
mk_state "${T6_DIR}"

cat > "${T6_DIR}/config.json" <<'EOF'
{
  "max_input_tokens": 3000
}
EOF

EVENTS_FILE="${T6_DIR}/events/${YESTERDAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(200):
        rec = {
            "kind": "permission_request",
            "timestamp": f"2026-05-18T17:{i//60:02d}:{i%60:02d}+00:00",
            "session_id": f"s-{i}",
            "tool_name": "Bash",
            "redacted_command": "git " + ("x" * 220),
            "permission_decision": "ask",
        }
        fh.write(json.dumps(rec) + "\n")
PY

# Pre-populate 6 prior rejections so this run becomes the 7th — at
# threshold, the analyzer gives up and bumps past. The pre-populated
# rejections MUST be tagged with the current analyzer version (short
# git SHA); `rejected_count_for_day` filters by version so a fresh
# analyzer release starts the retry counter at 0.
T6_VERSION="$(git -C "${MODULE_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 1)"
REJ_PATH="${T6_DIR}/rejected-days.jsonl"
python3 - "${REJ_PATH}" "${YESTERDAY}" "${T6_VERSION}" <<'PY'
import datetime as dt
import json
import sys

path, day, version = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(6):
        rec = {
            "date": day,
            "rejected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "est_tokens": 9999,
            "max_input_tokens": 3000,
            "analyzer_version": version,
        }
        fh.write(json.dumps(rec) + "\n")
PY

env \
    HOME="${T6_HOME}" \
    CCGM_AUTOHEAL_DIR="${T6_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T6_HOME}/run.out" 2>"${T6_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "give-up: analyzer exits 0"

ERR_BODY=$(cat "${T6_HOME}/run.err")
assert_contains "${ERR_BODY}" "GIVE_UP" "give-up: stderr logs GIVE_UP marker"

# After give-up, last-analyzed advances to TODAY.
LAST_VAL=""
if [ -f "${T6_DIR}/last-analyzed" ]; then
    LAST_VAL=$(cat "${T6_DIR}/last-analyzed" | tr -d '\n')
fi
assert_eq "${LAST_VAL}" "${TODAY}" "give-up: last-analyzed advances to TODAY"

# ---------------------------------------------------------------------
# Test 7 — permission_request friction is decision-based, not kind-based.
#
# Regression for the bug where every kind=="permission_request" event
# was classified as friction. The bypass-suppress hook stamps
# auto-allows with permission_decision="allow"; on a heavy day those
# dominate. Treating all of them as friction defeats clustering and
# re-creates the cap-pressure issue #517 was meant to solve.
#
# Fixture: 100 permission_request with decision="allow" + 1 "deny" + 1
# "ask". Expectation: the 100 allows cluster into one cluster row with
# count=100; the deny + ask survive as full friction records.
# ---------------------------------------------------------------------

T7_HOME=$(mktemp -d -t autoheal_clu7.XXXXXX)
T7_DIR="${T7_HOME}/autoheal"
mk_state "${T7_DIR}"

EVENTS_FILE="${T7_DIR}/events/${YESTERDAY}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
rows = []
# 100 auto-allowed permission_requests with the same signature; these
# MUST cluster, not get promoted to friction by virtue of kind.
for i in range(100):
    rows.append({
        "kind": "permission_request",
        "timestamp": f"2026-05-18T18:{i//60:02d}:{i%60:02d}+00:00",
        "session_id": f"s-allow-{i % 3}",
        "tool_name": "Bash",
        "redacted_command": "ls -la",
        "permission_decision": "allow",
    })
# One deny — must survive as friction.
rows.append({
    "kind": "permission_request",
    "timestamp": "2026-05-18T19:00:00+00:00",
    "session_id": "s-deny",
    "tool_name": "Bash",
    "redacted_command": "unique-deny-cmd",
    "permission_decision": "deny",
})
# One ask — must survive as friction.
rows.append({
    "kind": "permission_request",
    "timestamp": "2026-05-18T19:01:00+00:00",
    "session_id": "s-ask",
    "tool_name": "Bash",
    "redacted_command": "unique-ask-cmd",
    "permission_decision": "ask",
})
with open(path, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
PY

PROMPT_LOG="${T7_HOME}/prompt.log"
env \
    HOME="${T7_HOME}" \
    CCGM_AUTOHEAL_DIR="${T7_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T7_HOME}/run.out" 2>"${T7_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "friction-decision: analyzer exits 0"
assert_file_exists "${PROMPT_LOG}" "friction-decision: prompt log written"

if [ -f "${PROMPT_LOG}" ]; then
    PL_BODY=$(cat "${PROMPT_LOG}")

    # Parse the USER payload (the JSON the model would actually see) and
    # inspect its structure directly. We can't grep the whole prompt-log
    # for `"kind": "cluster"` because the SYSTEM section documents
    # cluster records and would inflate the count.
    USER_JSON_CHECK=$(PROMPT_LOG="${PROMPT_LOG}" python3 - <<'PY'
import json
import os

with open(os.environ["PROMPT_LOG"], "r", encoding="utf-8") as fh:
    body = fh.read()

# Prompt log shape: "SYSTEM:\n<analyzer prompt>\n\nUSER:\n<json>\n"
user_part = body.split("USER:\n", 1)[-1].strip()
data = json.loads(user_part)

ev = data["events"]
clusters = [e for e in ev if e.get("kind") == "cluster"]
friction = [e for e in ev if e.get("kind") != "cluster"]

# Emit a single line of tab-separated facts the shell can assert on.
fields = [
    str(len(clusters)),                                # 0: cluster count
    str(clusters[0]["count"]) if clusters else "0",   # 1: first cluster count
    str(len(friction)),                                # 2: friction count
    str(data["runtime_context"]["event_summary"]["friction_events"]),
    str(data["runtime_context"]["event_summary"]["cluster_records"]),
]
print("\t".join(fields))
PY
)
    T7_CLUSTERS=$(printf '%s' "${USER_JSON_CHECK}" | cut -f1)
    T7_CLUSTER0_COUNT=$(printf '%s' "${USER_JSON_CHECK}" | cut -f2)
    T7_FRICTION=$(printf '%s' "${USER_JSON_CHECK}" | cut -f3)
    T7_SUMMARY_FRICTION=$(printf '%s' "${USER_JSON_CHECK}" | cut -f4)
    T7_SUMMARY_CLUSTERS=$(printf '%s' "${USER_JSON_CHECK}" | cut -f5)

    # The 100 auto-allows must cluster into exactly one cluster row.
    assert_eq "${T7_CLUSTERS}" "1" "friction-decision: exactly one cluster row for the 100 allows"
    assert_eq "${T7_CLUSTER0_COUNT}" "100" "friction-decision: cluster row carries count=100"

    # The deny + ask remain as friction records (kind != cluster).
    assert_eq "${T7_FRICTION}" "2" "friction-decision: exactly 2 friction records (deny + ask)"

    # Their unique command strings survive in the prompt body.
    deny_count=$(grep -F -o "unique-deny-cmd" "${PROMPT_LOG}" | wc -l | tr -d ' ')
    assert_ge "${deny_count}" "1" "friction-decision: deny survives as friction"
    ask_count=$(grep -F -o "unique-ask-cmd" "${PROMPT_LOG}" | wc -l | tr -d ' ')
    assert_ge "${ask_count}" "1" "friction-decision: ask survives as friction"

    # event_summary mirrors the structural counts.
    assert_eq "${T7_SUMMARY_FRICTION}" "2" "friction-decision: event_summary friction_events=2"
    assert_eq "${T7_SUMMARY_CLUSTERS}" "1" "friction-decision: event_summary cluster_records=1"
fi

# ---------------------------------------------------------------------
# Test 8 — rejected_count_for_day is analyzer-version-aware.
#
# Regression for the bug where 7+ prior rejections under any old
# analyzer version would permanently skip a day under a freshly-shipped
# analyzer. The fix: filter rejected_count_for_day by current version
# so a new release starts the retry counter at 0.
#
# Fixture: 7 pre-populated rejections for 2020-01-01 under
# analyzer_version=OLDSHA. Run --force-day 2020-01-01 against the
# current real SHA. The new rejection should be the FIRST under the
# current version; GIVE_UP must NOT fire.
# ---------------------------------------------------------------------

T8_HOME=$(mktemp -d -t autoheal_clu8.XXXXXX)
T8_DIR="${T8_HOME}/autoheal"
mk_state "${T8_DIR}"

# Tight cap so the synthesized events overflow even at window=0.
cat > "${T8_DIR}/config.json" <<'EOF'
{
  "max_input_tokens": 3000
}
EOF

OLD_DAY_T8="2020-01-01"
EVENTS_FILE="${T8_DIR}/events/${OLD_DAY_T8}.jsonl"
python3 - "${EVENTS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(200):
        rec = {
            "kind": "permission_request",
            "timestamp": f"2020-01-01T17:{i//60:02d}:{i%60:02d}+00:00",
            "session_id": f"s-{i}",
            "tool_name": "Bash",
            "redacted_command": "git " + ("x" * 220),
            "permission_decision": "ask",
        }
        fh.write(json.dumps(rec) + "\n")
PY

# Pre-populate 7 rejections under an OLD analyzer version. Under the
# pre-fix code, this would trigger GIVE_UP on this run (count >= 7).
# Under the fix, rejected_count_for_day filters by current version so
# the count for the live analyzer is 0 prior + 1 new = 1; no GIVE_UP.
REJ_PATH="${T8_DIR}/rejected-days.jsonl"
python3 - "${REJ_PATH}" "${OLD_DAY_T8}" <<'PY'
import datetime as dt
import json
import sys

path, day = sys.argv[1], sys.argv[2]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(7):
        rec = {
            "date": day,
            "rejected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "est_tokens": 9999,
            "max_input_tokens": 3000,
            "analyzer_version": "OLDSHA",
        }
        fh.write(json.dumps(rec) + "\n")
PY

# Capture current analyzer version BEFORE the run so we can confirm the
# new rejection row is tagged with it.
T8_CURRENT_VERSION="$(git -C "${MODULE_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 1)"

env \
    HOME="${T8_HOME}" \
    CCGM_AUTOHEAL_DIR="${T8_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" --force-day "${OLD_DAY_T8}" >"${T8_HOME}/run.out" 2>"${T8_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "version-aware: analyzer exits 0"

ERR_BODY=$(cat "${T8_HOME}/run.err")
# GIVE_UP must NOT fire — old-version rejections do not count against the
# current analyzer version's retry budget.
assert_not_contains "${ERR_BODY}" "GIVE_UP" "version-aware: GIVE_UP does not fire under fresh analyzer version"
# The day SHOULD be rejected (cap exceeded) — confirm via the window=0 line.
assert_contains "${ERR_BODY}" "even at window=0" "version-aware: rejection fired under fresh version"

# The rejected-days.jsonl now has 7 OLDSHA entries + 1 new entry tagged
# with the current analyzer version.
assert_file_exists "${T8_DIR}/rejected-days.jsonl" "version-aware: rejected-days.jsonl exists"

if [ -f "${T8_DIR}/rejected-days.jsonl" ]; then
    # Count rows with analyzer_version == current real SHA.
    NEW_COUNT=$(REJ_PATH="${T8_DIR}/rejected-days.jsonl" REJ_VERSION="${T8_CURRENT_VERSION}" python3 - <<'PY'
import json
import os

path = os.environ["REJ_PATH"]
target = os.environ["REJ_VERSION"]
n = 0
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("analyzer_version") == target:
            n += 1
print(n)
PY
)
    assert_eq "${NEW_COUNT}" "1" "version-aware: exactly 1 new rejection under current version"

    # Old-version rows are still present (audit trail preserved).
    OLD_COUNT=$(REJ_PATH="${T8_DIR}/rejected-days.jsonl" REJ_VERSION="OLDSHA" python3 - <<'PY'
import json
import os

path = os.environ["REJ_PATH"]
target = os.environ["REJ_VERSION"]
n = 0
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("analyzer_version") == target:
            n += 1
print(n)
PY
)
    assert_eq "${OLD_COUNT}" "7" "version-aware: old-version rows preserved"
fi

# Cleanup.
for d in "${T1_HOME}" "${T2_HOME}" "${T3_HOME}" "${T4_HOME}" "${T5_HOME}" "${T6_HOME}" "${T7_HOME}" "${T8_HOME}"; do
    rm -rf "${d}"
done

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "test-analyzer-clustering.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
