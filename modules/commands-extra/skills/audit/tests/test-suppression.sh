#!/usr/bin/env bash
# CCGM audit -- test-suppression.sh
# Tests for Epic 3.3: suppress.py (.auditignore.yaml + inline comments)
#
# Test scenarios:
#   (a) Finding suppressed by .auditignore.yaml path+check-id rule:
#       -> has suppression.justification, still present in output.
#   (b) Finding suppressed by inline # audit-ignore: comment:
#       -> suppressed, still present in output.
#   (c) .auditignore entry missing reason -> warned/skipped (finding NOT suppressed).
#   (d) Expired suppression (expires < --today) -> NOT honored (no suppression field) + warning.
#   (e) Suppressed CRITICAL finding is still in the output (report would tag [SUPPRESSED]).
#
# All fixtures are constructed at runtime in mktemp dirs (trailing-XXXXXX).
# Usage: bash modules/commands-extra/skills/audit/tests/test-suppression.sh
# Exit:  0 = all tests passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPPRESS_SCRIPT="$SCRIPT_DIR/../scripts/suppress.py"

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

# Check whether a fingerprint exists as a finding record (no type field) in JSONL string.
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

# Get suppression.justification for a finding with given fingerprint.
# Returns "" if not present, or the justification string.
get_suppression_justification() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, fp = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            sup = obj.get("suppression")
            if sup and isinstance(sup, dict):
                print(sup.get("justification", ""))
            else:
                print("__no_suppression__")
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Check whether a finding has a suppression field at all.
has_suppression() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, fp = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            if "suppression" in obj:
                print("yes")
            else:
                print("no")
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# Get severity of a finding with given fingerprint.
get_severity() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
output, fp = sys.argv[1], sys.argv[2]
for l in output.splitlines():
    if not l.strip():
        continue
    try:
        obj = json.loads(l)
        if isinstance(obj, dict) and "type" not in obj and obj.get("fingerprint") == fp:
            print(obj.get("severity", ""))
            sys.exit(0)
    except Exception:
        pass
print("__not_found__")
PYEOF
}

# ---------------------------------------------------------------------------
# Global temp directory
# ---------------------------------------------------------------------------
TESTRUN_DIR="$(mktemp -d /tmp/ccgm-test-suppression-XXXXXX)"
trap 'rm -rf "$TESTRUN_DIR"' EXIT

# ---------------------------------------------------------------------------
# Helper: write a minimal valid findings JSONL with provenance + given findings
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

# Build a minimal valid finding JSON given check_id, path, line, severity, fingerprint.
make_finding() {
  python3 -c "
import json, sys
check_id, path, line, severity, fingerprint = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
print(json.dumps({
    'check_id': check_id,
    'rule_id': check_id,
    'severity': severity,
    'confidence': 'high',
    'detection': 'tool',
    'source': 'tool',
    'message': 'test finding for ' + check_id,
    'location': {'path': path, 'line': line},
    'fingerprint': fingerprint,
}))
" "$1" "$2" "$3" "$4" "$5"
}

# ---------------------------------------------------------------------------
# Test (a): Finding suppressed by .auditignore.yaml path+check-id rule
#           -> has suppression.justification, still present in output
# ---------------------------------------------------------------------------
printf '\nTest (a): .auditignore.yaml path+check-id rule -> suppression applied, finding retained\n'

TA_DIR="$TESTRUN_DIR/ta"
mkdir -p "$TA_DIR"

FP_A="aaaa1111bbbb2222:1"

# Source file (needed for inline scan path resolution, but no inline comment here)
mkdir -p "$TA_DIR/src"
printf 'function foo() {}\n' > "$TA_DIR/src/app.js"

FINDING_A="$(make_finding "security/no-console" "src/app.js" "5" "medium" "$FP_A")"
write_findings_jsonl "$TA_DIR/findings.jsonl" "$FINDING_A"

# Write .auditignore.yaml
cat > "$TA_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: security/no-console
  paths: [src/app.js]
  reason: console.log acceptable in this utility script
