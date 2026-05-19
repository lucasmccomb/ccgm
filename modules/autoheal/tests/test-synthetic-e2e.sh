#!/usr/bin/env bash
# test-synthetic-e2e.sh
#
# Flagship integration test for Epic 8 (plan.md §5 Epic 8 + §8.4).
#
# Exercises the FULL autoheal daily pipeline end-to-end, OFFLINE:
#
#   1. Seed a synthetic events.jsonl in a temp ~/.claude/autoheal/events/
#      with a varied 7-event mix (permission_request, tool_failure,
#      user_correction; redacted commands; varied tool_names).
#   2. Run bin/autoheal-analyze.sh with CCGM_AUTOHEAL_FIXTURE_API_RESPONSE
#      pointed at tests/fixtures/api-response-sample.json. This bypasses
#      curl entirely so we never reach api.anthropic.com.
#      Expect: proposals/{today}.jsonl created with the fixture's
#      privilege-passing proposals.
#   3. Run bin/autoheal-digest.sh against those proposals.
#      Expect: digests/{today}.md rendered with the proposals (5-cap
#      respected, footer present).
#   4. Stand up tests/fixtures/resend-mock-server.py and run
#      bin/autoheal-email.sh against it.
#      Expect: sent/{today}-*.flag written, mock recorded a POST.
#   5. Final assertions: all expected artifacts present, content shape
#      checks (jq queries against JSONL + grep against the digest),
#      and no real-API calls (mock-server log inspection).
#
# Run: bash modules/autoheal/tests/test-synthetic-e2e.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"

ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
DIGEST_SCRIPT="${MODULE_ROOT}/bin/autoheal-digest.sh"
EMAIL_SCRIPT="${MODULE_ROOT}/bin/autoheal-email.sh"
FIXTURE_API="${SCRIPT_DIR}/fixtures/api-response-sample.json"
MOCK_SERVER="${SCRIPT_DIR}/fixtures/resend-mock-server.py"
LIB_DIR="${REPO_ROOT}/modules/hooks/lib"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-e2e.XXXXXX)"
AUTOHEAL_DIR="${TMPROOT}/autoheal"
LOGS_DIR="${TMPROOT}/logs"
PIDFILE="${TMPROOT}/mock.pid"
PORTFILE="${TMPROOT}/mock.port"

cleanup() {
    if [ -f "${PIDFILE}" ]; then
        mock_pid="$(cat "${PIDFILE}" 2>/dev/null || echo "")"
        if [ -n "${mock_pid}" ]; then
            kill "${mock_pid}" 2>/dev/null || true
        fi
    fi
    rm -rf "${TMPROOT}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Assertion helpers (kept local; consistent with sibling tests).
# ---------------------------------------------------------------------------

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
            echo "  actual (first 400): $(printf '%s' "${haystack}" | head -c 400)"
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
            echo "  unexpectedly present: ${needle}"
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

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for f in "${ANALYZER}" "${DIGEST_SCRIPT}" "${EMAIL_SCRIPT}" \
         "${FIXTURE_API}" "${MOCK_SERVER}" "${LIB_DIR}/hook_utils.py"; do
    if [ ! -f "${f}" ]; then
        echo "FATAL: missing required file: ${f}"
        exit 1
    fi
done

for tool in jq python3 curl; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "FATAL: ${tool} required on PATH"
        exit 1
    fi
done

mkdir -p "${AUTOHEAL_DIR}/events" "${AUTOHEAL_DIR}/proposals" \
         "${AUTOHEAL_DIR}/digests" "${AUTOHEAL_DIR}/sent" "${LOGS_DIR}"

# Capture today / yesterday up front so all stages use the same dates.
TODAY="$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")"
YESTERDAY="$(python3 -c "import datetime as dt; print((dt.date.today()-dt.timedelta(days=1)).isoformat())")"

# ---------------------------------------------------------------------------
# Stage 1: seed synthetic events.jsonl with a varied 7-event mix.
# ---------------------------------------------------------------------------
#
# Events live under YESTERDAY because the analyzer's "compute_days" walks
# (last_analyzed, today]; on a fresh install the lookback window covers the
# last 7 days. Putting events on YESTERDAY ensures the analyzer picks them
# up regardless of the time-of-day the test runs.

