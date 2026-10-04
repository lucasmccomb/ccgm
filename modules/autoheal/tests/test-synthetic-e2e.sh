#!/usr/bin/env bash
# test-synthetic-e2e.sh
#
# Flagship integration test for Epic 8 (plan.md §5 Epic 8 + §8.4).
#
# Exercises the FULL autoheal daily pipeline end-to-end, OFFLINE:
#
#   1. Seed synthetic events in a temp ~/.claude/autoheal/events/: eight
#      zsh-quoting tool_failure rows over three sessions and two days (a
#      qualifying signature) plus noise the analyzer must ignore
#      (permission_request, user_correction, a one-off failure).
#   2. Run bin/autoheal-analyze.sh with tests/fixtures/fake-curl.py first on
#      PATH, so no request reaches api.anthropic.com. The fake serves a
#      count_tokens reply and a rule_insert answer.
#      Expect: proposals.jsonl holds one rule_insert whose diff was
#      built by code against the fixture repo.
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
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"
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
         "${MOCK_SERVER}" "${LIB_DIR}/hook_utils.py"; do
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
# Stage 1: seed synthetic events.
# ---------------------------------------------------------------------------
#
# The analyzer aggregates a 14-day window ending at TODAY, so the qualifying
# rows sit on TODAY and YESTERDAY (two days, three sessions).

EVENTS_FILE="${AUTOHEAL_DIR}/events/${TODAY}.jsonl"

fx_repo "${TMPROOT}/repo"
fx_home "${TMPROOT}" "${TMPROOT}/repo"
fx_events "${AUTOHEAL_DIR}" "${TODAY}" Bash echo zsh_not_found "(eval):1: ==== not found" 8 3
fx_events "${AUTOHEAL_DIR}" "${TODAY}" Bash "pnpm test" other "error: missing dependency" 1 1
python3 - "${EVENTS_FILE}" <<'PY'
import datetime as dt
import json
import sys

now = dt.datetime.now(dt.timezone.utc)
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    for i, (kind, tool, cmd) in enumerate([
        ("permission_request", "Bash", "git diff --staged"),
        ("permission_request", "WebFetch", None),
        ("user_correction", "Edit", None),
    ]):
        fh.write(json.dumps({
            "kind": kind, "timestamp": (now - dt.timedelta(minutes=i)).isoformat(),
            "session_id": f"sess-{i}", "tool_name": tool, "redacted_command": cmd,
            "cwd": "/tmp/repo", "clone_path": "/tmp/repo"}) + "\n")
PY

EVENT_COUNT="$(cat "${AUTOHEAL_DIR}"/events/*.jsonl | grep -c . || echo 0)"
assert_eq "$([ "${EVENT_COUNT}" -ge 10 ] && echo ok || echo "${EVENT_COUNT}")" "ok" "stage1: signal and noise rows seeded"

# ---------------------------------------------------------------------------
# Stage 2: run autoheal-analyze against the fake curl.
# ---------------------------------------------------------------------------
#
# Every curl call lands in fake-curl.py, which records it in calls.log. The
# test checks that log, so a real request would fail loudly instead of
# silently reaching the API.

FAKE_DIR="${TMPROOT}/fake"
fx_curl "${TMPROOT}/bin" "${FAKE_DIR}"
fx_answer "${FAKE_DIR}/messages.response.json" \
    '{"proposal":{"kind":"rule_insert","target_path":"modules/code-quality/rules/code-quality.md","anchor_heading":"Code Standards","insert_markdown":"- Bash runs under zsh. Quote separators such as `====`."}}'
PROMPT_LOG="${TMPROOT}/analyzer-prompt.log"

env \
    HOME="${TMPROOT}" \
    PATH="${TMPROOT}/bin:${PATH}" \
    FAKE_CURL_DIR="${FAKE_DIR}" \
    CCGM_AUTOHEAL_DIR="${AUTOHEAL_DIR}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-e2e" \
    ANTHROPIC_API_KEY="placeholder-not-a-real-key" \
    bash "${ANALYZER}" >"${TMPROOT}/analyze.out" 2>"${TMPROOT}/analyze.err"
ANALYZE_RC=$?

assert_eq "${ANALYZE_RC}" "0" "stage2: analyzer exits 0"

PROPOSALS_FILE="${AUTOHEAL_DIR}/proposals.jsonl"
assert_file_exists "${PROPOSALS_FILE}" "stage2: ledger written"
assert_file_exists "${PROMPT_LOG}" "stage2: prompt log captured"

# Shape check: one signature qualified, one proposal written.
if [ -f "${PROPOSALS_FILE}" ]; then
    PROP_COUNT="$(grep -c . "${PROPOSALS_FILE}" 2>/dev/null || echo 0)"
    assert_eq "${PROP_COUNT}" "1" "stage2: one proposal written"

    PROP_KIND="$(jq -r 'select(.id) | .kind' < "${PROPOSALS_FILE}" | head -1)"
    assert_eq "${PROP_KIND}" "rule_insert" "stage2: proposal kind is rule_insert"

    PROP_TARGET="$(jq -r 'select(.id) | .target' < "${PROPOSALS_FILE}" | head -1)"
    assert_eq "${PROP_TARGET}" "modules/code-quality/rules/code-quality.md" "stage2: target is a real file"
    assert_file_exists "${TMPROOT}/repo/${PROP_TARGET}" "stage2: target exists in the source repo"

    jq -r '.diff' < "${PROPOSALS_FILE}" > "${TMPROOT}/e2e.diff"
    git -C "${TMPROOT}/repo" apply --check "${TMPROOT}/e2e.diff"
    assert_eq "$?" "0" "stage2: the diff passes git apply --check"
fi

# Only the fake served requests: one measurement, one draft, nothing else.
assert_eq "$(fx_calls "${FAKE_DIR}" count_tokens)" "1" "stage2: one count_tokens call"
assert_eq "$(fx_calls "${FAKE_DIR}" messages)" "1" "stage2: one messages call"
ANALYZE_ERR="$(cat "${TMPROOT}/analyze.err" 2>/dev/null || echo "")"
assert_not_contains "${ANALYZE_ERR}" "Could not resolve host" "stage2: no DNS attempt"

# ---------------------------------------------------------------------------
# Stage 3: run autoheal-digest against the proposals file.
# ---------------------------------------------------------------------------

env \
    CCGM_AUTOHEAL_LEDGER="${AUTOHEAL_DIR}/proposals.jsonl" \
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
    assert_contains "${DIGEST_BODY}" "add a rule to code-quality.md" "stage3: proposal title rendered"
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
    CCGM_AUTOHEAL_LEDGER="${AUTOHEAL_DIR}/proposals.jsonl" \
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
    assert_contains "${POST_BODY}" "add a rule to code-quality.md" "stage4: POST body carries proposal title"

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

# Cost log exists from the analyze stage (one billed call).
COST_LOG="${AUTOHEAL_DIR}/cost.log"
assert_file_exists "${COST_LOG}" "stage5: cost log written"

# last-analyzed records the day the run finished.
LAST_FILE="${AUTOHEAL_DIR}/last-analyzed"
assert_file_exists "${LAST_FILE}" "stage5: last-analyzed written"
if [ -f "${LAST_FILE}" ]; then
    LAST_VAL="$(cat "${LAST_FILE}" 2>/dev/null || echo "")"
    assert_eq "${LAST_VAL}" "${TODAY}" "stage5: last-analyzed == today"
fi

# No real API or Resend call ever reached the public internet. The
# email step exclusively hit 127.0.0.1; the analyzer exclusively talked
# to the fake curl. The email error log file may be touched by `2>>` even
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
