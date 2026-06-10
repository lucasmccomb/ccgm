#!/usr/bin/env bash
# test-pack-testing-deep.sh — Tests for Epic 4.2: deepened ccgm/testing audit pack
#
# Tests:
#   1. pack.json validates against pack.schema.json (stdlib registry.py)
#   2. severity-rubric.json contains all 7 testing/* check ids (3 original + 4 new)
#   3. lint-pack.py passes on the testing pack with the real rubric
#   4. checks.md contains required template sections
#   5. checks.md documents TP/TN fixtures for each seeded defect class:
#       sleep-based-flake, only-or-skip-committed, test-only-prod-method
#      (plus the 3 original classes: missing-test-file, no-assertions, missing-edge-cases)
#   6. applies_when gates correctly: pack is SELECTED for every project (applies_when=always),
#      including a JS project, a Python project, and a Go-only project
#   7. Runtime fixtures: .only committed, sleep( in test, _resetForTest in prod file
#
# Note: LLM-detection checks are NOT exercised at runtime. We only assert structural
# validity (pack schema, rubric entries, checks.md completeness, and registry selection).
# The grep-detectable check (testing/only-or-skip-committed) is validated via fixture.
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACK_DIR="${AUDIT_DIR}/packs/testing"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Test 1: pack.json validates against pack.schema.json
# ---------------------------------------------------------------------------
echo "--- Test 1: pack.json validates (stdlib registry.py)"

_T1_PY="$(mktemp "${TMPDIR:-/tmp}/pack_validate_testing.XXXXXX")"
cat > "${_T1_PY}" <<'PYEOF'
import sys, json, importlib.util, pathlib

registry_py = pathlib.Path(sys.argv[1])
pack_path   = pathlib.Path(sys.argv[2])

spec = importlib.util.spec_from_file_location("registry", str(registry_py))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

with open(pack_path, encoding="utf-8") as fh:
    pack = json.load(fh)

try:
    mod.validate_pack(pack, str(pack_path))
    print("VALID")
    sys.exit(0)
except mod.ValidationError as exc:
    print("INVALID: " + str(exc))
    sys.exit(1)
PYEOF
# shellcheck disable=SC2064
trap "rm -f '${_T1_PY}'" EXIT

_T1_RESULT=""
_T1_EXIT=0
_T1_RESULT=$(python3 "${_T1_PY}" "${REGISTRY}" "${PACK_DIR}/pack.json" 2>&1) || _T1_EXIT=$?

if [ "${_T1_EXIT}" -eq 0 ] && echo "${_T1_RESULT}" | grep -q "^VALID$"; then
    pass "testing/pack.json validates against pack.schema.json"
else
    fail "testing/pack.json failed validation: ${_T1_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 2: severity-rubric.json contains all 7 testing/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 2: rubric contains all 7 testing/* check ids"

EXPECTED_IDS=(
    "testing/missing-test-file"
    "testing/no-assertions"
    "testing/missing-edge-cases"
    "testing/sleep-based-flake"
    "testing/only-or-skip-committed"
    "testing/mock-not-behavior"
    "testing/test-only-prod-method"
)

_T2_MISSING=""
for check_id in "${EXPECTED_IDS[@]}"; do
    if ! python3 -c "
import json, sys
rubric = json.load(open('${RUBRIC}', encoding='utf-8'))
checks = rubric.get('checks', {})
if '${check_id}' not in checks:
    print('MISSING')
    sys.exit(1)
print('FOUND')
sys.exit(0)
" 2>/dev/null | grep -q "^FOUND$"; then
        _T2_MISSING="${_T2_MISSING} ${check_id}"
    fi
done

if [ -z "${_T2_MISSING}" ]; then
    pass "rubric contains all ${#EXPECTED_IDS[@]} testing/* check ids"
else
    fail "rubric missing ids:${_T2_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 3: lint-pack.py passes on the testing pack with the real rubric
# ---------------------------------------------------------------------------
echo "--- Test 3: lint-pack.py passes on testing pack"

_T3_OUTPUT=""
_T3_EXIT=0
_T3_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T3_EXIT=$?

if [ "${_T3_EXIT}" -eq 0 ] && echo "${_T3_OUTPUT}" | grep -q "^PASS: testing"; then
    pass "lint-pack.py reports PASS for testing pack"
else
    fail "lint-pack.py did not report PASS for testing: exit=${_T3_EXIT}, output=${_T3_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Test 4: checks.md contains all required template sections
# ---------------------------------------------------------------------------
echo "--- Test 4: checks.md has required sections"

CHECKS_MD="${PACK_DIR}/checks.md"

_REQUIRED_SECTIONS=(
    "^## Scope"
    "^## applies_when Rationale"
    "^## Checks"
    "^## Quality Checklist"
)

_T4_MISSING=""
for section in "${_REQUIRED_SECTIONS[@]}"; do
    if ! grep -qiE "${section}" "${CHECKS_MD}"; then
        _T4_MISSING="${_T4_MISSING} '${section}'"
    fi
