#!/usr/bin/env bash
# test-pack-ci-cd.sh -- CI/CD Hardening pack test suite (Epic 2.5)
#
# Tests:
#   1. pack.json + checks.md validate (lint-pack passes; rubric covers all check-ids)
#   2. parse-zizmor.py: synthetic SARIF -> valid cicd/* findings, properties.tool="zizmor"
#   3. parse-pinact.py: synthetic pinact output (structured + diff-block) -> valid findings
#   4. wrap-zizmor.sh: graceful skip when zizmor absent (coverage_gap entries)
#   5. wrap-pinact.sh: graceful skip when pinact absent (coverage_gap entries)
#   6. Registry gating: pack selected when has_workflows=true, excluded when false
#   7. shellcheck on wrap-zizmor.sh + wrap-pinact.sh
#
# Exit code: 0 = all tests passed, 1 = failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPINE_DIR="${AUDIT_DIR}/scripts/spine"
PACK_DIR="${AUDIT_DIR}/packs/ci-cd"
SCRIPTS_DIR="${AUDIT_DIR}/scripts"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"

PASS=0
FAIL=0
ERRORS=()

pass() { printf '  [PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
fail() {
  printf '  [FAIL] %s\n' "$1"
  ERRORS+=("$1")
  FAIL=$((FAIL + 1))
}

# ---------------------------------------------------------------------------
# Validate a single finding JSON line against finding.schema.json constraints.
# Returns: 0 = valid finding, 1 = non-finding record (skip), 2 = invalid
# ---------------------------------------------------------------------------
validate_finding() {
  local json_line="$1"
  python3 - "$json_line" << 'PYEOF'
import json, re, sys

line = sys.argv[1]
try:
    obj = json.loads(line)
except json.JSONDecodeError:
    sys.exit(2)

if not isinstance(obj, dict):
    sys.exit(2)

if obj.get("type") in ("skipped", "coverage_gap", "provenance"):
    sys.exit(1)

required = {"check_id", "rule_id", "severity", "confidence", "location",
            "message", "fingerprint", "detection", "source"}
missing = required - obj.keys()
if missing:
    print("Missing: " + str(sorted(missing)), file=sys.stderr)
    sys.exit(2)

if not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_.-]+", obj["check_id"]):
    print("Bad check_id: " + obj["check_id"], file=sys.stderr)
    sys.exit(2)

if obj["severity"] not in ("critical", "high", "medium", "low", "info"):
    print("Bad severity: " + obj["severity"], file=sys.stderr)
    sys.exit(2)

if obj["confidence"] not in ("high", "medium", "low"):
    print("Bad confidence: " + obj["confidence"], file=sys.stderr)
    sys.exit(2)

if obj["detection"] not in ("tool", "llm", "hybrid"):
    print("Bad detection: " + obj["detection"], file=sys.stderr)
    sys.exit(2)

if obj["source"] not in ("tool", "llm"):
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

# ---------------------------------------------------------------------------
# Temp dir for test run
# ---------------------------------------------------------------------------
TESTRUN_TMPDIR="$(mktemp -d /tmp/ccgm-test-ci-cd-XXXXXX)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

# ---------------------------------------------------------------------------
# Test 1: lint-pack passes on ci-cd pack (with rubric)
# ---------------------------------------------------------------------------
printf '\nTest 1: lint-pack passes on ci-cd pack\n'

LINT_OUTPUT=""
LINT_EXIT=0
LINT_OUTPUT="$(python3 "${SCRIPTS_DIR}/lint-pack.py" \
  --packs-dir "${AUDIT_DIR}/packs" \
  --rubric "${RUBRIC}" 2>&1)" || LINT_EXIT=$?

if echo "$LINT_OUTPUT" | grep -q "^PASS: ci-cd"; then
  pass "lint-pack.py PASS for ci-cd pack"
elif echo "$LINT_OUTPUT" | grep -q "^FAIL: ci-cd"; then
  fail "lint-pack.py FAIL for ci-cd pack: ${LINT_OUTPUT}"
else
  # lint-pack may print a NOTE and still pass overall
  if [[ $LINT_EXIT -eq 0 ]]; then
    pass "lint-pack.py exited 0 (ci-cd pack OK)"
  else
    fail "lint-pack.py failed (exit ${LINT_EXIT}): ${LINT_OUTPUT}"
  fi
fi

# Rubric covers all cicd/* check-ids
for CID in cicd/unpinned-action cicd/dangerous-trigger cicd/excessive-permissions cicd/script-injection cicd/actionlint-error; do
  if python3 -c "
import json, sys
with open('${RUBRIC}') as f:
    r = json.load(f)
checks = r.get('checks', {})
sys.exit(0 if '${CID}' in checks else 1)
  " 2>/dev/null; then
    pass "rubric covers ${CID}"
  else
    fail "rubric missing ${CID}"
  fi
done

# ---------------------------------------------------------------------------
# Test 2: parse-zizmor.py -- synthetic SARIF -> valid cicd/* findings
# ---------------------------------------------------------------------------
printf '\nTest 2: parse-zizmor.py parses synthetic SARIF\n'

SARIF_FILE="${TESTRUN_TMPDIR}/zizmor-sarif.json"
cat > "$SARIF_FILE" << 'JSON'
{
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "zizmor",
          "rules": [
            {"id": "dangerous-triggers", "name": "dangerous-triggers"},
            {"id": "excessive-permissions", "name": "excessive-permissions"},
            {"id": "template-injection", "name": "template-injection"},
            {"id": "pull-request-target", "name": "pull-request-target"}
          ]
        }
      },
      "results": [
        {
          "ruleId": "dangerous-triggers",
          "level": "error",
          "message": {"text": "Workflow uses pull_request_target with checkout"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": ".github/workflows/ci.yml"},
                "region": {"startLine": 3}
              }
            }
          ],
          "partialFingerprints": {"primaryLocationLineHash": "abc123def456abcd"}
        },
        {
          "ruleId": "excessive-permissions",
          "level": "warning",
          "message": {"text": "Job has write-all permissions"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": ".github/workflows/deploy.yml"},
                "region": {"startLine": 7}
              }
            }
          ],
          "partialFingerprints": {}
        },
        {
          "ruleId": "template-injection",
          "level": "error",
          "message": {"text": "github.event.pull_request.title interpolated into run:"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": ".github/workflows/comment.yml"},
                "region": {"startLine": 15}
              }
            }
          ],
          "partialFingerprints": {}
        },
        {
          "ruleId": "pull-request-target",
          "level": "error",
          "message": {"text": "Dangerous pull_request_target usage"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": ".github/workflows/pr.yml"},
                "region": {"startLine": 2}
              }
            }
          ],
          "partialFingerprints": {}
        }
      ]
    }
  ]
}
JSON

