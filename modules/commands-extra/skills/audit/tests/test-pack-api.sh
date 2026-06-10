#!/usr/bin/env bash
# test-pack-api.sh — Tests for the ccgm/api-contract audit pack (issue #631)
#
# Tests:
#   1. pack.json validates against pack.schema.json (stdlib validator via registry.py)
#   2. severity-rubric.json contains all api/* check ids from pack.json
#   3. lint-pack.py passes on the api-contract pack with the real rubric
#   4. checks.md contains all required template sections
#   5. checks.md documents TP/TN fixtures for each check:
#        missing-input-validation, mass-assignment, unbounded-list, missing-versioning
#   6. applies_when gates correctly:
#        6a. JS project (package.json present) → pack INCLUDED
#        6b. Go-only project (no package.json) → pack EXCLUDED
#   7. Runtime fixtures: Express-style handler with NO validation (TP) and one WITH
#      validation (TN) are created; pack schema + rubric validate; lint-pack passes
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACK_DIR="${AUDIT_DIR}/packs/api-contract"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Shared temp dir for the whole run; cleaned up on EXIT
TESTRUN_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/ccgm-test-api-XXXXXX")"
trap 'rm -rf "${TESTRUN_TMPDIR}"' EXIT

# ---------------------------------------------------------------------------
# Test 1: pack.json validates against pack.schema.json
# ---------------------------------------------------------------------------
echo "--- Test 1: pack.json validates (stdlib registry.py)"

_T1_PY="${TESTRUN_TMPDIR}/pack_validate_api.py"
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

_T1_RESULT=""
_T1_EXIT=0
_T1_RESULT=$(python3 "${_T1_PY}" "${REGISTRY}" "${PACK_DIR}/pack.json" 2>&1) || _T1_EXIT=$?

if [ "${_T1_EXIT}" -eq 0 ] && echo "${_T1_RESULT}" | grep -q "^VALID$"; then
    pass "api-contract/pack.json validates against pack.schema.json"
else
    fail "api-contract/pack.json failed validation: ${_T1_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 2: severity-rubric.json contains all api/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 2: rubric contains all api/* check ids"

