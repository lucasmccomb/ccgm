#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/permission-event-logger.py
#
# Since #1099 the logger writes event rows only for PermissionRequest.
# PostToolUse and PostToolUseFailure only bump counts/{date}.json (see
# test-failure-logging.sh for the counter and the failure rows).
#
# Covers:
#   - A PermissionRequest produces one permission_request row with the
#     redacted command, cwd, and a timestamp.
#   - PostToolUse and PostToolUseFailure write no event rows.
#   - A command with embedded secrets has REDACTED markers in the stored row.
#   - transcript_path is captured when present, null when absent or not a
#     string.
#   - Malformed stdin exits 0.
#
# Each test points CCGM_AUTOHEAL_DIR at a fresh temp dir so the real
# ~/.claude/autoheal is never touched.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/permission-event-logger.py"
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

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  unexpected substring present: ${needle}"
            echo "  actual: ${haystack}"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
}

# Private $HOME so the hook imports the in-repo hook_utils and we never
# touch the user's real ~/.claude.
TMP_HOME=$(mktemp -d -t autoheal_test.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"

export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"

run_hook() {
    # $1 = JSON stdin; emits nothing on stdout, must exit 0.
    local payload="$1"
    echo "${payload}" | python3 "${HOOK}"
    return $?
}

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

row_field() {  # $1 = key of the first row
    python3 -c "
import json
print(json.loads(open('$(events_file)').readline()).get('$1'))
"
}

# 1. A PermissionRequest appends one permission_request row.
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git push --force feat-x"},"cwd":"/tmp/repo"}'
assert_eq "$?" "0" "logger exits 0 on PermissionRequest"
assert_eq "$(wc -l < "$(events_file)" | tr -d ' ')" "1" "PermissionRequest writes 1 line"
assert_eq "$(row_field kind)" "permission_request" "kind is permission_request"
assert_eq "$(row_field redacted_command)" "git push --force feat-x" "redacted_command preserved benign value"
assert_eq "$(row_field cwd)" "/tmp/repo" "cwd captured"
assert_eq "$(python3 -c "
import json, datetime
ts = json.loads(open('$(events_file)').readline())['timestamp']
datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
print('ok')
" 2>&1)" "ok" "timestamp parses as ISO 8601"

# 2. PostToolUse and PostToolUseFailure write no event rows.
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"/tmp/repo"}'
run_hook '{"hook_event_name":"PostToolUseFailure","session_id":"s1","tool_name":"Bash","tool_input":{"command":"false"},"error":"Exit code 1","is_interrupt":false,"cwd":"/tmp/repo"}'
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: PostToolUse/PostToolUseFailure must not write event rows"; }

# 3. Secret-bearing command is redacted in the stored row.
#
# Build the fake token at runtime so no literal token form ever appears
# in this file.
rm -rf "${CCGM_AUTOHEAL_DIR}"
PAYLOAD=$(python3 <<'PY'
import json
S = 'A' * 40
cmd = 'curl -H "Authorization: Bearer ' + S + '" https://api.example.com'
print(json.dumps({
    "hook_event_name": "PermissionRequest",
    "session_id": "s1",
    "tool_name": "Bash",
    "tool_input": {"command": cmd},
    "cwd": "/tmp/repo",
}))
PY
)
echo "${PAYLOAD}" | python3 "${HOOK}"
stored=$(row_field redacted_command)
assert_contains "${stored}" "[REDACTED:authorization_bearer]" "secret redacted in stored row"
assert_not_contains "${stored}" "AAAAAAAA" "raw secret bytes not present"

# 4. transcript_path: captured, null when omitted, null when not a string.
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp/repo","transcript_path":"/tmp/fake/transcript-abc.jsonl"}'
assert_eq "$(row_field transcript_path)" "/tmp/fake/transcript-abc.jsonl" "transcript_path captured"
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp/repo"}'
assert_eq "$(row_field transcript_path)" "None" "transcript_path null when omitted"
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp/repo","transcript_path":42}'
assert_eq "$(row_field transcript_path)" "None" "transcript_path null when not a string"

# 5. Malformed JSON stdin does not crash the hook (must still exit 0).
echo 'not even valid json {{{' | python3 "${HOOK}"
assert_eq "$?" "0" "malformed stdin exits 0"

# 6. Schema declares transcript_path as string|null and every permission_request
#    row key is declared (additionalProperties is false).
SCHEMA_PATH="${MODULE_ROOT}/lib/event-schema.json"
rm -rf "${CCGM_AUTOHEAL_DIR}"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp/repo","transcript_path":"/tmp/x.jsonl"}'
validate_ok=$(python3 <<PY
import json
schema = json.load(open("${SCHEMA_PATH}"))
props = schema["properties"]
assert set(props["transcript_path"]["type"]) == {"string", "null"}, props["transcript_path"]
row = json.loads(open("$(events_file)").readline())
extra = set(row) - set(props)
assert not extra, f"undeclared fields: {extra}"
assert not (set(schema["required"]) - set(row)), "required field missing"
print("ok")
PY
)
assert_eq "${validate_ok}" "ok" "permission_request row conforms to schema"

echo ""
echo "test-event-logging.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
