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
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
