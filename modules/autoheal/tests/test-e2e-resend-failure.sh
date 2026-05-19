#!/usr/bin/env bash
# test-e2e-resend-failure.sh
#
# End-to-end test for the Resend failure path (plan.md §5 Epic 7 +
# Epic 8). Exercises the contract documented in autoheal-email.sh:
#
#   - 4xx/5xx responses are RECORDED, not propagated. The daily
#     pipeline must keep going so the digest is preserved and so the
#     next run can retry with the same idempotency key.
#   - The error log captures the recipient AND the HTTP status code
#     so the operator can diagnose without re-running.
#   - The sent flag is NOT written on failure. This is what makes
#     the next day's run retry (the backfill scan keys off the flag).
#   - Once Resend returns 2xx (different mock invocation), the flag
#     is written and the idempotency key matches the first attempt
#     (same {today, recipient_hash}).
#
# Run: bash modules/autoheal/tests/test-e2e-resend-failure.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"

EMAIL_SCRIPT="${MODULE_ROOT}/bin/autoheal-email.sh"
DIGEST_SCRIPT="${MODULE_ROOT}/bin/autoheal-digest.sh"
MOCK_SERVER="${MODULE_ROOT}/tests/fixtures/resend-mock-server.py"
LIB_DIR="${REPO_ROOT}/modules/hooks/lib"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-resend-fail.XXXXXX)"
FAIL_PIDFILE="${TMPROOT}/fail-mock.pid"
FAIL_PORTFILE="${TMPROOT}/fail-mock.port"
OK_PIDFILE="${TMPROOT}/ok-mock.pid"
OK_PORTFILE="${TMPROOT}/ok-mock.port"

