#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/realtime-security-scanner.py (Epic 10).
#
# Covers:
#   - Default OFF posture: with realtime_alerts_enabled=false (or missing
#     config), every fixture command exits 0, no event logged, and the
#     scanner never even reads the patterns file.
#   - Each of the 7 patterns fires when enabled.
#   - Guard semantics:
#       * force_push_main_without_bypass with ALLOW_MAIN_COMMIT=1 → no alert
#       * force_push_main_without_bypass with ALLOW_MAIN_COMMIT unset → alert
#       * drop_production_db only fires when command also contains a
#         production token (prod/production/live).
#   - The deny envelope on stderr contains <autoheal-security-alert> AND
#     names the pattern.
#   - Logged event has kind=realtime_security_alert and the matched
#     pattern name.
#   - Bash-only: an Edit tool call with a fixture token in tool_input
#     does NOT fire the scanner.
#
# Fake secret tokens are constructed at runtime via string concatenation
# so the literal forms never appear in this file. This dodges GitHub
# push protection without weakening test coverage — at execution time
# the assembled bytes are identical to the patterns the scanner
# targets.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/realtime-security-scanner.py"
PATTERNS_FILE="${MODULE_ROOT}/lib/realtime-security-patterns.json"
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

# Set up an isolated $HOME so the scanner never touches the real
# ~/.claude. The patterns file is provided via CCGM_REALTIME_PATTERNS
# so we exercise the in-repo source.
TMP_HOME=$(mktemp -d -t autoheal_realtime_test.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"

export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"
export CCGM_REALTIME_PATTERNS="${PATTERNS_FILE}"
mkdir -p "${CCGM_AUTOHEAL_DIR}"

# Helpers to flip the realtime_alerts_enabled flag in the autoheal config.
write_config_enabled() {
    cat > "${CCGM_AUTOHEAL_DIR}/config.json" <<'EOF'
{"realtime_alerts_enabled": true}
EOF
}

write_config_disabled() {
    cat > "${CCGM_AUTOHEAL_DIR}/config.json" <<'EOF'
{"realtime_alerts_enabled": false}
EOF
}

remove_config() {
    rm -f "${CCGM_AUTOHEAL_DIR}/config.json"
}

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

# run_hook reads a JSON payload from $1 and writes stderr to $2 (the
# caller passes a file to capture stderr separately from rc). Returns
# the hook exit code.
run_hook() {
    local payload="$1"
    local stderr_file="$2"
    echo "${payload}" | python3 "${HOOK}" 2> "${stderr_file}" > /dev/null
    return $?
}

# Build a Bash tool_input JSON for the scanner stdin.
bash_payload() {
    local command="$1"
    python3 - "$command" <<'PY'
import json, sys
print(json.dumps({
    "hook_event_name": "PostToolUse",
    "session_id": "s-test",
    "tool_name": "Bash",
    "tool_input": {"command": sys.argv[1]},
    "cwd": "/tmp/test-repo",
}))
PY
}

# Build a non-Bash payload to verify the scope filter.
edit_payload() {
    local content="$1"
    python3 - "$content" <<'PY'
import json, sys
print(json.dumps({
    "hook_event_name": "PostToolUse",
    "session_id": "s-test",
    "tool_name": "Edit",
    "tool_input": {"file_path": "/tmp/x", "new_string": sys.argv[1]},
    "cwd": "/tmp/test-repo",
}))
PY
}

# Reset events file before each scenario.
reset_events() {
    rm -f "$(events_file)"
}

# Construct fake security tokens at runtime via string concat.
# At execution time these are byte-identical to the patterns the
# scanner targets, but the literal forms never sit in this file.
TOKEN_BUILDER=$(cat <<'PY'
import sys
S36 = 'A' * 40            # >= 36 chars after prefix
GHP = 'ghp' + '_' + S36
AWS = 'AK' + 'IA' + 'ABCDEFGHIJKLMNOP'
ANT = 'sk' + '-ant-' + 'api03-' + S36
print(GHP)
print(AWS)
print(ANT)
PY
)
TOKENS=$(python3 -c "${TOKEN_BUILDER}")
GHP_TOKEN=$(echo "${TOKENS}" | sed -n 1p)
AWS_TOKEN=$(echo "${TOKENS}" | sed -n 2p)
ANT_TOKEN=$(echo "${TOKENS}" | sed -n 3p)

# Sanity: tokens are non-empty.
[ -n "${GHP_TOKEN}" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: GHP token builder"; }
[ -n "${AWS_TOKEN}" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: AWS token builder"; }
[ -n "${ANT_TOKEN}" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: ANT token builder"; }

# ----------------------------------------------------------------------
# 1. Default OFF: missing config → scanner exits 0 immediately.
# ----------------------------------------------------------------------
remove_config
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "echo ${GHP_TOKEN} >> hello.txt")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "default OFF (no config): exit 0 on a token-bearing command"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event logged when no config"; }
assert_not_contains "$(cat "${STDERR}")" "<autoheal-security-alert>" "no alert emitted when no config"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 2. Default OFF: realtime_alerts_enabled=false → scanner exits 0,
#    no event, no alert. Also exercises the "never reads patterns file"
#    posture (we don't have a direct probe for "patterns file untouched"
#    but the rc + no-event combination is sufficient — the gate is the
#    first thing main() does).
# ----------------------------------------------------------------------
write_config_disabled
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "rm -rf /")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "realtime_alerts_enabled=false: exit 0 on rm -rf /"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event logged when disabled"; }
assert_not_contains "$(cat "${STDERR}")" "<autoheal-security-alert>" "no alert when disabled"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 3. Bonus assertion: when disabled, scanner exits 0 even if patterns
#    file is missing (proves the gate is first).
# ----------------------------------------------------------------------
write_config_disabled
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "rm -rf /")
CCGM_REALTIME_PATTERNS_BACKUP="${CCGM_REALTIME_PATTERNS}"
export CCGM_REALTIME_PATTERNS="/nonexistent/path/never-here.json"
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "disabled + missing patterns: still exit 0 (gate is first)"
export CCGM_REALTIME_PATTERNS="${CCGM_REALTIME_PATTERNS_BACKUP}"
rm -f "${STDERR}"

# Switch to enabled for the rest of the tests.
write_config_enabled

# ----------------------------------------------------------------------
# 4. Pattern: github_pat_in_commit_or_echo
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "echo ${GHP_TOKEN} | git commit -F -")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "github_pat: exit 2 when enabled"
stderr_text=$(cat "${STDERR}")
assert_contains "${stderr_text}" "<autoheal-security-alert>" "github_pat: alert block in stderr"
assert_contains "${stderr_text}" "github_pat_in_commit_or_echo" "github_pat: pattern name in alert"
[ -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: github_pat: event file created"; }
event_kind=$(python3 -c "import json; print(json.loads(open('$(events_file)').readline())['kind'])")
assert_eq "${event_kind}" "realtime_security_alert" "github_pat: event kind"
event_pattern=$(python3 -c "import json; print(json.loads(open('$(events_file)').readline())['security_pattern_matched'])")
assert_eq "${event_pattern}" "github_pat_in_commit_or_echo" "github_pat: event pattern name"
# The event must not contain the raw token (redact_secrets strips it).
event_cmd=$(python3 -c "import json; print(json.loads(open('$(events_file)').readline())['redacted_command'])")
assert_contains "${event_cmd}" "[REDACTED:github_pat]" "github_pat: token redacted in stored event"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 5. Pattern: aws_key_in_command
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "export AWS_ACCESS_KEY_ID=${AWS_TOKEN}")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "aws_key: exit 2"
assert_contains "$(cat "${STDERR}")" "aws_key_in_command" "aws_key: pattern name in alert"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 6. Pattern: anthropic_key_in_command
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "curl -H \"x-api-key: ${ANT_TOKEN}\" https://api.anthropic.com")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "anthropic_key: exit 2"
assert_contains "$(cat "${STDERR}")" "anthropic_key_in_command" "anthropic_key: pattern name in alert"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 7. Pattern: force_push_main_without_bypass (guard ALLOW_MAIN_COMMIT_unset)
# 7a. ALLOW_MAIN_COMMIT unset → alert fires.
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
unset ALLOW_MAIN_COMMIT
PAYLOAD=$(bash_payload "git push --force origin main")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "force_push_main: exit 2 when ALLOW_MAIN_COMMIT unset"
assert_contains "$(cat "${STDERR}")" "force_push_main_without_bypass" "force_push_main: pattern name in alert"
rm -f "${STDERR}"

