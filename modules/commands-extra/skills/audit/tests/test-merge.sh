#!/usr/bin/env bash
# CCGM audit -- test-merge.sh
# Tests for Epic 1.9: merge-findings.py (spine+LLM triage + merge orchestration)
#
# Synthetic test cases use mktemp dirs at runtime; the real-tool e2e uses a
# throwaway git repo.  All tmp dirs are cleaned up via a trap.
#
# ADV-009: the fake-secret fixture is CONSTRUCTED AT RUNTIME from fragments;
# the assembled string never appears in this tracked file.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-merge.sh
# Exit:  0 = all tests passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERGE_SCRIPT="$SCRIPT_DIR/../scripts/merge-findings.py"
SPINE_SCRIPT="$SCRIPT_DIR/../scripts/spine/run.sh"
RUBRIC_FILE="$SCRIPT_DIR/../schemas/severity-rubric.json"

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

# Validate a single finding JSON object against finding.schema.json.
# Returns:
#   0  valid finding
#   1  non-finding record (provenance/coverage_gap/skipped) -- caller skips
#   2  invalid finding
validate_finding() {
  local json_line="$1"
  python3 - "$json_line" << 'PYEOF'
import json, re, sys
line = sys.argv[1]
try:
    obj = json.loads(line)
except json.JSONDecodeError:
    sys.exit(1)
if not isinstance(obj, dict):
    sys.exit(1)
if obj.get("type") in ("skipped", "coverage_gap", "provenance"):
    sys.exit(1)
required = {"check_id","rule_id","severity","confidence","location","message","fingerprint","detection","source"}
missing = required - obj.keys()
if missing:
    print("Missing: " + str(sorted(missing)), file=sys.stderr)
    sys.exit(2)
if not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_.-]+", obj["check_id"]):
    print("Bad check_id: " + obj["check_id"], file=sys.stderr)
    sys.exit(2)
if obj["severity"] not in ("critical","high","medium","low","info"):
    print("Bad severity: " + obj["severity"], file=sys.stderr)
    sys.exit(2)
if obj["confidence"] not in ("high","medium","low"):
    print("Bad confidence: " + obj["confidence"], file=sys.stderr)
    sys.exit(2)
if obj["detection"] not in ("tool","llm","hybrid"):
    print("Bad detection: " + obj["detection"], file=sys.stderr)
    sys.exit(2)
if obj["source"] not in ("tool","llm"):
    print("Bad source: " + obj["source"], file=sys.stderr)
    sys.exit(2)
loc = obj.get("location", {})
if not isinstance(loc, dict) or "path" not in loc or "line" not in loc:
    print("Bad location", file=sys.stderr)
    sys.exit(2)
if not isinstance(loc["line"], int) or loc["line"] < 1:
    print("Bad line number", file=sys.stderr)
    sys.exit(2)
fp = obj.get("fingerprint", "")
if not re.fullmatch(r"[A-Za-z0-9_.:+/=\-]{8,128}", fp):
    print("Bad fingerprint: " + fp, file=sys.stderr)
    sys.exit(2)
sys.exit(0)
PYEOF
}

# Count finding lines in a JSONL string (excludes type= records)
count_findings() {
  python3 - "$1" << 'PYEOF'
import json, sys
count = 0
for l in sys.argv[1].splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj:
            count += 1
    except Exception:
        pass
print(count)
PYEOF
}

# Get field from first finding matching fingerprint in a JSONL string
# Usage: get_finding_field <jsonl_str> <fingerprint> <field>
get_finding_field() {
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

# Get nested field: get_finding_nested_field <jsonl_str> <fp> <parent_field> <child_field>
get_finding_nested_field() {
  python3 - "$1" "$2" "$3" "$4" << 'PYEOF'
import json, sys
output, fp, parent, child = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            parent_val = obj.get(parent)
            if isinstance(parent_val, dict):
                val = parent_val.get(child)
                print("" if val is None else str(val))
            else:
                print("__no_parent__")
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Check if fingerprint exists in output as a finding
fp_exists() {
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

# Count records of a given type in a JSONL string
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
        if obj.get("type") == type_val:
            count += 1
    except Exception:
        pass
print(count)
PYEOF
}

# Get type of first record in JSONL string
first_type() {
  python3 - "$1" << 'PYEOF'
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
}

# ---------------------------------------------------------------------------
# Global temp directory (all subtests use subdirs within it)
# ---------------------------------------------------------------------------
TESTRUN_DIR="$(mktemp -d /tmp/ccgm-test-merge-XXXXXX)"
trap 'rm -rf "$TESTRUN_DIR"' EXIT

# ---------------------------------------------------------------------------
# Helper: write a minimal spine JSONL
# ---------------------------------------------------------------------------
write_spine() {
  # write_spine <out_file> [finding_json] [note_json]
  local out_file="$1"
  local finding_json="${2:-}"
  local note_json="${3:-}"
  python3 - "$out_file" "$finding_json" "$note_json" << 'PYEOF'
import json, sys
out_file = sys.argv[1]
finding_json = sys.argv[2]
note_json = sys.argv[3]
lines = []
lines.append(json.dumps({
    "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
    "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
    "timestamp": "2026-01-01T00:00:00Z",
}))
if finding_json:
    lines.append(finding_json)
if note_json:
    lines.append(note_json)
with open(out_file, "w") as fh:
    for l in lines:
        fh.write(l + "\n")
PYEOF
}

# ---------------------------------------------------------------------------
# Test 1: same fingerprint -- tool finding wins over LLM finding
# ---------------------------------------------------------------------------
printf '\nTest 1: same fingerprint -- tool wins over llm\n'

T1_DIR="$TESTRUN_DIR/t1"
mkdir -p "$T1_DIR"

T1_FP="aabbccdd11223344:1"

T1_SPINE_FINDING="$(python3 -c "
import json
print(json.dumps({
  'check_id': 'code-quality/eslint-violation',
  'rule_id': 'no-console',
  'severity': 'critical',
  'confidence': 'high',
  'detection': 'tool',
  'source': 'tool',
  'message': 'console.log usage',
  'location': {'path': 'src/main.js', 'line': 10},
  'fingerprint': '${T1_FP}'
}))
")"

write_spine "$T1_DIR/spine.jsonl" "$T1_SPINE_FINDING"

python3 - "$T1_DIR/llm.json" "$T1_FP" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [
        {
          "check_id": "code-quality/eslint-violation",
          "rule_id": "no-console",
          "severity": "high",
          "confidence": "medium",
          "detection": "llm",
          "source": "llm",
          "message": "console.log usage detected by llm",
          "location": {"path": "src/main.js", "line": 10},
          "fingerprint": fp
        }
      ],
      "spine_triage": []
    }, fh)
