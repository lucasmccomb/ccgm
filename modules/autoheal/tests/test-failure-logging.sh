#!/usr/bin/env bash
# Test suite for the autoheal capture path (#1099 Phase 1.1 and 1.2):
#   hooks/failure-logger.py          (sole writer of failure rows)
#   hooks/permission-event-logger.py (permission rows + daily counter)
#
# Input shape under test is what Claude Code 2.1.289 sends on
# PostToolUseFailure: {hook_event_name, tool_name, tool_input, tool_use_id,
# error, is_interrupt, duration_ms} plus the common envelope.
#
# Covers:
#   - One failure produces exactly one row when both hooks run, as the
#     settings registration runs them.
#   - The row carries redacted error text, error_class, cmd_head, exit_code.
#   - is_interrupt produces a user_interrupt row.
#   - Routine PostToolUse writes no event rows, only counts/{date}.json.
#   - Every key the loggers write is declared in lib/event-schema.json.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FAIL_HOOK="${MODULE_ROOT}/hooks/failure-logger.py"
PERM_HOOK="${MODULE_ROOT}/hooks/permission-event-logger.py"
HOOK_LIB="$(cd "${MODULE_ROOT}/../hooks" && pwd)/lib"

PASS=0
FAIL=0

assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}

TMP_HOME=$(mktemp -d -t autoheal_failure.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"
export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"
export CCGM_ERROR_CLASSES="${MODULE_ROOT}/lib/error_classes.json"

TODAY=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")
EVENTS="${CCGM_AUTOHEAL_DIR}/events/${TODAY}.jsonl"
COUNTS="${CCGM_AUTOHEAL_DIR}/counts/${TODAY}.json"

# Build a hook payload. Args: event tool command error is_interrupt(0|1)
payload() {
    PEVENT="$1" PTOOL="$2" PCMD="$3" PERR="$4" PINT="$5" python3 -c "
import json, os
d = {'hook_event_name': os.environ['PEVENT'], 'session_id': 's1',
     'transcript_path': '/tmp/t.jsonl', 'cwd': '/tmp/repo',
     'tool_name': os.environ['PTOOL'], 'tool_use_id': 'toolu_1',
     'tool_input': {'command': os.environ['PCMD']} if os.environ['PTOOL'] == 'Bash' else {'file_path': '/tmp/x'}}
if os.environ['PEVENT'] == 'PostToolUseFailure':
    d['error'] = os.environ['PERR']
    d['is_interrupt'] = os.environ['PINT'] == '1'
    d['duration_ms'] = 12
print(json.dumps(d))
"
}

# Run a payload through both hooks, in settings order.
fire() {
    local p="$1"
    echo "${p}" | python3 "${PERM_HOOK}"
    echo "${p}" | python3 "${FAIL_HOOK}"
}

field() {  # $1 = row index (0-based), $2 = key
    python3 -c "
import json
rows = [json.loads(l) for l in open('${EVENTS}') if l.strip()]
print(rows[$1].get('$2'))
"
}

rows() { if [ -f "${EVENTS}" ]; then wc -l < "${EVENTS}" | tr -d ' '; else echo 0; fi; }

# 1. A zsh failure with error text: exactly one row, fully populated.
rm -rf "${CCGM_AUTOHEAL_DIR}"
fire "$(payload PostToolUseFailure Bash 'echo ==== done' $'Exit code 1\n(eval):1: == not found' 0)"
assert_eq "$(rows)" "1" "one failure -> exactly one row across both hooks"
assert_eq "$(field 0 kind)" "tool_failure" "kind is tool_failure"
assert_eq "$(field 0 error_class)" "zsh_not_found" "error_class set from error text"
assert_eq "$(field 0 cmd_head)" "echo" "cmd_head is the program"
assert_eq "$(field 0 exit_code)" "1" "exit_code parsed from 'Exit code N'"
case "$(field 0 error)" in *"== not found"*) PASS=$((PASS + 1));; *) FAIL=$((FAIL + 1)); echo "FAIL: error text recorded";; esac