# 7b. ALLOW_MAIN_COMMIT=1 → no alert (user bypass honored).
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "git push --force origin main")
ALLOW_MAIN_COMMIT=1 run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "force_push_main: exit 0 when ALLOW_MAIN_COMMIT=1"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event when ALLOW_MAIN_COMMIT=1"; }
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 8. Pattern: rm_rf_absolute_root
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "rm -rf /")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "rm_rf_root: exit 2"
assert_contains "$(cat "${STDERR}")" "rm_rf_absolute_root" "rm_rf_root: pattern name in alert"
rm -f "${STDERR}"

# rm -rf with a RELATIVE path should not fire (regex anchors on
# "rm -rf /" — leading slash after the flag). Absolute paths under
# any subdirectory of / DO match by spec — the plan-verbatim regex
# treats every absolute path as in scope.
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "rm -rf node_modules")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "rm_rf with relative path: no alert"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 9. Pattern: sudo_destructive
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "sudo rm /etc/passwd")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "sudo_destructive: exit 2"
assert_contains "$(cat "${STDERR}")" "sudo_destructive" "sudo_destructive: pattern name in alert"
rm -f "${STDERR}"

# sudo with a non-destructive verb should not fire.
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "sudo apt update")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "sudo apt update: no alert"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 10. Pattern: drop_production_db (guard production_connection_string)
# 10a. DROP TABLE with no prod token in the command → no alert (guard suppresses).
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "psql -d devdb -c 'DROP TABLE users'")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "drop_production_db: no alert when no prod token (devdb)"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event for DROP without prod token"; }
rm -f "${STDERR}"