YAML_EOF

set +e
TA_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TA_DIR/findings.jsonl" \
  --auditignore "$TA_DIR/.auditignore.yaml" \
  --repo "$TA_DIR" \
  --today 2026-06-10 2>/dev/null)"
TA_EXIT=$?
set -e

if [[ $TA_EXIT -eq 0 ]]; then
  pass "(a): suppress.py exits 0"
else
  fail "(a): suppress.py exits $TA_EXIT (expected 0)"
fi

# Finding must still be present in output
TA_PRESENT="$(fp_exists_as_finding "$TA_OUT" "$FP_A")"
if [[ "$TA_PRESENT" == "yes" ]]; then
  pass "(a): suppressed finding still present in output"
else
  fail "(a): suppressed finding absent from output (must be retained)"
fi

# Finding must have suppression.justification
TA_JUST="$(get_suppression_justification "$TA_OUT" "$FP_A")"
if [[ "$TA_JUST" == "console.log acceptable in this utility script" ]]; then
  pass "(a): suppression.justification matches .auditignore reason"
else
  fail "(a): suppression.justification='$TA_JUST' (expected the reason string)"
fi

# ---------------------------------------------------------------------------
# Test (b): Finding suppressed by inline # audit-ignore: comment
#           -> suppressed, still present in output
# ---------------------------------------------------------------------------
printf '\nTest (b): inline # audit-ignore: comment -> suppression applied, finding retained\n'

TB_DIR="$TESTRUN_DIR/tb"
mkdir -p "$TB_DIR/src"

FP_B="bbbb2222cccc3333:1"

# Source file with audit-ignore comment on line 3; finding is on line 4 (next line)
cat > "$TB_DIR/src/utils.py" << 'PY_EOF'
import os
import sys
# audit-ignore: code-quality/unused-import reason: kept for re-export
import logging
def main():
    pass
PY_EOF

# Finding on line 4 (the import logging line — next line after the comment on line 3)
FINDING_B="$(make_finding "code-quality/unused-import" "src/utils.py" "4" "low" "$FP_B")"
write_findings_jsonl "$TB_DIR/findings.jsonl" "$FINDING_B"

set +e
TB_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TB_DIR/findings.jsonl" \
  --repo "$TB_DIR" \
  --today 2026-06-10 2>/dev/null)"
TB_EXIT=$?
set -e

if [[ $TB_EXIT -eq 0 ]]; then
  pass "(b): suppress.py exits 0"
else
  fail "(b): suppress.py exits $TB_EXIT (expected 0)"
fi

# Finding must still be in output
TB_PRESENT="$(fp_exists_as_finding "$TB_OUT" "$FP_B")"
if [[ "$TB_PRESENT" == "yes" ]]; then
  pass "(b): inline-suppressed finding still present in output"
else
  fail "(b): inline-suppressed finding absent from output (must be retained)"
fi

# Finding must have suppression field
TB_HAS_SUP="$(has_suppression "$TB_OUT" "$FP_B")"
if [[ "$TB_HAS_SUP" == "yes" ]]; then
  pass "(b): inline comment produced suppression field on finding"
else
  fail "(b): inline comment did not produce suppression field (has_suppression=$TB_HAS_SUP)"
fi

# Justification from the inline comment reason text
TB_JUST="$(get_suppression_justification "$TB_OUT" "$FP_B")"
if [[ "$TB_JUST" == "reason: kept for re-export" ]]; then
  pass "(b): suppression.justification contains inline reason text"
else
  fail "(b): suppression.justification='$TB_JUST' (expected inline reason)"
fi

# ---------------------------------------------------------------------------
# Test (c): .auditignore entry missing reason -> warned/skipped (finding NOT suppressed)
# ---------------------------------------------------------------------------
printf '\nTest (c): .auditignore entry missing reason -> warned, finding NOT suppressed\n'

TC_DIR="$TESTRUN_DIR/tc"
mkdir -p "$TC_DIR/src"
printf 'x = 1\n' > "$TC_DIR/src/main.py"

