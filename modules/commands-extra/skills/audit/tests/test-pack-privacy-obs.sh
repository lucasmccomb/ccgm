#!/usr/bin/env bash
# test-pack-privacy-obs.sh — Tests for the ccgm/privacy and ccgm/observability audit packs
# (issue #632, Epic 4.5)
#
# Tests:
#   1.  privacy/pack.json validates against pack.schema.json
#   2.  observability/pack.json validates against pack.schema.json
#   3.  severity-rubric.json contains all privacy/* check ids
#   4.  severity-rubric.json contains all observability/* check ids
#   5.  lint-pack.py passes on privacy pack with the real rubric
#   6.  lint-pack.py passes on observability pack with the real rubric
#   7.  privacy/checks.md contains all required template sections
#   8.  observability/checks.md contains all required template sections
#   9.  privacy/checks.md documents TP/TN fixture for each check
#  10.  observability/checks.md documents TP/TN fixture for each check
#  11.  Both packs use applies_when: ["always"]
#  12.  runtime fixture: tracking SDK init without consent gate (privacy TP)
#  13.  runtime fixture: console.log(user) (observability TP)
#  14.  runtime fixture: clean counterparts (TN for both)
#  15.  privacy pack is self-distinct from tos-compliance (no shared check ids)
#
# Note: All checks are LLM-detection. We do NOT assert the LLM finds issues in
# fixtures — only structural validity and registry selection logic.
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PRIVACY_PACK_DIR="${AUDIT_DIR}/packs/privacy"
OBS_PACK_DIR="${AUDIT_DIR}/packs/observability"
TOS_PACK_DIR="${AUDIT_DIR}/packs/tos-compliance"
REGISTRY="${AUDIT_DIR}/scripts/registry.py"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0

