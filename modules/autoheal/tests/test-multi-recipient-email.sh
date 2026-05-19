#!/usr/bin/env bash
# test-multi-recipient-email.sh
#
# Verifies modules/autoheal/bin/autoheal-email.sh handles the
# `digest_email: [...]` list form (plan.md §1.2 multi-recipient + §5 Epic
# 7 + §5 Epic 12).
#
# Assertions:
#   1. digest_email = ["a@b.com","c@d.com","e@f.com"] -> 3 POSTs.
#   2. Each POST carries a distinct Idempotency-Key suffix that matches
#      the sha256 prefix of its recipient.
#   3. Each POST's `to` field carries the correct recipient.
#   4. Each successful POST writes a sent flag named with the recipient
#      hash.
#   5. Backwards-compat: a string-valued `digest_email` still works.
#   6. Failure mode: when the mock returns 500, the script records the
#      failure and DOES NOT write a sent flag for that recipient.
#
# Run: bash modules/autoheal/tests/test-multi-recipient-email.sh

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
TMPROOT="$(mktemp -d -t autoheal-multi-test.XXXXXX)"
PIDFILE="${TMPROOT}/mock.pid"
PORTFILE="${TMPROOT}/mock.port"
FAIL_PIDFILE="${TMPROOT}/fail-mock.pid"
FAIL_PORTFILE="${TMPROOT}/fail-mock.port"

cleanup() {
    for pf in "${PIDFILE}" "${FAIL_PIDFILE}"; do
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
            echo "FAIL: ${label} (missing: ${needle})"
            ;;
    esac
}

write_proposal() {
    local out_file="$1"; local pid="$2"
    jq -nc \
        --arg id "${pid}" \
        '{
            id: $id,
            kind: "settings_allow_add",
            title: "T",
            rationale: "R",
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
    echo "FATAL: mock server did not write port file"
    return 1
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for f in "${EMAIL_SCRIPT}" "${DIGEST_SCRIPT}" "${MOCK_SERVER}" "${LIB_DIR}/hook_utils.py"; do
    if [ ! -f "${f}" ]; then
        echo "FATAL: missing required file: ${f}"
        exit 1
    fi
done

for tool in jq python3 curl; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "FATAL: ${tool} required"
        exit 1
    fi
done

start_mock "${PIDFILE}" "${PORTFILE}" || exit 1
PORT="$(cat "${PORTFILE}")"
RESEND_URL="http://127.0.0.1:${PORT}/emails"

# ---------------------------------------------------------------------------
# Case A: 3 recipients via list.
# ---------------------------------------------------------------------------

CASE_A="${TMPROOT}/caseA"
mkdir -p "${CASE_A}/proposals" "${CASE_A}/digests" "${CASE_A}/sent" "${CASE_A}/logs"
TODAY_A="2026-05-18"
write_proposal "${CASE_A}/proposals/${TODAY_A}.jsonl" "prop_a"

CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_A}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_A}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_A}/sent" \
CCGM_AUTOHEAL_CONFIG="${CASE_A}/missing.json" \
CCGM_AUTOHEAL_TODAY="${TODAY_A}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    bash "${DIGEST_SCRIPT}" >/dev/null 2>&1

CONFIG_A="${CASE_A}/config.json"
cat > "${CONFIG_A}" <<JSON
{
  "email_enabled": true,
  "digest_email": ["a@b.com", "c@d.com", "e@f.com"]
}
JSON

# Reset mock counter.
curl -sS -X POST "http://127.0.0.1:${PORT}/reset" >/dev/null

CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_A}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_A}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_A}/sent" \
CCGM_AUTOHEAL_LOGS_DIR="${CASE_A}/logs" \
CCGM_AUTOHEAL_CONFIG="${CONFIG_A}" \
CCGM_AUTOHEAL_TODAY="${TODAY_A}" \
CCGM_AUTOHEAL_RESEND_URL="${RESEND_URL}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
RESEND_API_KEY="dummy-test-key" \
    bash "${EMAIL_SCRIPT}" >/dev/null 2>&1

REQS_A="$(curl -sS "http://127.0.0.1:${PORT}/requests")"
N_A="$(printf '%s' "${REQS_A}" | jq '.requests | length')"
assert_eq "${N_A}" "3" "caseA: 3 POSTs for 3 recipients"

DISTINCT_KEYS_A="$(printf '%s' "${REQS_A}" | jq -r '[.requests[].idempotency_key] | unique | length')"
assert_eq "${DISTINCT_KEYS_A}" "3" "caseA: 3 distinct idempotency keys"