FP_C="cccc3333dddd4444:1"

FINDING_C="$(make_finding "security/sql-injection" "src/main.py" "1" "high" "$FP_C")"
write_findings_jsonl "$TC_DIR/findings.jsonl" "$FINDING_C"

# Entry missing reason
cat > "$TC_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: security/sql-injection
  paths: [src/main.py]
YAML_EOF

set +e
TC_STDERR="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TC_DIR/findings.jsonl" \
  --auditignore "$TC_DIR/.auditignore.yaml" \
  --repo "$TC_DIR" \
  --today 2026-06-10 2>&1 >/dev/null)"
TC_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TC_DIR/findings.jsonl" \
  --auditignore "$TC_DIR/.auditignore.yaml" \
  --repo "$TC_DIR" \
  --today 2026-06-10 2>/dev/null)"
TC_EXIT=$?
set -e

if [[ $TC_EXIT -eq 0 ]]; then
  pass "(c): suppress.py exits 0 even with missing-reason entry"
else
  fail "(c): suppress.py exits $TC_EXIT (expected 0)"
fi

# A warning must be emitted to stderr
# Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
# producer if grep exits on its first match before the producer finishes
# writing, turning a genuine match into a reported failure (see #943,
# #945). A herestring has no second process to race against.
if grep -qi "warning\|WARNING\|reason\|missing" <<< "$TC_STDERR"; then
  pass "(c): warning emitted to stderr for missing reason"
else
  fail "(c): no warning on stderr for missing reason (got: $TC_STDERR)"
fi

# Finding must NOT have a suppression field (the entry was skipped)
TC_HAS_SUP="$(has_suppression "$TC_OUT" "$FP_C")"
if [[ "$TC_HAS_SUP" == "no" ]]; then
  pass "(c): finding NOT suppressed when entry missing reason"
else
  fail "(c): finding has suppression field (expected no suppression, has_suppression=$TC_HAS_SUP)"
fi

# Finding must still be present
TC_PRESENT="$(fp_exists_as_finding "$TC_OUT" "$FP_C")"
if [[ "$TC_PRESENT" == "yes" ]]; then
  pass "(c): finding still present in output"
else
  fail "(c): finding absent from output"
fi

# ---------------------------------------------------------------------------
# Test (d): Expired suppression (expires < --today) -> NOT honored + warning
# ---------------------------------------------------------------------------
printf '\nTest (d): expired suppression -> NOT honored, warning emitted\n'

TD_DIR="$TESTRUN_DIR/td"
mkdir -p "$TD_DIR/src"
printf 'const x = 1;\n' > "$TD_DIR/src/index.ts"

FP_D="dddd4444eeee5555:1"

FINDING_D="$(make_finding "typescript-react/missing-prop-types" "src/index.ts" "1" "medium" "$FP_D")"
write_findings_jsonl "$TD_DIR/findings.jsonl" "$FINDING_D"

# Entry with an expires date that is in the past relative to --today 2026-06-10
cat > "$TD_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: typescript-react/missing-prop-types
  paths: [src/index.ts]
  reason: suppressed during migration
  expires: 2026-01-01
YAML_EOF

set +e
TD_STDERR="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TD_DIR/findings.jsonl" \
  --auditignore "$TD_DIR/.auditignore.yaml" \
  --repo "$TD_DIR" \
  --today 2026-06-10 2>&1 >/dev/null)"
TD_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TD_DIR/findings.jsonl" \
  --auditignore "$TD_DIR/.auditignore.yaml" \
  --repo "$TD_DIR" \
  --today 2026-06-10 2>/dev/null)"
TD_EXIT=$?
set -e

if [[ $TD_EXIT -eq 0 ]]; then
  pass "(d): suppress.py exits 0 with expired entry"
else
  fail "(d): suppress.py exits $TD_EXIT (expected 0)"
fi

# A warning must be emitted
# Herestring, not a pipe: see the identical rationale above (#943, #945).
if grep -qi "warning\|WARNING\|expir" <<< "$TD_STDERR"; then
  pass "(d): warning emitted for expired suppression"