# 2. Secrets in the error are redacted; long errors are cut to 400 chars.
rm -rf "${CCGM_AUTOHEAL_DIR}"
SECRET_ERR=$(python3 -c "print('Exit code 1\ncurl: bad header Authorization: Bearer ' + 'A'*40 + ' ' + 'x'*600)")
fire "$(payload PostToolUseFailure Bash 'curl https://example.com' "${SECRET_ERR}" 0)"
err=$(field 0 error)
case "${err}" in *AAAAAAAA*) FAIL=$((FAIL + 1)); echo "FAIL: raw secret stored in error";; *) PASS=$((PASS + 1));; esac
case "${err}" in *"[REDACTED:"*) PASS=$((PASS + 1));; *) FAIL=$((FAIL + 1)); echo "FAIL: redaction marker missing";; esac
assert_eq "$(python3 -c "
import json
r = json.loads(open('${EVENTS}').readline())
print(len(r['error']) <= 400)
")" "True" "error capped at 400 chars"

# 3. Classifier cases.
classify() {  # $1 = error text, $2 = command
    rm -rf "${CCGM_AUTOHEAL_DIR}"
    fire "$(payload PostToolUseFailure Bash "$2" "$1" 0)"
    field 0 error_class
}
assert_eq "$(classify $'Exit code 1\nzsh: no matches found: --include=*.sh' 'grep -r x --include=*.sh .')" "zsh_no_matches" "zsh no matches"
assert_eq "$(classify $'Exit code 128\nfatal: pathspec '"'"'a/b'"'"' did not match any files' 'git add a/b')" "pathspec_no_match" "pathspec"
assert_eq "$(classify $'Exit code 127\nzsh: command not found: foo' 'foo')" "command_not_found" "command not found"
assert_eq "$(classify $'Exit code 1\ncat: x: No such file or directory' 'cat x')" "no_such_file" "no such file"
assert_eq "$(classify $'Exit code 1\nPermission denied' 'touch /x')" "permission_denied" "permission denied"
assert_eq "$(classify $'Exit code 1\nBRANCH GUARD: blocked git commit' 'git commit -m x')" "hook_denial_branch_guard" "branch guard denial"
assert_eq "$(classify $'Exit code 2\nsomething odd' 'make')" "exit_code" "bare exit code"
assert_eq "$(classify 'weird failure' 'make')" "other" "unmatched error -> other"

# 4. cmd_head.
head_of() {
    rm -rf "${CCGM_AUTOHEAL_DIR}"
    fire "$(payload PostToolUseFailure Bash "$1" 'Exit code 1' 0)"
    field 0 cmd_head
}
assert_eq "$(head_of 'git add -A')" "git add" "two-word head for git"
assert_eq "$(head_of 'FOO=1 cd /x && wrangler d1 execute db')" "wrangler d1" "skips env assignment and cd"
assert_eq "$(head_of 'cat /x | grep y')" "cat" "first program in a pipeline"
assert_eq "$(head_of 'cp -iv a b')" "cp" "flag is not a subcommand"
assert_eq "$(head_of 'git -C /x log --oneline')" "git log" "git -C <path> skipped"
assert_eq "$(head_of 'git -c a=b commit -m x')" "git commit" "git -c k=v skipped"
assert_eq "$(head_of 'git --no-pager --git-dir=/x/.git diff')" "git diff" "git bare and = global flags skipped"
assert_eq "$(head_of 'git --git-dir /x/.git --work-tree /x status')" "git status" "git global flags with separate arg skipped"
assert_eq "$(head_of 'gh -R o/r pr view 1')" "gh pr" "gh -R <repo> before subcommand skipped"
assert_eq "$(head_of 'gh pr view 1 -R o/r')" "gh pr" "gh -R after subcommand ignored"
assert_eq "$(head_of 'gh --repo o/r issue list')" "gh issue" "gh --repo <repo> skipped"
assert_eq "$(head_of 'git -C /x')" "git" "git with only global options"
rm -rf "${CCGM_AUTOHEAL_DIR}"
fire "$(payload PostToolUseFailure Read '' 'File not found' 0)"
assert_eq "$(field 0 cmd_head)" "None" "non-Bash tool has null cmd_head"

