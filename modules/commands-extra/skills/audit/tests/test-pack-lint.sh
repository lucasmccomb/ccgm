#!/usr/bin/env bash
# test-pack-lint.sh — tests for scripts/lint-pack.py.
#
# Tests:
#   1. Linter PASSES on a well-formed pack (all required sections present,
#      pack.json valid, rubric absent → skipped gracefully).
#   2. Linter FAILS on a pack missing a required checks.md section.
#   3. Linter FAILS on a pack with an invalid pack.json (schema error).
#   4. Linter FAILS on a pack with an orphaned check-id when a rubric IS present.
#   5. Linter PASSES on a well-formed pack when a rubric IS present and all
#      check-ids are covered.
#   6. Linter skips _TEMPLATE directory (no FAIL emitted for it).
#   7. Linter handles an absent packs/ directory gracefully (exit 0, NOTE printed).
#
# Exit 0 = all tests passed; exit 1 = one or more failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Create a minimal well-formed pack directory under a temp dir.
# Args: dest_dir
make_valid_pack() {
    local dest="$1"
    mkdir -p "${dest}"

    cat > "${dest}/pack.json" <<'JSON'
{
  "id": "ccgm/test-valid",
  "name": "Test Valid Pack",
  "version": "1.0.0",
  "applies_when": ["always"],
  "checks": [
    {
      "id": "tv/check-one",
      "severity": "high",
      "confidence": "high",
      "detection": "tool",
      "tool": "semgrep"
    }
  ]
}
JSON

    cat > "${dest}/checks.md" <<'MD'
# Test Valid Pack

## Scope

This pack audits for test-valid patterns.

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always`  | Applies to all repos. |

## Checks

### `tv/check-one`

**Severity:** high
**Confidence:** high
**Detection:** tool

#### Detection

Tool: semgrep

#### Spine Wiring

```yaml
check_id: tv/check-one
detection: tool
tool: semgrep
```

#### Severity / Confidence

**Severity rationale:** High impact.
**Confidence rationale:** Deterministic tool.
**Rubric entry:** tv/check-one

#### Fixture

**True positive:**
```
bad code here
```

**True negative:**
```
good code here
```

## Quality Checklist

- [x] check-ids match
- [x] fixtures present
MD
}

# Create a checks.md missing the "## Scope" section.
make_missing_section_pack() {
    local dest="$1"
    mkdir -p "${dest}"

    cat > "${dest}/pack.json" <<'JSON'
{
  "id": "ccgm/test-missing-section",
  "name": "Missing Section Pack",
  "version": "1.0.0",
  "applies_when": ["always"],
  "checks": [
    {
      "id": "ms/check-one",
      "severity": "low",
      "confidence": "low",
      "detection": "llm"
    }
  ]
}
JSON

    # Deliberately omit "## Scope"
    cat > "${dest}/checks.md" <<'MD'
# Missing Section Pack

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always`  | Applies to all repos. |

## Checks

### `ms/check-one`

**Severity:** low

## Quality Checklist

- [ ] check-ids match
MD
}