PYEOF

set +e
T1_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T1_DIR/spine.jsonl" \
  --llm "$T1_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T1_EXIT=$?
set -e

if [[ $T1_EXIT -eq 0 ]]; then
  pass "t1: merge-findings exits 0"
else
  fail "t1: merge-findings exits $T1_EXIT (expected 0)"
fi

T1_FINDING_COUNT="$(count_findings "$T1_OUT")"
if [[ "$T1_FINDING_COUNT" -eq 1 ]]; then
  pass "t1: exactly one finding survives dedup"
else
  fail "t1: expected 1 finding, got $T1_FINDING_COUNT"
fi

T1_SOURCE="$(get_finding_field "$T1_OUT" "$T1_FP" "source")"
if [[ "$T1_SOURCE" == "tool" ]]; then
  pass "t1: surviving finding is source=tool"
else
  fail "t1: surviving finding source='$T1_SOURCE' (expected 'tool')"
fi

# ---------------------------------------------------------------------------
# Test 2: hybrid triage -- dismissed absent, confirmed present
# ---------------------------------------------------------------------------
printf '\nTest 2: hybrid triage -- dismissed absent, confirmed present\n'

T2_DIR="$TESTRUN_DIR/t2"
mkdir -p "$T2_DIR"

T2_FP_DISMISSED="bbccddee22334455:1"
T2_FP_CONFIRMED="ccddee1122334466:1"

python3 - "$T2_DIR/spine.jsonl" "$T2_FP_DISMISSED" "$T2_FP_CONFIRMED" << 'PYEOF'
import json, sys
spine_file, fp_dis, fp_con = sys.argv[1], sys.argv[2], sys.argv[3]
lines = [
    {"type": "provenance", "tool": "ccgm-spine", "version": "1.0",
     "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
     "timestamp": "2026-01-01T00:00:00Z"},
    {"check_id": "security/hardcoded-secret", "rule_id": "semgrep-rule",
     "severity": "high", "confidence": "medium",
     "detection": "hybrid", "source": "tool",
     "message": "possible hardcoded secret",
     "location": {"path": "src/config.py", "line": 5},
     "fingerprint": fp_dis},
    {"check_id": "security/hardcoded-secret", "rule_id": "semgrep-rule",
     "severity": "high", "confidence": "medium",
     "detection": "hybrid", "source": "tool",
     "message": "another hardcoded secret",
     "location": {"path": "src/config.py", "line": 20},
     "fingerprint": fp_con},
]
with open(spine_file, "w") as fh:
    for l in lines:
        fh.write(json.dumps(l) + "\n")
PYEOF

python3 - "$T2_DIR/llm.json" "$T2_FP_DISMISSED" "$T2_FP_CONFIRMED" << 'PYEOF'
import json, sys
out, fp_dis, fp_con = sys.argv[1], sys.argv[2], sys.argv[3]
with open(out, "w") as fh:
    json.dump({
      "findings": [],
      "spine_triage": [
        {"fingerprint": fp_dis, "verdict": "dismissed", "note": "false positive"},
        {"fingerprint": fp_con, "verdict": "confirmed", "note": "real secret"}
      ]
    }, fh)
PYEOF

set +e
T2_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T2_DIR/spine.jsonl" \
  --llm "$T2_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T2_EXIT=$?
set -e

if [[ $T2_EXIT -eq 0 ]]; then
  pass "t2: merge exits 0"
else
  fail "t2: merge exits $T2_EXIT (expected 0)"
fi

DISMISSED_PRESENT="$(fp_exists "$T2_OUT" "$T2_FP_DISMISSED")"
if [[ "$DISMISSED_PRESENT" == "no" ]]; then
  pass "t2: dismissed hybrid is absent from output"
else
  fail "t2: dismissed hybrid is PRESENT in output (should have been dropped)"
fi

CONFIRMED_PRESENT="$(fp_exists "$T2_OUT" "$T2_FP_CONFIRMED")"
if [[ "$CONFIRMED_PRESENT" == "yes" ]]; then
  pass "t2: confirmed hybrid is present in output"
else
  fail "t2: confirmed hybrid is ABSENT from output (should be present)"