cleanup() {
    for pf in "${FAIL_PIDFILE}" "${OK_PIDFILE}"; do
        if [ -f "${pf}" ]; then
            mock_pid="$(cat "${pf}" 2>/dev/null || echo "")"
            if [ -n "${mock_pid}" ]; then
                kill "${mock_pid}" 2>/dev/null || true
            fi
        fi
    done
    rm -rf "${TMPROOT}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Assertion helpers
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

assert_file_absent() {
    local path="$1"
    local label="$2"
    if [ -e "${path}" ]; then
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  unexpectedly present: ${path}"
    else
        PASS=$((PASS + 1))
    fi
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

write_proposal() {
    local out_file="$1"
    local pid="$2"
    jq -nc \
        --arg id "${pid}" \
        '{
            id: $id,
            kind: "settings_allow_add",
            title: ("Allow " + $id),
            rationale: "Test fixture",
            confidence: 7,
            breadth_score: 2,
            occurrence_count: 3,
            session_ids: ["s1","s2"],
            proposed_diff_target: "modules/settings/settings.partial.json",
            proposed_diff: "+ allow",
            fingerprint: ("sha256-" + $id),
            originating_clone: "test",
            generated_at: "2026-05-18T08:00:00Z"
        }' >> "${out_file}"
}

start_mock() {
    local pidfile="$1"; local portfile="$2"; shift 2
    rm -f "${pidfile}" "${portfile}"
    python3 "${MOCK_SERVER}" \
        --port 0 \
        --pidfile "${pidfile}" \
        --port-file "${portfile}" \
        "$@" \
        >/dev/null 2>&1 &
    local i=0
    while [ ${i} -lt 60 ]; do
        if [ -s "${portfile}" ]; then
            return 0
        fi
        sleep 0.05
        i=$((i + 1))
    done
    echo "FATAL: mock server did not write port file: ${portfile}"
    return 1
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for f in "${EMAIL_SCRIPT}" "${DIGEST_SCRIPT}" "${MOCK_SERVER}" \
         "${LIB_DIR}/hook_utils.py"; do
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

# Shared dirs / today.
SHARED_DIR="${TMPROOT}/shared"
mkdir -p "${SHARED_DIR}/proposals" "${SHARED_DIR}/digests" \
         "${SHARED_DIR}/sent" "${SHARED_DIR}/logs"
TODAY="2026-05-18"
RECIPIENT="fail-then-ok@example.com"
REC_HASH="$(printf '%s' "${RECIPIENT}" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
SENT_FLAG="${SHARED_DIR}/sent/${TODAY}-${REC_HASH}.flag"
ERR_LOG="${SHARED_DIR}/logs/autoheal-email-${TODAY}.err.log"
EXPECTED_IDEM="ccgm-autoheal-${TODAY}-${REC_HASH}"

# Seed proposals + render digest once. Both attempts use the same
# digest body so the test mirrors a real "first attempt failed, second
# attempt retried" sequence.
write_proposal "${SHARED_DIR}/proposals/${TODAY}.jsonl" "prop_retry"

CCGM_AUTOHEAL_PROPOSALS_DIR="${SHARED_DIR}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${SHARED_DIR}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${SHARED_DIR}/sent" \
CCGM_AUTOHEAL_CONFIG="${SHARED_DIR}/digest-config-missing.json" \
CCGM_AUTOHEAL_TODAY="${TODAY}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    bash "${DIGEST_SCRIPT}" >/dev/null 2>&1

assert_file_exists "${SHARED_DIR}/digests/${TODAY}.md" "preflight: digest rendered"

# Email config: enabled + 1 recipient.
CONFIG_FILE="${SHARED_DIR}/config.json"
cat > "${CONFIG_FILE}" <<JSON
{
  "email_enabled": true,
  "digest_email": "${RECIPIENT}"
}
JSON

# ---------------------------------------------------------------------------
# Phase A: Resend mock returns 500.
#
# Expect:
#   - email script rc 0 (failure does NOT block the pipeline)
#   - error log contains the 500 and the recipient
#   - sent flag NOT written (so next day's run retries)
# ---------------------------------------------------------------------------

start_mock "${FAIL_PIDFILE}" "${FAIL_PORTFILE}" --fail-with 500 || exit 1
FAIL_PORT="$(cat "${FAIL_PORTFILE}")"
FAIL_URL="http://127.0.0.1:${FAIL_PORT}/emails"

# Reset before the attempt so the captured request count is 1.
curl -sS -X POST "http://127.0.0.1:${FAIL_PORT}/reset" >/dev/null

set +e
CCGM_AUTOHEAL_PROPOSALS_DIR="${SHARED_DIR}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${SHARED_DIR}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${SHARED_DIR}/sent" \
CCGM_AUTOHEAL_LOGS_DIR="${SHARED_DIR}/logs" \
CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
CCGM_AUTOHEAL_TODAY="${TODAY}" \
CCGM_AUTOHEAL_RESEND_URL="${FAIL_URL}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
RESEND_API_KEY="dummy-key" \
    bash "${EMAIL_SCRIPT}" >"${TMPROOT}/phaseA.out" 2>"${TMPROOT}/phaseA.err"
PHASEA_RC=$?
set -e

assert_eq "${PHASEA_RC}" "0" "phaseA: email script rc 0 (failure non-fatal)"

# Sent flag must NOT be present — that's what makes the next run retry.
assert_file_absent "${SENT_FLAG}" "phaseA: sent flag NOT written on 500"

# Error log must mention recipient and HTTP code.
assert_file_exists "${ERR_LOG}" "phaseA: error log written"
if [ -f "${ERR_LOG}" ]; then
    ERR_BODY="$(cat "${ERR_LOG}")"
    assert_contains "${ERR_BODY}" "${RECIPIENT}" "phaseA: error log names recipient"
    assert_contains "${ERR_BODY}" "500" "phaseA: error log captures 500"
    assert_contains "${ERR_BODY}" "${EXPECTED_IDEM}" "phaseA: error log captures idempotency key"
fi

# Mock server recorded the attempt — and recorded the idempotency key
# we expect to see again on retry.
PHASEA_REQS="$(curl -sS "http://127.0.0.1:${FAIL_PORT}/requests")"
PHASEA_N="$(printf '%s' "${PHASEA_REQS}" | jq '.requests | length')"
assert_eq "${PHASEA_N}" "1" "phaseA: mock recorded 1 POST"

PHASEA_IDEM="$(printf '%s' "${PHASEA_REQS}" | jq -r '.requests[0].idempotency_key')"
assert_eq "${PHASEA_IDEM}" "${EXPECTED_IDEM}" "phaseA: idempotency key formed correctly"

# Stop the failing mock before starting the OK one.
kill "$(cat "${FAIL_PIDFILE}")" 2>/dev/null || true
rm -f "${FAIL_PIDFILE}"

# ---------------------------------------------------------------------------
# Phase B: Resend mock returns 200. Same recipient, same date.
#
# Expect:
#   - sent flag now written
#   - idempotency key matches phaseA (so Resend would dedupe in prod)
#   - error log either absent or empty for the retry (no new failures)
# ---------------------------------------------------------------------------

# Truncate the error log so we can verify the retry produced no new errors.
: > "${ERR_LOG}"

start_mock "${OK_PIDFILE}" "${OK_PORTFILE}" || exit 1
OK_PORT="$(cat "${OK_PORTFILE}")"
OK_URL="http://127.0.0.1:${OK_PORT}/emails"

curl -sS -X POST "http://127.0.0.1:${OK_PORT}/reset" >/dev/null

set +e
CCGM_AUTOHEAL_PROPOSALS_DIR="${SHARED_DIR}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${SHARED_DIR}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${SHARED_DIR}/sent" \
CCGM_AUTOHEAL_LOGS_DIR="${SHARED_DIR}/logs" \
CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
CCGM_AUTOHEAL_TODAY="${TODAY}" \
CCGM_AUTOHEAL_RESEND_URL="${OK_URL}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
RESEND_API_KEY="dummy-key" \
    bash "${EMAIL_SCRIPT}" >"${TMPROOT}/phaseB.out" 2>"${TMPROOT}/phaseB.err"
PHASEB_RC=$?
set -e

assert_eq "${PHASEB_RC}" "0" "phaseB: email script rc 0 (success)"
assert_file_exists "${SENT_FLAG}" "phaseB: sent flag written on 200"

# Error log must be empty (no new failures appended on the successful retry).
if [ -s "${ERR_LOG}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: phaseB: error log unexpectedly non-empty after successful retry"
    echo "  contents:"
    sed 's/^/    /' "${ERR_LOG}"
else
    PASS=$((PASS + 1))
fi

# Idempotency key on the successful retry MUST match phaseA's key.
# This is the property that makes Resend's idempotency dedupe correctly
# in production — same input on the same day yields the same key.
PHASEB_REQS="$(curl -sS "http://127.0.0.1:${OK_PORT}/requests")"
PHASEB_N="$(printf '%s' "${PHASEB_REQS}" | jq '.requests | length')"
assert_eq "${PHASEB_N}" "1" "phaseB: mock recorded 1 POST"

PHASEB_IDEM="$(printf '%s' "${PHASEB_REQS}" | jq -r '.requests[0].idempotency_key')"
assert_eq "${PHASEB_IDEM}" "${EXPECTED_IDEM}" "phaseB: idempotency key matches phaseA"
assert_eq "${PHASEB_IDEM}" "${PHASEA_IDEM}" "phaseB: idempotency key identical across attempts"

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-e2e-resend-failure.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