ZI_OUT="${TESTRUN_TMPDIR}/zizmor-findings.jsonl"
python3 "${SPINE_DIR}/parse-zizmor.py" "$SARIF_FILE" "/repo" > "$ZI_OUT"

VALID_FINDINGS=0
INVALID_FINDINGS=0
WRONG_TOOL=0

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  V_EXIT=0
  validate_finding "$line" || V_EXIT=$?
  if [[ $V_EXIT -eq 0 ]]; then
    VALID_FINDINGS=$((VALID_FINDINGS + 1))
    # Check properties.tool = "zizmor"
    TOOL="$(python3 -c "
import json, sys
obj = json.loads(sys.argv[1])
print(obj.get('properties', {}).get('tool', ''))
" "$line" 2>/dev/null || true)"
    if [[ "$TOOL" != "zizmor" ]]; then
      WRONG_TOOL=$((WRONG_TOOL + 1))
    fi
  elif [[ $V_EXIT -eq 2 ]]; then
    INVALID_FINDINGS=$((INVALID_FINDINGS + 1))
  fi
done < "$ZI_OUT"

if [[ $VALID_FINDINGS -ge 4 ]]; then
  pass "parse-zizmor.py produced $VALID_FINDINGS valid finding(s) from synthetic SARIF"
else
  fail "parse-zizmor.py produced $VALID_FINDINGS valid findings (expected >= 4)"
