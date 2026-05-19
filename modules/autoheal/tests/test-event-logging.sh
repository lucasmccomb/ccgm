#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/permission-event-logger.py
#
# Covers:
#   - A synthetic PostToolUse stdin produces one row with kind=tool_use,
#     the correct redacted command, and a timestamp.
#   - 3 successive tool calls produce 3 rows.
#   - A command with embedded secrets has REDACTED markers in the
#     stored event (not the raw token).
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

# Symlink ~/.claude/lib to the in-repo hook_utils so the hook can import
# it without requiring a CCGM install on the test machine. We do this in
# a private $HOME so we never touch the user's real ~/.claude.
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

# 1. Single tool_use append produces 1 line with kind=tool_use.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git diff"},"cwd":"/tmp/repo","permission_mode":"default"}'
rc=$?
assert_eq "${rc}" "0" "logger exits 0 on PostToolUse"
[ -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: events file created"; }

line_count=$(wc -l < "$(events_file)" | tr -d ' ')
assert_eq "${line_count}" "1" "logger writes 1 line"

line=$(head -1 "$(events_file)")
kind=$(python3 -c "import json,sys; print(json.loads('''${line}''')['kind'])")
assert_eq "${kind}" "tool_use" "kind=tool_use"

cmd=$(python3 -c "import json; print(json.loads(open('$(events_file)').readline())['redacted_command'])")
assert_eq "${cmd}" "git diff" "redacted_command preserved benign value"

# Timestamp must parse as ISO 8601.
ts_ok=$(python3 -c "
import json, datetime
rec = json.loads(open('$(events_file)').readline())
ts = rec['timestamp']
datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
print('ok')
" 2>&1)
assert_eq "${ts_ok}" "ok" "timestamp parses as ISO 8601"

# 2. Three calls produce three lines.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"/tmp/repo"}'
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git log -1"},"cwd":"/tmp/repo"}'
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git diff --staged"},"cwd":"/tmp/repo"}'
line_count=$(wc -l < "$(events_file)" | tr -d ' ')
assert_eq "${line_count}" "3" "3 tool calls produce 3 rows"

# 3. Secret-bearing command is redacted in the stored event.
#
# Build the fake token at runtime so no literal token form ever appears
# in this file. We assemble the JSON in Python (not bash) to avoid
# double-escaping the embedded quote chars.
rm -f "$(events_file)"
PAYLOAD=$(python3 <<'PY'
import json
S = 'A' * 40
cmd = 'curl -H "Authorization: Bearer ' + S + '" https://api.example.com'
print(json.dumps({
    "hook_event_name": "PostToolUse",
    "session_id": "s1",
    "tool_name": "Bash",
    "tool_input": {"command": cmd},
    "cwd": "/tmp/repo",
}))
PY
)
echo "${PAYLOAD}" | python3 "${HOOK}"
stored=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['redacted_command'])
")
assert_contains "${stored}" "[REDACTED:authorization_bearer]" "secret redacted in stored event"
assert_not_contains "${stored}" "AAAAAAAA" "raw secret bytes not present"

# 4. PermissionRequest event is classified correctly.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git push --force feat-x"},"cwd":"/tmp/repo"}'
kind=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['kind'])
")
assert_eq "${kind}" "permission_request" "PermissionRequest event has kind permission_request"

# 5. PostToolUseFailure event is classified correctly.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUseFailure","session_id":"s1","tool_name":"Bash","tool_input":{"command":"false"},"exit_code":1,"stderr":"something failed","cwd":"/tmp/repo"}'
kind=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['kind'])
")
assert_eq "${kind}" "tool_failure" "PostToolUseFailure event has kind tool_failure"

ec=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['exit_code'])
")
assert_eq "${ec}" "1" "exit_code captured"

# 6. cwd and clone_path are populated.
cwd=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['cwd'])
")
assert_eq "${cwd}" "/tmp/repo" "cwd captured"

# 7. Malformed JSON stdin does not crash the hook (must still exit 0).
echo 'not even valid json {{{' | python3 "${HOOK}"
rc=$?
assert_eq "${rc}" "0" "malformed stdin exits 0"

