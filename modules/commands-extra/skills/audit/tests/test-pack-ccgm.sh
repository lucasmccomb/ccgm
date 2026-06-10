#!/usr/bin/env bash
# test-pack-ccgm.sh — Tests for the ccgm/ccgm-hygiene and ccgm/ccgm-standards audit packs
# (issue #633).
#
# Tests:
#   1.  ccgm-hygiene/pack.json validates against pack.schema.json (registry.py)
#   2.  ccgm-standards/pack.json validates against pack.schema.json (registry.py)
#   3.  severity-rubric.json contains all ccgm/* check ids from both packs
#   4.  lint-pack.py passes on ccgm-hygiene with the real rubric
#   5.  lint-pack.py passes on ccgm-standards with the real rubric
#   6.  ccgm-hygiene/checks.md has required sections
#   7.  ccgm-standards/checks.md has required sections
#   8.  checks.md documents TP/TN fixtures for each check (all 5 checks)
#   9.  applies_when=always: both packs are SELECTED for any detector input
#  10.  grep TP: a file with TODO: produces a grep match for shipped-todo-marker
#  11.  grep TN: a file without any markers produces no grep match for shipped-todo-marker
#  12.  grep TP: a script with "wrangler pages deploy" produces a grep match for cloudflare-pages-no-git
#  13.  grep TN: a script without "wrangler pages deploy" produces no grep match
#  14.  A source file with process.env.MISSING_VAR and a .env.example lacking it constitutes
#       a TP fixture for env-example-drift (fixture creation + structural assertion only)
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HYGIENE_PACK="${AUDIT_DIR}/packs/ccgm-hygiene"
STANDARDS_PACK="${AUDIT_DIR}/packs/ccgm-standards"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Single temp root; cleaned on exit.
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/test-pack-ccgm.XXXXXX")"
trap 'rm -rf "${TMPROOT}"' EXIT

# ---------------------------------------------------------------------------
# Reusable: validate a pack.json via registry.py's validate_pack
# ---------------------------------------------------------------------------
_VALIDATE_PY="$(mktemp "${TMPROOT}/validate_pack.XXXXXX.py")"
cat > "${_VALIDATE_PY}" <<'PYEOF'
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

# ---------------------------------------------------------------------------
# Test 1: ccgm-hygiene/pack.json validates
# ---------------------------------------------------------------------------
echo "--- Test 1: ccgm-hygiene/pack.json validates"

_T1_RESULT=""
_T1_EXIT=0
_T1_RESULT=$(python3 "${_VALIDATE_PY}" "${REGISTRY}" "${HYGIENE_PACK}/pack.json" 2>&1) || _T1_EXIT=$?

if [ "${_T1_EXIT}" -eq 0 ] && echo "${_T1_RESULT}" | grep -q "^VALID$"; then
    pass "ccgm-hygiene/pack.json validates against pack.schema.json"
else
    fail "ccgm-hygiene/pack.json failed validation: ${_T1_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 2: ccgm-standards/pack.json validates
# ---------------------------------------------------------------------------
echo "--- Test 2: ccgm-standards/pack.json validates"

_T2_RESULT=""
_T2_EXIT=0
_T2_RESULT=$(python3 "${_VALIDATE_PY}" "${REGISTRY}" "${STANDARDS_PACK}/pack.json" 2>&1) || _T2_EXIT=$?

if [ "${_T2_EXIT}" -eq 0 ] && echo "${_T2_RESULT}" | grep -q "^VALID$"; then
    pass "ccgm-standards/pack.json validates against pack.schema.json"
else
    fail "ccgm-standards/pack.json failed validation: ${_T2_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 3: rubric contains all ccgm/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 3: rubric contains all ccgm/* check ids"

EXPECTED_IDS=(
    "ccgm/shipped-todo-marker"
    "ccgm/env-example-drift"
    "ccgm/cloudflare-pages-no-git"
    "ccgm/project-standards-conformance"
    "ccgm/mcp-tool-annotations"
)

_T3_MISSING=""
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
        _T3_MISSING="${_T3_MISSING} ${check_id}"
    fi
done