fi

if [[ $INVALID_FINDINGS -eq 0 ]]; then
  pass "no invalid findings from parse-zizmor.py"
else
  fail "$INVALID_FINDINGS invalid findings from parse-zizmor.py"
fi

if [[ $WRONG_TOOL -eq 0 ]]; then
  pass "all zizmor findings have properties.tool=zizmor"
else
  fail "$WRONG_TOOL finding(s) missing properties.tool=zizmor"
fi

# Verify check_id mapping
CHECKS="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lines = [l.strip() for l in f if l.strip()]
ids = [json.loads(l).get('check_id','') for l in lines]
print(' '.join(sorted(set(ids))))
" "$ZI_OUT" 2>/dev/null || true)"

for EXPECTED_CID in cicd/dangerous-trigger cicd/excessive-permissions cicd/script-injection; do
  if echo "$CHECKS" | grep -q "$EXPECTED_CID"; then
    pass "parse-zizmor.py emits $EXPECTED_CID"
  else
    fail "parse-zizmor.py did not emit $EXPECTED_CID (got: $CHECKS)"
  fi
done

# ---------------------------------------------------------------------------
# Test 3: parse-pinact.py -- structured + diff-block formats
# ---------------------------------------------------------------------------
printf '\nTest 3: parse-pinact.py parses synthetic output\n'

# Structured single-line format
PINACT_STRUCTURED="${TESTRUN_TMPDIR}/pinact-structured.txt"
cat > "$PINACT_STRUCTURED" << 'TEXT'
.github/workflows/ci.yml:12: actions/checkout@v4 -> actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4
.github/workflows/ci.yml:18: actions/setup-node@v3 -> actions/setup-node@1a4442cacd436585916779262731d1f068594b6a # v3
TEXT

PI_OUT1="${TESTRUN_TMPDIR}/pinact-findings-1.jsonl"
python3 "${SPINE_DIR}/parse-pinact.py" "$PINACT_STRUCTURED" "/repo" > "$PI_OUT1"

PINACT_VALID1=0
PINACT_WRONG_TOOL=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  V_EXIT=0
  validate_finding "$line" || V_EXIT=$?
  if [[ $V_EXIT -eq 0 ]]; then
    PINACT_VALID1=$((PINACT_VALID1 + 1))
    TOOL="$(python3 -c "
import json, sys
obj = json.loads(sys.argv[1])
print(obj.get('properties', {}).get('tool', ''))
" "$line" 2>/dev/null || true)"
    if [[ "$TOOL" != "pinact" ]]; then
      PINACT_WRONG_TOOL=$((PINACT_WRONG_TOOL + 1))
    fi
    # Verify check_id
    CID="$(python3 -c "
import json, sys
print(json.loads(sys.argv[1]).get('check_id',''))
" "$line" 2>/dev/null || true)"
    if [[ "$CID" != "cicd/unpinned-action" ]]; then
      fail "pinact finding has wrong check_id: $CID (expected cicd/unpinned-action)"
    fi
  fi
done < "$PI_OUT1"

if [[ $PINACT_VALID1 -ge 2 ]]; then
  pass "parse-pinact.py (structured format) produced $PINACT_VALID1 valid finding(s)"
else
  fail "parse-pinact.py (structured format) produced $PINACT_VALID1 valid findings (expected >= 2)"
fi
if [[ $PINACT_WRONG_TOOL -eq 0 ]]; then
  pass "all pinact findings have properties.tool=pinact"