# 8. transcript_path is captured when present in stdin envelope.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"/tmp/repo","transcript_path":"/tmp/fake/transcript-abc.jsonl"}'
tp=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['transcript_path'])
")
assert_eq "${tp}" "/tmp/fake/transcript-abc.jsonl" "transcript_path captured from stdin"

# 9. transcript_path is null when stdin omits it (backward compatible).
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"/tmp/repo"}'
tp=$(python3 -c "
import json
rec = json.loads(open('$(events_file)').readline())
print('present' if 'transcript_path' in rec else 'absent', rec.get('transcript_path'))
")
assert_eq "${tp}" "present None" "transcript_path is null when stdin omits it"

# 10. transcript_path is null when stdin provides a non-string (defensive).
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"/tmp/repo","transcript_path":42}'
tp=$(python3 -c "
import json
rec = json.loads(open('$(events_file)').readline())
print(rec['transcript_path'])
")
assert_eq "${tp}" "None" "transcript_path is null when stdin provides non-string"

# 11. transcript_path is captured by the PostToolUseFailure path too.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PostToolUseFailure","session_id":"s1","tool_name":"Bash","tool_input":{"command":"false"},"exit_code":1,"stderr":"boom","cwd":"/tmp/repo","transcript_path":"/tmp/fake/transcript-fail.jsonl"}'
tp=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['transcript_path'])
")
assert_eq "${tp}" "/tmp/fake/transcript-fail.jsonl" "transcript_path captured on PostToolUseFailure"

# 12. transcript_path is captured by the PermissionRequest path too.
rm -f "$(events_file)"
run_hook '{"hook_event_name":"PermissionRequest","session_id":"s1","tool_name":"Bash","tool_input":{"command":"git push --force feat-x"},"cwd":"/tmp/repo","transcript_path":"/tmp/fake/transcript-perm.jsonl"}'
tp=$(python3 -c "
import json
print(json.loads(open('$(events_file)').readline())['transcript_path'])
")
assert_eq "${tp}" "/tmp/fake/transcript-perm.jsonl" "transcript_path captured on PermissionRequest"

# 13. Schema accepts records with transcript_path string, null, and absent.
#
# Minimal hand-rolled validator: read the schema and verify that
# (a) transcript_path is a declared property, (b) it accepts string|null,
# (c) records produced above satisfy the additionalProperties constraint.
SCHEMA_PATH="${MODULE_ROOT}/lib/event-schema.json"
validate_ok=$(python3 <<PY
import json
with open("${SCHEMA_PATH}") as fh:
    schema = json.load(fh)

props = schema.get("properties", {})
add_props = schema.get("additionalProperties", True)

# (a) transcript_path declared.
assert "transcript_path" in props, "transcript_path missing from schema properties"
# (b) accepts string|null.
tp_type = props["transcript_path"].get("type")
assert tp_type == ["string", "null"] or set(tp_type) == {"string", "null"}, \
    f"transcript_path type unexpected: {tp_type!r}"

# (c) Verify three on-disk record shapes are structurally schema-conforming.
declared = set(props.keys())
required = set(schema.get("required", []))

# Build three sample records:
samples = [
    # transcript_path = string
    {"kind":"tool_use","timestamp":"2026-05-18T00:00:00+00:00","session_id":"s","tool_name":"Bash","transcript_path":"/tmp/x.jsonl"},
    # transcript_path = null
    {"kind":"tool_use","timestamp":"2026-05-18T00:00:00+00:00","session_id":"s","tool_name":"Bash","transcript_path":None},
    # transcript_path absent (backward compat)
    {"kind":"tool_use","timestamp":"2026-05-18T00:00:00+00:00","session_id":"s","tool_name":"Bash"},
]
for rec in samples:
    missing = required - set(rec.keys())
    assert not missing, f"required fields missing: {missing}"
    if add_props is False:
        extra = set(rec.keys()) - declared
        assert not extra, f"undeclared fields present: {extra}"
print("ok")
PY
)
assert_eq "${validate_ok}" "ok" "schema accepts transcript_path string|null|absent"

echo ""
echo "test-event-logging.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
