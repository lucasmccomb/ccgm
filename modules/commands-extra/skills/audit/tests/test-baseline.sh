#!/usr/bin/env bash
# CCGM audit -- test-baseline.sh
# Tests for Epic 3.2: baseline/delta classification (baseline.py)
#
# Test scenarios:
#   1. Core classification: run1={A,B}, run2={B,C} -> C=new, B=existing, A=resolved.
#      Summary counts: new=1, existing=1, resolved=1.
#   2. --new-only: output contains only C (+summary); A (resolved) and B (existing) absent.
#   3. Malformed input: baseline file with invalid JSON -> exit 1.
#   4. --save-baseline: saved file matches --current byte-for-byte.
#   5. Metadata passthrough: provenance/coverage_gap records from --current appear in output.
#   6. Missing --baseline file: exit 1 with clear error.
#
# All fixtures are constructed at runtime in mktemp dirs.
# Usage: bash modules/commands-extra/skills/audit/tests/test-baseline.sh
# Exit:  0 = all tests passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE_SCRIPT="$SCRIPT_DIR/../scripts/baseline.py"

PASS=0
FAIL=0
ERRORS=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pass() {
  printf '  [PASS] %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf '  [FAIL] %s\n' "$1"
  ERRORS+=("$1")
  FAIL=$((FAIL + 1))
}

# Get the value of a JSON field from the first line matching a given fingerprint in JSONL.
# Usage: get_field <jsonl_str> <fingerprint> <field>
get_field() {
  python3 - "$1" "$2" "$3" << 'PYEOF'
import json, sys
output, fp, field = sys.argv[1], sys.argv[2], sys.argv[3]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            val = obj.get(field)
            print("" if val is None else str(val))
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Get a nested field: properties.baseline_status etc.
get_props_field() {
  python3 - "$1" "$2" "$3" << 'PYEOF'
import json, sys
output, fp, child = sys.argv[1], sys.argv[2], sys.argv[3]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            props = obj.get("properties") or {}
            if isinstance(props, dict):
                val = props.get(child)
                print("" if val is None else str(val))
            else:
                print("__no_properties__")
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Check whether a fingerprint exists as a finding record (no type field)
fp_exists_as_finding() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, fp = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            print("yes")
            sys.exit(0)
    except Exception:
        pass
print("no")
PYEOF
}

# Check whether a fingerprint exists as a resolved record
fp_exists_as_resolved() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, fp = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and obj.get("type") == "resolved" and obj.get("fingerprint") == fp:
            print("yes")
            sys.exit(0)
    except Exception:
        pass
print("no")
PYEOF
}

# Get a field from the baseline_summary record
get_summary_field() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, field = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and obj.get("type") == "baseline_summary":
            val = obj.get(field)
            print("" if val is None else str(val))
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Count records of a given type in JSONL string
count_type() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, type_val = sys.argv[1], sys.argv[2]
count = 0
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and obj.get("type") == type_val:
            count += 1
    except Exception:
        pass
print(count)
PYEOF
}

# ---------------------------------------------------------------------------
# Global temp directory
# ---------------------------------------------------------------------------
TESTRUN_DIR="$(mktemp -d /tmp/ccgm-test-baseline-XXXXXX)"
trap 'rm -rf "$TESTRUN_DIR"' EXIT

# ---------------------------------------------------------------------------
# Helper: write a findings.jsonl with a provenance header + given findings
# ---------------------------------------------------------------------------
write_findings_jsonl() {
  # write_findings_jsonl <out_file> <finding_json> [<finding_json> ...]
  local out_file="$1"
  shift
  python3 - "$out_file" "$@" << 'PYEOF'
import json, sys
out_file = sys.argv[1]
findings = sys.argv[2:]
with open(out_file, "w") as fh:
    # provenance record
    fh.write(json.dumps({
        "type": "provenance",
        "tool": "ccgm-merge",
        "version": "1.0",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    for f_json in findings:
        if f_json:
            fh.write(f_json + "\n")
PYEOF
}

# Minimal valid finding JSON given rule_id, fingerprint, check_id
make_finding() {
  python3 -c "
import json, sys
rule_id, fingerprint, check_id = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    'check_id': check_id,
    'rule_id': rule_id,
    'severity': 'medium',
    'confidence': 'high',
    'detection': 'tool',
    'source': 'tool',
    'message': 'test finding for ' + rule_id,
    'location': {'path': 'src/test.py', 'line': 1},
    'fingerprint': fingerprint,
}))
" "$1" "$2" "$3"
}

# ---------------------------------------------------------------------------
# Test 1: Core classification — run1={A,B}, run2={B,C}
# ---------------------------------------------------------------------------
printf '\nTest 1: core classification (new/existing/resolved + summary counts)\n'