fi

# ---------------------------------------------------------------------------
# Test 3: rubric overwrite
#   a) LLM finding check_id=code-quality/eslint-violation carrying
#      severity="critical" -> output severity="medium" +
#      properties.agentReportedSeverity == "critical"
#   b) finding with severity already matching rubric -> NO agentReportedSeverity
# ---------------------------------------------------------------------------
printf '\nTest 3: rubric overwrite\n'

T3_DIR="$TESTRUN_DIR/t3"
mkdir -p "$T3_DIR"

T3_FP_WRONG="ddee11223344aabb:1"
T3_FP_MATCH="ee11223344aabbcc:1"

write_spine "$T3_DIR/spine.jsonl"

python3 - "$T3_DIR/llm.json" "$T3_FP_WRONG" "$T3_FP_MATCH" << 'PYEOF'
import json, sys
out, fp_wrong, fp_match = sys.argv[1], sys.argv[2], sys.argv[3]
with open(out, "w") as fh:
    json.dump({
      "findings": [
        {
          "check_id": "code-quality/eslint-violation",
          "rule_id": "no-unused-vars",
          "severity": "critical",
          "confidence": "high",
          "detection": "llm",
          "source": "llm",
          "message": "eslint violation (wrong severity)",
          "location": {"path": "src/app.js", "line": 3},
          "fingerprint": fp_wrong
        },
        {
          "check_id": "code-quality/eslint-violation",
          "rule_id": "no-unused-vars",
          "severity": "medium",
          "confidence": "high",
          "detection": "llm",
          "source": "llm",
          "message": "eslint violation (correct severity)",
          "location": {"path": "src/app.js", "line": 7},
          "fingerprint": fp_match
        }
      ],
      "spine_triage": []
    }, fh)
PYEOF

set +e
T3_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T3_DIR/spine.jsonl" \
  --llm "$T3_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T3_EXIT=$?
set -e

if [[ $T3_EXIT -eq 0 ]]; then
  pass "t3: merge exits 0"
else
  fail "t3: merge exits $T3_EXIT (expected 0)"
fi

# Check finding with wrong severity
T3A_SEV="$(get_finding_field "$T3_OUT" "$T3_FP_WRONG" "severity")"
if [[ "$T3A_SEV" == "medium" ]]; then
  pass "t3a: rubric overwrote severity to 'medium'"
else
  fail "t3a: severity='$T3A_SEV' (expected 'medium' from rubric)"
fi

T3A_AGENT_SEV="$(get_finding_nested_field "$T3_OUT" "$T3_FP_WRONG" "properties" "agentReportedSeverity")"
if [[ "$T3A_AGENT_SEV" == "critical" ]]; then
  pass "t3a: agentReportedSeverity='critical' preserved in properties"
else
  fail "t3a: agentReportedSeverity='$T3A_AGENT_SEV' (expected 'critical')"
fi

# Check finding with matching severity -- must NOT have agentReportedSeverity
T3B_AGENT_SEV="$(get_finding_nested_field "$T3_OUT" "$T3_FP_MATCH" "properties" "agentReportedSeverity")"
if [[ "$T3B_AGENT_SEV" == "__not_found__" || "$T3B_AGENT_SEV" == "__no_parent__" || "$T3B_AGENT_SEV" == "" ]]; then
  pass "t3b: no agentReportedSeverity when severity matches rubric"
else
  fail "t3b: spurious agentReportedSeverity='$T3B_AGENT_SEV' when severity already matched rubric"
fi

# ---------------------------------------------------------------------------
# Test 4: unrubriced check_id -> confidence forced low, unrubriced=true
# ---------------------------------------------------------------------------
printf '\nTest 4: unrubriced check_id\n'

T4_DIR="$TESTRUN_DIR/t4"
mkdir -p "$T4_DIR"

T4_FP="ff11223344aabbcc:1"

write_spine "$T4_DIR/spine.jsonl"

python3 - "$T4_DIR/llm.json" "$T4_FP" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [
        {
          "check_id": "zzz/not-in-rubric",
          "rule_id": "custom-rule",
          "severity": "high",
          "confidence": "high",
          "detection": "llm",
          "source": "llm",
          "message": "custom finding not in rubric",
          "location": {"path": "src/utils.py", "line": 42},
          "fingerprint": fp
        }
      ],
      "spine_triage": []
    }, fh)
PYEOF

set +e
T4_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T4_DIR/spine.jsonl" \
  --llm "$T4_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T4_EXIT=$?
set -e

if [[ $T4_EXIT -eq 0 ]]; then
  pass "t4: merge exits 0"
else
  fail "t4: merge exits $T4_EXIT (expected 0)"
fi

T4_CONF="$(get_finding_field "$T4_OUT" "$T4_FP" "confidence")"
if [[ "$T4_CONF" == "low" ]]; then
  pass "t4: unrubriced finding has confidence=low"
else
  fail "t4: confidence='$T4_CONF' (expected 'low' for unrubriced)"
fi

T4_UNRUBRICED="$(get_finding_nested_field "$T4_OUT" "$T4_FP" "properties" "unrubriced")"
if [[ "$T4_UNRUBRICED" == "True" ]]; then
  pass "t4: properties.unrubriced=True set"
else
  fail "t4: properties.unrubriced='$T4_UNRUBRICED' (expected 'True')"
fi

# ---------------------------------------------------------------------------
# Test 5: coverage-gap folding + provenance passthrough
# ---------------------------------------------------------------------------
printf '\nTest 5: coverage-gap folding + provenance passthrough\n'

