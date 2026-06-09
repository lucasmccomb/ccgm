#!/usr/bin/env bash
# test-registry.sh — unit tests for the pack registry loader + schema validation.
# Module-local; NOT registered in module.json.
#
# Tests:
#   1. pack-go.json validates against pack.schema.json (stdlib validator)
#   2. pack-secrets.json validates against pack.schema.json (stdlib validator)
#   3. Given detected_ecosystems=[javascript], pack-go.json (language:go) is EXCLUDED
#   4. Given detected_ecosystems=[javascript], pack-secrets.json (always) is INCLUDED
#   5. pack-malformed.json fails validation with a clear error message
#   6. check-id containing a comma is REJECTED by the validator (Fix 1 pin)
#   7. tool-native fingerprint validates against finding.schema.json; empty fingerprint is REJECTED (Fix 2 pin)
#
# Passes: exit 0.  Fails: exit 1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
FIXTURES="${SCRIPT_DIR}/fixtures"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Helper: validate a pack JSON file via registry.py's validate_pack function.
# Prints "VALID" and exits 0 on success; "INVALID: <msg>" and exits 1 on failure.
# ---------------------------------------------------------------------------
validate_pack_file() {
    local pack_file="$1"
    python3 - "$REGISTRY" "$pack_file" <<'PYEOF'
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
}

# ---------------------------------------------------------------------------
# Helper: run registry.py with a given detector JSON and a temp packs directory
# populated from the given fixture pack files.
# ---------------------------------------------------------------------------
run_registry_with_packs() {
    local detector_json="$1"
    shift
    local tmpdir
    tmpdir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmpdir}'" RETURN

    for pf in "$@"; do
        local pack_name
        pack_name="$(basename "${pf}" .json)"
        mkdir -p "${tmpdir}/${pack_name}"
        cp "${pf}" "${tmpdir}/${pack_name}/pack.json"
    done

    CCGM_PACKS_DIR="${tmpdir}" python3 "${REGISTRY}" <<< "${detector_json}"
}

# ---------------------------------------------------------------------------
# Helper: assert that a JSON list returned by registry contains/excludes an id
# ---------------------------------------------------------------------------
assert_includes() {
    local json="$1"
    local pack_id="$2"
    echo "${json}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert '$pack_id' in ids, '$pack_id should be in result, got: ' + str(ids)
"
}

assert_excludes() {
    local json="$1"
    local pack_id="$2"
    echo "${json}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert '$pack_id' not in ids, '$pack_id should NOT be in result, got: ' + str(ids)
"
}

