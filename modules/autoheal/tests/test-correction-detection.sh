#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/user-correction-detector.py
#
# A prompt counts as a correction only when ALL hold (#1099 Phase 1.3):
#   - it matches a lib/correction-patterns.json pattern,
#   - it is short (<= 300 characters),
#   - the session had a tool_failure or user_interrupt row after the prompt
#     two turns back (so: within the last two turns).
#
# Covers:
#   - Each pattern fires after a failure and logs the right pattern name.
#   - The same prompts do nothing without a prior failure.
#   - A long multi-paragraph brief containing "instead" does not fire.
#   - An interrupt followed by "no, use X" fires.
#   - A failure more than two turns back does not count.
#   - context_event_ids lists the failure/interrupt rows the prompt follows.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/user-correction-detector.py"
HOOKS_MODULE="$(cd "${MODULE_ROOT}/../hooks" && pwd)"
HOOK_LIB="${HOOKS_MODULE}/lib"
PATTERNS_FILE="${MODULE_ROOT}/lib/correction-patterns.json"

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

TMP_HOME=$(mktemp -d -t autoheal_correction.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"

export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"
export CCGM_CORRECTION_PATTERNS="${PATTERNS_FILE}"

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

# seed_row KIND SESSION: append a tool_failure or user_interrupt row, now.
seed_row() {
    SEED_KIND="$1" SEED_SESSION="$2" python3 -c "
import json, os, datetime
path = os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'events', datetime.datetime.now(datetime.timezone.utc).date().isoformat() + '.jsonl')
os.makedirs(os.path.dirname(path), exist_ok=True)
rec = {
    'kind': os.environ['SEED_KIND'],
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'session_id': os.environ['SEED_SESSION'],
    'tool_name': 'Bash',
    'redacted_command': 'echo ==',
    'error': 'Exit code 1',
    'error_class': 'exit_code',
}
with open(path, 'a') as fh:
    fh.write(json.dumps(rec) + '\n')
"
}

# run_correction SESSION PROMPT
run_correction() {
    SESSION="$1" PROMPT_TEXT="$2" python3 -c "
import json, os, subprocess, sys
payload = {
    'hook_event_name': 'UserPromptSubmit',
    'session_id': os.environ['SESSION'],
    'prompt': os.environ['PROMPT_TEXT'],
    'cwd': '/tmp/repo',
}
p = subprocess.run(['python3', '${HOOK}'], input=json.dumps(payload), capture_output=True, text=True)
sys.exit(p.returncode)
"
    return $?
}

# correction_count [SESSION]: user_correction rows, optionally for one session.
correction_count() {
    if [ ! -f "$(events_file)" ]; then
        echo 0
        return
    fi
    CSESSION="${1:-}" python3 -c "
import json, os
n = 0
for line in open('$(events_file)'):
    line = line.strip()
    if not line: continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get('kind') != 'user_correction': continue
    if os.environ['CSESSION'] and r.get('session_id') != os.environ['CSESSION']: continue
    n += 1
print(n)
"
}

last_correction() {  # $1 = key
    python3 -c "
import json
recs = [json.loads(l) for l in open('$(events_file)') if l.strip()]
recs = [r for r in recs if r.get('kind') == 'user_correction']
print(recs[-1].get('$1') if recs else 'NONE')
"
}

# 1. Each correction pattern fires after a failure, with the right name.
declare -a PATTERNS=(
    "no, not like that"
    "stop doing that"
    "don't do that"
    "I told you we use Tailwind"
    "wait, no"
    "actually, that's wrong"
    "use pnpm instead"
    "that's wrong"
    "undo that"
    "no, use pnpm"
)
declare -a EXPECTED_NAMES=(
    "no_not_like_that"
    "stop_doing"
    "dont_do_that"
    "i_told_you"
    "wait_no"
    "actually_correction"
    "instead"
    "thats_wrong"
    "undo"
    "leading_no"
)

for i in "${!PATTERNS[@]}"; do
    sess="pat-$i"
    seed_row tool_failure "${sess}"
    run_correction "${sess}" "${PATTERNS[$i]}"
    assert_eq "$?" "0" "hook exits 0 for '${PATTERNS[$i]}'"
    assert_eq "$(correction_count "${sess}")" "1" "'${PATTERNS[$i]}' fires after a failure"
    assert_eq "$(last_correction correction_pattern_matched)" "${EXPECTED_NAMES[$i]}" "pattern name for '${PATTERNS[$i]}'"
done

# 2. The same phrases do nothing without a prior failure or interrupt.
for i in "${!PATTERNS[@]}"; do
    run_correction "cold-$i" "${PATTERNS[$i]}"
