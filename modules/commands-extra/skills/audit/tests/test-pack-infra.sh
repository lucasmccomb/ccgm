#!/usr/bin/env bash
# CCGM audit -- test suite for infra-iac pack (Epic 4.3)
#
# Tests:
#   1. Pack is SELECTED for a repo with a root-user Dockerfile (has_iac=true)
#   2. Pack is NOT selected for a plain repo (has_iac=false)
#   3. wrap-checkov.sh emits graceful coverage-gap when checkov is absent
#   4. parse-checkov.py unit test: synthetic JSON -> valid JSONL findings
#   5. pack.json validates against registry.py pack validator
#   6. severity-rubric.json has iac/* entries
#   7. shellcheck: wrap-checkov.sh is clean
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-pack-infra.sh
# Exit: 0 = all pass, non-zero = any failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$SCRIPT_DIR/.."
SPINE_DIR="$AUDIT_DIR/scripts/spine"
REGISTRY_PY="$AUDIT_DIR/scripts/registry.py"
DETECT_SH="$AUDIT_DIR/scripts/detect-ecosystems.sh"
RUBRIC_JSON="$AUDIT_DIR/schemas/severity-rubric.json"
PACK_DIR="$AUDIT_DIR/packs/infra-iac"

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

skip() {
  printf '  [SKIP] %s\n' "$1"
}

# ---------------------------------------------------------------------------
# Temp directory for all runtime fixtures
# ---------------------------------------------------------------------------
TESTRUN_TMPDIR="$(mktemp -d /tmp/ccgm-infra-test-XXXXXX)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

# ---------------------------------------------------------------------------
# Test 1: Pack SELECTED for has_iac repo (root-user Dockerfile)
# ---------------------------------------------------------------------------
printf '\nTest 1: infra-iac pack selected for has_iac=true fixture\n'

FIXTURE_IAC="$TESTRUN_TMPDIR/iac-repo"
mkdir -p "$FIXTURE_IAC"

# Root-user Dockerfile (no USER directive → runs as root)
cat > "$FIXTURE_IAC/Dockerfile" <<'EOF'
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y nginx
CMD ["nginx", "-g", "daemon off;"]
EOF

# Detect ecosystems for this fixture
DETECTOR_JSON="$TESTRUN_TMPDIR/detector-iac.json"
if bash "$DETECT_SH" "$FIXTURE_IAC" > "$DETECTOR_JSON" 2>/dev/null; then
  pass "detector ran successfully on iac fixture"
else
  fail "detector failed on iac fixture"
fi

# Verify has_iac=true in detector output
HAS_IAC=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['project_shape'].get('has_iac', False))" \
  "$DETECTOR_JSON" 2>/dev/null || echo "False")
if [ "$HAS_IAC" = "True" ]; then
  pass "detector: has_iac=true for Dockerfile fixture"
else
  fail "detector: expected has_iac=true, got: $HAS_IAC"
fi

# Use registry.py to select packs; verify infra-iac is selected
SELECTED_JSON="$TESTRUN_TMPDIR/selected-iac.json"
if python3 "$REGISTRY_PY" "$DETECTOR_JSON" > "$SELECTED_JSON" 2>/dev/null; then
  pass "registry.py ran successfully"
else
  fail "registry.py failed"
fi