T1_DIR="$TESTRUN_DIR/t1"
mkdir -p "$T1_DIR"

FP_A="aaaa1111bbbb2222:1"
FP_B="bbbb2222cccc3333:1"
FP_C="cccc3333dddd4444:1"

FINDING_A="$(make_finding "rule-a" "$FP_A" "code-quality/test-rule")"
FINDING_B="$(make_finding "rule-b" "$FP_B" "code-quality/test-rule")"
FINDING_C="$(make_finding "rule-c" "$FP_C" "security/test-rule")"

# Baseline (run1): A and B
write_findings_jsonl "$T1_DIR/baseline.jsonl" "$FINDING_A" "$FINDING_B"
# Current (run2): B and C
write_findings_jsonl "$T1_DIR/current.jsonl" "$FINDING_B" "$FINDING_C"

set +e
T1_OUT="$(python3 "$BASELINE_SCRIPT" \
  --current "$T1_DIR/current.jsonl" \
  --baseline "$T1_DIR/baseline.jsonl" 2>/dev/null)"
T1_EXIT=$?
set -e

if [[ $T1_EXIT -eq 0 ]]; then
  pass "t1: baseline.py exits 0"
else
  fail "t1: baseline.py exits $T1_EXIT (expected 0)"
fi

# C should be tagged "new"
T1_C_STATUS="$(get_props_field "$T1_OUT" "$FP_C" "baseline_status")"
if [[ "$T1_C_STATUS" == "new" ]]; then
  pass "t1: finding C tagged baseline_status=new"
else
  fail "t1: finding C baseline_status='$T1_C_STATUS' (expected 'new')"
fi

# B should be tagged "existing"
T1_B_STATUS="$(get_props_field "$T1_OUT" "$FP_B" "baseline_status")"
if [[ "$T1_B_STATUS" == "existing" ]]; then
  pass "t1: finding B tagged baseline_status=existing"
else
  fail "t1: finding B baseline_status='$T1_B_STATUS' (expected 'existing')"
fi

# A should appear as a resolved record
T1_A_RESOLVED="$(fp_exists_as_resolved "$T1_OUT" "$FP_A")"
if [[ "$T1_A_RESOLVED" == "yes" ]]; then
  pass "t1: finding A emitted as a resolved record"
else
  fail "t1: finding A is not present as a resolved record (expected type=resolved)"
fi

# A should NOT appear as a finding
T1_A_AS_FINDING="$(fp_exists_as_finding "$T1_OUT" "$FP_A")"
if [[ "$T1_A_AS_FINDING" == "no" ]]; then
  pass "t1: finding A does NOT appear as a finding record (correctly absent)"
else
  fail "t1: finding A incorrectly appears as a finding record"
fi

# Summary counts: new=1, existing=1, resolved=1
T1_SUM_NEW="$(get_summary_field "$T1_OUT" "new")"
T1_SUM_EXIST="$(get_summary_field "$T1_OUT" "existing")"
T1_SUM_RESOL="$(get_summary_field "$T1_OUT" "resolved")"

if [[ "$T1_SUM_NEW" == "1" ]]; then
  pass "t1: summary.new=1"
else
  fail "t1: summary.new='$T1_SUM_NEW' (expected 1)"
fi
if [[ "$T1_SUM_EXIST" == "1" ]]; then
  pass "t1: summary.existing=1"
else
  fail "t1: summary.existing='$T1_SUM_EXIST' (expected 1)"
fi
if [[ "$T1_SUM_RESOL" == "1" ]]; then
  pass "t1: summary.resolved=1"
else
  fail "t1: summary.resolved='$T1_SUM_RESOL' (expected 1)"
fi

# baseline_summary record should be the FIRST line
T1_FIRST_TYPE="$(python3 - "$T1_OUT" << 'PYEOF'
import json, sys
for l in sys.argv[1].splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        print(obj.get("type", "finding"))
        sys.exit(0)
    except Exception:
        pass
print("empty")
PYEOF
)"
if [[ "$T1_FIRST_TYPE" == "baseline_summary" ]]; then
  pass "t1: baseline_summary is the first record in output"
else
  fail "t1: first record type='$T1_FIRST_TYPE' (expected 'baseline_summary')"
fi

# ---------------------------------------------------------------------------
# Test 2: --new-only
# ---------------------------------------------------------------------------
printf '\nTest 2: --new-only filters to only new findings\n'

T2_DIR="$TESTRUN_DIR/t2"
mkdir -p "$T2_DIR"

# Reuse the same baselines from T1 (copy them)
cp "$T1_DIR/baseline.jsonl" "$T2_DIR/baseline.jsonl"
cp "$T1_DIR/current.jsonl" "$T2_DIR/current.jsonl"