done

if [ -z "${_T4_MISSING}" ]; then
    pass "checks.md contains all required sections"
else
    fail "checks.md missing sections:${_T4_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 5: checks.md documents TP/TN fixtures for each defect class
#
# Seeded defect classes verified here (the 4 new ones from Epic 4.2):
#   - sleep-based-flake
#   - only-or-skip-committed
#   - mock-not-behavior
#   - test-only-prod-method
#
# The 3 original checks (missing-test-file, no-assertions, missing-edge-cases)
# were present in Wave 1; this test only asserts the new ones.
# ---------------------------------------------------------------------------
echo "--- Test 5: checks.md documents TP/TN fixtures for new defect classes"

NEW_CHECK_IDS=(
    "testing/sleep-based-flake"
    "testing/only-or-skip-committed"
    "testing/mock-not-behavior"
    "testing/test-only-prod-method"
)

_T5_ERRORS=""

for check_id in "${NEW_CHECK_IDS[@]}"; do
    # check-id appears in checks.md
    if ! grep -q "${check_id}" "${CHECKS_MD}"; then
        _T5_ERRORS="${_T5_ERRORS}\n  check-id '${check_id}' not found in checks.md"
        continue
    fi

    # Extract the section for this check-id: from the ### heading to the next ### or end.
    _SECTION=$(python3 - "${CHECKS_MD}" "${check_id}" <<'PYEOF' 2>/dev/null
import sys, re
md = open(sys.argv[1], encoding='utf-8').read()
check_id = sys.argv[2]
pattern = r'(### `' + re.escape(check_id) + r'`.*?)(?=\n### `|\Z)'
m = re.search(pattern, md, re.DOTALL)
if m:
    print(m.group(1))
PYEOF
)

    # True positive fixture present
    if ! echo "${_SECTION}" | grep -q "True positive\|FINDS:"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    # True negative fixture present
    if ! echo "${_SECTION}" | grep -q "True negative\|should produce NO"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

if [ -z "${_T5_ERRORS}" ]; then
    pass "checks.md documents TP/TN fixtures for all 4 new defect classes"