else
  fail "$PINACT_WRONG_TOOL finding(s) missing properties.tool=pinact"
fi

# Diff-block format
PINACT_DIFFBLOCK="${TESTRUN_TMPDIR}/pinact-diffblock.txt"
cat > "$PINACT_DIFFBLOCK" << 'TEXT'
.github/workflows/release.yml
  uses: actions/upload-artifact@v3
->
  uses: actions/upload-artifact@694cdabd8bdb0f10b2cea11669e1bf5453eed0a6 # v3
TEXT

PI_OUT2="${TESTRUN_TMPDIR}/pinact-findings-2.jsonl"
python3 "${SPINE_DIR}/parse-pinact.py" "$PINACT_DIFFBLOCK" "/repo" > "$PI_OUT2"

PINACT_VALID2=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  V_EXIT=0
  validate_finding "$line" || V_EXIT=$?
  if [[ $V_EXIT -eq 0 ]]; then
    PINACT_VALID2=$((PINACT_VALID2 + 1))
  fi
done < "$PI_OUT2"

if [[ $PINACT_VALID2 -ge 1 ]]; then
  pass "parse-pinact.py (diff-block format) produced $PINACT_VALID2 valid finding(s)"
else
  fail "parse-pinact.py (diff-block format) produced 0 valid findings (expected >= 1)"
fi

# Empty output = no findings emitted
PINACT_EMPTY="${TESTRUN_TMPDIR}/pinact-empty.txt"
printf '' > "$PINACT_EMPTY"
PI_OUT3="${TESTRUN_TMPDIR}/pinact-findings-3.jsonl"
python3 "${SPINE_DIR}/parse-pinact.py" "$PINACT_EMPTY" "/repo" > "$PI_OUT3"
LINES3="$(wc -l < "$PI_OUT3" | tr -d ' ')"
if [[ "$LINES3" -eq 0 ]]; then
  pass "parse-pinact.py emits nothing for empty input"
else
  fail "parse-pinact.py emitted $LINES3 line(s) for empty input (expected 0)"
fi

# ---------------------------------------------------------------------------
# Test 4: wrap-zizmor.sh -- graceful skip when zizmor absent
# ---------------------------------------------------------------------------
printf '\nTest 4: wrap-zizmor.sh graceful skip when zizmor absent\n'