EVENTS_FILE="${AUTOHEAL_DIR}/events/${YESTERDAY}.jsonl"

python3 - "${EVENTS_FILE}" <<'PY'
import datetime as dt
import json
import sys

path = sys.argv[1]
now = dt.datetime.now(dt.timezone.utc)


def row(i, **kw):
    base = {
        "timestamp": (now - dt.timedelta(minutes=i)).isoformat(),
        "session_id": f"sess-{i % 3}",
        "tool_name": "Bash",
        "redacted_command": None,
        "exit_code": None,
        "stderr_excerpt": None,
        "permission_decision": None,
        "cwd": "/tmp/repo",
        "clone_path": "/tmp/repo",
    }
    base.update(kw)
    return base


# 3x permission_request for the same command (drives the synthesized
# proposal in the fixture: "Auto-approve git diff --staged").
events = [
    row(1, kind="permission_request", redacted_command="git diff --staged",
        permission_decision="ask"),
    row(2, kind="permission_request", redacted_command="git diff --staged",
        permission_decision="ask"),
    row(3, kind="permission_request", redacted_command="git diff --staged",
        permission_decision="ask"),
    # 2x tool_failure on a different command (variety; analyzer-fixture
    # ignores these but we want to prove the pipeline tolerates a mix).
    row(4, kind="tool_failure", tool_name="Bash",
        redacted_command="pnpm test", exit_code=1,
        stderr_excerpt="error: missing dependency"),
    row(5, kind="tool_failure", tool_name="Edit",
        redacted_command=None, exit_code=2,
        stderr_excerpt="permission denied"),
    # 1x user_correction (synthesized by user-correction-detector hook).
    row(6, kind="user_correction", tool_name="Edit",
        redacted_command=None),
    # 1x permission_request with a different tool.
    row(7, kind="permission_request", tool_name="WebFetch",
        redacted_command=None, permission_decision="ask"),
]

with open(path, "w", encoding="utf-8") as fh:
    for ev in events:
        fh.write(json.dumps(ev) + "\n")
PY

# Sanity: the events file is populated.
EVENT_COUNT="$(grep -c . "${EVENTS_FILE}" 2>/dev/null || echo 0)"
assert_eq "${EVENT_COUNT}" "7" "stage1: 7 events seeded"

# ---------------------------------------------------------------------------
# Stage 2: run autoheal-analyze with the fixture API response.
# ---------------------------------------------------------------------------
#
# CCGM_AUTOHEAL_FIXTURE_API_RESPONSE short-circuits the curl call entirely.
# CCGM_AUTOHEAL_API_URL points at an unreachable address as belt-and-braces:
# if the fixture path were ever ignored we want the test to FAIL LOUDLY, not
# silently reach the real API.

PROMPT_LOG="${TMPROOT}/analyzer-prompt.log"

env \
    HOME="${TMPROOT}" \
    CCGM_AUTOHEAL_DIR="${AUTOHEAL_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE_API}" \
    CCGM_AUTOHEAL_API_URL="http://127.0.0.1:1/never-called" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-e2e" \
    ANTHROPIC_API_KEY="placeholder-unused-because-fixture" \
    bash "${ANALYZER}" >"${TMPROOT}/analyze.out" 2>"${TMPROOT}/analyze.err"
ANALYZE_RC=$?

assert_eq "${ANALYZE_RC}" "0" "stage2: analyzer exits 0"

PROPOSALS_FILE="${AUTOHEAL_DIR}/proposals/${TODAY}.jsonl"
assert_file_exists "${PROPOSALS_FILE}" "stage2: proposals/{today}.jsonl written"
assert_file_exists "${PROMPT_LOG}" "stage2: prompt log captured"