pass() { printf "  PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Helper: validate a pack.json via registry.py
# ---------------------------------------------------------------------------
_T_PY="$(mktemp "${TMPDIR:-/tmp}/pack_validate_privacy_obs.XXXXXX")"
cat > "${_T_PY}" <<'PYEOF'
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
trap "rm -f '${_T_PY}'" EXIT

# ---------------------------------------------------------------------------
# Test 1: privacy/pack.json validates against pack.schema.json
# ---------------------------------------------------------------------------
echo "--- Test 1: privacy/pack.json validates"

_T1_RESULT=""
_T1_EXIT=0
_T1_RESULT=$(python3 "${_T_PY}" "${REGISTRY}" "${PRIVACY_PACK_DIR}/pack.json" 2>&1) || _T1_EXIT=$?

# Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
# producer if grep exits on its first match before the producer finishes
# writing, turning a genuine match into a reported failure (see #943,
# #945). A herestring has no second process to race against.
if [ "${_T1_EXIT}" -eq 0 ] && grep -q "^VALID$" <<< "${_T1_RESULT}"; then
    pass "privacy/pack.json validates against pack.schema.json"
else
    fail "privacy/pack.json failed validation: ${_T1_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 2: observability/pack.json validates against pack.schema.json
# ---------------------------------------------------------------------------
echo "--- Test 2: observability/pack.json validates"

_T2_RESULT=""
_T2_EXIT=0
_T2_RESULT=$(python3 "${_T_PY}" "${REGISTRY}" "${OBS_PACK_DIR}/pack.json" 2>&1) || _T2_EXIT=$?

# Herestring, not a pipe: see the identical rationale above (#943, #945).
if [ "${_T2_EXIT}" -eq 0 ] && grep -q "^VALID$" <<< "${_T2_RESULT}"; then
    pass "observability/pack.json validates against pack.schema.json"
else
    fail "observability/pack.json failed validation: ${_T2_RESULT}"
fi

# ---------------------------------------------------------------------------
# Test 3: rubric contains all privacy/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 3: rubric contains all privacy/* check ids"

PRIVACY_IDS=(
    "privacy/pii-without-consent"
    "privacy/pii-no-retention"
    "privacy/pii-in-url"
)

_T3_MISSING=""
for check_id in "${PRIVACY_IDS[@]}"; do
    # Producer is a real command (python3), not an echo/printf of a
    # variable: capture its output to a variable first, then herestring
    # into the early-exiting `grep -q` (see #943, #945). `|| true` keeps
    # python3's exit-1-on-missing from aborting this now-bare assignment.
    _T3_CHECK=$(python3 -c "
import json, sys
rubric = json.load(open('${RUBRIC}', encoding='utf-8'))
checks = rubric.get('checks', {})
if '${check_id}' not in checks:
    print('MISSING')
    sys.exit(1)
print('FOUND')
sys.exit(0)
" 2>/dev/null || true)
    if ! grep -q "^FOUND$" <<< "${_T3_CHECK}"; then
        _T3_MISSING="${_T3_MISSING} ${check_id}"
    fi
done

if [ -z "${_T3_MISSING}" ]; then
    pass "rubric contains all ${#PRIVACY_IDS[@]} privacy/* check ids"
else
    fail "rubric missing privacy ids:${_T3_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 4: rubric contains all observability/* check ids
# ---------------------------------------------------------------------------
echo "--- Test 4: rubric contains all observability/* check ids"

OBS_IDS=(
    "observability/pii-in-logs"
    "observability/missing-structured-logging"
    "observability/missing-error-reporting"
)

_T4_MISSING=""
for check_id in "${OBS_IDS[@]}"; do
    # Producer is a real command (python3): see the identical rationale
    # above (#943, #945).
    _T4_CHECK=$(python3 -c "
import json, sys
rubric = json.load(open('${RUBRIC}', encoding='utf-8'))
checks = rubric.get('checks', {})
if '${check_id}' not in checks:
    print('MISSING')
    sys.exit(1)
print('FOUND')
sys.exit(0)
" 2>/dev/null || true)
    if ! grep -q "^FOUND$" <<< "${_T4_CHECK}"; then
        _T4_MISSING="${_T4_MISSING} ${check_id}"
    fi
done

if [ -z "${_T4_MISSING}" ]; then
    pass "rubric contains all ${#OBS_IDS[@]} observability/* check ids"
else
    fail "rubric missing observability ids:${_T4_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 5: lint-pack.py passes on privacy pack with the real rubric
# ---------------------------------------------------------------------------
echo "--- Test 5: lint-pack.py passes on privacy pack"

_T5_OUTPUT=""
_T5_EXIT=0
_T5_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T5_EXIT=$?

# Herestring, not a pipe: see the identical rationale above (#943, #945).
if [ "${_T5_EXIT}" -eq 0 ] && grep -q "^PASS: privacy" <<< "${_T5_OUTPUT}"; then
    pass "lint-pack.py reports PASS for privacy pack"
else
    fail "lint-pack.py did not report PASS for privacy: exit=${_T5_EXIT}, output=${_T5_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Test 6: lint-pack.py passes on observability pack with the real rubric
# ---------------------------------------------------------------------------
echo "--- Test 6: lint-pack.py passes on observability pack"

_T6_OUTPUT=""
_T6_EXIT=0
_T6_OUTPUT=$(python3 "${LINTER}" \
    --packs-dir "${AUDIT_DIR}/packs" \
    --rubric "${RUBRIC}" 2>&1) || _T6_EXIT=$?

# Herestring, not a pipe: see the identical rationale above (#943, #945).
if [ "${_T6_EXIT}" -eq 0 ] && grep -q "^PASS: observability" <<< "${_T6_OUTPUT}"; then
    pass "lint-pack.py reports PASS for observability pack"
else
    fail "lint-pack.py did not report PASS for observability: exit=${_T6_EXIT}, output=${_T6_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Test 7: privacy/checks.md has all required template sections
# ---------------------------------------------------------------------------
echo "--- Test 7: privacy/checks.md has required sections"

PRIVACY_CHECKS_MD="${PRIVACY_PACK_DIR}/checks.md"
_REQUIRED_SECTIONS=(
    "^## Scope"
    "^## applies_when Rationale"
    "^## Checks"
    "^## Quality Checklist"
)

_T7_MISSING=""
for section in "${_REQUIRED_SECTIONS[@]}"; do
    if ! grep -qiE "${section}" "${PRIVACY_CHECKS_MD}"; then
        _T7_MISSING="${_T7_MISSING} '${section}'"
    fi
done

if [ -z "${_T7_MISSING}" ]; then
    pass "privacy/checks.md contains all required sections"
else
    fail "privacy/checks.md missing sections:${_T7_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 8: observability/checks.md has all required template sections
# ---------------------------------------------------------------------------
echo "--- Test 8: observability/checks.md has required sections"

OBS_CHECKS_MD="${OBS_PACK_DIR}/checks.md"
_T8_MISSING=""
for section in "${_REQUIRED_SECTIONS[@]}"; do
    if ! grep -qiE "${section}" "${OBS_CHECKS_MD}"; then
        _T8_MISSING="${_T8_MISSING} '${section}'"
    fi
done

if [ -z "${_T8_MISSING}" ]; then
    pass "observability/checks.md contains all required sections"
else
    fail "observability/checks.md missing sections:${_T8_MISSING}"
fi

# ---------------------------------------------------------------------------
# Test 9: privacy/checks.md documents TP/TN fixtures for each check
# ---------------------------------------------------------------------------
echo "--- Test 9: privacy/checks.md documents TP/TN fixtures"

_T9_ERRORS=""

for check_id in "${PRIVACY_IDS[@]}"; do
    if ! grep -q "${check_id}" "${PRIVACY_CHECKS_MD}"; then
        _T9_ERRORS="${_T9_ERRORS}\n  check-id '${check_id}' not found in privacy/checks.md"
        continue
    fi

    _SECTION=$(python3 - "${PRIVACY_CHECKS_MD}" "${check_id}" <<'PYEOF' 2>/dev/null
import sys, re
md = open(sys.argv[1], encoding='utf-8').read()
check_id = sys.argv[2]
pattern = r'(### `' + re.escape(check_id) + r'`.*?)(?=\n### `|\Z)'
m = re.search(pattern, md, re.DOTALL)
if m:
    print(m.group(1))
PYEOF
)

    # Herestring, not a pipe: see the identical rationale above (#943, #945).
    if ! grep -q "True positive\|FINDS:" <<< "${_SECTION}"; then
        _T9_ERRORS="${_T9_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    if ! grep -q "True negative\|should produce NO" <<< "${_SECTION}"; then
        _T9_ERRORS="${_T9_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

if [ -z "${_T9_ERRORS}" ]; then
    pass "privacy/checks.md documents TP/TN fixtures for all ${#PRIVACY_IDS[@]} privacy checks"
else
    fail "privacy/checks.md fixture coverage issues:$(printf '%b' "${_T9_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 10: observability/checks.md documents TP/TN fixtures for each check
# ---------------------------------------------------------------------------
echo "--- Test 10: observability/checks.md documents TP/TN fixtures"

_T10_ERRORS=""

for check_id in "${OBS_IDS[@]}"; do
    if ! grep -q "${check_id}" "${OBS_CHECKS_MD}"; then
        _T10_ERRORS="${_T10_ERRORS}\n  check-id '${check_id}' not found in observability/checks.md"
        continue
    fi

    _SECTION=$(python3 - "${OBS_CHECKS_MD}" "${check_id}" <<'PYEOF' 2>/dev/null
import sys, re
md = open(sys.argv[1], encoding='utf-8').read()
check_id = sys.argv[2]
pattern = r'(### `' + re.escape(check_id) + r'`.*?)(?=\n### `|\Z)'
m = re.search(pattern, md, re.DOTALL)
if m:
    print(m.group(1))
PYEOF
)

    # Herestring, not a pipe: see the identical rationale above (#943, #945).
    if ! grep -q "True positive\|FINDS:" <<< "${_SECTION}"; then
        _T10_ERRORS="${_T10_ERRORS}\n  no True positive fixture found for '${check_id}'"
    fi

    if ! grep -q "True negative\|should produce NO" <<< "${_SECTION}"; then
        _T10_ERRORS="${_T10_ERRORS}\n  no True negative fixture found for '${check_id}'"
    fi
done

if [ -z "${_T10_ERRORS}" ]; then
    pass "observability/checks.md documents TP/TN fixtures for all ${#OBS_IDS[@]} observability checks"
else
    fail "observability/checks.md fixture coverage issues:$(printf '%b' "${_T10_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 11: both packs declare applies_when: ["always"]
# ---------------------------------------------------------------------------
echo "--- Test 11: both packs use applies_when: [\"always\"]"

_T11_ERRORS=""

for pack_path in "${PRIVACY_PACK_DIR}/pack.json" "${OBS_PACK_DIR}/pack.json"; do
    _AW=$(python3 -c "
import json, sys
pack = json.load(open('${pack_path}', encoding='utf-8'))
aw = pack.get('applies_when', [])
if aw == ['always']:
    print('OK')
else:
    print('WRONG: ' + str(aw))
" 2>/dev/null)
    # Herestring, not a pipe: see the identical rationale above (#943, #945).
    if ! grep -q "^OK$" <<< "${_AW}"; then
        _PACK_NAME=$(basename "$(dirname "${pack_path}")")
        _T11_ERRORS="${_T11_ERRORS}\n  ${_PACK_NAME}/pack.json applies_when is not [\"always\"]: ${_AW}"
    fi
done

if [ -z "${_T11_ERRORS}" ]; then
    pass "both packs declare applies_when: [\"always\"]"
else
    fail "applies_when mismatch:$(printf '%b' "${_T11_ERRORS}")"
fi

# ---------------------------------------------------------------------------
# Test 12: runtime fixture — tracking SDK init without consent gate (privacy TP)
# ---------------------------------------------------------------------------
echo "--- Test 12: runtime fixture — privacy TP (tracking SDK without consent)"

_T12_DIR="$(mktemp -d "${TMPDIR:-/tmp}/privacy_obs_fixtures.XXXXXX")"
# shellcheck disable=SC2064
trap "rm -rf '${_T12_DIR}'" EXIT

# Privacy TP: Segment analytics.identify() with user.email — no consent check
cat > "${_T12_DIR}/analytics-tp.ts" <<'TS'
// privacy/pii-without-consent TRUE POSITIVE fixture
// analytics.identify() called with user email — no consent gate present
import analytics from '@segment/analytics-next';

export function identifyUser(user) {
  analytics.identify(user.id, {
    email: user.email,
    name: user.displayName,
  });
}
TS

if [ -f "${_T12_DIR}/analytics-tp.ts" ]; then
    pass "privacy TP fixture created: tracking SDK init with user PII, no consent gate"
else
    fail "privacy TP fixture creation failed"
fi

# ---------------------------------------------------------------------------
# Test 13: runtime fixture — console.log(user) (observability TP)
# ---------------------------------------------------------------------------
echo "--- Test 13: runtime fixture — observability TP (console.log(user))"

# Observability TP: entire user object logged in server route handler
cat > "${_T12_DIR}/log-pii-tp.ts" <<'TS'
// observability/pii-in-logs TRUE POSITIVE fixture
// console.log(user) in a server route — entire user object including PII emitted
async function handleLogin(req, res) {
  const user = await findUser(req.body.email);
  console.log(user);   // logs PII: email, name, phone, etc.
  if (!user) return res.status(404).json({ error: 'Not found' });
  res.json({ token: createToken(user.id) });
}
TS

if [ -f "${_T12_DIR}/log-pii-tp.ts" ]; then
    pass "observability TP fixture created: console.log(user) in server handler"
else
    fail "observability TP fixture creation failed"
fi

# ---------------------------------------------------------------------------
# Test 14: runtime fixtures — clean counterparts (TN for both packs)
# ---------------------------------------------------------------------------
echo "--- Test 14: runtime fixtures — clean counterparts (TN)"

# Privacy TN: consent check gates the identify call
cat > "${_T12_DIR}/analytics-tn.ts" <<'TS'
// privacy/pii-without-consent TRUE NEGATIVE fixture
// consent check gates the identify call — no finding expected
import analytics from '@segment/analytics-next';
import { getConsentState } from './consent';

export function identifyUser(user) {
  if (!getConsentState().analytics) return;
  analytics.identify(user.id, {
    email: user.email,
    name: user.displayName,
  });
}
TS

# Observability TN: structured logger used, only opaque userId
cat > "${_T12_DIR}/log-pii-tn.ts" <<'TS'
// observability/pii-in-logs TRUE NEGATIVE fixture
// structured logger with only opaque userId — no PII, no finding expected
import { logger } from './logger';

async function handleLogin(req, res) {
  const user = await findUser(req.body.email);
  logger.info({ userId: user?.id }, 'login attempt');
  if (!user) return res.status(404).json({ error: 'Not found' });
  res.json({ token: createToken(user.id) });
}
TS

if [ -f "${_T12_DIR}/analytics-tn.ts" ] && [ -f "${_T12_DIR}/log-pii-tn.ts" ]; then
    pass "TN fixtures created: consent-gated analytics + structured logger with opaque userId"
else
    fail "TN fixture creation failed"
fi

# ---------------------------------------------------------------------------
# Test 15: privacy is distinct from tos-compliance (no shared check ids)
# ---------------------------------------------------------------------------
echo "--- Test 15: privacy check ids are distinct from tos-compliance check ids"

_T15_OVERLAP=$(python3 - "${PRIVACY_PACK_DIR}/pack.json" "${TOS_PACK_DIR}/pack.json" <<'PYEOF' 2>/dev/null
import json, sys
privacy = json.load(open(sys.argv[1], encoding='utf-8'))
tos = json.load(open(sys.argv[2], encoding='utf-8'))

privacy_ids = {c['id'] for c in privacy.get('checks', [])}
tos_ids = {c['id'] for c in tos.get('checks', [])}

overlap = privacy_ids & tos_ids
if overlap:
    print('OVERLAP: ' + ', '.join(sorted(overlap)))
    sys.exit(1)
else:
    print('DISTINCT')
    sys.exit(0)
PYEOF
)

# Herestring, not a pipe: see the identical rationale above (#943, #945).
if grep -q "^DISTINCT$" <<< "${_T15_OVERLAP}"; then
    pass "privacy check ids are fully distinct from tos-compliance check ids"
else
    fail "privacy and tos-compliance share check ids: ${_T15_OVERLAP}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\nResults: %d passed, %d failed\n" "${PASS}" "${FAIL}"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