T5_DIR="$TESTRUN_DIR/t5"
mkdir -p "$T5_DIR"

T5_GAP="$(python3 -c "import json; print(json.dumps({'type':'coverage_gap','tool':'actionlint','check_id':'ci/invalid-workflow','description':'actionlint not installed'}))")"

write_spine "$T5_DIR/spine.jsonl" "" "$T5_GAP"

python3 - "$T5_DIR/llm.json" << 'PYEOF'
import json, sys
with open(sys.argv[1], "w") as fh:
    json.dump({"findings": [], "spine_triage": []}, fh)
PYEOF

set +e
T5_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T5_DIR/spine.jsonl" \
  --llm "$T5_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T5_EXIT=$?
set -e

if [[ $T5_EXIT -eq 0 ]]; then
  pass "t5: merge exits 0"
else
  fail "t5: merge exits $T5_EXIT (expected 0)"
fi

T5_FIRST="$(first_type "$T5_OUT")"
if [[ "$T5_FIRST" == "provenance" ]]; then
  pass "t5: provenance record appears first"
else
  fail "t5: first record type='$T5_FIRST' (expected 'provenance')"
fi

T5_GAP_COUNT="$(count_type "$T5_OUT" "coverage_gap")"
if [[ "$T5_GAP_COUNT" -ge 1 ]]; then
  pass "t5: coverage_gap records folded through ($T5_GAP_COUNT found)"
else
  fail "t5: no coverage_gap records in output (expected >= 1)"
fi

# Dedup: write the same gap twice to the spine -> should appear once in output
python3 - "$T5_DIR/spine_dup.jsonl" "$T5_GAP" << 'PYEOF'
import json, sys
spine_file, gap_json = sys.argv[1], sys.argv[2]
with open(spine_file, "w") as fh:
    fh.write(json.dumps({
        "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
        "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    # Write the same gap twice
    fh.write(gap_json + "\n")
    fh.write(gap_json + "\n")
PYEOF

set +e
T5_DUP_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T5_DIR/spine_dup.jsonl" \
  --llm "$T5_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
set -e

T5_DUP_GAP_COUNT="$(python3 - "$T5_DUP_OUT" "ci/invalid-workflow" << 'PYEOF'
import json, sys
output, check_id = sys.argv[1], sys.argv[2]
count = 0
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if obj.get("type") == "coverage_gap" and obj.get("check_id") == check_id:
            count += 1
    except Exception:
        pass
print(count)
PYEOF
)"

if [[ "$T5_DUP_GAP_COUNT" -eq 1 ]]; then
  pass "t5: duplicate coverage_gap records deduped to 1"
else
  fail "t5: duplicate coverage_gap not deduped (got $T5_DUP_GAP_COUNT, expected 1)"
fi

# ---------------------------------------------------------------------------
# Test 6: output validity -- every finding passes schema validation
# ---------------------------------------------------------------------------
printf '\nTest 6: output validity -- all findings pass schema validation\n'

T6_DIR="$TESTRUN_DIR/t6"
mkdir -p "$T6_DIR"

T6_FP_A="112233445566aabb:1"
T6_FP_B="223344556677bbcc:1"

python3 - "$T6_DIR/spine.jsonl" "$T6_FP_A" << 'PYEOF'
import json, sys
spine_file, fp_a = sys.argv[1], sys.argv[2]
with open(spine_file, "w") as fh:
    fh.write(json.dumps({
        "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
        "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    fh.write(json.dumps({
        "check_id": "secrets/leaked-credential",
        "rule_id": "aws-access-token",
        "severity": "high",
        "confidence": "high",
        "detection": "tool",
        "source": "tool",
        "message": "AWS key found AKIA[redacted:len=20]",
        "location": {"path": "config/env.py", "line": 2},
        "fingerprint": fp_a,
        "properties": {"tool": "gitleaks"}
    }) + "\n")
PYEOF

python3 - "$T6_DIR/llm.json" "$T6_FP_B" << 'PYEOF'
import json, sys
out, fp_b = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [
        {
          "check_id": "security/sql-injection",
          "rule_id": "sql-injection-001",
          "severity": "high",
          "confidence": "medium",
          "detection": "llm",
          "source": "llm",
          "message": "potential sql injection",
          "location": {"path": "src/db.py", "line": 15},
          "fingerprint": fp_b
        }
      ],
      "spine_triage": []
    }, fh)
PYEOF

set +e
T6_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T6_DIR/spine.jsonl" \
  --llm "$T6_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T6_EXIT=$?
set -e

if [[ $T6_EXIT -eq 0 ]]; then
  pass "t6: merge exits 0"
else
  fail "t6: merge exits $T6_EXIT (expected 0)"
fi

T6_VALID=0
T6_INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  V=0
  validate_finding "$line" || V=$?
  if [[ $V -eq 0 ]]; then
    T6_VALID=$((T6_VALID + 1))
  elif [[ $V -eq 2 ]]; then
    T6_INVALID=$((T6_INVALID + 1))
    printf '    SCHEMA FAIL: %s\n' "$line" >&2
  fi
done <<< "$T6_OUT"

if [[ $T6_VALID -ge 2 ]]; then
  pass "t6: $T6_VALID finding(s) validate against finding.schema.json"
else
  fail "t6: only $T6_VALID finding(s) valid (expected >= 2)"