else
  fail "(d): no warning for expired suppression (got: $TD_STDERR)"
fi

# Finding must NOT have a suppression field (expired suppression not honored)
TD_HAS_SUP="$(has_suppression "$TD_OUT" "$FP_D")"
if [[ "$TD_HAS_SUP" == "no" ]]; then
  pass "(d): expired suppression NOT applied to finding"
else
  fail "(d): expired suppression was applied (expected no suppression, has_suppression=$TD_HAS_SUP)"
fi

# Finding must still be present
TD_PRESENT="$(fp_exists_as_finding "$TD_OUT" "$FP_D")"
if [[ "$TD_PRESENT" == "yes" ]]; then
  pass "(d): finding still present when expired suppression not honored"
else
  fail "(d): finding absent from output"
fi

# ---------------------------------------------------------------------------
# Test (e): Suppressed CRITICAL finding is still in the output
#           (report would tag it [SUPPRESSED] rather than hiding it)
# ---------------------------------------------------------------------------
printf '\nTest (e): suppressed CRITICAL finding stays in output\n'

TE_DIR="$TESTRUN_DIR/te"
mkdir -p "$TE_DIR/src"
printf 'const secret = "hardcoded";\n' > "$TE_DIR/src/config.ts"

FP_E="eeee5555ffff6666:1"

FINDING_E="$(make_finding "secrets/hardcoded-credential" "src/config.ts" "1" "critical" "$FP_E")"
write_findings_jsonl "$TE_DIR/findings.jsonl" "$FINDING_E"

cat > "$TE_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: secrets/hardcoded-credential
  paths: [src/config.ts]
  reason: test credential, not real — see security policy
YAML_EOF

set +e
TE_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TE_DIR/findings.jsonl" \
  --auditignore "$TE_DIR/.auditignore.yaml" \
  --repo "$TE_DIR" \
  --today 2026-06-10 2>/dev/null)"
TE_EXIT=$?
set -e

if [[ $TE_EXIT -eq 0 ]]; then
  pass "(e): suppress.py exits 0 for CRITICAL finding"
else
  fail "(e): suppress.py exits $TE_EXIT (expected 0)"
fi

# CRITICAL finding must still be present in output (not silently dropped)
TE_PRESENT="$(fp_exists_as_finding "$TE_OUT" "$FP_E")"
if [[ "$TE_PRESENT" == "yes" ]]; then
  pass "(e): suppressed CRITICAL finding is still present in output"
else
  fail "(e): CRITICAL finding was omitted — suppressions must never drop findings"
fi

# The finding must have a suppression field
TE_HAS_SUP="$(has_suppression "$TE_OUT" "$FP_E")"
if [[ "$TE_HAS_SUP" == "yes" ]]; then
  pass "(e): CRITICAL finding has suppression field set"
else
  fail "(e): CRITICAL finding missing suppression field (has_suppression=$TE_HAS_SUP)"
fi

# Severity must remain critical (suppression does not downgrade severity)
TE_SEV="$(get_severity "$TE_OUT" "$FP_E")"
if [[ "$TE_SEV" == "critical" ]]; then
  pass "(e): CRITICAL finding retains severity=critical after suppression"
else
  fail "(e): CRITICAL finding severity='$TE_SEV' (expected 'critical')"
fi

# ---------------------------------------------------------------------------
# Test (f): Trailing inline # comment on id line -> suppression still applies (FIX 1)
# ---------------------------------------------------------------------------
printf '\nTest (f): trailing inline comment on id -> suppression still applies\n'

TF_DIR="$TESTRUN_DIR/tf"
mkdir -p "$TF_DIR/src"
printf 'x = 1\n' > "$TF_DIR/src/main.py"

FP_F="ffff6666aaaa7777:1"

FINDING_F="$(make_finding "security/foo" "src/main.py" "1" "high" "$FP_F")"
write_findings_jsonl "$TF_DIR/findings.jsonl" "$FINDING_F"

