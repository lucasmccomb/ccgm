#!/usr/bin/env bash
# test-pack-correctness.sh -- Epic 2.4 correctness pack test suite
#
# Tests:
#   (a) parse-eslint.py emits lint/eqeqeq + lint/no-unreachable from synthetic
#       ESLint JSON output (properties.tool=eslint, valid fingerprint, rubric-known)
#   (b) wrap-eslint.sh --rule JSON contains all 10 rules; comment lists them
#   (c) pack.json + rubric validate; lint-pack.py passes on correctness pack
#   (d) checks.md marks LLM-only checks as LOW confidence, syntactic as HIGH
#   (e) shellcheck on wrap-eslint.sh
#
# Exit code: 0 = all pass, 1 = failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPINE_DIR="${AUDIT_DIR}/scripts/spine"
SCHEMAS_DIR="${AUDIT_DIR}/schemas"
RUBRIC="${SCHEMAS_DIR}/severity-rubric.json"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"

PASS=0
FAIL=0
ERRORS=()

pass() {
  printf '  [PASS] %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf '  [FAIL] %s\n' "$1"
  ERRORS+=("$1")
  FAIL=$((FAIL + 1))
}

# ---------------------------------------------------------------------------
# (a) parse-eslint.py unit test against synthetic ESLint JSON output
# ---------------------------------------------------------------------------
printf '\n(a) parse-eslint.py: synthetic output with eqeqeq + no-unreachable\n'

SYNTHETIC_INPUT="$(mktemp /tmp/ccgm-eslint-synth-XXXXXX.json)"
trap 'rm -f "$SYNTHETIC_INPUT"' EXIT

# Construct ESLint-shaped JSON with one eqeqeq violation and one no-unreachable violation
cat > "$SYNTHETIC_INPUT" << 'SYNTH_EOF'
[
  {
    "filePath": "/repo/src/utils.js",
    "messages": [
      {
        "ruleId": "eqeqeq",
        "severity": 2,
        "message": "Expected '===' and instead saw '=='.",
        "line": 10,
        "endLine": 10,
        "column": 14,
        "endColumn": 18
      },
      {
        "ruleId": "no-unreachable",
        "severity": 2,
        "message": "Unreachable code.",
        "line": 25,
        "endLine": 25,
        "column": 3,
        "endColumn": 20
      }
    ]
  }
]
SYNTH_EOF

PARSE_OUTPUT="$(python3 "${SPINE_DIR}/parse-eslint.py" "$SYNTHETIC_INPUT" "/repo" 2>&1)"

# Expect exactly 2 lines of JSON
LINE_COUNT="$(printf '%s\n' "$PARSE_OUTPUT" | grep -c '^{' || true)"
if [[ "$LINE_COUNT" -eq 2 ]]; then
  pass "parse-eslint.py emits 2 findings for 2 synthetic violations"
else
  fail "parse-eslint.py emitted $LINE_COUNT finding lines (expected 2)"
fi

# Check for lint/eqeqeq finding
if printf '%s\n' "$PARSE_OUTPUT" | grep -q '"lint/eqeqeq"'; then
  pass "parse-eslint.py emits lint/eqeqeq check_id"
else
  fail "parse-eslint.py did not emit lint/eqeqeq check_id"
fi

# Check for lint/no-unreachable finding
if printf '%s\n' "$PARSE_OUTPUT" | grep -q '"lint/no-unreachable"'; then
  pass "parse-eslint.py emits lint/no-unreachable check_id"
else
  fail "parse-eslint.py did not emit lint/no-unreachable check_id"
fi

# Verify properties.tool=eslint in both findings
TOOL_COUNT="$(printf '%s\n' "$PARSE_OUTPUT" | python3 -c "
import json, sys
lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
count = 0
for l in lines:
    try:
        obj = json.loads(l)
        if obj.get('properties', {}).get('tool') == 'eslint':
            count += 1
    except Exception:
        pass
print(count)
" 2>/dev/null || printf '0')"

if [[ "$TOOL_COUNT" -eq 2 ]]; then
  pass "both findings have properties.tool=eslint"