# ---------------------------------------------------------------------------
# Test 1: pack-go.json is valid
# ---------------------------------------------------------------------------
echo "--- Test 1: pack-go.json validates (stdlib)"
result=""
if result=$(validate_pack_file "${FIXTURES}/pack-go.json" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    pass "pack-go.json is valid"
else
    fail "pack-go.json failed validation: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 2: pack-secrets.json is valid
# ---------------------------------------------------------------------------
echo "--- Test 2: pack-secrets.json validates (stdlib)"
result=""
if result=$(validate_pack_file "${FIXTURES}/pack-secrets.json" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    pass "pack-secrets.json is valid"
else
    fail "pack-secrets.json failed validation: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 3: language:go pack EXCLUDED when detected_ecosystems = [javascript]
# ---------------------------------------------------------------------------
echo "--- Test 3: language:go pack excluded for javascript ecosystem"
DETECTOR_JS='{"detected_ecosystems":["javascript"],"project_shape":{},"available_tools":[]}'
result=""
if result=$(run_registry_with_packs "${DETECTOR_JS}" \
        "${FIXTURES}/pack-go.json" \
        "${FIXTURES}/pack-secrets.json" 2>/dev/null); then
    if assert_excludes "${result}" "ccgm/go-security" 2>/dev/null; then
        pass "ccgm/go-security excluded when detected_ecosystems=[javascript]"
    else
        fail "ccgm/go-security was incorrectly included. Registry output: ${result}"
    fi
else
    fail "registry.py returned non-zero for test 3: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 4: always pack INCLUDED when detected_ecosystems = [javascript]
# ---------------------------------------------------------------------------
echo "--- Test 4: always pack included for javascript ecosystem"
result=""
if result=$(run_registry_with_packs "${DETECTOR_JS}" \
        "${FIXTURES}/pack-go.json" \
        "${FIXTURES}/pack-secrets.json" 2>/dev/null); then
    if assert_includes "${result}" "ccgm/secrets" 2>/dev/null; then
        pass "ccgm/secrets included (applies_when=[always]) when detected_ecosystems=[javascript]"
    else
        fail "ccgm/secrets was incorrectly excluded. Registry output: ${result}"
    fi
else
    fail "registry.py returned non-zero for test 4: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 5: malformed pack fails validation with a clear error
# ---------------------------------------------------------------------------
echo "--- Test 5: pack-malformed.json fails validation"
result=""
if result=$(validate_pack_file "${FIXTURES}/pack-malformed.json" 2>&1); then
    fail "pack-malformed.json should have failed validation but passed: ${result}"
else
    if echo "${result}" | grep -q "INVALID:"; then
        pass "pack-malformed.json correctly rejected with clear error: ${result}"
    else
        fail "pack-malformed.json rejected but error message unclear: ${result}"
    fi
fi

# ---------------------------------------------------------------------------
# Helper: validate a finding JSON file against finding.schema.json using
# Python stdlib (validates pattern, type, required, enum, additionalProperties).
# Prints "VALID" and exits 0 on success; "INVALID: <msg>" and exits 1 on failure.
# ---------------------------------------------------------------------------
FINDING_SCHEMA="${AUDIT_DIR}/schemas/finding.schema.json"

# Write the Python validator script to a temp file so it can be called without
# heredoc-inside-command-substitution issues.
_FINDING_VALIDATOR_PY="$(mktemp /tmp/finding_validator_XXXXXX.py)"
cat > "${_FINDING_VALIDATOR_PY}" <<'PYEOF'
import sys, json, re

schema_path = sys.argv[1]
finding_path = sys.argv[2]

with open(schema_path, encoding="utf-8") as fh:
    schema = json.load(fh)

with open(finding_path, encoding="utf-8") as fh:
    finding = json.load(fh)

# Validate required fields
required = schema.get("required", [])
missing = [f for f in required if f not in finding]
if missing:
    print("INVALID: missing required fields: " + str(sorted(missing)))
    sys.exit(1)

# Validate each property
props = schema.get("properties", {})
for key, val in finding.items():
    if key not in props:
        if not schema.get("additionalProperties", True):
            print("INVALID: unexpected field: " + key)
            sys.exit(1)
        continue
    prop = props[key]
    if prop.get("type") == "string" and not isinstance(val, str):
        print("INVALID: " + key + " must be a string")
        sys.exit(1)
    pattern = prop.get("pattern")
    if pattern and isinstance(val, str):
        if not re.fullmatch(pattern, val):
            print("INVALID: " + key + " does not match pattern " + pattern + " (got " + repr(val) + ")")
            sys.exit(1)
    enum = prop.get("enum")
    if enum and val not in enum:
        print("INVALID: " + key + " must be one of " + str(enum) + " (got " + repr(val) + ")")
        sys.exit(1)

print("VALID")
sys.exit(0)
PYEOF
# shellcheck disable=SC2064
trap "rm -f '${_FINDING_VALIDATOR_PY}'" EXIT

validate_finding_file() {
    local finding_file="$1"
    python3 "${_FINDING_VALIDATOR_PY}" "${FINDING_SCHEMA}" "${finding_file}"
}

# Write the pack-id validator script to a temp file (avoids heredoc-in-subshell)
_PACK_VALIDATE_PY="$(mktemp /tmp/pack_validate_XXXXXX.py)"
cat > "${_PACK_VALIDATE_PY}" <<'PYEOF'
import sys, json, importlib.util, pathlib

registry_py = pathlib.Path(sys.argv[1])
pack_file   = pathlib.Path(sys.argv[2])

spec = importlib.util.spec_from_file_location("registry", str(registry_py))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

with open(pack_file, encoding="utf-8") as fh:
    pack = json.load(fh)

try:
    mod.validate_pack(pack, str(pack_file))
    print("VALID")
    sys.exit(0)
except mod.ValidationError as exc:
    print("INVALID: " + str(exc))
    sys.exit(1)
PYEOF
# shellcheck disable=SC2064
trap "rm -f '${_PACK_VALIDATE_PY}' '${_FINDING_VALIDATOR_PY}'" EXIT

validate_pack_from_file() {
    local pack_file="$1"
    python3 "${_PACK_VALIDATE_PY}" "${REGISTRY}" "${pack_file}"
}

# ---------------------------------------------------------------------------
# Test 6: check-id with comma is REJECTED (pins Fix 1 — validator regex no comma)
# ---------------------------------------------------------------------------
echo "--- Test 6: check-id with comma is rejected"
_T6_PACK="$(mktemp /tmp/pack_comma_XXXXXX.json)"
cat > "${_T6_PACK}" <<'JSON'
{
  "id": "ccgm/test-comma",
  "name": "Comma Test",
  "version": "1.0.0",
  "applies_when": ["always"],
  "checks": [
    {
      "id": "bad/check,id",
      "severity": "high",
      "confidence": "high",
      "detection": "tool"
    }
  ]
}
JSON
result=""
if result=$(validate_pack_from_file "${_T6_PACK}" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    fail "check-id 'bad/check,id' should have been rejected but was VALID"
else
    if echo "${result}" | grep -q "INVALID:"; then
        pass "check-id 'bad/check,id' correctly rejected: ${result}"
    else
        fail "check-id 'bad/check,id' rejected but error unclear: ${result}"
    fi
fi
rm -f "${_T6_PACK}"

# ---------------------------------------------------------------------------
# Test 7a: tool-native fingerprint validates against finding.schema.json (pins Fix 2)
# ---------------------------------------------------------------------------
echo "--- Test 7a: tool-native fingerprint validates against finding.schema.json"
# gitleaks-style fingerprint: hex+colon+path+colon+rule+colon+lineno
TOOL_NATIVE_FINGERPRINT="a1b2c3d4e5f6a7b8:path/to/file:rule-name:42"
_T7A_FINDING="$(mktemp /tmp/finding_tool_XXXXXX.json)"
cat > "${_T7A_FINDING}" <<JSON
{
  "check_id": "secrets/hardcoded-api-key",
  "rule_id": "generic-api-key",
  "severity": "critical",
  "confidence": "high",
  "location": {"path": "src/config.js", "line": 10},
  "message": "Hardcoded API key detected",
  "fingerprint": "${TOOL_NATIVE_FINGERPRINT}",
  "detection": "tool",
  "source": "tool"
}
JSON
result=""
if result=$(validate_finding_file "${_T7A_FINDING}" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    pass "tool-native fingerprint '${TOOL_NATIVE_FINGERPRINT}' accepted by finding.schema.json"
else
    fail "tool-native fingerprint '${TOOL_NATIVE_FINGERPRINT}' was incorrectly rejected: ${result}"
fi
rm -f "${_T7A_FINDING}"

# ---------------------------------------------------------------------------
# Test 7b: empty fingerprint is REJECTED by finding.schema.json (pins Fix 2)
# ---------------------------------------------------------------------------
echo "--- Test 7b: empty fingerprint is rejected by finding.schema.json"
_T7B_FINDING="$(mktemp /tmp/finding_emptyfp_XXXXXX.json)"
cat > "${_T7B_FINDING}" <<'JSON'
{
  "check_id": "secrets/hardcoded-api-key",
  "rule_id": "generic-api-key",
  "severity": "critical",
  "confidence": "high",
  "location": {"path": "src/config.js", "line": 10},
  "message": "Hardcoded API key detected",
  "fingerprint": "",
  "detection": "tool",
  "source": "tool"
}
JSON
result=""
if result=$(validate_finding_file "${_T7B_FINDING}" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    fail "empty fingerprint should have been rejected but was VALID"
else
    if echo "${result}" | grep -q "INVALID:"; then
        pass "empty fingerprint correctly rejected: ${result}"
    else
        fail "empty fingerprint rejected but error unclear: ${result}"
    fi
fi
rm -f "${_T7B_FINDING}"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