fi
if [[ $T6_INVALID -eq 0 ]]; then
  pass "t6: no invalid findings"
else
  fail "t6: $T6_INVALID finding(s) failed schema validation"
fi

# Rubric: secrets/leaked-credential spine finding -> severity should become critical
T6_LEAKED_SEV="$(get_finding_field "$T6_OUT" "$T6_FP_A" "severity")"
if [[ "$T6_LEAKED_SEV" == "critical" ]]; then
  pass "t6: secrets/leaked-credential rubric applied (severity=critical)"
else
  fail "t6: secrets/leaked-credential severity='$T6_LEAKED_SEV' (expected 'critical' from rubric)"
fi

# ---------------------------------------------------------------------------
# Test 7 (REAL-TOOL E2E): gitleaks on a throwaway repo + rubric enforcement
# ---------------------------------------------------------------------------
printf '\nTest 7 (real-tool e2e): gitleaks integration\n'

if ! command -v gitleaks > /dev/null 2>&1; then
  printf '  [SKIP] gitleaks not installed -- e2e test skipped\n'
else
  E2E_DIR="$(mktemp -d /tmp/ccgm-e2e-XXXXXX)"
  # Note: outer trap already removes TESTRUN_DIR; add E2E_DIR cleanup
  trap 'rm -rf "$TESTRUN_DIR" "$E2E_DIR"' EXIT

  # Build a throwaway git repo with a fake AWS key.
  # ADV-009: the assembled key string is CONSTRUCTED AT RUNTIME from fragments.
  # The prefix "AKIA" and the 16-char suffix "ABCDEFGHIJKLMNOP" are never
  # concatenated in any tracked file -- only at runtime here.
  # NOTE: the AWS docs example key is "AKIA" + "IOSFODNN7EXAMPLE" (fragmented
  # here per ADV-009 to prevent secret-scanner false positives on this file);
  # that combined value is allow-listed in gitleaks.  We use a different 16-char
  # suffix ("ABCDEFGHIJKLMNOP") that triggers real detection without being a
  # real credential.
  git init "$E2E_DIR/repo" --quiet 2>/dev/null
  git -C "$E2E_DIR/repo" config user.email "test@test.test"
  git -C "$E2E_DIR/repo" config user.name "Test"
  # Disable global hooks for this throwaway repo so the test is self-contained
  # and does not trigger any project pre-commit infrastructure.
  git -C "$E2E_DIR/repo" config core.hooksPath /dev/null 2>/dev/null || true

  # Construct the fake key from two separate string fragments (ADV-009)
  KEY_PART1="AKIA"
  KEY_PART2="ABCDEFGHIJKLMNOP"
  FAKE_KEY="${KEY_PART1}${KEY_PART2}"

  # Write a file containing the assembled key (runtime only -- not tracked by CCGM)
  python3 - "$E2E_DIR/repo/secrets.env" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("# Test environment\n")
    fh.write(f"AWS_ACCESS_KEY_ID={key}\n")
    fh.write("APP_ENV=development\n")
PYEOF

  git -C "$E2E_DIR/repo" add secrets.env
  git -C "$E2E_DIR/repo" commit -m "test: add config" --quiet 2>/dev/null

  # Run the real spine (gitleaks only)
  E2E_SPINE="$E2E_DIR/spine.jsonl"
  set +e
  bash "$SPINE_SCRIPT" --repo "$E2E_DIR/repo" --tools gitleaks --output "$E2E_SPINE" 2>/dev/null
  SPINE_E2E_EXIT=$?
  set -e

  if [[ $SPINE_E2E_EXIT -eq 0 ]]; then
    pass "t7: spine (gitleaks) exits 0"
  else
    fail "t7: spine (gitleaks) exits $SPINE_E2E_EXIT (expected 0)"
  fi

  # Run merge with real rubric (no LLM files)
  E2E_MERGED="$E2E_DIR/merged.jsonl"
  set +e
  python3 "$MERGE_SCRIPT" --spine "$E2E_SPINE" --rubric "$RUBRIC_FILE" \
    --repo "$E2E_DIR/repo" --output "$E2E_MERGED" 2>/dev/null
  MERGE_E2E_EXIT=$?
  set -e

  if [[ $MERGE_E2E_EXIT -eq 0 ]]; then
    pass "t7: merge-findings exits 0 on real spine output"
  else
    fail "t7: merge-findings exits $MERGE_E2E_EXIT (expected 0)"
  fi

  # Assert >= 1 finding with check_id=secrets/leaked-credential
  E2E_CRED_COUNT="$(python3 - "$E2E_MERGED" << 'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as fh:
    for l in fh:
        l = l.strip()
        if not l:
            continue
        try:
            obj = json.loads(l)
            if isinstance(obj, dict) and "type" not in obj:
                if obj.get("check_id") == "secrets/leaked-credential":
                    count += 1
        except Exception:
            pass
print(count)
PYEOF
)"

  if [[ "$E2E_CRED_COUNT" -ge 1 ]]; then
    pass "t7: >= 1 finding with check_id=secrets/leaked-credential from real gitleaks"
  else
    fail "t7: 0 findings with check_id=secrets/leaked-credential (expected >= 1)"
  fi

  # Assert severity=critical.
  # parse-gitleaks.py maps aws-access-token to "critical" in _RULE_SEVERITY, so
  # the parser severity and the rubric severity coincide for this rule.  The
  # NON-vacuous proof that rubric enforcement is mechanical (not just passing
  # through the parser value) is t6: t6 feeds the same check_id with spine
  # severity="high" and asserts output severity="critical" -- proving the rubric
  # step fires independently of what the parser emitted.  See t6 above.
  E2E_SEV="$(python3 - "$E2E_MERGED" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    for l in fh:
        l = l.strip()
        if not l:
            continue
        try:
            obj = json.loads(l)
            if isinstance(obj, dict) and "type" not in obj:
                if obj.get("check_id") == "secrets/leaked-credential":
                    print(obj.get("severity", "?"))
                    sys.exit(0)
        except Exception:
            pass