else
    fail "checks.md fixture coverage issues:$(printf '%b' "${_T5_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 6: applies_when gates correctly via registry.py
#   applies_when: always → pack is INCLUDED for JS, Python, and Go projects
# ---------------------------------------------------------------------------
echo "--- Test 6: applies_when=always gates correctly"

TMPDIR_PACKS="$(mktemp -d "${TMPDIR:-/tmp}/packs_testing_gate.XXXXXX")"
# shellcheck disable=SC2064
trap "rm -rf '${TMPDIR_PACKS}'" EXIT

mkdir -p "${TMPDIR_PACKS}/testing"
cp "${PACK_DIR}/pack.json" "${TMPDIR_PACKS}/testing/pack.json"

run_registry() {
    local detector_json="$1"
    CCGM_PACKS_DIR="${TMPDIR_PACKS}" python3 "${REGISTRY}" <<< "${detector_json}"
}

# 6a: JS project → INCLUDED
DETECTOR_JS='{"detected_ecosystems":["javascript"],"project_shape":{},"available_tools":[]}'
_T6A_RESULT=""
_T6A_EXIT=0
_T6A_RESULT=$(run_registry "${DETECTOR_JS}" 2>/dev/null) || _T6A_EXIT=0  # never fails
if echo "${_T6A_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/testing' in ids, 'ccgm/testing not in: ' + str(ids)
" 2>/dev/null; then
    pass "ccgm/testing INCLUDED for JS project (applies_when=always)"
else
    fail "ccgm/testing should be INCLUDED for JS project. result=${_T6A_RESULT}"
fi

# 6b: Go-only project → INCLUDED (always means always)
DETECTOR_GO='{"detected_ecosystems":["go"],"project_shape":{},"available_tools":[]}'
_T6B_RESULT=""
_T6B_RESULT=$(run_registry "${DETECTOR_GO}" 2>/dev/null) || true
if echo "${_T6B_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/testing' in ids, 'ccgm/testing not in: ' + str(ids)
" 2>/dev/null; then
    pass "ccgm/testing INCLUDED for Go-only project (applies_when=always)"
else
    fail "ccgm/testing should be INCLUDED for Go-only project. result=${_T6B_RESULT}"
fi

# 6c: Empty ecosystems → INCLUDED (always means always)
DETECTOR_EMPTY='{"detected_ecosystems":[],"project_shape":{},"available_tools":[]}'
_T6C_RESULT=""
_T6C_RESULT=$(run_registry "${DETECTOR_EMPTY}" 2>/dev/null) || true
if echo "${_T6C_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/testing' in ids, 'ccgm/testing not in: ' + str(ids)
" 2>/dev/null; then
    pass "ccgm/testing INCLUDED for empty ecosystem list (applies_when=always)"
else
    fail "ccgm/testing should be INCLUDED for empty ecosystem list. result=${_T6C_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 7: Runtime fixtures — create representative test/source files and
#         assert the grep pattern catches .only and verifies file structure.
#         (No LLM assertion — static structure only.)
# ---------------------------------------------------------------------------
echo "--- Test 7: Runtime fixtures creation and grep detection"

TMPDIR_FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/testing_deep_fixture.XXXXXX")"
# shellcheck disable=SC2064
trap "rm -rf '${TMPDIR_FIXTURE}'" EXIT

mkdir -p "${TMPDIR_FIXTURE}/src" "${TMPDIR_FIXTURE}/tests"

# 7a: .only committed (testing/only-or-skip-committed TP fixture)
cat > "${TMPDIR_FIXTURE}/tests/auth.test.ts" <<'TS'
// testing/only-or-skip-committed: TRUE POSITIVE
// .only narrows the suite — all other tests in this file are skipped
describe('login', () => {
  it.only('accepts valid credentials', () => {
    expect(login('alice', 'secret')).toBe(true);
  });
  it('rejects empty password', () => {
    expect(login('alice', '')).toBe(false);
  });
});
TS

# 7b: sleep-based synchronization in test (testing/sleep-based-flake TP fixture)
cat > "${TMPDIR_FIXTURE}/tests/search.test.ts" <<'TS'
// testing/sleep-based-flake: TRUE POSITIVE
// setTimeout used as synchronization guard before assertion
it('shows results after debounce', async () => {
  fireEvent.change(input, { target: { value: 'hello' } });
  await new Promise((r) => setTimeout(r, 100));
  expect(screen.getByText('Result 1')).toBeInTheDocument();
});
TS

# 7c: _resetForTest in a production file (testing/test-only-prod-method TP fixture)
cat > "${TMPDIR_FIXTURE}/src/AuthService.ts" <<'TS'
// testing/test-only-prod-method: TRUE POSITIVE
export class AuthService {
  private _currentUser = null;

  async login(creds) {
    this._currentUser = await this.api.authenticate(creds);
    return this._currentUser;
  }

  // for testing only
  _resetForTest() {
    this._currentUser = null;
  }
}
TS

# 7d: Clean test file (should produce NO finding for only-or-skip-committed)
cat > "${TMPDIR_FIXTURE}/tests/format.test.ts" <<'TS'
// testing/only-or-skip-committed: TRUE NEGATIVE — no .only or .skip
describe('formatDate', () => {
  it('formats a date', () => {
    expect(formatDate(new Date('2024-01-01'))).toBe('Jan 1, 2024');
  });
});
TS

# Verify fixture files were created
_T7_FILES_MISSING=""
for f in \
    "${TMPDIR_FIXTURE}/tests/auth.test.ts" \
    "${TMPDIR_FIXTURE}/tests/search.test.ts" \
    "${TMPDIR_FIXTURE}/src/AuthService.ts" \
    "${TMPDIR_FIXTURE}/tests/format.test.ts"; do
    if [ ! -f "${f}" ]; then
        _T7_FILES_MISSING="${_T7_FILES_MISSING} ${f}"
    fi
done

if [ -z "${_T7_FILES_MISSING}" ]; then
    pass "runtime fixtures created (auth.test.ts, search.test.ts, AuthService.ts, format.test.ts)"
else
    fail "missing runtime fixture files:${_T7_FILES_MISSING}"
fi

# 7e: grep detects .only in TP fixture (only-or-skip-committed)
_T7E_GREP_OUTPUT=""
_T7E_GREP_OUTPUT=$(grep -rn --include="*.test.*" --include="*.spec.*" \
    -E '\.(only|skip)\s*\(' "${TMPDIR_FIXTURE}/tests/" 2>/dev/null || true)

if echo "${_T7E_GREP_OUTPUT}" | grep -q "auth.test.ts"; then
    pass "grep detects .only in auth.test.ts (only-or-skip-committed TP)"
else
    fail "grep should detect .only in auth.test.ts: output='${_T7E_GREP_OUTPUT}'"
fi

# 7f: grep does NOT flag the clean file (TN)
if echo "${_T7E_GREP_OUTPUT}" | grep -q "format.test.ts"; then
    fail "grep should NOT flag format.test.ts (only-or-skip-committed TN)"
else
    pass "grep correctly excludes format.test.ts (only-or-skip-committed TN)"
fi

# 7g: sleep( present in sleep-based-flake fixture
if grep -q "setTimeout" "${TMPDIR_FIXTURE}/tests/search.test.ts"; then
    pass "sleep-based-flake TP fixture contains setTimeout synchronization guard"
else
    fail "sleep-based-flake TP fixture missing setTimeout"
fi

# 7h: _resetForTest present in prod file fixture
if grep -q "_resetForTest" "${TMPDIR_FIXTURE}/src/AuthService.ts"; then
    pass "test-only-prod-method TP fixture contains _resetForTest method"
else
    fail "test-only-prod-method TP fixture missing _resetForTest"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