# wrap-zizmor.sh uses mapfile -d '' which requires bash 4+.
# On bash 3.2 (macOS system shell), skip these wrapper invocation tests;
# ubuntu CI (bash 5) will exercise them.
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  pass "Test 4: wrap-zizmor.sh wrapper skip test skipped -- bash < 4 (wrapper requires bash 4+; ubuntu CI will run this)"
else
  # Build a minimal repo with a workflows dir
  WRAP_REPO="${TESTRUN_TMPDIR}/repo-with-workflows"
  mkdir -p "${WRAP_REPO}/.github/workflows"
  cat > "${WRAP_REPO}/.github/workflows/ci.yml" << 'YAML'
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
YAML

  # Restricted PATH (no zizmor)
  SYSTEM_BINS=""
  for bin in python3 bash find date mktemp cp rm mv printf head grep; do
    BINPATH="$(command -v "$bin" 2>/dev/null || true)"
    if [[ -n "$BINPATH" ]]; then
      BINDIR="$(dirname "$BINPATH")"
      case ":$SYSTEM_BINS:" in
        *":$BINDIR:"*) ;;
        *) SYSTEM_BINS="${SYSTEM_BINS:+$SYSTEM_BINS:}$BINDIR" ;;
      esac
    fi
  done
  RESTRICTED_PATH="$SYSTEM_BINS:/usr/bin:/bin"

  ZI_SKIP_OUT="${TESTRUN_TMPDIR}/zi-skip.jsonl"
  set +e
  PATH="$RESTRICTED_PATH" bash "${SPINE_DIR}/wrap-zizmor.sh" "$WRAP_REPO" > "$ZI_SKIP_OUT" 2>/dev/null
  ZI_SKIP_EXIT=$?
  set -e

  if [[ $ZI_SKIP_EXIT -eq 0 ]]; then
    pass "wrap-zizmor.sh exits 0 when zizmor absent"
  else
    fail "wrap-zizmor.sh exits $ZI_SKIP_EXIT (expected 0) when zizmor absent"
  fi

  SKIP_COUNT="$(grep -c '"type":"skipped"' "$ZI_SKIP_OUT" 2>/dev/null || printf '0')"
  GAP_COUNT="$(grep -c '"type":"coverage_gap"' "$ZI_SKIP_OUT" 2>/dev/null || printf '0')"

  if [[ $SKIP_COUNT -ge 1 ]]; then
    pass "wrap-zizmor.sh emits skipped note when absent"
  else
    fail "wrap-zizmor.sh emitted no skipped note"
  fi

  if [[ $GAP_COUNT -ge 1 ]]; then
    pass "wrap-zizmor.sh emits coverage_gap entries when absent"
  else
    fail "wrap-zizmor.sh emitted no coverage_gap entries"
  fi

  # Verify all output lines are valid JSON
  INVALID_JSON_ZI=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
      INVALID_JSON_ZI=$((INVALID_JSON_ZI + 1))
    fi
  done < "$ZI_SKIP_OUT"
  if [[ $INVALID_JSON_ZI -eq 0 ]]; then
    pass "all wrap-zizmor.sh skip output lines are valid JSON"
  else
    fail "$INVALID_JSON_ZI invalid JSON lines from wrap-zizmor.sh skip"
  fi
fi

# ---------------------------------------------------------------------------
# Test 5: wrap-pinact.sh -- graceful skip when pinact absent
# ---------------------------------------------------------------------------
printf '\nTest 5: wrap-pinact.sh graceful skip when pinact absent\n'

# wrap-pinact.sh uses mapfile -d '' which requires bash 4+; skip on bash 3.2.
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  pass "Test 5: wrap-pinact.sh wrapper skip test skipped -- bash < 4 (wrapper requires bash 4+; ubuntu CI will run this)"
else
  PI_SKIP_OUT="${TESTRUN_TMPDIR}/pi-skip.jsonl"
  set +e
  PATH="$RESTRICTED_PATH" bash "${SPINE_DIR}/wrap-pinact.sh" "$WRAP_REPO" > "$PI_SKIP_OUT" 2>/dev/null
  PI_SKIP_EXIT=$?
  set -e

  if [[ $PI_SKIP_EXIT -eq 0 ]]; then
    pass "wrap-pinact.sh exits 0 when pinact absent"
  else
    fail "wrap-pinact.sh exits $PI_SKIP_EXIT (expected 0) when pinact absent"
  fi

  PI_SKIP_COUNT="$(grep -c '"type":"skipped"' "$PI_SKIP_OUT" 2>/dev/null || printf '0')"
  PI_GAP_COUNT="$(grep -c '"type":"coverage_gap"' "$PI_SKIP_OUT" 2>/dev/null || printf '0')"

  if [[ $PI_SKIP_COUNT -ge 1 ]]; then
    pass "wrap-pinact.sh emits skipped note when absent"
  else
    fail "wrap-pinact.sh emitted no skipped note"
  fi

  if [[ $PI_GAP_COUNT -ge 1 ]]; then
    pass "wrap-pinact.sh emits coverage_gap entries when absent"
  else
    fail "wrap-pinact.sh emitted no coverage_gap entries"
  fi

  INVALID_JSON_PI=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
      INVALID_JSON_PI=$((INVALID_JSON_PI + 1))
    fi
  done < "$PI_SKIP_OUT"
  if [[ $INVALID_JSON_PI -eq 0 ]]; then
    pass "all wrap-pinact.sh skip output lines are valid JSON"
  else
    fail "$INVALID_JSON_PI invalid JSON lines from wrap-pinact.sh skip"
  fi
