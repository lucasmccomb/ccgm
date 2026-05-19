#!/usr/bin/env bash
# Test suite verifying that all 17 secret-pattern families documented in
# modules/autoheal/lib/secret-patterns.json are actually redacted when an
# event flows through permission-event-logger.py.
#
# Fake-token shapes are constructed at runtime via string concat so the
# literal token forms never appear in this file (GitHub push protection
# scanner does not see them). At execution time the concatenated strings
# are byte-for-byte identical to the patterns redact_secrets() targets.
#
# The redaction itself is unit-tested in modules/hooks/tests/test-hook-utils.sh.
# This test verifies the contract end-to-end: a tool_input containing a
# secret produces a stored event whose redacted_command bears the right
# [REDACTED:<name>] marker.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/permission-event-logger.py"
export HOOK
HOOKS_MODULE="$(cd "${MODULE_ROOT}/../hooks" && pwd)"
HOOK_LIB="${HOOKS_MODULE}/lib"
PATTERNS_JSON="${MODULE_ROOT}/lib/secret-patterns.json"

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

TMP_HOME=$(mktemp -d -t autoheal_redact.XXXXXX)
trap 'rm -rf "${TMP_HOME}"' EXIT
mkdir -p "${TMP_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${TMP_HOME}/.claude/lib/hook_utils.py"

export HOME="${TMP_HOME}"
export CCGM_AUTOHEAL_DIR="${TMP_HOME}/autoheal"

today() {
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

events_file() {
    echo "${CCGM_AUTOHEAL_DIR}/events/$(today).jsonl"
}

# Sanity: secret-patterns.json lists exactly 17 patterns.
count=$(python3 -c "
import json
print(len(json.load(open('${PATTERNS_JSON}'))['patterns']))
")
assert_eq "${count}" "17" "secret-patterns.json lists 17 patterns"

# For each of the 17 pattern families, build a fake token, ship it
# through the hook, and assert the stored event has the right marker.
#
# String concat dodges GitHub push protection. The Python here-doc emits
# one assertion per pattern; we capture the totals and verify all-pass.
result=$(python3 <<'PY'
import json, os, subprocess, sys

S40 = 'A' * 40
S36 = 'A' * 36
SHORT = 'A' * 32
B = '1234567890abcdefghijklmn'

# Each tuple: (pattern_name, fake_token_string). The fake token is
# constructed via concat so no literal pattern appears in this file.
fakes = [
    ('anthropic',           'sk' + '-ant-' + 'api03-' + S36),
    ('stripe_live',         'sk' + '_' + 'live_' + B),
    ('stripe_test',         'sk' + '_' + 'test_' + B),
    ('github_pat',          'ghp' + '_' + S36),
    ('github_oauth',        'gho' + '_' + S36),
    ('github_u2s',          'ghu' + '_' + S36),
    ('github_s2s',          'ghs' + '_' + S36),
    ('github_refresh',      'ghr' + '_' + S36),
    ('aws_access_key',      'AK' + 'IA' + 'ABCDEFGHIJKLMNOP'),
    ('google_api',          'A' + 'Iza' + 'Sy' + 'A' + '1234567890abcdefghijklmnopqrstuvwx'),
    ('slack',               'xo' + 'xb-' + '1234567890-9876543210-abcdefghij'),
    ('resend',              're' + '_' + 'AbCdEfGh' + '_' + '1234567890abcdef'),
    ('supabase',            'sb' + '_' + 'secret_' + '1234567890abcdefghij'),
    ('openai',              'sk' + '-' + SHORT),
    ('authorization_bearer','Authorization: Bearer ' + 'abc.def.ghi-jkl'),
    ('env_var_kv',          'API' + '_' + 'KEY' + '=' + 'abcdef1234567890'),
    ('password_flag',       'mycli ' + '--password ' + 'hunter2hunter2'),
]

events_path = os.path.join(os.environ['CCGM_AUTOHEAL_DIR'], 'events', __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat() + '.jsonl')
os.makedirs(os.path.dirname(events_path), exist_ok=True)
# Clean slate.
if os.path.exists(events_path):
    os.remove(events_path)

ok = 0
missed = []
for name, fake in fakes:
    cmd = 'echo ' + fake
    payload = {
        'hook_event_name': 'PostToolUse',
        'session_id': 's-' + name,
        'tool_name': 'Bash',
        'tool_input': {'command': cmd},
        'cwd': '/tmp/repo',
    }
    subprocess.run(['python3', os.environ['HOOK']], input=json.dumps(payload), text=True, check=False)

# Now read the events file and walk each line.
with open(events_path) as fh:
    lines = [json.loads(line) for line in fh if line.strip()]

# Build a session -> redacted_command map.
by_session = {r['session_id']: r['redacted_command'] for r in lines}

for name, fake in fakes:
    cmd_stored = by_session.get('s-' + name, '')
    marker = f'[REDACTED:{name}]'
    if marker in (cmd_stored or '') and fake not in (cmd_stored or ''):
        ok += 1
    else:
        missed.append((name, cmd_stored))

print(f'OK {ok} / {len(fakes)}')
for name, val in missed:
    print('MISS', name, '|', repr(val))
PY
)

total_line=$(echo "${result}" | head -1)
assert_eq "${total_line}" "OK 17 / 17" "all 17 patterns redacted via the event-logger path"

# If there were misses, print them for debugging.
if echo "${result}" | grep -q "MISS"; then
    echo "${result}" | grep MISS
fi

echo ""
echo "test-redaction-coverage.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