# Create a pack with an invalid pack.json (missing required "checks" field).
make_invalid_json_pack() {
    local dest="$1"
    mkdir -p "${dest}"

    cat > "${dest}/pack.json" <<'JSON'
{
  "id": "ccgm/test-invalid-json",
  "name": "Invalid JSON Pack",
  "version": "1.0.0",
  "applies_when": ["always"]
}
JSON
    # checks field is intentionally absent — fails schema validation.

    cat > "${dest}/checks.md" <<'MD'
# Invalid JSON Pack

## Scope

This pack has an invalid pack.json.

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always`  | Always. |

## Checks

(none — pack.json is intentionally invalid)

## Quality Checklist

- [ ] check-ids match
MD
}

# ---------------------------------------------------------------------------
# Test 1: well-formed pack, no rubric → PASS
# ---------------------------------------------------------------------------
echo "--- Test 1: well-formed pack, no rubric → PASS"
_T1_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T1_DIR}'" EXIT

make_valid_pack "${_T1_DIR}/test-valid"

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T1_DIR}" --rubric "${_T1_DIR}/nonexistent-rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -eq 0 ] && echo "${output}" | grep -q "^PASS: test-valid"; then
    pass "well-formed pack passes linter (no rubric)"
else
    fail "well-formed pack should pass but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 2: pack missing required checks.md section → FAIL
# ---------------------------------------------------------------------------
echo "--- Test 2: pack missing required section → FAIL"
_T2_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T2_DIR}'" EXIT

make_missing_section_pack "${_T2_DIR}/test-missing"

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T2_DIR}" --rubric "${_T2_DIR}/nonexistent-rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -ne 0 ] && echo "${output}" | grep -q "^FAIL: test-missing"; then
    if echo "${output}" | grep -qi "missing required section"; then
        pass "pack missing section correctly rejected with clear error"
    else
        fail "pack missing section rejected but error message unclear: ${output}"
    fi
else
    fail "pack missing section should fail but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 3: invalid pack.json (schema error) → FAIL
# ---------------------------------------------------------------------------
echo "--- Test 3: invalid pack.json → FAIL"
_T3_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T3_DIR}'" EXIT

make_invalid_json_pack "${_T3_DIR}/test-invalid"

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T3_DIR}" --rubric "${_T3_DIR}/nonexistent-rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -ne 0 ] && echo "${output}" | grep -q "^FAIL: test-invalid"; then
    if echo "${output}" | grep -qi "schema validation failed\|missing required"; then
        pass "invalid pack.json correctly rejected with clear error"
    else
        fail "invalid pack.json rejected but error message unclear: ${output}"
    fi
else
    fail "invalid pack.json should fail but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 4: orphan check-id when rubric IS present → FAIL
# ---------------------------------------------------------------------------
echo "--- Test 4: orphan check-id with rubric present → FAIL"
_T4_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T4_DIR}'" EXIT

make_valid_pack "${_T4_DIR}/test-orphan"

# Write a rubric that does NOT contain "tv/check-one"
cat > "${_T4_DIR}/rubric.json" <<'JSON'
[
  {"id": "other/check", "severity": "low", "confidence": "low"}
]
JSON

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T4_DIR}" --rubric "${_T4_DIR}/rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -ne 0 ] && echo "${output}" | grep -q "^FAIL: test-orphan"; then
    if echo "${output}" | grep -qi "no entry in severity-rubric"; then
        pass "orphan check-id correctly rejected when rubric is present"
    else
        fail "orphan check-id rejected but error message unclear: ${output}"
    fi
else
    fail "orphan check-id should fail when rubric present but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 5: well-formed pack + rubric covers all check-ids → PASS
# ---------------------------------------------------------------------------
echo "--- Test 5: well-formed pack + matching rubric → PASS"
_T5_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T5_DIR}'" EXIT

make_valid_pack "${_T5_DIR}/test-covered"

# Write a rubric in dict-envelope form ({"checks": {<id>: {...}}}) that DOES contain "tv/check-one".
# This pins the dict-envelope branch added to lint-pack.py so reverting it would break this test.
cat > "${_T5_DIR}/rubric.json" <<'JSON'
{"checks": {"tv/check-one": {"severity": "high", "confidence": "high"}}}
JSON

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T5_DIR}" --rubric "${_T5_DIR}/rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -eq 0 ] && echo "${output}" | grep -q "^PASS: test-covered"; then
    pass "well-formed pack with matching rubric passes linter"
else
    fail "well-formed pack + matching rubric should pass but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 6: _TEMPLATE directory is skipped (not flagged as FAIL)
# ---------------------------------------------------------------------------
echo "--- Test 6: _TEMPLATE directory is skipped"
_T6_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T6_DIR}'" EXIT

# _TEMPLATE has no pack.json — if the linter didn't skip it, it would fail.
mkdir -p "${_T6_DIR}/_TEMPLATE"
cp "${AUDIT_DIR}/packs/_TEMPLATE/checks.md" "${_T6_DIR}/_TEMPLATE/checks.md"

# Also add a valid pack so the linter has something to lint.
make_valid_pack "${_T6_DIR}/test-real"

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T6_DIR}" --rubric "${_T6_DIR}/nonexistent-rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -eq 0 ] && ! echo "${output}" | grep -q "^FAIL: _TEMPLATE"; then
    pass "_TEMPLATE directory is skipped by linter"
else
    fail "_TEMPLATE should be skipped but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 7: absent packs/ directory → graceful exit 0 with NOTE
# ---------------------------------------------------------------------------
echo "--- Test 7: absent packs/ directory → graceful exit 0"
_T7_DIR="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${_T7_DIR}'" EXIT

output=""
exit_code=0
output=$(python3 "${LINTER}" --packs-dir "${_T7_DIR}/nonexistent" --rubric "${_T7_DIR}/nonexistent-rubric.json" 2>&1) || exit_code=$?

if [ "${exit_code}" -eq 0 ] && echo "${output}" | grep -qi "packs directory not found\|nothing to lint"; then
    pass "absent packs/ directory handled gracefully (exit 0)"
else
    fail "absent packs/ directory should exit 0 with NOTE but exit_code=${exit_code}: ${output}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