set +e
T2_OUT="$(python3 "$BASELINE_SCRIPT" \
  --current "$T2_DIR/current.jsonl" \
  --baseline "$T2_DIR/baseline.jsonl" \
  --new-only 2>/dev/null)"
T2_EXIT=$?
set -e

if [[ $T2_EXIT -eq 0 ]]; then
  pass "t2: baseline.py --new-only exits 0"
else
  fail "t2: baseline.py --new-only exits $T2_EXIT (expected 0)"
fi

# C (new) should be present as a finding
T2_C_PRESENT="$(fp_exists_as_finding "$T2_OUT" "$FP_C")"
if [[ "$T2_C_PRESENT" == "yes" ]]; then
  pass "t2: --new-only: new finding C is present"
else
  fail "t2: --new-only: new finding C is absent (expected present)"
fi

# B (existing) should be absent
T2_B_PRESENT="$(fp_exists_as_finding "$T2_OUT" "$FP_B")"
if [[ "$T2_B_PRESENT" == "no" ]]; then
  pass "t2: --new-only: existing finding B is absent"
else
  fail "t2: --new-only: existing finding B is present (expected absent)"
fi

# A (resolved) should be absent when --new-only
T2_A_RESOLVED="$(fp_exists_as_resolved "$T2_OUT" "$FP_A")"
if [[ "$T2_A_RESOLVED" == "no" ]]; then
  pass "t2: --new-only: resolved record A is absent"
else
  fail "t2: --new-only: resolved record A is present (expected absent)"
fi

# Summary record still present
T2_SUM_COUNT="$(count_type "$T2_OUT" "baseline_summary")"
if [[ "$T2_SUM_COUNT" -eq 1 ]]; then
  pass "t2: --new-only: baseline_summary record is present"
else
  fail "t2: --new-only: baseline_summary count='$T2_SUM_COUNT' (expected 1)"
fi

# Summary counts still reflect the full picture
T2_SUM_NEW="$(get_summary_field "$T2_OUT" "new")"
T2_SUM_RESOL="$(get_summary_field "$T2_OUT" "resolved")"
if [[ "$T2_SUM_NEW" == "1" && "$T2_SUM_RESOL" == "1" ]]; then
  pass "t2: --new-only: summary counts (new=1, resolved=1) still accurate"
else
  fail "t2: --new-only: summary counts unexpected (new=$T2_SUM_NEW, resolved=$T2_SUM_RESOL)"
fi

# ---------------------------------------------------------------------------
# Test 3: malformed baseline -> exit 1
# ---------------------------------------------------------------------------
printf '\nTest 3: malformed input -> exit 1\n'

T3_DIR="$TESTRUN_DIR/t3"
mkdir -p "$T3_DIR"

# Current is valid
write_findings_jsonl "$T3_DIR/current.jsonl" "$FINDING_B"

# Baseline is intentionally malformed JSON
printf '{"type":"provenance"}\n{this is not json\n' > "$T3_DIR/bad-baseline.jsonl"

set +e
T3_STDERR="$(python3 "$BASELINE_SCRIPT" \
  --current "$T3_DIR/current.jsonl" \
  --baseline "$T3_DIR/bad-baseline.jsonl" 2>&1 >/dev/null)"
T3_EXIT=$?
set -e

if [[ $T3_EXIT -eq 1 ]]; then
  pass "t3: malformed baseline -> exit 1"
else
  fail "t3: malformed baseline exits $T3_EXIT (expected 1)"
fi

# Stderr should contain an actionable error message
if echo "$T3_STDERR" | grep -qi "error\|ERROR\|invalid\|not valid"; then
  pass "t3: stderr contains actionable error message"
else
  fail "t3: stderr does not mention 'error' or 'invalid' (got: $T3_STDERR)"
fi

# ---------------------------------------------------------------------------
# Test 4: --save-baseline copies --current byte-for-byte
# ---------------------------------------------------------------------------
printf '\nTest 4: --save-baseline saves current as next baseline\n'

T4_DIR="$TESTRUN_DIR/t4"
mkdir -p "$T4_DIR"

write_findings_jsonl "$T4_DIR/baseline.jsonl" "$FINDING_A"
write_findings_jsonl "$T4_DIR/current.jsonl" "$FINDING_A" "$FINDING_C"

set +e
python3 "$BASELINE_SCRIPT" \
  --current "$T4_DIR/current.jsonl" \
  --baseline "$T4_DIR/baseline.jsonl" \
  --save-baseline "$T4_DIR/saved.jsonl" \
  --output "$T4_DIR/classified.jsonl" 2>/dev/null
T4_EXIT=$?
set -e

if [[ $T4_EXIT -eq 0 ]]; then
  pass "t4: --save-baseline run exits 0"
else
  fail "t4: --save-baseline run exits $T4_EXIT (expected 0)"