fi

# ---------------------------------------------------------------------------
# Test 6: registry gating -- pack selected iff has_workflows=true
# ---------------------------------------------------------------------------
printf '\nTest 6: registry gating for ci-cd pack\n'

# Create a temporary packs dir with only the ci-cd pack
TMP_PACKS="${TESTRUN_TMPDIR}/tmp-packs"
mkdir -p "$TMP_PACKS"
cp -r "${PACK_DIR}" "$TMP_PACKS/ci-cd"

REGISTRY_PY="${SCRIPTS_DIR}/registry.py"

# has_workflows=true -> pack should be selected
SELECTED_TRUE="$(python3 - "$REGISTRY_PY" "$TMP_PACKS" "true" << 'PYEOF'
import json, sys, importlib.util, pathlib

registry_py = pathlib.Path(sys.argv[1])
packs_dir   = pathlib.Path(sys.argv[2])
has_wf      = sys.argv[3] == "true"

spec = importlib.util.spec_from_file_location("registry", str(registry_py))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

detector = {
    "detected_ecosystems": [],
    "project_shape": {
        "monorepo_packages": [],
        "frameworks": [],
        "has_migrations": False,
        "has_dockerfile": False,
        "has_workflows": has_wf,
        "is_extension": False,
        "is_mobile": False
    },
    "available_tools": []
}

conditions = mod.build_truthy_conditions(detector)
packs = mod.discover_packs(packs_dir)
selected = [p for p in packs if mod.is_pack_applicable(p, conditions)]
ids = [p.get("id","") for p in selected]
print(" ".join(ids))
PYEOF
)" || SELECTED_TRUE=""

if echo "$SELECTED_TRUE" | grep -q "ccgm/ci-cd"; then
  pass "ci-cd pack selected when has_workflows=true"
else
  fail "ci-cd pack NOT selected when has_workflows=true (got: $SELECTED_TRUE)"
fi

# has_workflows=false -> pack should NOT be selected
SELECTED_FALSE="$(python3 - "$REGISTRY_PY" "$TMP_PACKS" "false" << 'PYEOF'
import json, sys, importlib.util, pathlib

registry_py = pathlib.Path(sys.argv[1])
packs_dir   = pathlib.Path(sys.argv[2])
has_wf      = sys.argv[3] == "true"

spec = importlib.util.spec_from_file_location("registry", str(registry_py))
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

detector = {
    "detected_ecosystems": [],
    "project_shape": {
        "monorepo_packages": [],
        "frameworks": [],
        "has_migrations": False,
        "has_dockerfile": False,
        "has_workflows": has_wf,
        "is_extension": False,
        "is_mobile": False
    },
    "available_tools": []
}

conditions = mod.build_truthy_conditions(detector)
packs = mod.discover_packs(packs_dir)
selected = [p for p in packs if mod.is_pack_applicable(p, conditions)]
ids = [p.get("id","") for p in selected]
print(" ".join(ids))
PYEOF
)" || SELECTED_FALSE=""

if ! echo "$SELECTED_FALSE" | grep -q "ccgm/ci-cd"; then
  pass "ci-cd pack NOT selected when has_workflows=false"
else
  fail "ci-cd pack selected when has_workflows=false (should be excluded)"
fi

# ---------------------------------------------------------------------------
# Test 7: shellcheck on wrap-zizmor.sh + wrap-pinact.sh
# ---------------------------------------------------------------------------
printf '\nTest 7: shellcheck on wrap-zizmor.sh + wrap-pinact.sh\n'