if [ -z "${_T3_MISSING}" ]; then
    pass "rubric contains all ${#EXPECTED_IDS[@]} ccgm/* check ids"
else
    fail "rubric missing ids:${_T3_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 4: lint-pack.py passes on ccgm-hygiene
# ---------------------------------------------------------------------------
echo "--- Test 4: lint-pack.py passes on ccgm-hygiene pack"

# Run linter across all packs (including new ones) to detect regressions.
_T4_OUTPUT=""
_T4_EXIT=0
_T4_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T4_EXIT=$?

if [ "${_T4_EXIT}" -eq 0 ] && echo "${_T4_OUTPUT}" | grep -q "^PASS: ccgm-hygiene"; then
    pass "lint-pack.py reports PASS for ccgm-hygiene"
else
    fail "lint-pack.py did not PASS for ccgm-hygiene: exit=${_T4_EXIT}, output=${_T4_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Test 5: lint-pack.py passes on ccgm-standards
# ---------------------------------------------------------------------------
echo "--- Test 5: lint-pack.py passes on ccgm-standards pack"

if [ "${_T4_EXIT}" -eq 0 ] && echo "${_T4_OUTPUT}" | grep -q "^PASS: ccgm-standards"; then
    pass "lint-pack.py reports PASS for ccgm-standards"
else
    fail "lint-pack.py did not PASS for ccgm-standards: exit=${_T4_EXIT}, output=${_T4_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Test 6: ccgm-hygiene/checks.md has all required sections
# ---------------------------------------------------------------------------
echo "--- Test 6: ccgm-hygiene/checks.md has required sections"

HYGIENE_MD="${HYGIENE_PACK}/checks.md"
_REQUIRED_SECTIONS=(
    "^## Scope"
    "^## applies_when Rationale"
    "^## Checks"
    "^## Quality Checklist"
)

_T6_MISSING=""
for section in "${_REQUIRED_SECTIONS[@]}"; do
    if ! grep -qiE "${section}" "${HYGIENE_MD}"; then
        _T6_MISSING="${_T6_MISSING} '${section}'"
    fi
done

if [ -z "${_T6_MISSING}" ]; then
    pass "ccgm-hygiene/checks.md contains all required sections"
else
    fail "ccgm-hygiene/checks.md missing sections:${_T6_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 7: ccgm-standards/checks.md has all required sections
# ---------------------------------------------------------------------------
echo "--- Test 7: ccgm-standards/checks.md has required sections"

STANDARDS_MD="${STANDARDS_PACK}/checks.md"

_T7_MISSING=""
for section in "${_REQUIRED_SECTIONS[@]}"; do
    if ! grep -qiE "${section}" "${STANDARDS_MD}"; then
        _T7_MISSING="${_T7_MISSING} '${section}'"
    fi
done

if [ -z "${_T7_MISSING}" ]; then
    pass "ccgm-standards/checks.md contains all required sections"
else
    fail "ccgm-standards/checks.md missing sections:${_T7_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 8: checks.md documents TP/TN fixtures for each check (all 5)
# ---------------------------------------------------------------------------
echo "--- Test 8: checks.md documents TP/TN fixtures for all 5 checks"

# Collect (check_id, checks_md_path) pairs
declare -a CHECK_IDS=(
    "ccgm/shipped-todo-marker"
    "ccgm/env-example-drift"
    "ccgm/cloudflare-pages-no-git"
    "ccgm/project-standards-conformance"
    "ccgm/mcp-tool-annotations"
)
declare -a CHECK_MDS=(
    "${HYGIENE_MD}"
    "${HYGIENE_MD}"
    "${HYGIENE_MD}"
    "${STANDARDS_MD}"
    "${STANDARDS_MD}"
)

_T8_ERRORS=""

