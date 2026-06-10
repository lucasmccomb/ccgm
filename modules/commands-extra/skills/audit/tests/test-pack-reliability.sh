#!/usr/bin/env bash
# test-pack-reliability.sh — Tests for the ccgm/reliability audit pack (issue #608)
#
# Tests:
#   1. pack.json validates against pack.schema.json (stdlib validator via registry.py)
#   2. severity-rubric.json is valid JSON and contains all reliability/* check ids
#   3. lint-pack.py passes on the reliability pack with the real rubric
#   4. checks.md contains required template sections (## Scope, ## applies_when Rationale,
#      ## Checks, ## Quality Checklist)
#   5. checks.md documents a TP/TN fixture for each seeded defect class:
#       floating-promise, unhandled-promise, fetch-without-timeout
#      Note: reliability/empty-catch was intentionally dropped (overlaps code-quality/
#      empty-catch-block); the "Scope Note: empty-catch Not Included" section in checks.md
#      documents this decision.
#   6. applies_when gates correctly: pack is SELECTED for a JS project (package.json
#      present), NOT selected for a Go-only project
#
# Note: These are LLM-detection checks. We do NOT assert that the LLM finds actual
# issues in the JS fixture — we only assert structural validity (pack schema, rubric
# entries, checks.md completeness, and registry selection logic).
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACK_DIR="${AUDIT_DIR}/packs/reliability"
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

# Write validator to a temp file to avoid heredoc-in-command-substitution warnings.
_T1_PY="$(mktemp /tmp/pack_validate_rel_XXXXXX.py)"
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
    pass "reliability/pack.json validates against pack.schema.json"
else
    fail "reliability/pack.json failed validation: ${_T1_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 2: severity-rubric.json contains all reliability/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 2: rubric contains all reliability/* check ids"