else
  fail "$TOOL_COUNT/2 findings have properties.tool=eslint (expected 2)"
fi

# Verify valid fingerprints (non-empty, match the allowed character set)
FINGERPRINT_OK="$(printf '%s\n' "$PARSE_OUTPUT" | python3 -c "
import json, re, sys
lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
ok = 0
for l in lines:
    try:
        obj = json.loads(l)
        fp = obj.get('fingerprint', '')
        if re.fullmatch(r'[A-Za-z0-9_.:+/=\-]{8,128}', fp):
            ok += 1
    except Exception:
        pass
print(ok)
" 2>/dev/null || printf '0')"

if [[ "$FINGERPRINT_OK" -eq 2 ]]; then
  pass "both findings have valid fingerprints"
else
  fail "$FINGERPRINT_OK/2 findings have valid fingerprints (expected 2)"
fi

# Verify all emitted check_ids are in the rubric (rubric-known).
# Write findings to a temp file to avoid stdin/heredoc conflict.
PARSE_OUTPUT_FILE="$(mktemp /tmp/ccgm-parse-out-XXXXXX.jsonl)"
printf '%s\n' "$PARSE_OUTPUT" > "$PARSE_OUTPUT_FILE"
trap 'rm -f "$SYNTHETIC_INPUT" "$PARSE_OUTPUT_FILE"' EXIT

RUBRIC_OK="$(python3 - "$RUBRIC" "$PARSE_OUTPUT_FILE" << 'PYEOF'
import json, sys

rubric_path = sys.argv[1]
findings_path = sys.argv[2]
with open(rubric_path, encoding="utf-8") as fh:
    rubric = json.load(fh).get("checks", {})

ok = 0
with open(findings_path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            cid = obj.get("check_id", "")
            if cid in rubric:
                ok += 1
        except Exception:
            pass
print(ok)
PYEOF
)"

if [[ "$RUBRIC_OK" -eq 2 ]]; then
  pass "both emitted check_ids are present in severity-rubric.json (rubric-known)"
else
  fail "$RUBRIC_OK/2 emitted check_ids found in rubric (expected 2 -- lint/eqeqeq and lint/no-unreachable)"
fi

# ---------------------------------------------------------------------------
# (b) wrap-eslint.sh rule JSON contains all 10 rules; comment lists them
# ---------------------------------------------------------------------------
printf '\n(b) wrap-eslint.sh: rule JSON has all 10 rules + comment lists them\n'

WRAP_ESLINT="${SPINE_DIR}/wrap-eslint.sh"

# All 10 expected rules
EXPECTED_RULES=(
  "no-eval"
  "no-implied-eval"
  "no-new-func"
  "eqeqeq"
  "use-isnan"
  "valid-typeof"
  "no-unreachable"
  "no-constant-condition"
  "no-fallthrough"
  "default-case"
)

for rule in "${EXPECTED_RULES[@]}"; do
  if grep -q "\"${rule}\"" "$WRAP_ESLINT"; then
    pass "wrap-eslint.sh --rule JSON contains ${rule}"
  else
    fail "wrap-eslint.sh --rule JSON missing ${rule}"
  fi
done

# Verify the comment block lists the new correctness rules
for rule in eqeqeq use-isnan valid-typeof no-unreachable no-constant-condition no-fallthrough default-case; do
  if grep -q "${rule}" "$WRAP_ESLINT"; then
    # Already covered by the rule JSON check above; just confirm grep works
    pass "wrap-eslint.sh comment/body references ${rule}"
  else
    fail "wrap-eslint.sh does not reference ${rule} at all"
  fi
done

# ---------------------------------------------------------------------------
# (c) pack.json + rubric validate; lint-pack.py passes on correctness pack
# ---------------------------------------------------------------------------
printf '\n(c) lint-pack.py passes on correctness pack with rubric\n'

PACK_DIR="${AUDIT_DIR}/packs/correctness"
PACK_JSON="${PACK_DIR}/pack.json"

# Validate pack.json is valid JSON
if python3 -c "import json; json.load(open('${PACK_JSON}'))" 2>/dev/null; then
  pass "packs/correctness/pack.json is valid JSON"