EXPECTED_IDS=(
    "api/missing-input-validation"
    "api/mass-assignment"
    "api/unbounded-list"
    "api/missing-versioning"
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
    pass "rubric contains all ${#EXPECTED_IDS[@]} api/* check ids"
else
    fail "rubric missing ids:${_T2_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 3: lint-pack.py passes on the api-contract pack with the real rubric
# ---------------------------------------------------------------------------
echo "--- Test 3: lint-pack.py passes on api-contract pack"

_T3_OUTPUT=""
_T3_EXIT=0
_T3_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T3_EXIT=$?

if [ "${_T3_EXIT}" -eq 0 ] && echo "${_T3_OUTPUT}" | grep -q "^PASS: api-contract"; then
    pass "lint-pack.py reports PASS for api-contract pack"
else
    fail "lint-pack.py did not report PASS for api-contract: exit=${_T3_EXIT}, output=${_T3_OUTPUT}"
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
# Test 5: checks.md documents TP/TN fixtures for every check
# ---------------------------------------------------------------------------
echo "--- Test 5: checks.md documents TP/TN fixtures for each check"

SEEDED_CHECK_IDS=(
    "api/missing-input-validation"
    "api/mass-assignment"
    "api/unbounded-list"
    "api/missing-versioning"
)

_T5_ERRORS=""

for check_id in "${SEEDED_CHECK_IDS[@]}"; do
    # check-id appears in checks.md
    if ! grep -q "${check_id}" "${CHECKS_MD}"; then
        _T5_ERRORS="${_T5_ERRORS}\n  check-id '${check_id}' not found in checks.md"
        continue
    fi

    # Extract the per-check section (from ### heading to next ### heading or EOF)
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

    # True positive marker
    if ! echo "${_SECTION}" | grep -q "True positive\|FINDS:"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    # True negative marker
    if ! echo "${_SECTION}" | grep -q "True negative\|should produce NO"; then
        _T5_ERRORS="${_T5_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

if [ -z "${_T5_ERRORS}" ]; then
    pass "checks.md documents TP/TN fixtures for all ${#SEEDED_CHECK_IDS[@]} checks"
else
    fail "checks.md fixture coverage issues:$(printf '%b' "${_T5_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 6: applies_when gates correctly via registry.py
#   6a. JS project (package.json present) → pack INCLUDED
#   6b. Go-only project (no package.json) → pack EXCLUDED
# ---------------------------------------------------------------------------
echo "--- Test 6: applies_when gates correctly"

TMPDIR_PACKS="${TESTRUN_TMPDIR}/packs-gate"
mkdir -p "${TMPDIR_PACKS}/api-contract"
cp "${PACK_DIR}/pack.json" "${TMPDIR_PACKS}/api-contract/pack.json"

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
assert 'ccgm/api-contract' in ids, 'ccgm/api-contract not in: ' + str(ids)
" 2>/dev/null; then
        _T6A_INCLUDED=1
    fi
fi

if [ "${_T6A_INCLUDED}" -eq 1 ]; then
    pass "ccgm/api-contract INCLUDED for JS project (language:javascript)"
else
    fail "ccgm/api-contract should be INCLUDED for JS project but was not. exit=${_T6A_EXIT}, result=${_T6A_RESULT}"
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
assert 'ccgm/api-contract' not in ids, 'ccgm/api-contract should not be in: ' + str(ids)
" 2>/dev/null; then
        _T6B_EXCLUDED=1
    fi
fi

if [ "${_T6B_EXCLUDED}" -eq 1 ]; then
    pass "ccgm/api-contract EXCLUDED for Go-only project (no language:javascript)"
else
    fail "ccgm/api-contract should be EXCLUDED for Go project but was not. exit=${_T6B_EXIT}, result=${_T6B_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 7: Runtime fixtures — Express handler fixtures (static structure only;
#         no LLM assertion). TP fixture has no schema validation; TN has zod.
#         Verify: files created, pack validates, rubric validates, lint-pack passes.
# ---------------------------------------------------------------------------
echo "--- Test 7: Runtime fixtures (TP handler without validation, TN with zod)"

FIXTURE_DIR="${TESTRUN_TMPDIR}/fixture-project"
mkdir -p "${FIXTURE_DIR}/src/routes"

# TP: Express handler reading req.body directly — no schema validation
cat > "${FIXTURE_DIR}/src/routes/users.ts" <<'TSEOF'
// api-contract fixture: missing-input-validation (TP)
// req.body used directly — no zod/joi/yup validation before ORM call
import express from "express";
const router = express.Router();

router.post("/users", async (req, res) => {
  const { email, role } = req.body;
  // mass-assignment (TP): full spread into ORM create
  const user = await db.user.create({ data: { ...req.body } });
  // unbounded-list (TP): findMany with no take
  const allUsers = await db.user.findMany();
  res.json({ user, allUsers });
});

export default router;
TSEOF

# TN: Express handler with zod validation — should NOT trigger missing-input-validation
cat > "${FIXTURE_DIR}/src/routes/posts.ts" <<'TSEOF'
// api-contract fixture: with zod validation (TN for missing-input-validation)
import express from "express";
import { z } from "zod";
const router = express.Router();

const CreatePostBody = z.object({
  title: z.string().min(1).max(200),
  content: z.string(),
});

router.post("/api/v1/posts", async (req, res) => {
  const { title, content } = CreatePostBody.parse(req.body);
  // Only allow-listed fields forwarded to ORM (TN for mass-assignment)
  const post = await db.post.create({ data: { title, content } });
  // Bounded list with max cap (TN for unbounded-list)
  const limit = Math.min(Number(req.query.limit) || 20, 100);
  const posts = await db.post.findMany({ take: limit });
  res.json({ post, posts });
});

export default router;
TSEOF

# package.json so the ecosystem detector recognises this as a JS project
cat > "${FIXTURE_DIR}/package.json" <<'JSON'
{ "name": "api-contract-test-fixture", "version": "1.0.0", "dependencies": { "express": "^4.18.0", "zod": "^3.22.0" } }
JSON

# Verify files were created
if [ -f "${FIXTURE_DIR}/src/routes/users.ts" ] && \
   [ -f "${FIXTURE_DIR}/src/routes/posts.ts" ] && \
   [ -f "${FIXTURE_DIR}/package.json" ]; then
    pass "JS runtime fixtures created (TP handler, TN handler, package.json)"
else
    fail "JS runtime fixture creation failed"
fi

# Pack schema and rubric must still validate after adding the rubric entries
_T7_LINT_OUTPUT=""
_T7_LINT_EXIT=0
_T7_LINT_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T7_LINT_EXIT=$?

if [ "${_T7_LINT_EXIT}" -eq 0 ] && echo "${_T7_LINT_OUTPUT}" | grep -q "^PASS: api-contract"; then
    pass "lint-pack.py still reports PASS for api-contract after adding rubric entries"
else
    fail "lint-pack.py failed after rubric entries added: exit=${_T7_LINT_EXIT}, output=${_T7_LINT_OUTPUT}"
fi

# Verify rubric JSON is still valid after edit
_T7_RUBRIC_EXIT=0
python3 -m json.tool "${RUBRIC}" > /dev/null 2>&1 || _T7_RUBRIC_EXIT=$?
if [ "${_T7_RUBRIC_EXIT}" -eq 0 ]; then
    pass "severity-rubric.json is valid JSON after api/* entries added"
else
    fail "severity-rubric.json is NOT valid JSON after api/* entries added"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
