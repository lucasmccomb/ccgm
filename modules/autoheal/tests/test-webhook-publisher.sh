#!/usr/bin/env bash
# test-webhook-publisher.sh
#
# Verifies bin/autoheal-publish.sh (plan.md §3.10, §5 Epic 12).
#
# Properties exercised:
#   1. webhook_url null → no HTTP requests; stderr says "webhook disabled"
#   2. webhook_url set → POSTs proposals/events to ${url}/v1/ingest with
#      Authorization: Bearer ${webhook_token}; envelope shape correct
#      (kind, ts, session_id, machine_id, data)
#   3. 500 response → cursor NOT advanced; publish log written; exit 0
#   4. 2xx after retry → cursor advances; idempotent re-run produces no
#      additional POSTs
#
# Local mock server only (modules/autoheal/tests/fixtures/webhook-server-mock.py).
# No real network.
#
# Run: bash modules/autoheal/tests/test-webhook-publisher.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PUBLISH_SCRIPT="${MODULE_ROOT}/bin/autoheal-publish.sh"
MOCK_SERVER="${MODULE_ROOT}/tests/fixtures/webhook-server-mock.py"

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
            echo "  actual (first 400): $(printf '%s' "${haystack}" | head -c 400)"
            ;;
    esac
}

assert_file_exists() {
    if [ -f "$1" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $2"
        echo "  expected file: $1"
    fi
}

assert_file_absent() {
    if [ ! -e "$1" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $2"
        echo "  unexpected path: $1"
    fi
}

if [ ! -f "${PUBLISH_SCRIPT}" ]; then
    echo "FATAL: publish script missing at ${PUBLISH_SCRIPT}"
    exit 1
fi
if [ ! -f "${MOCK_SERVER}" ]; then
    echo "FATAL: mock server missing at ${MOCK_SERVER}"
    exit 1
fi
for tool in jq python3 curl; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "FATAL: ${tool} required on PATH"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Mock server lifecycle
# ---------------------------------------------------------------------------

TMPROOT="$(mktemp -d -t autoheal-publish.XXXXXX)"
MOCK_PIDFILE="${TMPROOT}/mock.pid"
MOCK_PORTFILE="${TMPROOT}/mock.port"

cleanup() {
    for pf in "${MOCK_PIDFILE}"; do
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

start_mock() {
    rm -f "${MOCK_PIDFILE}" "${MOCK_PORTFILE}"
    python3 "${MOCK_SERVER}" \
        --port 0 \
        --pidfile "${MOCK_PIDFILE}" \
        --port-file "${MOCK_PORTFILE}" \
        "$@" \
        >/dev/null 2>&1 &
    local i=0
    while [ ${i} -lt 60 ]; do
        if [ -s "${MOCK_PORTFILE}" ]; then
            return 0
        fi
        sleep 0.05
        i=$((i + 1))
    done
    echo "FATAL: mock server did not write port file"
    return 1
}

stop_mock() {
    if [ -f "${MOCK_PIDFILE}" ]; then
        kill "$(cat "${MOCK_PIDFILE}")" 2>/dev/null || true
        rm -f "${MOCK_PIDFILE}" "${MOCK_PORTFILE}"
    fi
}

reset_mock() {
    curl -sS -X POST "http://127.0.0.1:${MOCK_PORT}/reset" >/dev/null
}

mock_requests() {
    curl -sS "http://127.0.0.1:${MOCK_PORT}/requests"
}

# ---------------------------------------------------------------------------
# Fixture: today's proposals + events. Two of each.
# ---------------------------------------------------------------------------

TODAY="2026-05-18"
AUTOHEAL_DIR="${TMPROOT}/autoheal"
mkdir -p "${AUTOHEAL_DIR}/proposals" \
         "${AUTOHEAL_DIR}/events" \
         "${AUTOHEAL_DIR}/digests" \
         "${AUTOHEAL_DIR}/published" \
         "${TMPROOT}/logs"

PROPOSAL_FILE="${AUTOHEAL_DIR}/proposals/${TODAY}.jsonl"
EVENT_FILE="${AUTOHEAL_DIR}/events/${TODAY}.jsonl"

jq -nc \
    '{id:"prop_001",kind:"settings_allow_add",title:"Allow t1",rationale:"r1",
      confidence:7,breadth_score:2,occurrence_count:3,session_ids:["s1","s2"],
      proposed_diff_target:"modules/settings/settings.partial.json",
      proposed_diff:"+ allow",fingerprint:"sha256-a",originating_clone:"test",
      generated_at:"2026-05-18T07:00:00Z"}' > "${PROPOSAL_FILE}"
jq -nc \
    '{id:"prop_002",kind:"settings_allow_add",title:"Allow t2",rationale:"r2",
      confidence:8,breadth_score:1,occurrence_count:4,session_ids:["s3"],
      proposed_diff_target:"modules/settings/settings.partial.json",
      proposed_diff:"+ allow2",fingerprint:"sha256-b",originating_clone:"test",
      generated_at:"2026-05-18T07:30:00Z"}' >> "${PROPOSAL_FILE}"

jq -nc \
    '{id:"evt_001",kind:"tool_use",timestamp:"2026-05-18T08:00:00Z",
      session_id:"s1",tool_name:"Bash",redacted_command:"git status",cwd:"/tmp"}' > "${EVENT_FILE}"