print("not_found")
PYEOF
)"

  if [[ "$E2E_SEV" == "critical" ]]; then
    pass "t7: severity=critical enforced by rubric (parser+rubric both map aws-access-token->critical)"
  else
    fail "t7: severity='$E2E_SEV' (expected 'critical' from rubric)"
  fi

  # Assert valid fingerprint
  E2E_FP_VALID="$(python3 - "$E2E_MERGED" << 'PYEOF'
import json, re, sys
with open(sys.argv[1]) as fh:
    for l in fh:
        l = l.strip()
        if not l:
            continue
        try:
            obj = json.loads(l)
            if isinstance(obj, dict) and "type" not in obj:
                if obj.get("check_id") == "secrets/leaked-credential":
                    fp = obj.get("fingerprint", "")
                    if re.fullmatch(r"[A-Za-z0-9_.:+/=\-]{8,128}", fp):
                        print("valid")
                    else:
                        print("invalid:" + fp)
                    sys.exit(0)
        except Exception:
            pass
print("not_found")
PYEOF
)"

  if [[ "$E2E_FP_VALID" == "valid" ]]; then
    pass "t7: finding has valid fingerprint"
  else
    fail "t7: fingerprint result='$E2E_FP_VALID' (expected 'valid')"
  fi

  # Assert the assembled fake key does NOT appear in merged output (redaction held)
  if grep -qF "$FAKE_KEY" "$E2E_MERGED" 2>/dev/null; then
    fail "t7: assembled fake key appears in merged output -- redaction failed"
  else
    pass "t7: assembled fake key is NOT in merged output -- redaction held"
  fi

  # Run spine with actionlint (not installed) -> verify coverage_gap folds through merge
  E2E_ACTION_SPINE="$E2E_DIR/spine_action.jsonl"
  set +e
  bash "$SPINE_SCRIPT" --repo "$E2E_DIR/repo" --tools actionlint --output "$E2E_ACTION_SPINE" 2>/dev/null
  set -e

  E2E_ACTION_MERGED="$E2E_DIR/merged_action.jsonl"
  set +e
  python3 "$MERGE_SCRIPT" --spine "$E2E_ACTION_SPINE" --rubric "$RUBRIC_FILE" \
    --repo "$E2E_DIR/repo" --output "$E2E_ACTION_MERGED" 2>/dev/null
  ACTION_MERGE_EXIT=$?
  set -e

  if [[ $ACTION_MERGE_EXIT -eq 0 ]]; then
    pass "t7: merge exits 0 on actionlint-only spine"
  else
    fail "t7: merge exits $ACTION_MERGE_EXIT on actionlint spine"
  fi

  E2E_ACTION_GAP_COUNT="$(python3 - "$E2E_ACTION_MERGED" << 'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as fh:
    for l in fh:
        l = l.strip()
        if not l:
            continue
        try:
            obj = json.loads(l)
            if obj.get("type") == "coverage_gap":
                count += 1
        except Exception:
            pass
print(count)
PYEOF
)"

  if [[ "$E2E_ACTION_GAP_COUNT" -ge 1 ]]; then
    pass "t7: actionlint coverage_gap folds through merge ($E2E_ACTION_GAP_COUNT gap(s))"
  else
    fail "t7: no coverage_gap records in actionlint spine merge output (expected >= 1)"
  fi
fi

# ---------------------------------------------------------------------------
# Test 8: worker trust-boundary -- dismissed verdict on tool-detection finding
#   (a) dismissed verdict targeting detection="tool" finding -> warning on stderr
#       AND the finding is kept (non-hybrid findings are not dismissible)
# ---------------------------------------------------------------------------
printf '\nTest 8a: dismissed verdict on tool-detection finding -- warn + keep\n'

T8_DIR="$TESTRUN_DIR/t8"
mkdir -p "$T8_DIR"

T8_FP_TOOL="334455667788aabb:1"

python3 - "$T8_DIR/spine.jsonl" "$T8_FP_TOOL" << 'PYEOF'
import json, sys
spine_file, fp = sys.argv[1], sys.argv[2]
with open(spine_file, "w") as fh:
    fh.write(json.dumps({
        "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
        "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    fh.write(json.dumps({
        "check_id": "security/hardcoded-secret",
        "rule_id": "gitleaks-rule",
        "severity": "high",
        "confidence": "high",
        "detection": "tool",
        "source": "tool",
        "message": "hardcoded secret detected by tool",
        "location": {"path": "src/config.py", "line": 10},
        "fingerprint": fp,
    }) + "\n")
PYEOF

python3 - "$T8_DIR/llm.json" "$T8_FP_TOOL" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [],
      "spine_triage": [
        {"fingerprint": fp, "verdict": "dismissed", "note": "worker tries to dismiss tool finding"}
      ]
    }, fh)
PYEOF

