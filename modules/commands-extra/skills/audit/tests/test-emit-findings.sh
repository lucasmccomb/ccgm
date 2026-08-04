#!/usr/bin/env bash
# test-emit-findings.sh
# Tests for Epic 1.6: findings JSONL emitter + stable fingerprint
#
# Verifies:
#   - Every output line parses as JSON and validates against finding.schema.json
#   - Fingerprint is stable across an unrelated line insertion elsewhere in the file
#   - Fingerprint is stable across whitespace reformat of the primary line
#   - NO SARIF document is produced (no runs[]/tool.driver)
#   - Source-tool fingerprints are preserved VERBATIM
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-emit-findings.sh
# Exit:  0 = all pass, non-zero = at least one failure

set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EMIT_SCRIPT="$SCRIPT_DIR/../scripts/emit-findings.py"
SCHEMA_FILE="$SCRIPT_DIR/../schemas/finding.schema.json"

# Verify prerequisites
if [ ! -f "$EMIT_SCRIPT" ]; then
  echo "ERROR: emit-findings.py not found at: $EMIT_SCRIPT" >&2
  exit 1
fi
if [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: finding.schema.json not found at: $SCHEMA_FILE" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not found" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

pass() {
  local name="$1"
  echo "  PASS: $name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  local name="$1"
  local detail="${2:-}"
  echo "  FAIL: $name${detail:+ — $detail}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("$name${detail:+: $detail}")
}

# Minimal stdlib schema validator — checks required fields and enum values.
# Returns 0 if the object is valid, 1 with a message otherwise.
validate_against_schema() {
  local json="$1"
  python3 - "$json" <<'PYEOF'
import json, re, sys

obj = json.loads(sys.argv[1])

required = {"check_id","rule_id","severity","confidence","location","message","fingerprint","detection","source"}
missing = required - obj.keys()
if missing:
    print(f"missing fields: {sorted(missing)}", end="")
    sys.exit(1)

for field, allowed in [
    ("severity", {"critical","high","medium","low","info"}),
    ("confidence", {"high","medium","low"}),
    ("detection", {"tool","llm","hybrid"}),
    ("source", {"tool","llm"}),
]:
    if obj[field] not in allowed:
        print(f"{field}='{obj[field]}' not in {sorted(allowed)}", end="")
        sys.exit(1)

loc = obj["location"]
if not isinstance(loc, dict) or "path" not in loc or "line" not in loc:
    print("location missing path/line", end="")
    sys.exit(1)
if not isinstance(loc["line"], int) or loc["line"] < 1:
    print(f"location.line={loc['line']!r} invalid", end="")
    sys.exit(1)

if not re.match(r"^[a-z0-9_-]+/[a-z0-9_.-]+$", obj["check_id"]):
    print(f"check_id '{obj['check_id']}' pattern mismatch", end="")
    sys.exit(1)

fp = obj["fingerprint"]
if not re.match(r"^[A-Za-z0-9_.:+/=-]{8,128}$", fp):
    print(f"fingerprint '{fp}' pattern mismatch", end="")
    sys.exit(1)
PYEOF
}

# ---------------------------------------------------------------------------
# Temp workspace
# ---------------------------------------------------------------------------
TMPDIR_ROOT=$(mktemp -d)
trap 'rm -rf "$TMPDIR_ROOT"' EXIT

# ---------------------------------------------------------------------------
# Minimal valid finding template (no fingerprint — should be computed)
# ---------------------------------------------------------------------------
make_finding() {
  local path="$1"
  local line="$2"
  cat <<JSON
{
  "check_id": "sq/sql-injection",
  "rule_id": "sql-injection-001",
  "severity": "high",
  "confidence": "medium",
  "detection": "tool",
  "source": "tool",
  "message": "Potential SQL injection via unsanitised user input",
  "location": { "path": "$path", "line": $line }
}
JSON
}

# ---------------------------------------------------------------------------
# Test 1: Output lines parse as JSON and validate against schema
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 1: Output lines are valid JSON conforming to finding.schema.json ==="

T1_DIR=$(mktemp -d "$TMPDIR_ROOT/t1-XXXXX")
# Create a small source file so fingerprint can read context
mkdir -p "$T1_DIR/src"
cat > "$T1_DIR/src/db.py" <<'PYEOF'
import sqlite3

def run_query(conn, user_input):
    # line 4 — potential injection
    cursor = conn.execute("SELECT * FROM users WHERE name = " + user_input)
    return cursor.fetchall()
PYEOF

T1_INPUT="$T1_DIR/input.json"
cat > "$T1_INPUT" <<JSON
[
  $(make_finding "src/db.py" 4)
]
JSON

T1_OUT=$(AUDIT_FINDINGS_PATH="$T1_DIR/findings.jsonl" \
  python3 "$EMIT_SCRIPT" "$T1_INPUT" 2>&1 && echo "exit:0" || echo "exit:1")

# Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
# producer if grep exits on its first match before the producer finishes
# writing, turning a genuine match into a reported failure (see #943,
# #945). A herestring has no second process to race against.
if grep -q "exit:1" <<< "$T1_OUT"; then
  fail "t1: emitter exit code" "$T1_OUT"
else
  pass "t1: emitter exited 0"
fi

if [ -f "$T1_DIR/findings.jsonl" ]; then
  pass "t1: findings.jsonl created"
  LINE_COUNT=$(wc -l < "$T1_DIR/findings.jsonl" | tr -d ' ')
  if [ "$LINE_COUNT" -eq 1 ]; then
    pass "t1: one line per finding"
  else
    fail "t1: one line per finding" "got $LINE_COUNT lines"
  fi

  # Parse every line as JSON
  ALL_VALID=1
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if ! echo "$line" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
      fail "t1: line is valid JSON" "not parseable: ${line:0:80}"
      ALL_VALID=0
    fi
  done < "$T1_DIR/findings.jsonl"
  [ "$ALL_VALID" -eq 1 ] && pass "t1: all lines parse as JSON"

  # Schema validation
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    ERR=$(validate_against_schema "$line" 2>&1) || true
    if [ -n "$ERR" ]; then
      fail "t1: schema validation" "$ERR"
    else
      pass "t1: line validates against finding.schema.json"
    fi
  done < "$T1_DIR/findings.jsonl"
else
  fail "t1: findings.jsonl created" "file not found"
fi

# ---------------------------------------------------------------------------
# Test 2: Fingerprint is stable across an unrelated line insertion elsewhere
#
# Strategy: the finding is at line 4. The unrelated insertion goes AFTER line 7
# (well outside the +-2 window of line 4), so the context lines [2..6] are
# identical in both versions and the fingerprint must not change.
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 2: Fingerprint stable across unrelated line insertion ==="

T2_DIR=$(mktemp -d "$TMPDIR_ROOT/t2-XXXXX")
mkdir -p "$T2_DIR/src"

# Version A: 7 lines; finding is at line 4
cat > "$T2_DIR/src/auth.py" <<'PYEOF'
import os
import db

def authenticate(user, pwd):
    query = "SELECT * FROM users WHERE user=" + user
    return db.execute(query)

PYEOF

T2_INPUT_A="$T2_DIR/input_a.json"
cat > "$T2_INPUT_A" <<JSON
[
  $(make_finding "src/auth.py" 5)
]
JSON

AUDIT_FINDINGS_PATH="$T2_DIR/a.jsonl" \
  python3 "$EMIT_SCRIPT" "$T2_INPUT_A" >/dev/null 2>&1
FP_A=$(python3 -c "import json,sys; print(json.loads(open('$T2_DIR/a.jsonl').readline())['fingerprint'])")

# Version B: insert two unrelated lines AFTER line 8 (outside the +-2 window);
# the finding line (5) and its +-2 context are IDENTICAL to version A.
cat > "$T2_DIR/src/auth.py" <<'PYEOF'
import os
import db

def authenticate(user, pwd):
    query = "SELECT * FROM users WHERE user=" + user
    return db.execute(query)

# Unrelated new helper added below — well outside the +-2 window of line 5
def logout(session):
    session.clear()
PYEOF

# Finding still at line 5 — same content, same context window
T2_INPUT_B="$T2_DIR/input_b.json"
cat > "$T2_INPUT_B" <<JSON
[
  $(make_finding "src/auth.py" 5)
]
JSON

AUDIT_FINDINGS_PATH="$T2_DIR/b.jsonl" \
  python3 "$EMIT_SCRIPT" "$T2_INPUT_B" >/dev/null 2>&1
FP_B=$(python3 -c "import json,sys; print(json.loads(open('$T2_DIR/b.jsonl').readline())['fingerprint'])")

if [ "$FP_A" = "$FP_B" ]; then
  pass "t2: fingerprint stable across unrelated line insertion"
else
  fail "t2: fingerprint stable across unrelated line insertion" \
    "A='$FP_A' B='$FP_B' (context at the finding line should be identical)"
fi

# ---------------------------------------------------------------------------
# Test 3: Fingerprint stable across whitespace reformat of the primary line
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 3: Fingerprint stable across whitespace reformat ==="

T3_DIR=$(mktemp -d "$TMPDIR_ROOT/t3-XXXXX")
mkdir -p "$T3_DIR/src"

# Version A: compact spacing
cat > "$T3_DIR/src/query.py" <<'PYEOF'
import db

def get_user(name):
    return db.execute("SELECT * FROM users WHERE name="+name)

def other():
    pass
PYEOF

T3_INPUT_A="$T3_DIR/input_a.json"
cat > "$T3_INPUT_A" <<JSON
[
  $(make_finding "src/query.py" 4)
]
JSON

AUDIT_FINDINGS_PATH="$T3_DIR/a.jsonl" \
  python3 "$EMIT_SCRIPT" "$T3_INPUT_A" >/dev/null 2>&1
FP3_A=$(python3 -c "import json,sys; print(json.loads(open('$T3_DIR/a.jsonl').readline())['fingerprint'])")

# Version B: reformatted with extra spaces / expanded string concat
cat > "$T3_DIR/src/query.py" <<'PYEOF'
import db

def get_user( name ):
    return db.execute( "SELECT * FROM users WHERE name=" + name )

def other():
    pass
PYEOF

T3_INPUT_B="$T3_DIR/input_b.json"
cat > "$T3_INPUT_B" <<JSON
[
  $(make_finding "src/query.py" 4)
]
JSON

AUDIT_FINDINGS_PATH="$T3_DIR/b.jsonl" \
  python3 "$EMIT_SCRIPT" "$T3_INPUT_B" >/dev/null 2>&1
FP3_B=$(python3 -c "import json,sys; print(json.loads(open('$T3_DIR/b.jsonl').readline())['fingerprint'])")

if [ "$FP3_A" = "$FP3_B" ]; then
  pass "t3: fingerprint stable across whitespace reformat"
else
  fail "t3: fingerprint stable across whitespace reformat" \
    "A='$FP3_A' B='$FP3_B'"
fi

# ---------------------------------------------------------------------------
# Test 4: Source-tool fingerprint preserved VERBATIM
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 4: Source-tool fingerprint preserved verbatim ==="

T4_DIR=$(mktemp -d "$TMPDIR_ROOT/t4-XXXXX")
VERBATIM_FP="gitleaks:abc123def456:1"

T4_INPUT="$T4_DIR/input.json"
cat > "$T4_INPUT" <<JSON
[
  {
    "check_id": "sq/hardcoded-secret",
    "rule_id": "secret-001",
    "severity": "critical",
    "confidence": "high",
    "detection": "tool",
    "source": "tool",
    "message": "Hardcoded API key detected",
    "location": { "path": "config.py", "line": 10 },
    "fingerprint": "$VERBATIM_FP"
  }
]
JSON

AUDIT_FINDINGS_PATH="$T4_DIR/findings.jsonl" \
  python3 "$EMIT_SCRIPT" "$T4_INPUT" >/dev/null 2>&1

GOT_FP=$(python3 -c "import json,sys; print(json.loads(open('$T4_DIR/findings.jsonl').readline())['fingerprint'])")

if [ "$GOT_FP" = "$VERBATIM_FP" ]; then
  pass "t4: verbatim source fingerprint preserved"
else
  fail "t4: verbatim source fingerprint preserved" \
    "expected '$VERBATIM_FP', got '$GOT_FP'"
fi

# ---------------------------------------------------------------------------
# Test 5: NO SARIF document produced (gate #30)
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 5: Output is line-delimited JSON only — no SARIF ==="

T5_DIR=$(mktemp -d "$TMPDIR_ROOT/t5-XXXXX")
mkdir -p "$T5_DIR/src"
echo 'x = 1' > "$T5_DIR/src/main.py"

T5_INPUT="$T5_DIR/input.json"
cat > "$T5_INPUT" <<JSON
[
  $(make_finding "src/main.py" 1)
]
JSON

AUDIT_FINDINGS_PATH="$T5_DIR/findings.jsonl" \
  python3 "$EMIT_SCRIPT" "$T5_INPUT" >/dev/null 2>&1

# SARIF indicators: "runs", "tool", "driver", "$schema" with "sarif"
SARIF_FOUND=0
while IFS= read -r line; do
  [ -z "$line" ] && continue

  # No SARIF wrapper — must NOT have runs[] or tool.driver keys at top level
  if echo "$line" | python3 -c "
import json, sys
obj = json.load(sys.stdin)
if 'runs' in obj or ('tool' in obj and 'driver' in obj.get('tool', {})):
    sys.exit(1)
" 2>/dev/null; then
    :
  else
    fail "t5: no SARIF document structure in output" \
      "line contains 'runs' or 'tool.driver'"
    SARIF_FOUND=1
  fi

  # No \$schema key pointing to SARIF
  if echo "$line" | python3 -c "
import json, sys
obj = json.load(sys.stdin)
schema = obj.get('\$schema','')
if 'sarif' in schema.lower():
    sys.exit(1)
" 2>/dev/null; then
    :
  else
    fail "t5: no SARIF schema reference in output" \
      "line contains SARIF \$schema"
    SARIF_FOUND=1
  fi
done < "$T5_DIR/findings.jsonl"

[ "$SARIF_FOUND" -eq 0 ] && pass "t5: output is line-delimited JSON (no SARIF)"

# ---------------------------------------------------------------------------
# Test 6: Multiple findings — correct count and all valid
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 6: Multiple findings — count and schema ==="

T6_DIR=$(mktemp -d "$TMPDIR_ROOT/t6-XXXXX")
mkdir -p "$T6_DIR/src"
cat > "$T6_DIR/src/app.py" <<'PYEOF'
secret = "hardcoded_token_12345"
conn.execute("SELECT * FROM t WHERE id=" + user_id)
eval(user_code)
PYEOF

T6_INPUT="$T6_DIR/input.json"
cat > "$T6_INPUT" <<JSON
[
  {
    "check_id": "sq/hardcoded-secret",
    "rule_id": "secret-001",
    "severity": "critical",
    "confidence": "high",
    "detection": "tool",
    "source": "tool",
    "message": "Hardcoded token",
    "location": { "path": "src/app.py", "line": 1 }
  },
  {
    "check_id": "sq/sql-injection",
    "rule_id": "sql-001",
    "severity": "high",
    "confidence": "medium",
    "detection": "llm",
    "source": "llm",
    "message": "SQL injection risk",
    "location": { "path": "src/app.py", "line": 2 }
  },
  {
    "check_id": "sq/code-injection",
    "rule_id": "eval-001",
    "severity": "critical",
    "confidence": "high",
    "detection": "tool",
    "source": "tool",
    "message": "eval of user input",
    "location": { "path": "src/app.py", "line": 3 }
  }
]
JSON

AUDIT_FINDINGS_PATH="$T6_DIR/findings.jsonl" \
  python3 "$EMIT_SCRIPT" "$T6_INPUT" >/dev/null 2>&1

LINE_COUNT6=$(wc -l < "$T6_DIR/findings.jsonl" | tr -d ' ')
if [ "$LINE_COUNT6" -eq 3 ]; then
  pass "t6: 3 findings produce 3 lines"
else
  fail "t6: 3 findings produce 3 lines" "got $LINE_COUNT6"
fi

IDX=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  IDX=$((IDX + 1))
  ERR=$(validate_against_schema "$line" 2>&1) || true
  if [ -n "$ERR" ]; then
    fail "t6: line $IDX schema valid" "$ERR"
  else
    pass "t6: line $IDX schema valid"
  fi
done < "$T6_DIR/findings.jsonl"

# ---------------------------------------------------------------------------
# Test 7: Missing file — graceful fallback fingerprint still matches schema
# ---------------------------------------------------------------------------
echo ""
echo "=== Test 7: Missing source file — graceful fallback fingerprint ==="

T7_DIR=$(mktemp -d "$TMPDIR_ROOT/t7-XXXXX")
# Do NOT create the referenced file

T7_INPUT="$T7_DIR/input.json"
cat > "$T7_INPUT" <<JSON
[
  {
    "check_id": "sq/missing-file",
    "rule_id": "mf-001",
    "severity": "low",
    "confidence": "low",
    "detection": "tool",
    "source": "tool",
    "message": "Finding with a missing source file",
    "location": { "path": "does/not/exist.py", "line": 42 }
  }
]
JSON

AUDIT_FINDINGS_PATH="$T7_DIR/findings.jsonl" \
  python3 "$EMIT_SCRIPT" "$T7_INPUT" >/dev/null 2>&1

if [ -f "$T7_DIR/findings.jsonl" ]; then
  pass "t7: emitter succeeds with missing file"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    ERR=$(validate_against_schema "$line" 2>&1) || true
    if [ -n "$ERR" ]; then
      fail "t7: fallback fingerprint schema valid" "$ERR"
    else
      pass "t7: fallback fingerprint schema valid"
    fi
  done < "$T7_DIR/findings.jsonl"
else
  fail "t7: emitter succeeds with missing file" "findings.jsonl not created"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=================================="
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=================================="

if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo "Failed tests:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
fi

exit 0