# Shape check: exactly one proposal accepted (fixture has one, and it
# passes the privilege gate: confidence=9, breadth_score=1).
if [ -f "${PROPOSALS_FILE}" ]; then
    PROP_COUNT="$(grep -c . "${PROPOSALS_FILE}" 2>/dev/null || echo 0)"
    assert_eq "${PROP_COUNT}" "1" "stage2: one proposal accepted (fixture)"

    PROP_KIND="$(jq -r 'select(.id) | .kind' < "${PROPOSALS_FILE}" | head -1)"
    assert_eq "${PROP_KIND}" "settings_allow_add" "stage2: proposal kind preserved"

    PROP_CONFIDENCE="$(jq -r 'select(.id) | .confidence' < "${PROPOSALS_FILE}" | head -1)"
    assert_eq "${PROP_CONFIDENCE}" "9" "stage2: proposal confidence preserved"

    PROP_BREADTH="$(jq -r 'select(.id) | .breadth_score' < "${PROPOSALS_FILE}" | head -1)"
    assert_eq "${PROP_BREADTH}" "1" "stage2: proposal breadth_score preserved"
fi

# No real API call ever happened: the fixture path was hot and the
# CCGM_AUTOHEAL_API_URL was an unreachable 127.0.0.1:1, so an accidental
# curl would have produced an error in stderr. Verify we did not see one.
ANALYZE_ERR="$(cat "${TMPROOT}/analyze.err" 2>/dev/null || echo "")"
assert_not_contains "${ANALYZE_ERR}" "curl: " "stage2: no curl invocation (fixture honored)"
assert_not_contains "${ANALYZE_ERR}" "Could not resolve host" "stage2: no DNS attempt"

# ---------------------------------------------------------------------------
# Stage 3: run autoheal-digest against the proposals file.
# ---------------------------------------------------------------------------

env \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${AUTOHEAL_DIR}/proposals" \
    CCGM_AUTOHEAL_DIGESTS_DIR="${AUTOHEAL_DIR}/digests" \
    CCGM_AUTOHEAL_SENT_DIR="${AUTOHEAL_DIR}/sent" \
    CCGM_AUTOHEAL_CONFIG="${AUTOHEAL_DIR}/config-missing.json" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    bash "${DIGEST_SCRIPT}" >"${TMPROOT}/digest.out" 2>"${TMPROOT}/digest.err"
DIGEST_RC=$?

assert_eq "${DIGEST_RC}" "0" "stage3: digest exits 0"

DIGEST_FILE="${AUTOHEAL_DIR}/digests/${TODAY}.md"
assert_file_exists "${DIGEST_FILE}" "stage3: digest markdown rendered"

if [ -f "${DIGEST_FILE}" ]; then
    DIGEST_BODY="$(cat "${DIGEST_FILE}")"
    assert_contains "${DIGEST_BODY}" "Autoheal digest" "stage3: digest header present"
    assert_contains "${DIGEST_BODY}" "Auto-approve git diff --staged" "stage3: fixture title rendered"
    assert_contains "${DIGEST_BODY}" "/autoheal-apply" "stage3: apply hint present"
    assert_contains "${DIGEST_BODY}" "/autoheal-toggle" "stage3: footer toggle link present"
fi

# ---------------------------------------------------------------------------
# Stage 4: stand up the Resend mock and send the email.
# ---------------------------------------------------------------------------
#
# Start the mock with --port 0 so it picks a free port. The script writes
# the actual port to PORTFILE; we poll briefly for it.

rm -f "${PIDFILE}" "${PORTFILE}"
python3 "${MOCK_SERVER}" \
    --port 0 \
    --pidfile "${PIDFILE}" \
    --port-file "${PORTFILE}" \
    >/dev/null 2>&1 &

# Wait for the port file (max ~3s).
i=0
while [ ${i} -lt 60 ]; do
    if [ -s "${PORTFILE}" ]; then
        break
    fi
    sleep 0.05
    i=$((i + 1))
done

if [ ! -s "${PORTFILE}" ]; then
    echo "FATAL: mock server did not write port file in time"
    exit 1
fi

MOCK_PORT="$(cat "${PORTFILE}")"
RESEND_URL="http://127.0.0.1:${MOCK_PORT}/emails"

# Email config: enabled + one recipient.
CONFIG_FILE="${AUTOHEAL_DIR}/config.json"
cat > "${CONFIG_FILE}" <<JSON
{
  "email_enabled": true,
  "digest_email": "e2e-test@example.com"
}
JSON

