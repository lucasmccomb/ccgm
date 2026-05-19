#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/permission-request-suppress.py
#
# Covers:
#   - Default-mode PermissionRequest does NOT auto-allow (suppression
#     only fires in bypass mode).
#   - Bypass mode with 3 prior allow approvals across 2 sessions DOES
#     auto-allow (emits an 'allow' decision and exits 0).
#   - Bypass mode with only 2 prior approvals (below the threshold)
#     does NOT auto-allow.
#   - Bypass mode where the (tool, command) signature is snoozed does
#     NOT auto-allow.
#
# All event history is written into a fresh CCGM_AUTOHEAL_DIR temp dir
# so the user's real ~/.claude/autoheal is never touched.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/permission-request-suppress.py"
HOOKS_MODULE="$(cd "${MODULE_ROOT}/../hooks" && pwd)"
HOOK_LIB="${HOOKS_MODULE}/lib"

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

TMP_HOME=$(mktemp -d -t autoheal_suppress.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"

export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"
mkdir -p "${CCGM_AUTOHEAL_DIR}/events"

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

# Seed `n` approvals across `k` sessions for a given Bash command verb.
seed_history() {
    local cmd="$1"
    local n="$2"
    local k="$3"
    python3 <<PY
import json, os, datetime
path = '$(events_file)'
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a') as fh:
    for i in range($n):
        session = f'sess-{i % $k}'
        rec = {
            'kind': 'permission_request',
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'session_id': session,
            'tool_name': 'Bash',
            'redacted_command': '$cmd',
            'permission_decision': 'allow',
            'exit_code': None,
            'stderr_excerpt': None,
            'cwd': '/tmp/repo',
            'clone_path': '/tmp/repo',
        }
        fh.write(json.dumps(rec) + '\n')
PY
}

# 1. Default-mode PermissionRequest: no auto-allow even with rich history.
seed_history "git diff" 5 3
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-default","tool_name":"Bash","tool_input":{"command":"git diff foo"},"permission_mode":"default","cwd":"/tmp/repo"}' | python3 "${HOOK}")
rc=$?
assert_eq "${rc}" "0" "default mode exits 0"
assert_eq "${out}" "" "default mode emits no decision (empty stdout)"

# 2. Bypass mode + 3 approvals across 2 sessions: auto-allow.
rm -f "$(events_file)"
seed_history "git diff" 3 2
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-bypass","tool_name":"Bash","tool_input":{"command":"git diff bar"},"permission_mode":"bypassPermissions","cwd":"/tmp/repo"}' | python3 "${HOOK}")
rc=$?
assert_eq "${rc}" "0" "bypass with history exits 0"
decision=$(echo "${out}" | python3 -c "import json, sys; print(json.load(sys.stdin)['hookSpecificOutput']['permissionDecision'])")
assert_eq "${decision}" "allow" "auto-allow decision emitted"
reason=$(echo "${out}" | python3 -c "import json, sys; print(json.load(sys.stdin)['hookSpecificOutput']['permissionDecisionReason'])")
assert_contains "${reason}" "autoheal" "reason mentions autoheal"

# 3. Bypass mode + only 2 prior approvals: no auto-allow.
rm -f "$(events_file)"
seed_history "git diff" 2 2
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-bypass","tool_name":"Bash","tool_input":{"command":"git diff baz"},"permission_mode":"bypassPermissions","cwd":"/tmp/repo"}' | python3 "${HOOK}")
rc=$?
assert_eq "${rc}" "0" "bypass with <3 approvals exits 0"
assert_eq "${out}" "" "bypass with <3 approvals emits no decision"

# 4. Bypass + 3 approvals but all in ONE session: still no auto-allow.
rm -f "$(events_file)"
seed_history "git diff" 3 1
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-bypass","tool_name":"Bash","tool_input":{"command":"git diff qux"},"permission_mode":"bypassPermissions","cwd":"/tmp/repo"}' | python3 "${HOOK}")
rc=$?
assert_eq "${rc}" "0" "bypass with single-session history exits 0"
assert_eq "${out}" "" "bypass with single-session history emits no decision"

# 5. Bypass + history + signature snoozed: no auto-allow.
rm -f "$(events_file)"
seed_history "git diff" 3 2
# Snoozed until +1 hour from now.
python3 <<'PY'
import json, datetime, os
sig = 'Bash::git diff'
data = {sig: {'snoozed_until': (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()}}
os.makedirs(os.environ['CCGM_AUTOHEAL_DIR'], exist_ok=True)
with open(os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'snoozed.json'), 'w') as fh:
    json.dump(data, fh)
PY
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-bypass","tool_name":"Bash","tool_input":{"command":"git diff thing"},"permission_mode":"bypassPermissions","cwd":"/tmp/repo"}' | python3 "${HOOK}")
rc=$?
assert_eq "${rc}" "0" "snoozed bypass exits 0"
assert_eq "${out}" "" "snoozed bypass emits no decision"

# 6. Bypass + history + signature with EXPIRED snooze: auto-allow.
rm -f "${CCGM_AUTOHEAL_DIR}/snoozed.json"
python3 <<'PY'
import json, datetime, os
sig = 'Bash::git diff'
data = {sig: {'snoozed_until': (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()}}
with open(os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'snoozed.json'), 'w') as fh:
    json.dump(data, fh)
PY
out=$(echo '{"hook_event_name":"PermissionRequest","session_id":"s-bypass","tool_name":"Bash","tool_input":{"command":"git diff later"},"permission_mode":"bypassPermissions","cwd":"/tmp/repo"}' | python3 "${HOOK}")
decision=$(echo "${out}" | python3 -c "import json, sys; print(json.load(sys.stdin)['hookSpecificOutput']['permissionDecision'])")
assert_eq "${decision}" "allow" "expired snooze does not block auto-allow"

# 7. Malformed stdin exits 0 cleanly.
echo 'not json {{{' | python3 "${HOOK}"
rc=$?
assert_eq "${rc}" "0" "malformed stdin exits 0"

echo ""
echo "test-permission-suppress.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