# Entry with a trailing inline comment on the id line
cat > "$TF_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: security/foo  # legacy check, still suppressed
  reason: known false-positive in generated code
YAML_EOF

set +e
TF_OUT="$(python3 "$SUPPRESS_SCRIPT" \
  --findings "$TF_DIR/findings.jsonl" \
  --auditignore "$TF_DIR/.auditignore.yaml" \
  --repo "$TF_DIR" \
  --today 2026-06-10 2>/dev/null)"
TF_EXIT=$?
set -e

if [[ $TF_EXIT -eq 0 ]]; then
  pass "(f): suppress.py exits 0 with trailing comment on id"
else
  fail "(f): suppress.py exits $TF_EXIT (expected 0)"
fi

# The finding MUST be suppressed — the comment must have been stripped
TF_JUST="$(get_suppression_justification "$TF_OUT" "$FP_F")"
if [[ "$TF_JUST" == "known false-positive in generated code" ]]; then
  pass "(f): trailing comment stripped from id; suppression applied correctly"
else
  fail "(f): suppression.justification='$TF_JUST' (expected the reason — trailing comment was not stripped)"
fi

# ---------------------------------------------------------------------------
# Test (g): flow-map scalar value -> suppress.py exits 1 (FIX 2 fail-closed)
# ---------------------------------------------------------------------------
printf '\nTest (g): flow-map value in reason -> suppress.py exits 1\n'

TG_DIR="$TESTRUN_DIR/tg"
mkdir -p "$TG_DIR/src"
printf 'x = 1\n' > "$TG_DIR/src/main.py"

FP_G="gggg7777hhhh8888:1"
FINDING_G="$(make_finding "security/foo" "src/main.py" "1" "high" "$FP_G")"
write_findings_jsonl "$TG_DIR/findings.jsonl" "$FINDING_G"

# Entry where reason is a flow-map (out-of-subset)
cat > "$TG_DIR/.auditignore.yaml" << 'YAML_EOF'
- id: security/foo
  reason: {x: y}
YAML_EOF

set +e
python3 "$SUPPRESS_SCRIPT" \
  --findings "$TG_DIR/findings.jsonl" \
  --auditignore "$TG_DIR/.auditignore.yaml" \
  --repo "$TG_DIR" \
  --today 2026-06-10 > /dev/null 2>&1
TG_EXIT=$?
set -e

if [[ $TG_EXIT -eq 1 ]]; then
  pass "(g): flow-map scalar value causes exit 1 (fail-closed)"
else
  fail "(g): suppress.py exited $TG_EXIT (expected 1 for flow-map value)"
fi

# ---------------------------------------------------------------------------
# Test (h): tab-indented entry -> suppress.py exits 1 (FIX 2 fail-closed)
# ---------------------------------------------------------------------------
printf '\nTest (h): tab-indented entry -> suppress.py exits 1\n'

TH_DIR="$TESTRUN_DIR/th"
mkdir -p "$TH_DIR/src"
printf 'x = 1\n' > "$TH_DIR/src/main.py"

FP_H="hhhh8888iiii9999:1"
FINDING_H="$(make_finding "security/foo" "src/main.py" "1" "high" "$FP_H")"
write_findings_jsonl "$TH_DIR/findings.jsonl" "$FINDING_H"

# Entry where continuation key uses a TAB for indentation
printf -- '- id: security/foo\n' > "$TH_DIR/.auditignore.yaml"
printf '\treason: tab-indented value\n' >> "$TH_DIR/.auditignore.yaml"

set +e
python3 "$SUPPRESS_SCRIPT" \
  --findings "$TH_DIR/findings.jsonl" \
  --auditignore "$TH_DIR/.auditignore.yaml" \
  --repo "$TH_DIR" \
  --today 2026-06-10 > /dev/null 2>&1
TH_EXIT=$?
set -e

if [[ $TH_EXIT -eq 1 ]]; then
  pass "(h): tab-indented entry causes exit 1 (fail-closed)"
else
  fail "(h): suppress.py exited $TH_EXIT (expected 1 for tab-indented entry)"
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