env \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${AUTOHEAL_DIR}/proposals" \
    CCGM_AUTOHEAL_DIGESTS_DIR="${AUTOHEAL_DIR}/digests" \
    CCGM_AUTOHEAL_SENT_DIR="${AUTOHEAL_DIR}/sent" \
    CCGM_AUTOHEAL_LOGS_DIR="${LOGS_DIR}" \
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_RESEND_URL="${RESEND_URL}" \
    CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    RESEND_API_KEY="dummy-key-not-real" \
    bash "${EMAIL_SCRIPT}" >"${TMPROOT}/email.out" 2>"${TMPROOT}/email.err"
EMAIL_RC=$?

assert_eq "${EMAIL_RC}" "0" "stage4: email script exits 0"

# Sent flag written: hash is sha256(recipient)[:12].
REC_HASH="$(printf '%s' "e2e-test@example.com" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
SENT_FLAG="${AUTOHEAL_DIR}/sent/${TODAY}-${REC_HASH}.flag"
assert_file_exists "${SENT_FLAG}" "stage4: sent flag written for recipient"

# Mock server recorded exactly one POST.
REQS_JSON="$(curl -sS "http://127.0.0.1:${MOCK_PORT}/requests" 2>/dev/null || echo '{"requests":[]}')"
N_POSTS="$(printf '%s' "${REQS_JSON}" | jq '.requests | length')"
assert_eq "${N_POSTS}" "1" "stage4: mock recorded 1 POST"

if [ "${N_POSTS}" = "1" ]; then
    POST_TO="$(printf '%s' "${REQS_JSON}" | jq -r '.requests[0].body_json.to[0]')"
    assert_eq "${POST_TO}" "e2e-test@example.com" "stage4: POST 'to' field matches recipient"

    POST_SUBJECT="$(printf '%s' "${REQS_JSON}" | jq -r '.requests[0].body_json.subject')"
    assert_contains "${POST_SUBJECT}" "autoheal digest" "stage4: POST subject names autoheal digest"

    POST_BODY="$(printf '%s' "${REQS_JSON}" | jq -r '.requests[0].body_json.text')"
    assert_contains "${POST_BODY}" "Auto-approve git diff --staged" "stage4: POST body carries proposal title"

    # Idempotency key: ccgm-autoheal-{today}-{rec_hash}.
    POST_IDEM="$(printf '%s' "${REQS_JSON}" | jq -r '.requests[0].idempotency_key')"
    assert_eq "${POST_IDEM}" "ccgm-autoheal-${TODAY}-${REC_HASH}" "stage4: idempotency key includes recipient hash"
fi

# ---------------------------------------------------------------------------
# Stage 5: cross-cutting end-to-end assertions.
# ---------------------------------------------------------------------------

# All expected artifacts on disk.
assert_file_exists "${EVENTS_FILE}" "stage5: events file persisted"
assert_file_exists "${PROPOSALS_FILE}" "stage5: proposals file persisted"
assert_file_exists "${DIGEST_FILE}" "stage5: digest file persisted"
assert_file_exists "${SENT_FLAG}" "stage5: sent flag persisted"

# Cost log exists from analyze stage (proves the fixture path still
# wrote a cost record, even though the fixture has $0 cost).
COST_LOG="${AUTOHEAL_DIR}/cost.log"
assert_file_exists "${COST_LOG}" "stage5: cost log written"

# last-analyzed advanced to today.
LAST_FILE="${AUTOHEAL_DIR}/last-analyzed"
assert_file_exists "${LAST_FILE}" "stage5: last-analyzed advanced"
if [ -f "${LAST_FILE}" ]; then
    LAST_VAL="$(cat "${LAST_FILE}" 2>/dev/null || echo "")"
    assert_eq "${LAST_VAL}" "${TODAY}" "stage5: last-analyzed == today"
fi

# No real API or Resend call ever reached the public internet. The
# email step exclusively hit 127.0.0.1; the analyzer exclusively read
# the fixture. The email error log file may be touched by `2>>` even
# on success, but it must be EMPTY when the Resend mock succeeded.
EMAIL_ERR_LOG="${LOGS_DIR}/autoheal-email-${TODAY}.err.log"
if [ -s "${EMAIL_ERR_LOG}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: stage5: email err log non-empty (Resend mock succeeded; no err expected)"
    echo "  contents:"
    sed 's/^/    /' "${EMAIL_ERR_LOG}"
else
    PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-synthetic-e2e.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