jq -nc \
    '{id:"evt_002",kind:"tool_failure",timestamp:"2026-05-18T08:05:00Z",
      session_id:"s1",tool_name:"Bash",redacted_command:"git push",cwd:"/tmp"}' >> "${EVENT_FILE}"

# Config with a fixed token so we can assert the Authorization header.
TOKEN="test-token-deadbeef"
CONFIG_FILE="${AUTOHEAL_DIR}/config.json"
make_config() {
    local url="$1"
    if [ -z "${url}" ] || [ "${url}" = "null" ]; then
        jq -n --arg token "${TOKEN}" \
            '{webhook_url:null, webhook_token:$token,
              webhook_kinds:["proposal","event","digest"], webhook_max_per_run:100}' \
            > "${CONFIG_FILE}"
    else
        jq -n --arg token "${TOKEN}" --arg url "${url}" \
            '{webhook_url:$url, webhook_token:$token,
              webhook_kinds:["proposal","event","digest"], webhook_max_per_run:100}' \
            > "${CONFIG_FILE}"
    fi
}

run_publish() {
    set +e
    CCGM_AUTOHEAL_DIR="${AUTOHEAL_DIR}" \
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_LOGS_DIR="${TMPROOT}/logs" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_MACHINE_ID="test-host-001" \
        bash "${PUBLISH_SCRIPT}" >"${TMPROOT}/out" 2>"${TMPROOT}/err"
    local rc=$?
    set -e
    echo "${rc}"
}

# ===========================================================================
# Test 1: webhook_url null → no requests, stderr message, exit 0.
# ===========================================================================

make_config ""
rc=$(run_publish)
assert_eq "${rc}" "0" "test1: rc=0 when webhook_url is null"

stderr1="$(cat "${TMPROOT}/err")"
assert_contains "${stderr1}" "webhook disabled" "test1: stderr says 'webhook disabled'"

# Cursor must not exist.
assert_file_absent "${AUTOHEAL_DIR}/published/${TODAY}.last" "test1: no cursor created"

# Publish log must not exist (we never tried to POST).
assert_file_absent "${TMPROOT}/logs/autoheal-publish-${TODAY}.log" "test1: no publish log when disabled"

# ===========================================================================
# Test 2: webhook_url set → POSTs all records; cursor advances.
# ===========================================================================

start_mock || exit 1
MOCK_PORT="$(cat "${MOCK_PORTFILE}")"
MOCK_BASE_URL="http://127.0.0.1:${MOCK_PORT}"
reset_mock

make_config "${MOCK_BASE_URL}"
rc=$(run_publish)
assert_eq "${rc}" "0" "test2: rc=0 when webhook enabled and mock returns 200"

REQS="$(mock_requests)"
N="$(printf '%s' "${REQS}" | jq '.requests | length')"
# 2 proposals + 2 events + 0 digest (no digest file written) = 4
assert_eq "${N}" "4" "test2: mock received 4 envelopes (2 proposals + 2 events)"

# First request: proposal_001 with correct envelope shape.
first_kind="$(printf '%s' "${REQS}" | jq -r '.requests[0].body_json.kind')"
assert_eq "${first_kind}" "proposal" "test2: first envelope kind=proposal"

first_machine="$(printf '%s' "${REQS}" | jq -r '.requests[0].body_json.machine_id')"
assert_eq "${first_machine}" "test-host-001" "test2: first envelope machine_id propagated"