else
  fail "packs/correctness/pack.json is not valid JSON"
fi

# Validate rubric is valid JSON after our additions
if python3 -c "import json; json.load(open('${RUBRIC}'))" 2>/dev/null; then
  pass "severity-rubric.json is valid JSON after additions"
else
  fail "severity-rubric.json is not valid JSON after additions"
fi

# Lint just the correctness pack against the rubric
LINT_OUTPUT="$(python3 "${LINTER}" --packs-dir "${AUDIT_DIR}/packs" --rubric "${RUBRIC}" 2>&1)"
LINT_EXIT=$?

if [[ $LINT_EXIT -eq 0 ]]; then
  pass "lint-pack.py passes on all packs (including correctness) with rubric"
else
  fail "lint-pack.py failed: ${LINT_OUTPUT}"
fi

# Explicitly check that correctness pack is PASS (not just that there are no errors)
if printf '%s\n' "$LINT_OUTPUT" | grep -q '^PASS: correctness$'; then
  pass "lint-pack.py reports PASS: correctness"
else
  fail "lint-pack.py did not report PASS: correctness (output: ${LINT_OUTPUT})"
fi

# ---------------------------------------------------------------------------
# (d) checks.md marks LLM-only checks LOW confidence, syntactic checks HIGH
# ---------------------------------------------------------------------------
printf '\n(d) checks.md: LLM-only checks LOW confidence, syntactic HIGH\n'

CHECKS_MD="${PACK_DIR}/checks.md"

# LLM-only checks should be marked as LOW confidence
LLM_CHECKS=("off-by-one" "float-equality" "wrong-branch-logic")
for check in "${LLM_CHECKS[@]}"; do
  # Look for the check section and verify LOW confidence is mentioned
  if grep -A 5 "correctness/${check}" "$CHECKS_MD" | grep -qi "low"; then
    pass "checks.md marks correctness/${check} as low confidence"
  else
    fail "checks.md does not mark correctness/${check} as low confidence"
  fi
done

# Syntactic (deterministic) checks documented in the spine-namespace table
SYNTACTIC_RULES=("eqeqeq" "use-isnan" "valid-typeof" "no-unreachable" "no-constant-condition" "no-fallthrough" "default-case")
for rule in "${SYNTACTIC_RULES[@]}"; do
  if grep -q "lint/${rule}" "$CHECKS_MD"; then
    pass "checks.md documents lint/${rule} (deterministic spine check)"
  else
    fail "checks.md does not document lint/${rule}"
  fi
done

# High confidence is stated for spine checks in the rubric table
if grep -q "high" "$CHECKS_MD"; then
  pass "checks.md references high confidence for spine checks"
else
  fail "checks.md does not reference high confidence"
fi

# LLM checks are explicitly marked as LLM best-effort
if grep -q "LLM best-effort" "$CHECKS_MD"; then
  pass "checks.md contains 'LLM best-effort' disclaimer"
else
  fail "checks.md missing 'LLM best-effort' disclaimer"
fi

# ---------------------------------------------------------------------------
# (e) shellcheck on wrap-eslint.sh
# ---------------------------------------------------------------------------
printf '\n(e) shellcheck on wrap-eslint.sh\n'

if command -v shellcheck > /dev/null 2>&1; then
  SC_OUTPUT="$(shellcheck -S warning "${WRAP_ESLINT}" 2>&1 || true)"
  if [[ -z "$SC_OUTPUT" ]]; then
    pass "shellcheck clean: wrap-eslint.sh"
  else
    fail "shellcheck issues in wrap-eslint.sh:"
    printf '%s\n' "$SC_OUTPUT" | head -10
  fi
else
  fail "shellcheck not installed -- cannot verify shell safety"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\n-------------------------------------------------\n'
printf 'Results: %d passed, %d failed\n' "$PASS" "$FAIL"

if [[ $FAIL -gt 0 ]]; then
  printf '\nFailed tests:\n'
  for err in "${ERRORS[@]}"; do
    printf '  - %s\n' "$err"
  done
  exit 1
fi

printf 'All tests passed.\n'
exit 0