fi

if [[ -f "$T4_DIR/saved.jsonl" ]]; then
  pass "t4: --save-baseline created the saved file"
else
  fail "t4: --save-baseline did not create the file at expected path"
fi

if diff -q "$T4_DIR/current.jsonl" "$T4_DIR/saved.jsonl" > /dev/null 2>&1; then
  pass "t4: saved baseline is byte-identical to --current"
else
  fail "t4: saved baseline differs from --current"
fi

# The classified output file should exist and contain a summary
if [[ -f "$T4_DIR/classified.jsonl" ]]; then
  T4_SUM="$(count_type "$(cat "$T4_DIR/classified.jsonl")" "baseline_summary")"
  if [[ "$T4_SUM" -eq 1 ]]; then
    pass "t4: --output file contains baseline_summary"
  else
    fail "t4: --output file missing baseline_summary (count=$T4_SUM)"
  fi
else
  fail "t4: --output file not created"
fi

# ---------------------------------------------------------------------------
# Test 5: metadata passthrough (provenance/coverage_gap from --current in output)
# ---------------------------------------------------------------------------
printf '\nTest 5: metadata passthrough from --current\n'

T5_DIR="$TESTRUN_DIR/t5"
mkdir -p "$T5_DIR"

# Write current with a coverage_gap record
python3 - "$T5_DIR/current_with_meta.jsonl" "$FINDING_C" << 'PYEOF'
import json, sys
out_file, finding_json = sys.argv[1], sys.argv[2]
with open(out_file, "w") as fh:
    fh.write(json.dumps({
        "type": "provenance",
        "tool": "ccgm-merge",
        "version": "1.0",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    fh.write(json.dumps({
        "type": "coverage_gap",
        "tool": "actionlint",
        "check_id": "ci/invalid-workflow",
        "description": "actionlint not installed",
    }) + "\n")
    fh.write(finding_json + "\n")
PYEOF

# Empty baseline
write_findings_jsonl "$T5_DIR/empty-baseline.jsonl"

set +e
T5_OUT="$(python3 "$BASELINE_SCRIPT" \
  --current "$T5_DIR/current_with_meta.jsonl" \
  --baseline "$T5_DIR/empty-baseline.jsonl" 2>/dev/null)"
T5_EXIT=$?
set -e

if [[ $T5_EXIT -eq 0 ]]; then
  pass "t5: metadata passthrough run exits 0"
else
  fail "t5: metadata passthrough run exits $T5_EXIT (expected 0)"
fi

# provenance record should be present
T5_PROV_COUNT="$(count_type "$T5_OUT" "provenance")"
if [[ "$T5_PROV_COUNT" -ge 1 ]]; then
  pass "t5: provenance record from --current passed through ($T5_PROV_COUNT found)"
else
  fail "t5: provenance record missing from output (expected >= 1)"
fi

# coverage_gap record should be present
T5_GAP_COUNT="$(count_type "$T5_OUT" "coverage_gap")"
if [[ "$T5_GAP_COUNT" -ge 1 ]]; then
  pass "t5: coverage_gap record from --current passed through ($T5_GAP_COUNT found)"
else
  fail "t5: coverage_gap record missing from output (expected >= 1)"
fi

# Finding C should be present and tagged new (baseline was empty)
T5_C_STATUS="$(get_props_field "$T5_OUT" "$FP_C" "baseline_status")"
if [[ "$T5_C_STATUS" == "new" ]]; then
  pass "t5: finding C tagged new against empty baseline"
else
  fail "t5: finding C baseline_status='$T5_C_STATUS' (expected 'new' vs empty baseline)"
fi

# ---------------------------------------------------------------------------
# Test 6: missing --baseline file -> exit 1
# ---------------------------------------------------------------------------
printf '\nTest 6: missing --baseline file -> exit 1\n'

T6_DIR="$TESTRUN_DIR/t6"
mkdir -p "$T6_DIR"
write_findings_jsonl "$T6_DIR/current.jsonl" "$FINDING_A"

set +e
T6_STDERR="$(python3 "$BASELINE_SCRIPT" \
  --current "$T6_DIR/current.jsonl" \
  --baseline "$T6_DIR/nonexistent-baseline.jsonl" 2>&1 >/dev/null)"
T6_EXIT=$?
set -e

if [[ $T6_EXIT -eq 1 ]]; then
  pass "t6: missing --baseline file -> exit 1"
else
  fail "t6: missing --baseline exits $T6_EXIT (expected 1)"
fi

if echo "$T6_STDERR" | grep -qi "error\|ERROR\|cannot\|not found"; then
  pass "t6: stderr contains actionable error for missing baseline"
else
  fail "t6: stderr does not mention error for missing baseline (got: $T6_STDERR)"
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