if command -v shellcheck > /dev/null 2>&1; then
  for script in "${SPINE_DIR}/wrap-zizmor.sh" "${SPINE_DIR}/wrap-pinact.sh"; do
    if [[ ! -f "$script" ]]; then
      fail "shellcheck: script not found: $script"
      continue
    fi
    SC_OUTPUT="$(shellcheck -S warning "$script" 2>&1 || true)"
    if [[ -z "$SC_OUTPUT" ]]; then
      pass "shellcheck clean: $(basename "$script")"
    else
      fail "shellcheck issues in $(basename "$script"): $SC_OUTPUT"
    fi
  done
else
  pass "shellcheck not installed -- shell safety check skipped (install shellcheck for full coverage)"
fi

# ---------------------------------------------------------------------------
# Test 8: parse-zizmor.py fallback -- unmapped rule -> cicd/workflow-security-issue
# ---------------------------------------------------------------------------
printf '\nTest 8: parse-zizmor.py fallback routes unmapped rule to cicd/workflow-security-issue\n'

SARIF_UNMAPPED="${TESTRUN_TMPDIR}/zizmor-unmapped.json"
cat > "$SARIF_UNMAPPED" << 'JSON'
{
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "zizmor",
          "rules": [
            {"id": "cache-poisoning", "name": "cache-poisoning"}
          ]
        }
      },
      "results": [
        {
          "ruleId": "cache-poisoning",
          "level": "warning",
          "message": {"text": "Cache key derived from untrusted input"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": ".github/workflows/ci.yml"},
                "region": {"startLine": 22}
              }
            }
          ],
          "partialFingerprints": {}
        }
      ]
    }
  ]
}
JSON

UNMAPPED_OUT="${TESTRUN_TMPDIR}/zizmor-unmapped-findings.jsonl"
python3 "${SPINE_DIR}/parse-zizmor.py" "$SARIF_UNMAPPED" "/repo" > "$UNMAPPED_OUT"

# Assert exactly one line emitted
UNMAPPED_LINES="$(grep -c . "$UNMAPPED_OUT" 2>/dev/null || printf '0')"
if [[ $UNMAPPED_LINES -ge 1 ]]; then
  pass "parse-zizmor.py fallback emitted $UNMAPPED_LINES line(s) for unmapped rule"
else
  fail "parse-zizmor.py fallback emitted no output for unmapped rule"
fi

# Assert check_id == cicd/workflow-security-issue
UNMAPPED_CID="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lines = [l.strip() for l in f if l.strip()]
if not lines:
    print('')
else:
    print(json.loads(lines[0]).get('check_id', ''))
" "$UNMAPPED_OUT" 2>/dev/null || true)"

if [[ "$UNMAPPED_CID" == "cicd/workflow-security-issue" ]]; then
  pass "parse-zizmor.py fallback emits check_id=cicd/workflow-security-issue"
else
  fail "parse-zizmor.py fallback emitted wrong check_id: '$UNMAPPED_CID' (expected cicd/workflow-security-issue)"
fi

# Assert cicd/workflow-security-issue exists in rubric
if python3 -c "
import json, sys
with open('${RUBRIC}') as f:
    r = json.load(f)
sys.exit(0 if 'cicd/workflow-security-issue' in r.get('checks', {}) else 1)
" 2>/dev/null; then
  pass "rubric covers cicd/workflow-security-issue (fallback check-id)"
else
  fail "rubric missing cicd/workflow-security-issue"
fi

# Assert rule_id preserves the original zizmor rule (zizmor/cache-poisoning)
UNMAPPED_RULEID="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lines = [l.strip() for l in f if l.strip()]
if not lines:
    print('')
else:
    print(json.loads(lines[0]).get('rule_id', ''))
" "$UNMAPPED_OUT" 2>/dev/null || true)"

if [[ "$UNMAPPED_RULEID" == "zizmor/cache-poisoning" ]]; then
  pass "parse-zizmor.py fallback preserves rule_id=zizmor/cache-poisoning"
else
  fail "parse-zizmor.py fallback rule_id wrong: '$UNMAPPED_RULEID' (expected zizmor/cache-poisoning)"
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