INFRA_SELECTED=$(python3 -c "
import json, sys
packs = json.load(open(sys.argv[1]))
ids = [p['id'] for p in packs]
print('yes' if 'ccgm/infra-iac' in ids else 'no')
" "$SELECTED_JSON" 2>/dev/null || echo "no")

if [ "$INFRA_SELECTED" = "yes" ]; then
  pass "registry: infra-iac pack selected for has_iac=true repo"
else
  fail "registry: infra-iac pack NOT selected for has_iac=true repo"
fi

# ---------------------------------------------------------------------------
# Test 1b: Public-ingress Terraform fixture also triggers has_iac
# ---------------------------------------------------------------------------
printf '\nTest 1b: infra-iac pack selected for Terraform fixture\n'

FIXTURE_TF="$TESTRUN_TMPDIR/tf-repo"
mkdir -p "$FIXTURE_TF"
cat > "$FIXTURE_TF/main.tf" <<'EOF'
resource "aws_security_group" "open" {
  name = "wide-open"
  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
EOF

DETECTOR_TF="$TESTRUN_TMPDIR/detector-tf.json"
bash "$DETECT_SH" "$FIXTURE_TF" > "$DETECTOR_TF" 2>/dev/null

TF_HAS_IAC=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['project_shape'].get('has_iac', False))" \
  "$DETECTOR_TF" 2>/dev/null || echo "False")
if [ "$TF_HAS_IAC" = "True" ]; then
  pass "detector: has_iac=true for Terraform fixture"
else
  fail "detector: expected has_iac=true for .tf fixture, got: $TF_HAS_IAC"
fi

SELECTED_TF="$TESTRUN_TMPDIR/selected-tf.json"
python3 "$REGISTRY_PY" "$DETECTOR_TF" > "$SELECTED_TF" 2>/dev/null

TF_INFRA_SELECTED=$(python3 -c "
import json, sys
packs = json.load(open(sys.argv[1]))
ids = [p['id'] for p in packs]
print('yes' if 'ccgm/infra-iac' in ids else 'no')
" "$SELECTED_TF" 2>/dev/null || echo "no")

if [ "$TF_INFRA_SELECTED" = "yes" ]; then
  pass "registry: infra-iac selected for Terraform fixture"
else
  fail "registry: infra-iac NOT selected for Terraform fixture"
fi

# ---------------------------------------------------------------------------
# Test 2: Pack NOT selected for plain (no-IaC) repo
# ---------------------------------------------------------------------------
printf '\nTest 2: infra-iac pack NOT selected for plain repo\n'

FIXTURE_PLAIN="$TESTRUN_TMPDIR/plain-repo"
mkdir -p "$FIXTURE_PLAIN"
printf '{"name":"plain","version":"1.0.0"}\n' > "$FIXTURE_PLAIN/package.json"

DETECTOR_PLAIN="$TESTRUN_TMPDIR/detector-plain.json"
bash "$DETECT_SH" "$FIXTURE_PLAIN" > "$DETECTOR_PLAIN" 2>/dev/null

PLAIN_HAS_IAC=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['project_shape'].get('has_iac', False))" \
  "$DETECTOR_PLAIN" 2>/dev/null || echo "True")
if [ "$PLAIN_HAS_IAC" = "False" ]; then
  pass "detector: has_iac=false for plain JS repo"
else
  fail "detector: expected has_iac=false for plain JS repo, got: $PLAIN_HAS_IAC"
fi

SELECTED_PLAIN="$TESTRUN_TMPDIR/selected-plain.json"
python3 "$REGISTRY_PY" "$DETECTOR_PLAIN" > "$SELECTED_PLAIN" 2>/dev/null

PLAIN_INFRA_SELECTED=$(python3 -c "
import json, sys
packs = json.load(open(sys.argv[1]))
ids = [p['id'] for p in packs]
print('yes' if 'ccgm/infra-iac' in ids else 'no')
" "$SELECTED_PLAIN" 2>/dev/null || echo "yes")

if [ "$PLAIN_INFRA_SELECTED" = "no" ]; then
  pass "registry: infra-iac pack NOT selected for plain repo"
else
  fail "registry: infra-iac pack incorrectly selected for plain repo (no IaC)"
fi

# ---------------------------------------------------------------------------
# Test 3: wrap-checkov.sh graceful skip when checkov absent
# ---------------------------------------------------------------------------
printf '\nTest 3: wrap-checkov.sh graceful coverage-gap when checkov absent\n'

WRAP_CHECKOV="$SPINE_DIR/wrap-checkov.sh"

if [[ ! -f "$WRAP_CHECKOV" ]]; then
  fail "wrap-checkov.sh not found at: $WRAP_CHECKOV"
else
  pass "wrap-checkov.sh file exists"
fi

# Build a deterministic scratch PATH that excludes checkov.
# bash and python3 are linked from their currently-active location (may be
# homebrew on macOS) so bash 4+ and the real python3 are available.
# All other tools come from /usr/bin and /bin only, excluding homebrew
# audit tools (checkov, etc.) from leaking in.
SCRATCH_BINDIR="$TESTRUN_TMPDIR/scratch-bin"
mkdir -p "$SCRATCH_BINDIR"
for _bin in bash python3; do
  _src="$(command -v "$_bin" 2>/dev/null || true)"
  [[ -n "$_src" ]] && ln -sf "$_src" "$SCRATCH_BINDIR/$_bin" 2>/dev/null || true
done
for _bin in find dirname date mktemp cp rm mv printf head grep cat; do
  for _dir in /usr/bin /bin; do
    if [[ -x "$_dir/$_bin" ]]; then
      ln -sf "$_dir/$_bin" "$SCRATCH_BINDIR/$_bin" 2>/dev/null || true
      break
    fi
  done
done
RESTRICTED_PATH="$SCRATCH_BINDIR"

WRAP_OUTPUT="$TESTRUN_TMPDIR/wrap-checkov-absent.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_CHECKOV" "$FIXTURE_IAC" > "$WRAP_OUTPUT" 2>/dev/null
WRAP_EXIT=$?
set -e

if [[ $WRAP_EXIT -eq 0 ]]; then
  pass "wrap-checkov.sh exits 0 when checkov absent"
else
  fail "wrap-checkov.sh exits $WRAP_EXIT (expected 0) when checkov absent"
fi

if [[ -s "$WRAP_OUTPUT" ]]; then
  pass "wrap-checkov.sh produced output when checkov absent"
else
  fail "wrap-checkov.sh produced no output when checkov absent"
fi

# Verify output contains a skipped note
SKIP_COUNT="$(grep -c '"type":"skipped"' "$WRAP_OUTPUT" 2>/dev/null || printf '0')"
if [[ "$SKIP_COUNT" -gt 0 ]]; then
  pass "wrap-checkov.sh: found $SKIP_COUNT skipped note(s)"
else
  fail "wrap-checkov.sh: no skipped notes found (expected >= 1)"
fi

# Verify output contains coverage_gap entries
GAP_COUNT="$(grep -c '"type":"coverage_gap"' "$WRAP_OUTPUT" 2>/dev/null || printf '0')"
if [[ "$GAP_COUNT" -gt 0 ]]; then
  pass "wrap-checkov.sh: found $GAP_COUNT coverage-gap entries"
else
  fail "wrap-checkov.sh: no coverage_gap entries found (expected >= 1)"
fi

# All output lines must be valid JSON
INVALID_JSON=0
while IFS= read -r line; do
  if [[ -z "$line" ]]; then continue; fi
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID_JSON=$((INVALID_JSON + 1))
  fi
done < "$WRAP_OUTPUT"

if [[ $INVALID_JSON -eq 0 ]]; then
  pass "wrap-checkov.sh: all output lines are valid JSON"
else
  fail "wrap-checkov.sh: $INVALID_JSON output line(s) are invalid JSON"
fi

# ---------------------------------------------------------------------------
# Test 4: parse-checkov.py unit test -- synthetic JSON input
# ---------------------------------------------------------------------------
printf '\nTest 4: parse-checkov.py unit test against synthetic JSON\n'

PARSE_CHECKOV="$SPINE_DIR/parse-checkov.py"
if [[ ! -f "$PARSE_CHECKOV" ]]; then
  fail "parse-checkov.py not found at: $PARSE_CHECKOV"
else
  pass "parse-checkov.py file exists"
fi

# Synthetic checkov output: single-framework shape
SYNTHETIC_JSON="$TESTRUN_TMPDIR/synthetic-checkov.json"
cat > "$SYNTHETIC_JSON" <<'JSON'
{
  "check_type": "terraform",
  "results": {
    "failed_checks": [
      {
        "check_id": "CKV_AWS_20",
        "check_name": "Ensure the S3 bucket has access control list (ACL) is private",
        "file_path": "/main.tf",
        "file_line_range": [1, 10],
        "resource": "aws_s3_bucket.example"
      },
      {
        "check_id": "CKV_AWS_79",
        "check_name": "Ensure Instance Metadata Service Version 1 is not enabled",
        "file_path": "/ec2.tf",
        "file_line_range": [5, 20],
        "resource": "aws_instance.web"
      }
    ],
    "passed_checks": [],
    "skipped_checks": []
  }
}
JSON

PARSE_OUTPUT="$TESTRUN_TMPDIR/parse-checkov-output.jsonl"
FAKE_REPO="$TESTRUN_TMPDIR/fake-repo"
mkdir -p "$FAKE_REPO"

set +e
python3 "$PARSE_CHECKOV" "$SYNTHETIC_JSON" "$FAKE_REPO" > "$PARSE_OUTPUT" 2>/dev/null
PARSE_EXIT=$?
set -e

if [[ $PARSE_EXIT -eq 0 ]]; then
  pass "parse-checkov.py exits 0 on synthetic input"
else
  fail "parse-checkov.py exits $PARSE_EXIT on synthetic input (expected 0)"
fi

# Count findings
FINDING_COUNT=0
INVALID_FINDINGS=0

while IFS= read -r line; do
  if [[ -z "$line" ]]; then continue; fi
  IS_FINDING=$(python3 -c "
import json,sys
try:
    obj = json.loads(sys.argv[1])
    if isinstance(obj,dict) and obj.get('type') not in ('skipped','coverage_gap','provenance'):
        print('yes')
    else:
        print('no')
except Exception:
    print('no')
" "$line" 2>/dev/null || echo "no")
  if [[ "$IS_FINDING" == "yes" ]]; then
    FINDING_COUNT=$((FINDING_COUNT + 1))
    # Validate required fields
    VALID=$(python3 -c "
import json, re, sys
obj = json.loads(sys.argv[1])
required = {'check_id','rule_id','severity','confidence','location','message','fingerprint','detection','source'}
missing = required - obj.keys()
if missing:
    print('missing:' + ','.join(sorted(missing)))
    sys.exit(0)
if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9_.-]+', obj['check_id']):
    print('bad_check_id')
    sys.exit(0)
loc = obj.get('location',{})
if 'path' not in loc or 'line' not in loc:
    print('bad_location')
    sys.exit(0)
print('ok')
" "$line" 2>/dev/null || echo "error")
    if [[ "$VALID" != "ok" ]]; then
      INVALID_FINDINGS=$((INVALID_FINDINGS + 1))
    fi
  fi
done < "$PARSE_OUTPUT"

if [[ $FINDING_COUNT -ge 2 ]]; then
  pass "parse-checkov.py: found $FINDING_COUNT findings from synthetic input (expected >= 2)"
else
  fail "parse-checkov.py: expected >= 2 findings, got $FINDING_COUNT"
fi

if [[ $INVALID_FINDINGS -eq 0 ]]; then
  pass "parse-checkov.py: all findings have required fields and valid structure"
else
  fail "parse-checkov.py: $INVALID_FINDINGS finding(s) with invalid structure"
fi

# Verify check_id is iac/checkov-violation and rule_id is the checkov code
CHECK_ID_OK=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lines = [l.strip() for l in f if l.strip()]
findings = []
for l in lines:
    obj = json.loads(l)
    if obj.get('type') not in ('skipped','coverage_gap','provenance'):
        findings.append(obj)
if not findings:
    print('no_findings')
    sys.exit(0)
for f in findings:
    if f.get('check_id') != 'iac/checkov-violation':
        print('wrong_check_id:' + f.get('check_id',''))
        sys.exit(0)
    if not f.get('rule_id','').startswith('CKV'):
        print('wrong_rule_id:' + f.get('rule_id',''))
        sys.exit(0)
print('ok')
" "$PARSE_OUTPUT" 2>/dev/null || echo "error")

if [[ "$CHECK_ID_OK" == "ok" ]]; then
  pass "parse-checkov.py: check_id=iac/checkov-violation, rule_id=CKV_* as expected"
else
  fail "parse-checkov.py: unexpected check_id/rule_id: $CHECK_ID_OK"
fi

# Verify multi-framework input shape also parses
printf '\nTest 4b: parse-checkov.py handles multi-framework (array) input\n'

SYNTHETIC_MULTI="$TESTRUN_TMPDIR/synthetic-checkov-multi.json"
cat > "$SYNTHETIC_MULTI" <<'JSON'
[
  {
    "check_type": "terraform",
    "results": {
      "failed_checks": [
        {
          "check_id": "CKV_AWS_3",
          "check_name": "Ensure all data stored in the EBS is securely encrypted",
          "file_path": "/ebs.tf",
          "file_line_range": [1, 5],
          "resource": "aws_ebs_volume.data"
        }
      ]
    }
  },
  {
    "check_type": "dockerfile",
    "results": {
      "failed_checks": [
        {
          "check_id": "CKV_DOCKER_2",
          "check_name": "Ensure that HEALTHCHECK instructions have been added to container images",
          "file_path": "/Dockerfile",
          "file_line_range": [1, 3],
          "resource": "Dockerfile"
        }
      ]
    }
  }
]
JSON

PARSE_MULTI_OUTPUT="$TESTRUN_TMPDIR/parse-checkov-multi.jsonl"
set +e
python3 "$PARSE_CHECKOV" "$SYNTHETIC_MULTI" "$FAKE_REPO" > "$PARSE_MULTI_OUTPUT" 2>/dev/null
PARSE_MULTI_EXIT=$?
set -e

if [[ $PARSE_MULTI_EXIT -eq 0 ]]; then
  pass "parse-checkov.py exits 0 on multi-framework input"
else
  fail "parse-checkov.py exits $PARSE_MULTI_EXIT on multi-framework input"
fi

MULTI_FINDING_COUNT=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    lines = [l.strip() for l in f if l.strip()]
count = sum(1 for l in lines
    if json.loads(l).get('type') not in ('skipped','coverage_gap','provenance'))
print(count)
" "$PARSE_MULTI_OUTPUT" 2>/dev/null || echo "0")

if [[ "$MULTI_FINDING_COUNT" -ge 2 ]]; then
  pass "parse-checkov.py: multi-framework: $MULTI_FINDING_COUNT findings (expected >= 2)"
else
  fail "parse-checkov.py: multi-framework: expected >= 2 findings, got $MULTI_FINDING_COUNT"
fi

# ---------------------------------------------------------------------------
# Test 5: pack.json validates via registry.py validator
# ---------------------------------------------------------------------------
printf '\nTest 5: infra-iac pack.json passes registry.py validation\n'

PACK_JSON="$PACK_DIR/pack.json"
if [[ ! -f "$PACK_JSON" ]]; then
  fail "pack.json not found at: $PACK_JSON"
else
  pass "pack.json file exists"
fi

PACK_VALIDATE=$(python3 - "$PACK_JSON" "$REGISTRY_PY" << 'PYEOF'
import json, sys, os
sys.path.insert(0, os.path.dirname(sys.argv[2]))
from registry import validate_pack, ValidationError

with open(sys.argv[1]) as f:
    pack = json.load(f)

try:
    validate_pack(pack, sys.argv[1])
    print("ok")
except ValidationError as e:
    print("error:" + str(e))
PYEOF
)

if [[ "$PACK_VALIDATE" == "ok" ]]; then
  pass "pack.json passes registry.py validation"
else
  fail "pack.json fails registry.py validation: $PACK_VALIDATE"
fi

# ---------------------------------------------------------------------------
# Test 6: severity-rubric.json contains iac/* entries
# ---------------------------------------------------------------------------
printf '\nTest 6: severity-rubric.json has iac/* entries\n'

if [[ ! -f "$RUBRIC_JSON" ]]; then
  fail "severity-rubric.json not found at: $RUBRIC_JSON"
else
  pass "severity-rubric.json file exists"
fi

for CHECK_ID in "iac/dockerfile-root-user" "iac/dockerfile-latest-tag" "iac/public-ingress" \
                "iac/missing-encryption" "iac/hardcoded-secret-in-iac" \
                "iac/dockerfile-issue" "iac/checkov-violation"; do
  HAS_ENTRY=$(python3 -c "
import json, sys
rubric = json.load(open(sys.argv[1]))
checks = rubric.get('checks', {})
print('yes' if sys.argv[2] in checks else 'no')
" "$RUBRIC_JSON" "$CHECK_ID" 2>/dev/null || echo "no")
  if [[ "$HAS_ENTRY" == "yes" ]]; then
    pass "rubric: $CHECK_ID entry present"
  else
    fail "rubric: $CHECK_ID entry MISSING"
  fi
done

# ---------------------------------------------------------------------------
# Test 7: shellcheck on wrap-checkov.sh
# ---------------------------------------------------------------------------
printf '\nTest 7: shellcheck on wrap-checkov.sh\n'

if command -v shellcheck > /dev/null 2>&1; then
  SC_OUTPUT="$(shellcheck -S warning "$WRAP_CHECKOV" 2>&1 || true)"
  if [[ -z "$SC_OUTPUT" ]]; then
    pass "shellcheck clean: wrap-checkov.sh"
  else
    fail "shellcheck issues in wrap-checkov.sh:"
    printf '%s\n' "$SC_OUTPUT" | head -10
  fi
else
  skip "shellcheck not installed -- wrap-checkov.sh shell-safety check skipped"
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