set +e
T8A_STDERR="$(python3 "$MERGE_SCRIPT" --spine "$T8_DIR/spine.jsonl" \
  --llm "$T8_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>&1 >/dev/null)"
T8A_OUT="$(python3 "$MERGE_SCRIPT" --spine "$T8_DIR/spine.jsonl" \
  --llm "$T8_DIR/llm.json" --rubric "$RUBRIC_FILE" 2>/dev/null)"
T8A_EXIT=$?
set -e

if [[ $T8A_EXIT -eq 0 ]]; then
  pass "t8a: merge exits 0 (tool finding kept)"
else
  fail "t8a: merge exits $T8A_EXIT (expected 0)"
fi

T8A_PRESENT="$(fp_exists "$T8A_OUT" "$T8_FP_TOOL")"
if [[ "$T8A_PRESENT" == "yes" ]]; then
  pass "t8a: tool-detection finding is kept despite dismissed verdict"
else
  fail "t8a: tool-detection finding was incorrectly dropped by dismissed verdict"
fi

if echo "$T8A_STDERR" | grep -q "WARNING.*non-hybrid\|WARNING.*not dismissible"; then
  pass "t8a: stderr warning emitted for attempted non-hybrid dismissal"
else
  fail "t8a: no warning on stderr for attempted non-hybrid dismissal (got: $T8A_STDERR)"
fi

# ---------------------------------------------------------------------------
# Test 8b: invalid finding (string line) -> exit 1 with actionable message
# ---------------------------------------------------------------------------
printf '\nTest 8b: invalid finding (string line) -> exit 1 with actionable message\n'

T8B_FP="445566778899bbcc:1"

python3 - "$T8_DIR/llm_badline.json" "$T8B_FP" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [
        {
          "check_id": "code-quality/eslint-violation",
          "rule_id": "no-unused-vars",
          "severity": "medium",
          "confidence": "medium",
          "detection": "llm",
          "source": "llm",
          "message": "eslint violation",
          # line is a string instead of int -- malformed input
          "location": {"path": "src/app.js", "line": "7"},
          "fingerprint": fp
        }
      ],
      "spine_triage": []
    }, fh)
PYEOF

write_spine "$T8_DIR/spine_empty.jsonl"

set +e
T8B_STDERR="$(python3 "$MERGE_SCRIPT" --spine "$T8_DIR/spine_empty.jsonl" \
  --llm "$T8_DIR/llm_badline.json" --rubric "$RUBRIC_FILE" 2>&1 >/dev/null)"
T8B_EXIT=$?
set -e

if [[ $T8B_EXIT -eq 1 ]]; then
  pass "t8b: merge exits 1 on string-line finding"
else
  fail "t8b: merge exits $T8B_EXIT (expected 1 for malformed input)"
fi

# Assert actionable error message (not a bare traceback)
if echo "$T8B_STDERR" | grep -q "VALIDATION ERROR\|location.line must be"; then
  pass "t8b: stderr contains actionable error message (not a traceback)"
else
  fail "t8b: stderr does not contain actionable error message (got: $T8B_STDERR)"
fi

# Assert no traceback leaked
if echo "$T8B_STDERR" | grep -q "Traceback\|TypeError"; then
  fail "t8b: bare Python traceback leaked to stderr (got: $T8B_STDERR)"
else
  pass "t8b: no bare traceback in stderr"
fi

# ---------------------------------------------------------------------------
# Test 8c: deterministic ordering -- two runs produce byte-identical output
# ---------------------------------------------------------------------------
printf '\nTest 8c: deterministic ordering -- two runs produce byte-identical output\n'

T8C_DIR="$TESTRUN_DIR/t8c"
mkdir -p "$T8C_DIR"

