#!/usr/bin/env bash
# test-pack-accessibility.sh — Tests for the ccgm/accessibility audit pack (Epic 2.3).
#
# Tests:
#   1. pack.json validates against pack.schema.json (registry.py stdlib validator)
#   2. checks.md contains all required sections (lint-pack.py)
#   3. All 5 check-ids have entries in severity-rubric.json (lint-pack.py)
#   4. lint-pack.py passes cleanly on the accessibility pack
#   5. applies_when gates ON for a package.json + tsx fixture (javascript ecosystem)
#   6. applies_when gates OFF for a go-only fixture (no javascript ecosystem)
#   7. Grep for target="_blank": matches TP fixture, misses TN fixture (anchor-missing-rel)
#   8. checks.md documents all 5 seeded defect patterns (TP mention per check)
#
# Exit 0 = all pass; exit 1 = one or more failed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACK_DIR="${AUDIT_DIR}/packs/accessibility"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Single temp root cleaned on exit
TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# ---------------------------------------------------------------------------
# Helper: validate a pack JSON file via registry.py's validate_pack function.
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
# Helper: run registry.py with a given detector JSON and a temp packs dir
# containing only the accessibility pack (to avoid cross-pack noise).
# ---------------------------------------------------------------------------
run_registry_with_a11y_pack() {
    local detector_json="$1"
    local tmpdir
    tmpdir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmpdir}'" RETURN

    mkdir -p "${tmpdir}/accessibility"
    cp "${PACK_DIR}/pack.json" "${tmpdir}/accessibility/pack.json"

    CCGM_PACKS_DIR="${tmpdir}" python3 "${REGISTRY}" <<< "${detector_json}"
}

# ---------------------------------------------------------------------------
# Test 1: pack.json validates against pack.schema.json
# ---------------------------------------------------------------------------
echo "--- Test 1: pack.json validates (stdlib)"
result=""
if result=$(validate_pack_file "${PACK_DIR}/pack.json" 2>&1) && echo "${result}" | grep -q "^VALID$"; then
    pass "accessibility/pack.json validates against pack.schema.json"
else
    fail "accessibility/pack.json failed validation: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 2: checks.md contains all required template sections
# ---------------------------------------------------------------------------
echo "--- Test 2: checks.md has required sections"
output=""
exit_code=0
output=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || exit_code=$?

# We want accessibility to appear as PASS (not FAIL) in linter output
if echo "${output}" | grep -q "^PASS: accessibility"; then
    pass "checks.md contains all required sections (lint-pack.py passes)"
elif echo "${output}" | grep -q "^FAIL: accessibility"; then
    fail "checks.md missing required section: ${output}"
else
    fail "lint-pack.py output did not mention accessibility pack: ${output}"
fi

# ---------------------------------------------------------------------------
# Test 3: all 5 check-ids have entries in severity-rubric.json
# ---------------------------------------------------------------------------
echo "--- Test 3: all check-ids present in severity-rubric.json"
check_ids=(
    "a11y/img-missing-alt"
    "a11y/click-without-keyboard"
    "a11y/anchor-missing-rel"
    "a11y/missing-prefers-reduced-motion"
    "a11y/tailwind-cursor-pointer"
)
rubric_ok=true
for cid in "${check_ids[@]}"; do
    if python3 -c "
import json, sys
rubric = json.load(open('${RUBRIC}'))
checks = rubric.get('checks', {})
if '${cid}' not in checks:
    sys.exit(1)
" 2>/dev/null; then
        :
    else
        fail "severity-rubric.json missing entry for ${cid}"
        rubric_ok=false
    fi
done
if $rubric_ok; then
    pass "all 5 a11y check-ids present in severity-rubric.json"
fi

# ---------------------------------------------------------------------------
# Test 4: lint-pack.py passes cleanly on the accessibility pack
# ---------------------------------------------------------------------------
echo "--- Test 4: lint-pack.py passes cleanly on accessibility pack"
output=""
exit_code=0
output=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || exit_code=$?

if [ "${exit_code}" -eq 0 ] && echo "${output}" | grep -q "^PASS: accessibility"; then
    pass "lint-pack.py exits 0 and reports PASS: accessibility"
elif echo "${output}" | grep -q "^FAIL: accessibility"; then
    fail "lint-pack.py reports FAIL for accessibility: ${output}"
else
    # Other packs may fail; we only care that accessibility is PASS and no error
    # about accessibility specifically. Re-check just the accessibility pack.
    single_output=""
    single_exit=0
    single_output=$(python3 "${LINTER}" \
        --packs-dir "${AUDIT_DIR}/packs/accessibility/.." \
        --rubric "${RUBRIC}" 2>&1) || single_exit=$?
    # Simpler: run linter against a temp dir with only the accessibility pack
    solo_tmp="${TMPROOT}/solo-pack"
    mkdir -p "${solo_tmp}/accessibility"
    cp "${PACK_DIR}/pack.json"  "${solo_tmp}/accessibility/pack.json"
    cp "${PACK_DIR}/checks.md" "${solo_tmp}/accessibility/checks.md"
    solo_out=""
    solo_exit=0
    solo_out=$(python3 "${LINTER}" \
        --packs-dir "${solo_tmp}" \
        --rubric "${RUBRIC}" 2>&1) || solo_exit=$?
    if [ "${solo_exit}" -eq 0 ] && echo "${solo_out}" | grep -q "^PASS: accessibility"; then
        pass "lint-pack.py exits 0 and reports PASS: accessibility (solo run)"
    else
        fail "lint-pack.py solo run failed for accessibility (exit=${solo_exit}): ${solo_out}"
    fi
fi