first_session="$(printf '%s' "${REQS}" | jq -r '.requests[0].body_json.session_id')"
# proposals don't carry session_id at the top level; expect empty string
assert_eq "${first_session}" "" "test2: first envelope session_id (proposal has none)"

first_data_id="$(printf '%s' "${REQS}" | jq -r '.requests[0].body_json.data.id')"
assert_eq "${first_data_id}" "prop_001" "test2: first envelope data.id=prop_001"

first_auth="$(printf '%s' "${REQS}" | jq -r '.requests[0].authorization')"
assert_eq "${first_auth}" "Bearer ${TOKEN}" "test2: Authorization header sent"

first_ct="$(printf '%s' "${REQS}" | jq -r '.requests[0].content_type')"
assert_eq "${first_ct}" "application/json" "test2: Content-Type header sent"

# Event envelopes appear after the two proposals; verify ordering.
third_kind="$(printf '%s' "${REQS}" | jq -r '.requests[2].body_json.kind')"
assert_eq "${third_kind}" "event" "test2: third envelope kind=event"

third_data_id="$(printf '%s' "${REQS}" | jq -r '.requests[2].body_json.data.id')"
assert_eq "${third_data_id}" "evt_001" "test2: third envelope data.id=evt_001"

third_session="$(printf '%s' "${REQS}" | jq -r '.requests[2].body_json.session_id')"
assert_eq "${third_session}" "s1" "test2: event envelope session_id propagated"

# Cursor file written; both kinds advanced.
CURSOR_FILE="${AUTOHEAL_DIR}/published/${TODAY}.last"
assert_file_exists "${CURSOR_FILE}" "test2: cursor file created"
cursor_proposal="$(awk '$1=="proposal" {print $2}' "${CURSOR_FILE}")"
cursor_event="$(awk '$1=="event" {print $2}' "${CURSOR_FILE}")"
assert_eq "${cursor_proposal}" "2" "test2: proposal cursor advanced to 2"
assert_eq "${cursor_event}" "2" "test2: event cursor advanced to 2"

# ===========================================================================
# Test 2b: idempotent re-run — no additional POSTs since cursor is caught up.
# ===========================================================================

reset_mock
rc=$(run_publish)
assert_eq "${rc}" "0" "test2b: rc=0 on idempotent re-run"

REQS_AFTER="$(mock_requests)"
N_AFTER="$(printf '%s' "${REQS_AFTER}" | jq '.requests | length')"
assert_eq "${N_AFTER}" "0" "test2b: idempotent rerun sends 0 envelopes"

stop_mock

# ===========================================================================
# Test 3: 500 response → cursor unchanged for the failing kind, err log
# written, exit 0 (no block).
# ===========================================================================

# Reset cursor file: simulate a fresh day where nothing has been published.
rm -f "${AUTOHEAL_DIR}/published/${TODAY}.last"

start_mock --fail-with 500 || exit 1
MOCK_PORT="$(cat "${MOCK_PORTFILE}")"
MOCK_BASE_URL="http://127.0.0.1:${MOCK_PORT}"
reset_mock

make_config "${MOCK_BASE_URL}"
rc=$(run_publish)
assert_eq "${rc}" "0" "test3: rc=0 even on 500 (failures non-fatal)"

# Mock recorded one request per kind: each kind stops on its own first
# failure (avoid DOSing a broken endpoint within a kind), but kinds are
# processed independently. proposals → 1 attempt (500, stop), then
# events → 1 attempt (500, stop). digest has no file → 0 attempts. = 2.
REQS="$(mock_requests)"
N="$(printf '%s' "${REQS}" | jq '.requests | length')"
assert_eq "${N}" "2" "test3: mock recorded 2 requests (one per kind, each stopped)"

# Cursor file should either be absent or contain proposal=0 / event=0.
if [ -f "${AUTOHEAL_DIR}/published/${TODAY}.last" ]; then
    cursor_proposal="$(awk 'BEGIN{n=0} $1=="proposal" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last")"
    cursor_event="$(awk 'BEGIN{n=0} $1=="event" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last")"
    assert_eq "${cursor_proposal:-0}" "0" "test3: proposal cursor stayed at 0"
    assert_eq "${cursor_event:-0}" "0" "test3: event cursor stayed at 0"
else
    PASS=$((PASS + 2))