# Each idempotency key must include the sha256 hash of its recipient.
for recipient in a@b.com c@d.com e@f.com; do
    expected_hash="$(printf '%s' "${recipient}" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
    expected_key="ccgm-autoheal-${TODAY_A}-${expected_hash}"
    # Find the request whose to[0] matches this recipient and check its key.
    actual_key="$(printf '%s' "${REQS_A}" | jq -r --arg to "${recipient}" '
        .requests[] | select(.body_json.to[0] == $to) | .idempotency_key
    ')"
    assert_eq "${actual_key}" "${expected_key}" "caseA: ${recipient} key matches sha256 prefix"

    # Sent flag exists for each.
    flag="${CASE_A}/sent/${TODAY_A}-${expected_hash}.flag"
    if [ -f "${flag}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: caseA: sent flag missing for ${recipient} (${flag})"
    fi
done

# ---------------------------------------------------------------------------
# Case B: Backwards-compat: digest_email as a string.
# ---------------------------------------------------------------------------

CASE_B="${TMPROOT}/caseB"
mkdir -p "${CASE_B}/proposals" "${CASE_B}/digests" "${CASE_B}/sent" "${CASE_B}/logs"
TODAY_B="2026-05-20"
write_proposal "${CASE_B}/proposals/${TODAY_B}.jsonl" "prop_b"

CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_B}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_B}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_B}/sent" \
CCGM_AUTOHEAL_CONFIG="${CASE_B}/missing.json" \
CCGM_AUTOHEAL_TODAY="${TODAY_B}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    bash "${DIGEST_SCRIPT}" >/dev/null 2>&1

CONFIG_B="${CASE_B}/config.json"
cat > "${CONFIG_B}" <<JSON
{
  "email_enabled": true,
  "digest_email": "only@example.com"
}
JSON

curl -sS -X POST "http://127.0.0.1:${PORT}/reset" >/dev/null

CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_B}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_B}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_B}/sent" \
CCGM_AUTOHEAL_LOGS_DIR="${CASE_B}/logs" \
CCGM_AUTOHEAL_CONFIG="${CONFIG_B}" \
CCGM_AUTOHEAL_TODAY="${TODAY_B}" \
CCGM_AUTOHEAL_RESEND_URL="${RESEND_URL}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
RESEND_API_KEY="dummy-test-key" \
    bash "${EMAIL_SCRIPT}" >/dev/null 2>&1

REQS_B="$(curl -sS "http://127.0.0.1:${PORT}/requests")"
N_B="$(printf '%s' "${REQS_B}" | jq '.requests | length')"
assert_eq "${N_B}" "1" "caseB: string digest_email -> 1 POST"
TO_B="$(printf '%s' "${REQS_B}" | jq -r '.requests[0].body_json.to[0]')"
assert_eq "${TO_B}" "only@example.com" "caseB: string recipient sent"

# ---------------------------------------------------------------------------
# Case C: Failure mode: server returns 500. No sent flag should be written.
# ---------------------------------------------------------------------------

start_mock "${FAIL_PIDFILE}" "${FAIL_PORTFILE}" --fail-with 500 || exit 1
FAIL_PORT="$(cat "${FAIL_PORTFILE}")"
FAIL_RESEND_URL="http://127.0.0.1:${FAIL_PORT}/emails"

CASE_C="${TMPROOT}/caseC"
mkdir -p "${CASE_C}/proposals" "${CASE_C}/digests" "${CASE_C}/sent" "${CASE_C}/logs"
TODAY_C="2026-05-21"
write_proposal "${CASE_C}/proposals/${TODAY_C}.jsonl" "prop_c"

CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_C}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_C}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_C}/sent" \
CCGM_AUTOHEAL_CONFIG="${CASE_C}/missing.json" \
CCGM_AUTOHEAL_TODAY="${TODAY_C}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
    bash "${DIGEST_SCRIPT}" >/dev/null 2>&1

CONFIG_C="${CASE_C}/config.json"
cat > "${CONFIG_C}" <<JSON
{
  "email_enabled": true,
  "digest_email": "fail@example.com"
}
JSON

EMAIL_EXIT=0
CCGM_AUTOHEAL_PROPOSALS_DIR="${CASE_C}/proposals" \
CCGM_AUTOHEAL_DIGESTS_DIR="${CASE_C}/digests" \
CCGM_AUTOHEAL_SENT_DIR="${CASE_C}/sent" \
CCGM_AUTOHEAL_LOGS_DIR="${CASE_C}/logs" \
CCGM_AUTOHEAL_CONFIG="${CONFIG_C}" \
CCGM_AUTOHEAL_TODAY="${TODAY_C}" \
CCGM_AUTOHEAL_RESEND_URL="${FAIL_RESEND_URL}" \
CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
RESEND_API_KEY="dummy-test-key" \
    bash "${EMAIL_SCRIPT}" >/dev/null 2>&1 || EMAIL_EXIT=$?

assert_eq "${EMAIL_EXIT}" "0" "caseC: script exits 0 even on resend failure"

FAIL_HASH="$(printf '%s' "fail@example.com" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
FAIL_FLAG="${CASE_C}/sent/${TODAY_C}-${FAIL_HASH}.flag"
if [ -f "${FAIL_FLAG}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: caseC: sent flag written despite 500 response"
else
    PASS=$((PASS + 1))
fi

# Error log written.
ERR_LOG="${CASE_C}/logs/autoheal-email-${TODAY_C}.err.log"
if [ -f "${ERR_LOG}" ]; then
    PASS=$((PASS + 1))
    ERR_BODY="$(cat "${ERR_LOG}")"
    assert_contains "${ERR_BODY}" "fail@example.com" "caseC: error log mentions recipient"
    assert_contains "${ERR_BODY}" "500" "caseC: error log mentions http code"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: caseC: error log not written: ${ERR_LOG}"
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-multi-recipient-email.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