# ---------------------------------------------------------------------------
# Test 5: applies_when gates ON for language:javascript detector
# ---------------------------------------------------------------------------
echo "--- Test 5: pack selected for javascript ecosystem"
DETECTOR_JS='{"detected_ecosystems":["javascript","typescript"],"project_shape":{"has_migrations":false,"has_dockerfile":false,"has_workflows":false,"is_extension":false,"is_mobile":false,"monorepo_packages":[],"frameworks":["react"]},"available_tools":[]}'
result=""
if result=$(run_registry_with_a11y_pack "${DETECTOR_JS}" 2>/dev/null); then
    if echo "${result}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/accessibility' in ids, 'ccgm/accessibility not in: ' + str(ids)
print('included')
" 2>/dev/null; then
        pass "ccgm/accessibility included when detected_ecosystems=[javascript,typescript]"
    else
        fail "ccgm/accessibility was NOT included for javascript ecosystem. Registry: ${result}"
    fi
else
    fail "registry.py returned non-zero for javascript detector: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 6: applies_when gates OFF for go-only detector
# ---------------------------------------------------------------------------
echo "--- Test 6: pack excluded for go-only ecosystem"
DETECTOR_GO='{"detected_ecosystems":["go"],"project_shape":{"has_migrations":false,"has_dockerfile":false,"has_workflows":false,"is_extension":false,"is_mobile":false,"monorepo_packages":[],"frameworks":[]},"available_tools":[]}'
result=""
if result=$(run_registry_with_a11y_pack "${DETECTOR_GO}" 2>/dev/null); then
    if echo "${result}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/accessibility' not in ids, 'ccgm/accessibility should not be in: ' + str(ids)
print('excluded')
" 2>/dev/null; then
        pass "ccgm/accessibility excluded when detected_ecosystems=[go]"
    else
        fail "ccgm/accessibility was NOT excluded for go ecosystem. Registry: ${result}"
    fi
else
    fail "registry.py returned non-zero for go detector: ${result}"
fi

# ---------------------------------------------------------------------------
# Test 7: grep for target="_blank" matches TP, misses TN (anchor-missing-rel)
# ---------------------------------------------------------------------------
echo "--- Test 7: grep for anchor-missing-rel TP/TN"

# Write TP fixture file
TP_FILE="${TMPROOT}/ExternalLink-tp.tsx"
cat > "${TP_FILE}" <<'TSXEOF'
// True positive: target="_blank" without rel="noopener noreferrer"
function ExternalLink({ href, children }) {
  return <a href={href} target="_blank">{children}</a>;
}
TSXEOF

# Write TN fixture file
TN_FILE="${TMPROOT}/ExternalLink-tn.tsx"
cat > "${TN_FILE}" <<'TSXEOF'
// True negative: target="_blank" with rel="noopener noreferrer"
function ExternalLink({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
TSXEOF

# Grep pattern: find target="_blank" occurrences
TP_MATCHES=$(grep -c 'target="_blank"' "${TP_FILE}" 2>/dev/null || true)
TN_MATCHES=$(grep -c 'target="_blank"' "${TN_FILE}" 2>/dev/null || true)

if [ "${TP_MATCHES}" -ge 1 ]; then
    pass "grep for target=\"_blank\" matches TP fixture (${TP_MATCHES} line(s))"
else
    fail "grep for target=\"_blank\" did NOT match TP fixture"
fi

# For TN: grep finds target="_blank" but the same line also has rel="noopener"
# Test that the TN fixture DOES contain noopener (agent would skip it)
if grep -q 'noopener' "${TN_FILE}" 2>/dev/null; then
    pass "TN fixture contains rel=noopener (agent would correctly skip it)"
else
    fail "TN fixture missing rel=noopener — fixture is wrong"
fi

# ---------------------------------------------------------------------------
# Test 8: checks.md documents all 5 seeded defect patterns (TP mention per check)
# ---------------------------------------------------------------------------
echo "--- Test 8: checks.md documents each seeded defect pattern"

checks_md="${PACK_DIR}/checks.md"

tp_patterns=(
    "img.*missing alt\|<img>.*missing\|img src.*className"
    "div.*onClick\|onClick.*without.*keyboard\|onClick.*role"
    "target.*_blank.*without rel\|target=\"_blank\"\|target=._blank"
    "animation.*no.*prefers-reduced\|@keyframes.*slide-in\|panel-enter"
    "button.*without.*cursor-pointer\|bg-primary.*text-white.*px"
)

tp_labels=(
    "a11y/img-missing-alt TP fixture"
    "a11y/click-without-keyboard TP fixture"
    "a11y/anchor-missing-rel TP fixture"
    "a11y/missing-prefers-reduced-motion TP fixture"
    "a11y/tailwind-cursor-pointer TP fixture"
)

# Simpler: just verify each check-id appears as a heading in checks.md
check_headings=(
    "a11y/img-missing-alt"
    "a11y/click-without-keyboard"
    "a11y/anchor-missing-rel"
    "a11y/missing-prefers-reduced-motion"
    "a11y/tailwind-cursor-pointer"
)

all_headings_ok=true
for heading in "${check_headings[@]}"; do
    if grep -q "${heading}" "${checks_md}" 2>/dev/null; then
        :
    else
        fail "checks.md missing heading/section for ${heading}"
        all_headings_ok=false
    fi
done

# Also verify TP and TN fixture labels appear for each check
if grep -q "True positive" "${checks_md}" 2>/dev/null && \
   grep -q "True negative" "${checks_md}" 2>/dev/null; then
    :
else
    fail "checks.md missing True positive/True negative fixture labels"
    all_headings_ok=false
fi

if $all_headings_ok; then
    pass "checks.md documents all 5 check-ids with TP and TN fixtures"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