done
total=0
for i in "${!PATTERNS[@]}"; do total=$((total + $(correction_count "cold-$i"))); done
assert_eq "${total}" "0" "no failure in session: no correction rows"

# A failure in a DIFFERENT session does not count.
seed_row tool_failure "other-session"
run_correction "lonely" "no, not like that"
assert_eq "$(correction_count lonely)" "0" "failure in another session does not count"

# 3. A long multi-paragraph brief does not fire, even after a failure and
#    even though it contains "instead" and "I told you".
seed_row tool_failure "brief"
BRIEF=$(python3 -c "
para = 'Please write the report to a file instead of printing it, and I told you last week that the format must stay stable. ' * 3
print(para + '\n\n' + para + '\n\n' + para)
")
run_correction "brief" "${BRIEF}"
assert_eq "$(correction_count brief)" "0" "long brief after a failure does not fire"

# Length boundary: 300 chars fires, 301 does not.
seed_row tool_failure "len300"
P300=$(python3 -c "s='no, not like that '; print((s + 'x' * 300)[:300])")
run_correction "len300" "${P300}"
assert_eq "$(correction_count len300)" "1" "300-char prompt fires"
seed_row tool_failure "len301"
P301=$(python3 -c "s='no, not like that '; print((s + 'x' * 301)[:301])")
run_correction "len301" "${P301}"
assert_eq "$(correction_count len301)" "0" "301-char prompt does not fire"

# 4. Interrupt, then "no, use X" fires.
seed_row user_interrupt "intr"
run_correction "intr" "no, use rg"
assert_eq "$(correction_count intr)" "1" "interrupt then 'no, use X' fires"
assert_eq "$(last_correction correction_pattern_matched)" "leading_no" "interrupt correction pattern"

# 5. Benign short prompts after a failure do not fire.
seed_row tool_failure "benign"
run_correction "benign" "let me check the docs and report back"
run_correction "benign" "looks good to me"
run_correction "benign" "running tests now"
assert_eq "$(correction_count benign)" "0" "benign prompts add 0 events"

# 6. Turn window: a failure more than two prompts back does not count.
seed_row tool_failure "stale"
run_correction "stale" "ok, continue"
run_correction "stale" "thanks, go on"
run_correction "stale" "that's wrong"
assert_eq "$(correction_count stale)" "0" "failure two prompts back is out of window"

# One intervening prompt is still inside the window.
seed_row tool_failure "fresh"
run_correction "fresh" "ok, continue"
run_correction "fresh" "that's wrong"
assert_eq "$(correction_count fresh)" "1" "failure one prompt back is in window"

# 7. context_event_ids lists the failure/interrupt rows (at most 3).
seed_row tool_failure "ctx"
seed_row user_interrupt "ctx"
seed_row tool_failure "ctx"
seed_row tool_failure "ctx"
run_correction "ctx" "no, not like that"
assert_eq "$(last_correction context_event_ids | python3 -c "import sys,ast; print(len(ast.literal_eval(sys.stdin.read().strip())))")" "3" "context_event_ids holds the 3 most recent failure/interrupt rows"

# 8. Malformed stdin exits 0.
echo 'not json {{{' | python3 "${HOOK}"
assert_eq "$?" "0" "malformed stdin exits 0"

# 9. correction-patterns.json is the source of truth and holds 10 patterns.
[ -f "${PATTERNS_FILE}" ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: ${PATTERNS_FILE} does not exist"; }
JSON_COUNT=$(python3 -c "
import json
print(len(json.load(open('${PATTERNS_FILE}'))['patterns']))
")
assert_eq "${JSON_COUNT}" "10" "correction-patterns.json contains 10 patterns"

# 10. The hook loads patterns from the JSON file (no inlined regex list).
if grep -q '_load_correction_patterns' "${HOOK}" && \
   grep -q 'CCGM_CORRECTION_PATTERNS' "${HOOK}" && \
   ! grep -q 'no_not_like_that.*re\.compile' "${HOOK}"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: hook source must load patterns from JSON, not inline them"
fi

# 11. Missing patterns file: hook is a no-op and exits 0.
BACKUP="${CCGM_CORRECTION_PATTERNS}"
export CCGM_CORRECTION_PATTERNS="/nonexistent/path/never-here.json"
seed_row tool_failure "nopat"
run_correction "nopat" "no, not like that"
assert_eq "$?" "0" "missing patterns file: hook exits 0"
assert_eq "$(correction_count nopat)" "0" "missing patterns file: no event emitted"
export CCGM_CORRECTION_PATTERNS="${BACKUP}"

echo ""
echo "test-correction-detection.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
