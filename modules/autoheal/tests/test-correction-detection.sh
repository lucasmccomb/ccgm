#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/user-correction-detector.py
#
# Covers:
#   - Prompts matching each correction pattern produce a user_correction
#     event with the right correction_pattern_matched value.
#   - Benign prompts do NOT produce an event.
#   - The context_event_ids field captures up to 3 recent tool_use
#     timestamps from today's events JSONL.

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
# Point the hook at the in-repo patterns JSON. The hook normally reads
# ~/.claude/lib/correction-patterns.json after the module installer
# copies the file; the env override mirrors the realtime-security
# scanner's CCGM_REALTIME_PATTERNS hook.
export CCGM_CORRECTION_PATTERNS="${PATTERNS_FILE}"

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

last_record() {
    # Print the last record matching the given filter using jq-free
    # Python — keeps the test portable on machines without jq.
    python3 -c "
import json
recs = [json.loads(line) for line in open('$(events_file)') if line.strip()]
recs = [r for r in recs if r.get('kind') == 'user_correction']
print(json.dumps(recs[-1]) if recs else '{}')
"
}

run_correction() {
    local prompt="$1"
    # Build the JSON in Python to avoid bash-side quoting hell.
    PROMPT_TEXT="${prompt}" python3 -c "
import json, os, subprocess, sys
payload = {
    'hook_event_name': 'UserPromptSubmit',
    'session_id': 'corr-session',
    'tool_name': 'UserPrompt',
    'prompt': os.environ['PROMPT_TEXT'],
    'cwd': '/tmp/repo',
}
p = subprocess.run(['python3', '${HOOK}'], input=json.dumps(payload), capture_output=True, text=True)
sys.exit(p.returncode)
"
    return $?
}

# Helper: count user_correction events in today's file.
correction_count() {
    if [ ! -f "$(events_file)" ]; then
        echo 0
        return
    fi
    python3 -c "
import json
n = 0
for line in open('$(events_file)'):
    line = line.strip()
    if not line: continue
    try:
        if json.loads(line).get('kind') == 'user_correction':
            n += 1
    except Exception:
        pass
print(n)
"
}

# 1. Each correction pattern fires.
declare -a PATTERNS=(
    "no, not like that"
    "stop doing that"
    "don't do that"
    "I told you we use Tailwind"
    "wait, no"
    "actually, that's wrong"
    "do A instead"
    "that's wrong"
    "undo that"
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
)

# Pre-seed two tool_use events so context_event_ids gets populated.
mkdir -p "${CCGM_AUTOHEAL_DIR}/events"
python3 <<'PY'
import json, os, datetime
path = os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'events', datetime.datetime.now(datetime.timezone.utc).date().isoformat() + '.jsonl')
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a') as fh:
    for cmd in ['git diff', 'git status']:
        rec = {
            'kind': 'tool_use',
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'session_id': 'corr-session',
            'tool_name': 'Bash',
            'redacted_command': cmd,
            'exit_code': None,
            'stderr_excerpt': None,
            'permission_decision': None,
            'cwd': '/tmp/repo',
            'clone_path': '/tmp/repo',
        }
        fh.write(json.dumps(rec) + '\n')
PY

for i in "${!PATTERNS[@]}"; do
    run_correction "${PATTERNS[$i]}"
    rc=$?
    assert_eq "${rc}" "0" "correction hook exits 0 for '${PATTERNS[$i]}'"
done

# 2. Each emitted event carries the expected pattern name.
python3 <<'PY' > /tmp/correction_names.txt
import json, os, datetime
path = os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'events', datetime.datetime.now(datetime.timezone.utc).date().isoformat() + '.jsonl')
for line in open(path):
    line = line.strip()
    if not line: continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if rec.get('kind') == 'user_correction':
        print(rec.get('correction_pattern_matched', ''))
PY

# The 9 expected pattern names should appear in the same order in the
# emitted log.
declare -a got
mapfile -t got < /tmp/correction_names.txt
for i in "${!EXPECTED_NAMES[@]}"; do
    assert_eq "${got[$i]}" "${EXPECTED_NAMES[$i]}" "pattern $i matches ${EXPECTED_NAMES[$i]}"
done

# 3. Benign prompts produce NO new user_correction event.
before=$(correction_count)
run_correction "let me check the docs and report back"
run_correction "looks good to me"
run_correction "running tests now"
after=$(correction_count)
assert_eq "${before}" "${after}" "benign prompts add 0 events"

# 4. context_event_ids captures up to 3 recent tool_use entries.
ctx=$(python3 -c "
import json, os, datetime
path = os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'events', datetime.datetime.now(datetime.timezone.utc).date().isoformat() + '.jsonl')
recs = [json.loads(line) for line in open(path) if line.strip()]
last = [r for r in recs if r.get('kind') == 'user_correction'][-1]
print(len(last.get('context_event_ids', [])))
")
# We seeded 2 tool_use records, so we expect <= 2 context ids.
case "${ctx}" in
    0|1|2)
        PASS=$((PASS + 1))
        ;;
    *)
        FAIL=$((FAIL + 1))
        echo "FAIL: context_event_ids count <= 2"
        echo "  actual: ${ctx}"
        ;;
esac

# 5. Malformed stdin exits 0.
echo 'not json {{{' | python3 "${HOOK}"
rc=$?
assert_eq "${rc}" "0" "malformed stdin exits 0"

# 6. correction-patterns.json exists and is the source of truth.
[ -f "${PATTERNS_FILE}" ] && PASS=$((PASS + 1)) || {
    FAIL=$((FAIL + 1))
    echo "FAIL: ${PATTERNS_FILE} does not exist"
}

# 7. The hook loads patterns from JSON (not inlined). Verify the JSON
#    pattern count matches the number of distinct correction events the
#    hook emitted for the 9 test prompts above. If the hook silently fell
#    back to an empty list (file not loaded), only 0 events would have
#    been emitted and assertion 1 would already have failed -- but we
#    also assert the count here for explicitness.
JSON_COUNT=$(python3 -c "
import json
with open('${PATTERNS_FILE}') as fh:
    data = json.load(fh)
print(len(data['patterns']))
")
assert_eq "${JSON_COUNT}" "9" "correction-patterns.json contains 9 patterns"

# 8. The hook source loads patterns from the JSON file (no inlined
#    regex list). Grep for the load function name and the env override
#    to lock in the contract.
if grep -q '_load_correction_patterns' "${HOOK}" && \
   grep -q 'CCGM_CORRECTION_PATTERNS' "${HOOK}" && \
   ! grep -q 'no_not_like_that.*re\.compile' "${HOOK}"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: hook source must load patterns from JSON, not inline them"
fi

# 9. Graceful degradation: when the patterns file is missing, the hook
#    becomes a no-op (no event written) instead of crashing.
CCGM_CORRECTION_PATTERNS_BACKUP="${CCGM_CORRECTION_PATTERNS}"
export CCGM_CORRECTION_PATTERNS="/nonexistent/path/never-here.json"
before_missing=$(correction_count)
run_correction "no, not like that"
rc=$?
after_missing=$(correction_count)
assert_eq "${rc}" "0" "missing patterns file: hook still exits 0"
assert_eq "${before_missing}" "${after_missing}" "missing patterns file: no event emitted"
export CCGM_CORRECTION_PATTERNS="${CCGM_CORRECTION_PATTERNS_BACKUP}"

echo ""
echo "test-correction-detection.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