# 5. is_interrupt -> user_interrupt, still one row.
rm -rf "${CCGM_AUTOHEAL_DIR}"
fire "$(payload PostToolUseFailure Bash 'sleep 100' '[Request interrupted by user for tool use]' 1)"
assert_eq "$(rows)" "1" "interrupt -> exactly one row"
assert_eq "$(field 0 kind)" "user_interrupt" "interrupt kind"

# 6. Routine PostToolUse: no event rows, counter only. 200 calls, 3 failures.
rm -rf "${CCGM_AUTOHEAL_DIR}"
for i in $(seq 1 120); do fire "$(payload PostToolUse Bash "ls" '' 0)"; done
for i in $(seq 1 77);  do fire "$(payload PostToolUse Read '' '' 0)"; done
for i in 1 2 3; do fire "$(payload PostToolUseFailure Bash 'echo ==' 'Exit code 1' 0)"; done
assert_eq "$(rows)" "3" "197 routine calls write 0 rows; only the 3 failures are logged"
assert_eq "$(python3 -c "
import json
c = json.load(open('${COUNTS}'))
print(c.get('Bash'), c.get('Read'), sum(c.values()))
")" "123 77 200" "counts/{date}.json totals match tool calls (successes + failures)"

rm -rf "${CCGM_AUTOHEAL_DIR}"
for i in $(seq 1 300); do fire "$(payload PostToolUse Bash 'ls' '' 0)"; done
assert_eq "$(rows)" "0" "300 routine calls write 0 event rows"
assert_eq "$(python3 -c "import json; print(json.load(open('${COUNTS}'))['Bash'])")" "300" "300 routine calls counted"

# 7. PermissionRequest still logs a permission_request row and is not a call.
rm -rf "${CCGM_AUTOHEAL_DIR}"
fire "$(payload PermissionRequest Bash 'ls' '' 0)"
assert_eq "$(field 0 kind)" "permission_request" "permission_request row still written"
if [ ! -f "${COUNTS}" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: permission request must not bump the call counter"; fi

# 8. Concurrent counter updates do not lose increments.
rm -rf "${CCGM_AUTOHEAL_DIR}"
P=$(payload PostToolUse Bash ls '' 0)
for i in $(seq 1 40); do echo "${P}" | python3 "${PERM_HOOK}" & done
wait
assert_eq "$(python3 -c "import json; print(json.load(open('${COUNTS}'))['Bash'])")" "40" "40 concurrent calls -> counter 40"

# 9. Hooks stay exit 0 on malformed input.
echo 'not json {{{' | python3 "${FAIL_HOOK}"; assert_eq "$?" "0" "failure-logger exits 0 on malformed stdin"
echo 'not json {{{' | python3 "${PERM_HOOK}"; assert_eq "$?" "0" "permission-event-logger exits 0 on malformed stdin"

# 10. Every key written is declared in the schema; kinds valid.
rm -rf "${CCGM_AUTOHEAL_DIR}"
fire "$(payload PostToolUseFailure Bash 'ls x' $'Exit code 128\nfatal: pathspec x did not match' 0)"
fire "$(payload PostToolUseFailure Bash 'sleep 9' 'interrupted' 1)"
fire "$(payload PermissionRequest Bash 'ls' '' 0)"
assert_eq "$(python3 -c "
import json
schema = json.load(open('${MODULE_ROOT}/lib/event-schema.json'))
declared = set(schema['properties'])
kinds = set(schema['properties']['kind']['enum'])
bad = []
for l in open('${EVENTS}'):
    r = json.loads(l)
    if set(r) - declared: bad.append(sorted(set(r) - declared))
    if r['kind'] not in kinds: bad.append(r['kind'])
    if set(schema['required']) - set(r): bad.append('missing')
print(bad)
")" "[]" "rows conform to event-schema.json"
assert_eq "$(python3 -c "
import json
s = json.load(open('${MODULE_ROOT}/lib/event-schema.json'))
k = s['properties']['kind']['enum']
print('user_interrupt' in k, 'tool_use' in k)
")" "True False" "schema has user_interrupt and no tool_use"

echo ""
echo "test-failure-logging.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