fi

# Publish log written with 500 + url.
LOG_FILE="${TMPROOT}/logs/autoheal-publish-${TODAY}.log"
assert_file_exists "${LOG_FILE}" "test3: publish log written"
if [ -f "${LOG_FILE}" ]; then
    log_body="$(cat "${LOG_FILE}")"
    assert_contains "${log_body}" "500" "test3: log captures 500 status"
    assert_contains "${log_body}" "/v1/ingest" "test3: log captures ingest URL"
fi

stop_mock

# ===========================================================================
# Test 4: 2xx after retry → cursor advances on retry; second run is a no-op.
#
# Scenario:
#   - Attempt 1: mock returns 500 → proposal+event cursors stay at 0.
#   - Attempt 2: mock now returns 200 → cursors advance to 2,2.
#   - Attempt 3: idempotent → 0 POSTs.
#
# We model this by restarting the mock between attempts so attempt 1 has
# fail-with 500 and attempt 2 is a clean (always-200) mock.
# ===========================================================================

# Fresh cursor for the new scenario.
rm -f "${AUTOHEAL_DIR}/published/${TODAY}.last"
rm -f "${TMPROOT}/logs/autoheal-publish-${TODAY}.log"

start_mock --fail-with 500 || exit 1
MOCK_PORT="$(cat "${MOCK_PORTFILE}")"
MOCK_BASE_URL="http://127.0.0.1:${MOCK_PORT}"
reset_mock

make_config "${MOCK_BASE_URL}"

# Attempt 1: all POSTs fail (500), each kind stops on its first attempt.
rc=$(run_publish)
assert_eq "${rc}" "0" "test4: attempt 1 rc=0 (all 500)"

REQS="$(mock_requests)"
N1="$(printf '%s' "${REQS}" | jq '.requests | length')"
# Each kind stops on first failure: 1 proposal + 1 event = 2.
assert_eq "${N1}" "2" "test4: attempt 1 sent 2 requests (1 per kind, all failed)"

# Cursors: both should be 0 (or absent).
cursor_proposal_a="$(awk 'BEGIN{n=0} $1=="proposal" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last" 2>/dev/null || echo 0)"
cursor_event_a="$(awk 'BEGIN{n=0} $1=="event" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last" 2>/dev/null || echo 0)"
assert_eq "${cursor_proposal_a}" "0" "test4: proposal cursor unchanged after attempt 1 (failure)"
assert_eq "${cursor_event_a}" "0" "test4: event cursor unchanged after attempt 1 (failure)"

# Stop the failing mock and start a healthy one on a new port for the
# retry. We point the config at the new URL — this is the "operator
# fixed the receiver" simulation.
stop_mock
start_mock || exit 1
MOCK_PORT="$(cat "${MOCK_PORTFILE}")"
MOCK_BASE_URL="http://127.0.0.1:${MOCK_PORT}"
reset_mock
make_config "${MOCK_BASE_URL}"

# Attempt 2: mock now returns 200. Cursors should advance fully.
rc=$(run_publish)
assert_eq "${rc}" "0" "test4: attempt 2 rc=0 (healthy mock)"

REQS="$(mock_requests)"
N2="$(printf '%s' "${REQS}" | jq '.requests | length')"
# Attempt 2 sends 2 proposals + 2 events (all from cursor=0). Total = 4.
assert_eq "${N2}" "4" "test4: attempt 2 sent 4 records (catching up after failure)"

cursor_proposal_b="$(awk 'BEGIN{n=0} $1=="proposal" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last")"
cursor_event_b="$(awk 'BEGIN{n=0} $1=="event" {n=$2} END{print n+0}' "${AUTOHEAL_DIR}/published/${TODAY}.last")"
assert_eq "${cursor_proposal_b}" "2" "test4: proposal cursor advanced after retry"
assert_eq "${cursor_event_b}" "2" "test4: event cursor advanced after retry"

# Attempt 3: full no-op (everything published). reset mock req log only.
reset_mock
rc=$(run_publish)
assert_eq "${rc}" "0" "test4: attempt 3 rc=0"

REQS="$(mock_requests)"
N3="$(printf '%s' "${REQS}" | jq '.requests | length')"
assert_eq "${N3}" "0" "test4: attempt 3 sends 0 (caught up)"

stop_mock

echo ""
echo "test-webhook-publisher.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