for i in "${!CHECK_IDS[@]}"; do
    check_id="${CHECK_IDS[$i]}"
    md_file="${CHECK_MDS[$i]}"

    # check-id present in checks.md
    if ! grep -q "${check_id}" "${md_file}"; then
        _T8_ERRORS="${_T8_ERRORS}\n  check-id '${check_id}' not found in $(basename "${md_file}")"
        continue
    fi

    # Extract the section for this check-id
    _SECTION=$(python3 - "${md_file}" "${check_id}" <<'PYEOF' 2>/dev/null
import sys, re
md = open(sys.argv[1], encoding='utf-8').read()
check_id = sys.argv[2]
pattern = r'(### `' + re.escape(check_id) + r'`.*?)(?=\n### `|\Z)'
m = re.search(pattern, md, re.DOTALL)
if m:
    print(m.group(1))
PYEOF
)

    if ! echo "${_SECTION}" | grep -q "True positive\|FINDS:"; then
        _T8_ERRORS="${_T8_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    if ! echo "${_SECTION}" | grep -q "True negative\|should produce NO"; then
        _T8_ERRORS="${_T8_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

if [ -z "${_T8_ERRORS}" ]; then
    pass "checks.md documents TP/TN fixtures for all 5 ccgm/* checks"
else
    fail "fixture coverage issues:$(printf '%b' "${_T8_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 9: applies_when=always → both packs selected for any detector input
# ---------------------------------------------------------------------------
echo "--- Test 9: applies_when=always selects both packs for any detector"

# Temp packs dir with just the two new packs
_T9_PACKS="${TMPROOT}/packs-ccgm"
mkdir -p "${_T9_PACKS}/ccgm-hygiene" "${_T9_PACKS}/ccgm-standards"
cp "${HYGIENE_PACK}/pack.json"   "${_T9_PACKS}/ccgm-hygiene/pack.json"
cp "${STANDARDS_PACK}/pack.json" "${_T9_PACKS}/ccgm-standards/pack.json"

# Run registry with a bare detector (no ecosystems, no shape flags)
DETECTOR_BARE='{"detected_ecosystems":[],"project_shape":{},"available_tools":[]}'

_T9_RESULT=""
_T9_EXIT=0
_T9_RESULT=$(CCGM_PACKS_DIR="${_T9_PACKS}" python3 "${REGISTRY}" <<< "${DETECTOR_BARE}" 2>/dev/null) || _T9_EXIT=$?

_T9_OK=0
if [ "${_T9_EXIT}" -eq 0 ]; then
    if echo "${_T9_RESULT}" | python3 -c "
import json, sys
packs = json.load(sys.stdin)
ids = [p['id'] for p in packs]
assert 'ccgm/ccgm-hygiene' in ids, 'ccgm/ccgm-hygiene not in: ' + str(ids)
assert 'ccgm/ccgm-standards' in ids, 'ccgm/ccgm-standards not in: ' + str(ids)
" 2>/dev/null; then
        _T9_OK=1
    fi
fi

if [ "${_T9_OK}" -eq 1 ]; then
    pass "both ccgm packs SELECTED for bare detector (applies_when=always)"
else
    fail "ccgm packs not both selected: exit=${_T9_EXIT}, result=${_T9_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 10: grep TP — shipped-todo-marker detects a TODO: marker
# ---------------------------------------------------------------------------
echo "--- Test 10: grep TP — shipped-todo-marker detects TODO: marker"

_T10_FILE="${TMPROOT}/todo-tp.ts"
cat > "${_T10_FILE}" <<'EOF'
// Source file with a committed TODO marker — should be flagged
export function refreshToken(token: string) {
  // TODO: add rate limiting before calling this in production
  return fetchNewToken(token);
}
EOF

_T10_MATCH=""
_T10_EXIT=0
_T10_MATCH=$(grep -nE '\b(TODO|FIXME|XXX|HACK)\b' "${_T10_FILE}" 2>/dev/null) || _T10_EXIT=$?

if [ -n "${_T10_MATCH}" ]; then
    pass "grep TP: TODO: marker detected in source file (shipped-todo-marker)"
else
    fail "grep TP: TODO: marker should have been detected but was not"
fi

# ---------------------------------------------------------------------------
# Test 11: grep TN — shipped-todo-marker produces no match on clean file
# ---------------------------------------------------------------------------
echo "--- Test 11: grep TN — shipped-todo-marker: no match on clean file"

_T11_FILE="${TMPROOT}/todo-tn.ts"
cat > "${_T11_FILE}" <<'EOF'
// Source file with no deferred-work markers
export function refreshToken(token: string) {
  return fetchNewToken(token);
}
EOF

_T11_MATCH=""
_T11_EXIT=0
_T11_MATCH=$(grep -nE '\b(TODO|FIXME|XXX|HACK)\b' "${_T11_FILE}" 2>/dev/null) || _T11_EXIT=$?

if [ -z "${_T11_MATCH}" ]; then
    pass "grep TN: clean file produces no match (shipped-todo-marker)"
else
    fail "grep TN: clean file should produce no match but got: ${_T11_MATCH}"
fi

# ---------------------------------------------------------------------------
# Test 12: grep TP — cloudflare-pages-no-git detects wrangler pages deploy
# ---------------------------------------------------------------------------
echo "--- Test 12: grep TP — cloudflare-pages-no-git detects wrangler pages deploy"

_T12_FILE="${TMPROOT}/deploy-tp.sh"
cat > "${_T12_FILE}" <<'EOF'
#!/usr/bin/env bash
# CI deploy script — creates direct-upload CF Pages project (bad pattern)
npx wrangler pages deploy dist --project-name my-app
EOF

_T12_MATCH=""
_T12_EXIT=0
_T12_MATCH=$(grep -n 'wrangler pages deploy' "${_T12_FILE}" 2>/dev/null) || _T12_EXIT=$?

if [ -n "${_T12_MATCH}" ]; then
    pass "grep TP: wrangler pages deploy detected in deploy script (cloudflare-pages-no-git)"
else
    fail "grep TP: wrangler pages deploy should have been detected but was not"
fi

# ---------------------------------------------------------------------------
# Test 13: grep TN — cloudflare-pages-no-git: no match on script without CF Pages
# ---------------------------------------------------------------------------
echo "--- Test 13: grep TN — cloudflare-pages-no-git: no match on clean script"

_T13_FILE="${TMPROOT}/deploy-tn.sh"
cat > "${_T13_FILE}" <<'EOF'
#!/usr/bin/env bash
# CI deploy script — project uses Git integration via dashboard
npm run build
EOF

_T13_MATCH=""
_T13_EXIT=0
_T13_MATCH=$(grep -n 'wrangler pages deploy' "${_T13_FILE}" 2>/dev/null) || _T13_EXIT=$?

if [ -z "${_T13_MATCH}" ]; then
    pass "grep TN: clean deploy script produces no match (cloudflare-pages-no-git)"
else
    fail "grep TN: clean deploy script should produce no match but got: ${_T13_MATCH}"
fi

# ---------------------------------------------------------------------------
# Test 14: env-example-drift TP fixture — process.env.MISSING_VAR + incomplete .env.example
# ---------------------------------------------------------------------------
echo "--- Test 14: env-example-drift TP fixture creation"

_T14_DIR="${TMPROOT}/env-drift-tp"
mkdir -p "${_T14_DIR}/src"

# Source file referencing a var absent from .env.example
cat > "${_T14_DIR}/src/client.ts" <<'EOF'
// Env-example-drift TP fixture: STRIPE_SECRET_KEY referenced but not in .env.example
import Stripe from 'stripe';
import { createClient } from '@supabase/supabase-js';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_ANON_KEY!);
EOF

# .env.example missing STRIPE_SECRET_KEY
cat > "${_T14_DIR}/.env.example" <<'EOF'
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
# Note: STRIPE_SECRET_KEY is intentionally absent to trigger the check
EOF

# Assert fixture structure: source file references an env var absent from .env.example
_T14_REFS=$(grep -oE 'process\.env\.[A-Z_]+' "${_T14_DIR}/src/client.ts" | sed 's/process\.env\.//' | sort -u)
_T14_DOCUMENTED=$(grep -vE '^\s*#|^\s*$' "${_T14_DIR}/.env.example" | cut -d= -f1 | sort -u)

_T14_MISSING=$(comm -23 \
    <(echo "${_T14_REFS}") \
    <(echo "${_T14_DOCUMENTED}"))

if [ -n "${_T14_MISSING}" ]; then
    pass "env-example-drift TP fixture: source references vars absent from .env.example (${_T14_MISSING})"
else
    fail "env-example-drift TP fixture: expected at least one undocumented env var but found none"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