# Write spine with two findings at different paths/lines
python3 - "$T8C_DIR/spine.jsonl" << 'PYEOF'
import json, sys
with open(sys.argv[1], "w") as fh:
    fh.write(json.dumps({
        "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
        "repo": "/tmp/test-repo", "tools_requested": "gitleaks",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    fh.write(json.dumps({
        "check_id": "security/hardcoded-secret",
        "rule_id": "rule-b",
        "severity": "high", "confidence": "high",
        "detection": "tool", "source": "tool",
        "message": "secret at z file",
        "location": {"path": "z/file.py", "line": 5},
        "fingerprint": "zz9988776655aabb:1",
    }) + "\n")
    fh.write(json.dumps({
        "check_id": "code-quality/eslint-violation",
        "rule_id": "rule-a",
        "severity": "medium", "confidence": "medium",
        "detection": "tool", "source": "tool",
        "message": "eslint at a file",
        "location": {"path": "a/file.py", "line": 1},
        "fingerprint": "aa1122334455bbcc:1",
    }) + "\n")
PYEOF

set +e
T8C_RUN1="$(python3 "$MERGE_SCRIPT" --spine "$T8C_DIR/spine.jsonl" \
  --rubric "$RUBRIC_FILE" 2>/dev/null)"
T8C_RUN2="$(python3 "$MERGE_SCRIPT" --spine "$T8C_DIR/spine.jsonl" \
  --rubric "$RUBRIC_FILE" 2>/dev/null)"
set -e

if [[ "$T8C_RUN1" == "$T8C_RUN2" ]]; then
  pass "t8c: two runs produce byte-identical output (deterministic)"
else
  fail "t8c: runs differ -- output is non-deterministic"
fi

# Also verify that findings are sorted (a/file.py before z/file.py)
T8C_PATHS="$(python3 - "$T8C_RUN1" << 'PYEOF'
import json, sys
paths = []
for l in sys.argv[1].splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj:
            paths.append(obj.get("location", {}).get("path", ""))
    except Exception:
        pass
print(",".join(paths))
PYEOF
)"

if [[ "$T8C_PATHS" == "a/file.py,z/file.py" ]]; then
  pass "t8c: output is sorted by path (a/file.py before z/file.py)"
else
  fail "t8c: output order unexpected: '$T8C_PATHS' (expected 'a/file.py,z/file.py')"
fi

# ---------------------------------------------------------------------------
# Test 8d: conflicting cross-file verdicts -> finding kept + warning
# ---------------------------------------------------------------------------
printf '\nTest 8d: conflicting cross-file verdicts -> finding kept + warning\n'

T8D_DIR="$TESTRUN_DIR/t8d"
mkdir -p "$T8D_DIR"

T8D_FP="556677889900ccdd:1"

python3 - "$T8D_DIR/spine.jsonl" "$T8D_FP" << 'PYEOF'
import json, sys
spine_file, fp = sys.argv[1], sys.argv[2]
with open(spine_file, "w") as fh:
    fh.write(json.dumps({
        "type": "provenance", "tool": "ccgm-spine", "version": "1.0",
        "repo": "/tmp/test-repo", "tools_requested": "semgrep",
        "timestamp": "2026-01-01T00:00:00Z",
    }) + "\n")
    fh.write(json.dumps({
        "check_id": "security/hardcoded-secret",
        "rule_id": "semgrep-rule",
        "severity": "high", "confidence": "medium",
        "detection": "hybrid", "source": "tool",
        "message": "possible secret",
        "location": {"path": "src/auth.py", "line": 7},
        "fingerprint": fp,
    }) + "\n")
PYEOF

# Worker A says dismissed
python3 - "$T8D_DIR/worker_a.json" "$T8D_FP" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [],
      "spine_triage": [{"fingerprint": fp, "verdict": "dismissed", "note": "worker A says false positive"}]
    }, fh)
PYEOF

# Worker B says confirmed
python3 - "$T8D_DIR/worker_b.json" "$T8D_FP" << 'PYEOF'
import json, sys
out, fp = sys.argv[1], sys.argv[2]
with open(out, "w") as fh:
    json.dump({
      "findings": [],
      "spine_triage": [{"fingerprint": fp, "verdict": "confirmed", "note": "worker B says real"}]
    }, fh)
PYEOF

# Test both orderings: A then B, and B then A
set +e
T8D_STDERR_AB="$(python3 "$MERGE_SCRIPT" --spine "$T8D_DIR/spine.jsonl" \
  --llm "$T8D_DIR/worker_a.json" --llm "$T8D_DIR/worker_b.json" \
  --rubric "$RUBRIC_FILE" 2>&1 >/dev/null)"
T8D_OUT_AB="$(python3 "$MERGE_SCRIPT" --spine "$T8D_DIR/spine.jsonl" \
  --llm "$T8D_DIR/worker_a.json" --llm "$T8D_DIR/worker_b.json" \
  --rubric "$RUBRIC_FILE" 2>/dev/null)"
T8D_EXIT_AB=$?

T8D_STDERR_BA="$(python3 "$MERGE_SCRIPT" --spine "$T8D_DIR/spine.jsonl" \
  --llm "$T8D_DIR/worker_b.json" --llm "$T8D_DIR/worker_a.json" \
  --rubric "$RUBRIC_FILE" 2>&1 >/dev/null)"
T8D_OUT_BA="$(python3 "$MERGE_SCRIPT" --spine "$T8D_DIR/spine.jsonl" \
  --llm "$T8D_DIR/worker_b.json" --llm "$T8D_DIR/worker_a.json" \
  --rubric "$RUBRIC_FILE" 2>/dev/null)"
T8D_EXIT_BA=$?
set -e

if [[ $T8D_EXIT_AB -eq 0 && $T8D_EXIT_BA -eq 0 ]]; then
  pass "t8d: merge exits 0 for both orderings"
else
  fail "t8d: merge exits $T8D_EXIT_AB (A+B) / $T8D_EXIT_BA (B+A) (expected 0)"
fi

T8D_PRESENT_AB="$(fp_exists "$T8D_OUT_AB" "$T8D_FP")"
T8D_PRESENT_BA="$(fp_exists "$T8D_OUT_BA" "$T8D_FP")"

if [[ "$T8D_PRESENT_AB" == "yes" && "$T8D_PRESENT_BA" == "yes" ]]; then
  pass "t8d: finding kept in both orderings (dismissal requires unanimity)"
else
  fail "t8d: finding unexpectedly dropped -- AB=$T8D_PRESENT_AB, BA=$T8D_PRESENT_BA"
fi

if echo "$T8D_STDERR_AB" | grep -q "WARNING.*conflict\|WARNING.*unanimity\|WARNING.*dismissal"; then
  pass "t8d: warning emitted for conflicting verdicts (A+B order)"
else
  fail "t8d: no conflict warning in A+B order (stderr: $T8D_STDERR_AB)"
fi

if echo "$T8D_STDERR_BA" | grep -q "WARNING.*conflict\|WARNING.*unanimity\|WARNING.*dismissal"; then
  pass "t8d: warning emitted for conflicting verdicts (B+A order)"
else
  fail "t8d: no conflict warning in B+A order (stderr: $T8D_STDERR_BA)"
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