# 10b. DROP TABLE with prod token → alert fires.
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "psql -d production -c 'DROP TABLE users'")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "drop_production_db: exit 2 when production token present"
assert_contains "$(cat "${STDERR}")" "drop_production_db" "drop_production_db: pattern name in alert"
rm -f "${STDERR}"

# 10c. DROP DATABASE with 'prod' substring also fires.
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "psql -d myapp_prod -c 'DROP DATABASE archive'")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "2" "drop_production_db: exit 2 with 'prod' substring"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 11. Safe command does not fire any pattern.
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(bash_payload "git diff --staged")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "safe command (git diff): exit 0"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event for safe command"; }
assert_not_contains "$(cat "${STDERR}")" "<autoheal-security-alert>" "safe command: no alert"
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 12. Non-Bash tool calls are ignored even with a token in tool_input.
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
PAYLOAD=$(edit_payload "echo ${GHP_TOKEN}")
run_hook "${PAYLOAD}" "${STDERR}"
rc=$?
assert_eq "${rc}" "0" "Edit tool call with token: exit 0 (scope filter)"
[ ! -f "$(events_file)" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: no event for Edit tool call"; }
rm -f "${STDERR}"

# ----------------------------------------------------------------------
# 13. Malformed stdin: exit 0 (never block the host tool call).
# ----------------------------------------------------------------------
reset_events
STDERR=$(mktemp)
echo 'not valid json {{{' | python3 "${HOOK}" 2> "${STDERR}" > /dev/null
rc=$?
assert_eq "${rc}" "0" "malformed stdin: exit 0"
rm -f "${STDERR}"

echo ""
echo "test-realtime-security-scanner.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