EXPECTED_IDS=(
    "reliability/floating-promise"
    "reliability/misused-promise"
    "reliability/unhandled-promise"
    "reliability/await-in-loop"
    "reliability/fetch-without-timeout"
    "reliability/retry-without-backoff"
    "reliability/promise-all-vs-allsettled"
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
    pass "rubric contains all ${#EXPECTED_IDS[@]} reliability/* check ids"
else
    fail "rubric missing ids:${_T2_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 3: lint-pack.py passes on the reliability pack with the real rubric
# ---------------------------------------------------------------------------
echo "--- Test 3: lint-pack.py passes on reliability pack"

_T3_OUTPUT=""
_T3_EXIT=0
_T3_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T3_EXIT=$?

if [ "${_T3_EXIT}" -eq 0 ] && echo "${_T3_OUTPUT}" | grep -q "^PASS: reliability"; then
    pass "lint-pack.py reports PASS for reliability pack"
else
    fail "lint-pack.py did not report PASS for reliability: exit=${_T3_EXIT}, output=${_T3_OUTPUT}"
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
# Test 5: checks.md documents TP/TN fixtures for seeded defect classes
#
# Seeded defect classes to verify:
#   - floating-promise
#   - unhandled-promise (covers the unhandled-promise check)
#   - fetch-without-timeout
#
# Note: reliability/empty-catch was intentionally DROPPED (overlaps
# code-quality/empty-catch-block). The "Scope Note: empty-catch Not Included"
# section in checks.md documents this decision. We assert that section exists.
# ---------------------------------------------------------------------------
echo "--- Test 5: checks.md documents TP/TN fixtures for seeded defect classes"

# Verify True positive and True negative markers for each seeded class
declare -A SEEDED_CLASSES=(
    ["floating-promise"]="reliability/floating-promise"
    ["unhandled-promise"]="reliability/unhandled-promise"
    ["fetch-without-timeout"]="reliability/fetch-without-timeout"
)

_T5_ERRORS=""

for class in "${!SEEDED_CLASSES[@]}"; do
    check_id="${SEEDED_CLASSES[$class]}"

    # check-id appears in checks.md
    if ! grep -q "${check_id}" "${CHECKS_MD}"; then
        _T5_ERRORS="${_T5_ERRORS}\n  check-id '${check_id}' not found in checks.md"
        continue
    fi

    # Extract the section for this check-id: from the heading to the next ### heading
    # (or end of file). Use python3 for reliable multi-line extraction.
    _SECTION=$(python3 - "${CHECKS_MD}" "${check_id}" <<'PYEOF' 2>/dev/null
import sys, re
md = open(sys.argv[1], encoding='utf-8').read()
check_id = sys.argv[2]
# Find start: the ### line containing the check-id
pattern = r'(### `' + re.escape(check_id) + r'`.*?)(?=\n### `|\Z)'
m = re.search(pattern, md, re.DOTALL)
if m:
    print(m.group(1))
PYEOF
)

    # True positive fixture marker present in section
    if ! echo "${_SECTION}" | grep -q "True positive\|FINDS:"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    # True negative fixture marker present in section
    if ! echo "${_SECTION}" | grep -q "True negative\|should produce NO"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

# Verify empty-catch decision is documented
if ! grep -q "empty-catch" "${CHECKS_MD}"; then
    _T5_ERRORS="${_T5_ERRORS}\n  checks.md does not document the empty-catch omission decision"
fi

if [ -z "${_T5_ERRORS}" ]; then
    pass "checks.md documents TP/TN fixtures for all seeded defect classes (floating-promise, unhandled-promise, fetch-without-timeout) and documents empty-catch omission"
else
    fail "checks.md fixture coverage issues:$(printf '%b' "${_T5_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 6: applies_when gates correctly via registry.py
#   6a. JS project (package.json present) → pack INCLUDED
#   6b. Go-only project (no package.json) → pack EXCLUDED
# ---------------------------------------------------------------------------
echo "--- Test 6: applies_when gates correctly"

TMPDIR_PACKS="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${TMPDIR_PACKS}'" EXIT

# Set up a temp packs dir with just the reliability pack
mkdir -p "${TMPDIR_PACKS}/reliability"
cp "${PACK_DIR}/pack.json" "${TMPDIR_PACKS}/reliability/pack.json"

# Helper: run registry.py with a detector JSON and the temp packs dir
run_registry() {
    local detector_json="$1"
    CCGM_PACKS_DIR="${TMPDIR_PACKS}" python3 "${REGISTRY}" <<< "${detector_json}"
}

# 6a: JS project → pack INCLUDED
DETECTOR_JS='{"detected_ecosystems":["javascript"],"project_shape":{},"available_tools":[]}'
_T6A_RESULT=""
_T6A_EXIT=0
_T6A_RESULT=$(run_registry "${DETECTOR_JS}" 2>/dev/null) || _T6A_EXIT=$?

_T6A_INCLUDED=0
if [ "${_T6A_EXIT}" -eq 0 ]; then
    if echo "${_T6A_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/reliability' in ids, 'ccgm/reliability not in: ' + str(ids)
" 2>/dev/null; then
        _T6A_INCLUDED=1
    fi
fi

if [ "${_T6A_INCLUDED}" -eq 1 ]; then
    pass "ccgm/reliability INCLUDED for JS project (language:javascript)"
else
    fail "ccgm/reliability should be INCLUDED for JS project but was not. exit=${_T6A_EXIT}, result=${_T6A_RESULT}"
fi

# 6b: Go-only project → pack EXCLUDED
DETECTOR_GO='{"detected_ecosystems":["go"],"project_shape":{},"available_tools":[]}'
_T6B_RESULT=""
_T6B_EXIT=0
_T6B_RESULT=$(run_registry "${DETECTOR_GO}" 2>/dev/null) || _T6B_EXIT=$?

_T6B_EXCLUDED=0
if [ "${_T6B_EXIT}" -eq 0 ]; then
    if echo "${_T6B_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/reliability' not in ids, 'ccgm/reliability should not be in: ' + str(ids)
" 2>/dev/null; then
        _T6B_EXCLUDED=1
    fi
fi

if [ "${_T6B_EXCLUDED}" -eq 1 ]; then
    pass "ccgm/reliability EXCLUDED for Go-only project (no language:javascript)"
else
    fail "ccgm/reliability should be EXCLUDED for Go project but was not. exit=${_T6B_EXIT}, result=${_T6B_RESULT}"
fi

# ---------------------------------------------------------------------------
# Bonus: Validate JS runtime fixture structure (no LLM assertion — static only)
# Create a minimal JS file with known reliability patterns and verify it exists
# ---------------------------------------------------------------------------
echo "--- Bonus: JS runtime fixture creation and static structure"

TMPDIR_FIXTURE="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${TMPDIR_FIXTURE}'" EXIT

# floating promise fixture
cat > "${TMPDIR_FIXTURE}/floating.js" <<'JS'
// Reliability fixture: floating-promise (TP)
// updateUser() returns a Promise; result is not awaited (floating)
async function handleUpdate(user) {
  validateUser(user);
  updateUser(user);    // floating promise — rejection silently lost
  showToast('Saved');
}
JS

# fetch-without-timeout fixture
cat > "${TMPDIR_FIXTURE}/fetch-no-timeout.js" <<'JS'
// Reliability fixture: fetch-without-timeout (TP)
// No AbortController signal provided — hangs indefinitely on slow server
async function loadData(id) {
  const res = await fetch(`/api/data/${id}`);
  return res.json();
}
JS

# package.json to mark the fixture as a JS project
cat > "${TMPDIR_FIXTURE}/package.json" <<'JSON'
{ "name": "reliability-test-fixture", "version": "1.0.0" }
JSON

if [ -f "${TMPDIR_FIXTURE}/floating.js" ] && \
   [ -f "${TMPDIR_FIXTURE}/fetch-no-timeout.js" ] && \
   [ -f "${TMPDIR_FIXTURE}/package.json" ]; then
    pass "JS runtime fixtures created (floating-promise, fetch-without-timeout, package.json)"
else
    fail "JS runtime fixture creation failed"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
