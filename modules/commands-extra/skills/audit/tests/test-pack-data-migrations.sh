#!/usr/bin/env bash
# test-pack-data-migrations.sh
# Tests for the data-migrations audit pack (Epic 2.1).
#
# Tests:
#   1. pack.json validates against pack.schema.json (registry validate_pack)
#   2. checks.md has all required template sections (lint-pack.py)
#   3. severity-rubric.json contains all dm/* check-ids from pack.json
#   4. lint-pack.py passes on the data-migrations pack against the real rubric
#   5. Graceful-degradation: wrap-squawk.sh emits coverage_gap when squawk absent
#   6. Graceful-degradation: wrap-sqlfluff.sh emits coverage_gap when sqlfluff absent
#   7. Unit test: parse-squawk.py emits valid dm/* findings from synthetic JSON
#   8. Unit test: parse-sqlfluff.py emits valid dm/* findings from synthetic JSON
#   9. Unit test: parse-squawk.py sets properties.tool = "squawk"
#  10. Unit test: parse-sqlfluff.py sets properties.tool = "sqlfluff"
#  11. Unit test: parse-squawk.py maps require-concurrent-index-creation -> dm/index-without-concurrently
#  12. Unit test: parse-sqlfluff.py maps SECURITY DEFINER description -> dm/security-definer-function
#  13. Unit test: parse-squawk.py includes fingerprint field matching expected pattern
#  14. Fixture repo: graceful-degradation path emits coverage_gap notes (squawk/sqlfluff absent)
#
# Exit 0 = all tests passed; exit 1 = one or more failures.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPINE_DIR="${AUDIT_DIR}/scripts/spine"
PACK_DIR="${AUDIT_DIR}/packs/data-migrations"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"
PARSE_SQUAWK="${SPINE_DIR}/parse-squawk.py"
PARSE_SQLFLUFF="${SPINE_DIR}/parse-sqlfluff.py"
WRAP_SQUAWK="${SPINE_DIR}/wrap-squawk.sh"
WRAP_SQLFLUFF="${SPINE_DIR}/wrap-sqlfluff.sh"

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
# Temp dir for the whole test run
# ---------------------------------------------------------------------------
TESTRUN_TMPDIR="$(mktemp -d /tmp/ccgm-test-dm-XXXXXX)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

# ---------------------------------------------------------------------------
# Test 1: pack.json validates against pack.schema.json via lint-pack.py
# ---------------------------------------------------------------------------
printf '\nTest 1: pack.json validates (lint-pack.py --rubric /dev/null)\n'

if [[ ! -f "$PACK_DIR/pack.json" ]]; then
  fail "pack.json does not exist at $PACK_DIR/pack.json"
else
  # Use lint-pack.py with a nonexistent rubric to test schema validation only
  OUT="$(python3 "$LINTER" --packs-dir "$(dirname "$PACK_DIR")" --rubric "$TESTRUN_TMPDIR/no-rubric.json" 2>&1 || true)"
  if echo "$OUT" | grep -q "^PASS: data-migrations"; then
    pass "pack.json passes schema validation (no rubric)"
  else
    fail "pack.json schema validation failed: $OUT"
  fi
fi

# ---------------------------------------------------------------------------
# Test 2: checks.md has all required template sections
# ---------------------------------------------------------------------------
printf '\nTest 2: checks.md has all required sections\n'

if [[ ! -f "$PACK_DIR/checks.md" ]]; then
  fail "checks.md does not exist at $PACK_DIR/checks.md"
else
  for section_pattern in \
    "^## Scope" \
    "^## applies_when Rationale" \
    "^## Checks" \
    "^## Quality Checklist"; do
    if grep -qiE "$section_pattern" "$PACK_DIR/checks.md"; then
      pass "checks.md contains section matching '$section_pattern'"
    else
      fail "checks.md missing section matching '$section_pattern'"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Test 3: severity-rubric.json contains all dm/* check-ids from pack.json
# ---------------------------------------------------------------------------
printf '\nTest 3: rubric contains all dm/* check-ids\n'

if [[ ! -f "$RUBRIC" ]]; then
  fail "severity-rubric.json not found at $RUBRIC"
else
  # Extract check ids from pack.json using python3 stdlib
  PACK_CHECK_IDS="$(python3 - "$PACK_DIR/pack.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    pack = json.load(f)
for c in pack.get("checks", []):
    print(c["id"])
PYEOF
)"
  while IFS= read -r cid; do
    [[ -z "$cid" ]] && continue
    if python3 - "$RUBRIC" "$cid" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    rubric = json.load(f)
checks = rubric.get("checks", {})
cid = sys.argv[2]
sys.exit(0 if cid in checks else 1)
PYEOF
    then
      pass "rubric contains check-id '$cid'"
    else
      fail "rubric MISSING check-id '$cid'"
    fi
  done <<< "$PACK_CHECK_IDS"
fi

# ---------------------------------------------------------------------------
# Test 4: lint-pack.py passes on data-migrations pack with real rubric
# ---------------------------------------------------------------------------
printf '\nTest 4: lint-pack.py PASS on data-migrations pack (real rubric)\n'

OUT="$(python3 "$LINTER" --packs-dir "$(dirname "$PACK_DIR")" --rubric "$RUBRIC" 2>&1 || true)"
if echo "$OUT" | grep -q "^PASS: data-migrations"; then
  pass "lint-pack.py reports PASS for data-migrations with real rubric"
else
  fail "lint-pack.py did NOT report PASS for data-migrations: $OUT"
fi

# ---------------------------------------------------------------------------
# Test 5: wrap-squawk.sh graceful-degradation when squawk absent
# ---------------------------------------------------------------------------
printf '\nTest 5: wrap-squawk.sh emits coverage_gap when squawk absent\n'

# Create a minimal migration fixture
FIXTURE_REPO="$TESTRUN_TMPDIR/fixture-repo"
mkdir -p "$FIXTURE_REPO/supabase/migrations"

# Seed fixture with all 4 defect types
cat > "$FIXTURE_REPO/supabase/migrations/0001_defects.sql" <<'SQLEOF'
-- dm/unquoted-reserved-keyword: "order" column without quotes
CREATE TABLE items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order TEXT,
    position INTEGER
);

-- dm/index-without-concurrently: missing CONCURRENTLY
CREATE INDEX idx_items_order ON items(order);

-- dm/missing-rls: table created without ENABLE ROW LEVEL SECURITY
CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid,
    content text
);

-- dm/security-definer-function: SECURITY DEFINER present
CREATE OR REPLACE FUNCTION admin_all_users()
RETURNS void
LANGUAGE sql
SECURITY DEFINER
AS $$ SELECT 1; $$;
SQLEOF

# Build a deterministic scratch PATH that excludes squawk and sqlfluff.
# Strategy: create a tmpdir with symlinks to only the required binaries.
# For bash and python3, use the currently-active interpreter (may be homebrew
# on macOS) so that bash 4+ associative arrays and the real python3 are
# available.  All other tools come from /usr/bin and /bin only so that
# homebrew-installed audit tools (squawk, sqlfluff, etc.) cannot leak in.
SCRATCH_BINDIR="$TESTRUN_TMPDIR/scratch-bin"
mkdir -p "$SCRATCH_BINDIR"
# bash and python3: use command -v (real version, may be homebrew on macOS)
for _bin in bash python3; do
  _src="$(command -v "$_bin" 2>/dev/null || true)"
  [[ -n "$_src" ]] && ln -sf "$_src" "$SCRATCH_BINDIR/$_bin" 2>/dev/null || true
done
# All other tools: system paths only to exclude homebrew audit tools
for _bin in find dirname date mktemp rm cp printf head grep cat; do
  for _dir in /usr/bin /bin; do
    if [[ -x "$_dir/$_bin" ]]; then
      ln -sf "$_dir/$_bin" "$SCRATCH_BINDIR/$_bin" 2>/dev/null || true
      break
    fi
  done
done
RESTRICTED_PATH="$SCRATCH_BINDIR"

SQUAWK_OUT="$TESTRUN_TMPDIR/squawk-graceful.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_SQUAWK" "$FIXTURE_REPO" > "$SQUAWK_OUT" 2>/dev/null
SQUAWK_EXIT=$?
set -e

if [[ $SQUAWK_EXIT -eq 0 ]]; then
  pass "wrap-squawk.sh exits 0 when squawk absent"
else
  fail "wrap-squawk.sh exits $SQUAWK_EXIT (expected 0)"
fi

# Should have a skipped note or coverage_gap
if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$SQUAWK_OUT" 2>/dev/null; then
  pass "wrap-squawk.sh emits skipped/coverage_gap note when squawk absent"
else
  fail "wrap-squawk.sh produced no skip/gap notes when squawk absent"
fi

# All output should be valid JSON
INVALID_JSON=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID_JSON=$((INVALID_JSON + 1))
  fi
done < "$SQUAWK_OUT"
if [[ $INVALID_JSON -eq 0 ]]; then
  pass "wrap-squawk.sh output is valid JSONL when squawk absent"
else
  fail "wrap-squawk.sh output has $INVALID_JSON invalid JSON lines"
fi

# ---------------------------------------------------------------------------
# Test 6: wrap-sqlfluff.sh graceful-degradation when sqlfluff absent
# ---------------------------------------------------------------------------
printf '\nTest 6: wrap-sqlfluff.sh emits coverage_gap when sqlfluff absent\n'

SQLFLUFF_OUT="$TESTRUN_TMPDIR/sqlfluff-graceful.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_SQLFLUFF" "$FIXTURE_REPO" > "$SQLFLUFF_OUT" 2>/dev/null
SQLFLUFF_EXIT=$?
set -e

if [[ $SQLFLUFF_EXIT -eq 0 ]]; then
  pass "wrap-sqlfluff.sh exits 0 when sqlfluff absent"
else
  fail "wrap-sqlfluff.sh exits $SQLFLUFF_EXIT (expected 0)"
fi

if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$SQLFLUFF_OUT" 2>/dev/null; then
  pass "wrap-sqlfluff.sh emits skipped/coverage_gap note when sqlfluff absent"
else
  fail "wrap-sqlfluff.sh produced no skip/gap notes when sqlfluff absent"
fi

# ---------------------------------------------------------------------------
# Synthetic JSON fixtures for parse-squawk.py unit tests
# ---------------------------------------------------------------------------
printf '\nTest 7-11: parse-squawk.py unit tests against synthetic JSON\n'

SQUAWK_SYNTHETIC="$TESTRUN_TMPDIR/squawk-synthetic.json"
cat > "$SQUAWK_SYNTHETIC" <<'JSON'
[
  {
    "file": "/repo/supabase/migrations/0001_defects.sql",
    "violations": [
      {
        "rule": "require-concurrent-index-creation",
        "level": "Warning",
        "messages": [
          {"Note": "Use CONCURRENTLY when creating indexes to avoid locking the table during index creation."}
        ],
        "position": {
          "start": {"line": 8, "col": 1},
          "end":   {"line": 8, "col": 50}
        }
      },
      {
        "rule": "ban-drop-database",
        "level": "Error",
        "messages": [
          {"Note": "Dropping a database is a destructive and irreversible operation."}
        ],
        "position": {
          "start": {"line": 15, "col": 1},
          "end":   {"line": 15, "col": 20}
        }
      }
    ]
  }
]
JSON

SQUAWK_PARSE_OUT="$TESTRUN_TMPDIR/squawk-parsed.jsonl"
python3 "$PARSE_SQUAWK" "$SQUAWK_SYNTHETIC" "/repo" > "$SQUAWK_PARSE_OUT"

# Count findings
FINDING_COUNT="$(grep -c '"check_id"' "$SQUAWK_PARSE_OUT" 2>/dev/null || printf '0')"
if [[ "$FINDING_COUNT" -ge 2 ]]; then
  pass "parse-squawk.py emits $FINDING_COUNT finding(s) from synthetic JSON"
else
  fail "parse-squawk.py emitted $FINDING_COUNT finding(s) (expected >= 2)"
fi

# Test 8: all output is valid JSON
INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID=$((INVALID + 1))
  fi
done < "$SQUAWK_PARSE_OUT"
if [[ $INVALID -eq 0 ]]; then
  pass "parse-squawk.py output is valid JSONL"
else
  fail "parse-squawk.py output has $INVALID invalid JSON lines"
fi

# Test 9: properties.tool = "squawk"
if grep -q '"tool":"squawk"' "$SQUAWK_PARSE_OUT"; then
  pass "parse-squawk.py sets properties.tool = squawk"
else
  fail "parse-squawk.py missing properties.tool = squawk"
fi

# Test 11: require-concurrent-index-creation -> dm/index-without-concurrently
if grep -q '"check_id":"dm/index-without-concurrently"' "$SQUAWK_PARSE_OUT"; then
  pass "parse-squawk.py maps require-concurrent-index-creation -> dm/index-without-concurrently"
else
  fail "parse-squawk.py did NOT map require-concurrent-index-creation -> dm/index-without-concurrently"
fi

# Test 13: fingerprint field present and non-empty
if python3 - "$SQUAWK_PARSE_OUT" <<'PYEOF'
import json, sys, re
fp_pattern = re.compile(r"[A-Za-z0-9_.:+/=\-]{8,128}")
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        fp = obj.get("fingerprint", "")
        if not fp_pattern.fullmatch(fp):
            print(f"Bad fingerprint: {fp!r}", file=sys.stderr)
            sys.exit(1)
sys.exit(0)
PYEOF
then
  pass "parse-squawk.py fingerprint field is present and valid"
else
  fail "parse-squawk.py fingerprint field is missing or invalid"
fi

# Test: parse-squawk.py empty-messages -> "squawk rule <rule>" (no doubled tail)
SQUAWK_EMPTY_MSG="$TESTRUN_TMPDIR/squawk-empty-msg.json"
cat > "$SQUAWK_EMPTY_MSG" <<'JSON'
[
  {
    "file": "/repo/supabase/migrations/0003_test.sql",
    "violations": [
      {
        "rule": "prefer-robust-stmts",
        "level": "Warning",
        "messages": [],
        "position": {
          "start": {"line": 3, "col": 1},
          "end":   {"line": 3, "col": 10}
        }
      }
    ]
  }
]
JSON

SQUAWK_EMPTY_OUT="$TESTRUN_TMPDIR/squawk-empty-parsed.jsonl"
python3 "$PARSE_SQUAWK" "$SQUAWK_EMPTY_MSG" "/repo" > "$SQUAWK_EMPTY_OUT"

if python3 - "$SQUAWK_EMPTY_OUT" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        msg = obj.get("message", "")
        # Must be exactly "squawk rule <rule>" -- no "squawk violation" tail
        if msg != "squawk rule prefer-robust-stmts":
            print("Bad message: {!r}".format(msg), file=sys.stderr)
            sys.exit(1)
sys.exit(0)
PYEOF
then
  pass "parse-squawk.py empty-messages yields 'squawk rule <rule>' (no doubled tail)"
else
  fail "parse-squawk.py empty-messages: wrong message (expected 'squawk rule prefer-robust-stmts')"
fi

# ---------------------------------------------------------------------------
# Synthetic JSON fixtures for parse-sqlfluff.py unit tests
# ---------------------------------------------------------------------------
printf '\nTest 8, 10, 12: parse-sqlfluff.py unit tests against synthetic JSON\n'

SQLFLUFF_SYNTHETIC="$TESTRUN_TMPDIR/sqlfluff-synthetic.json"
cat > "$SQLFLUFF_SYNTHETIC" <<'JSON'
[
  {
    "filepath": "/repo/supabase/migrations/0002_rpc.sql",
    "violations": [
      {
        "start_line_no": 5,
        "start_line_pos": 1,
        "end_line_no": 5,
        "end_line_pos": 20,
        "description": "Found SECURITY DEFINER in function definition. Review privilege escalation risk.",
        "name": "ST07",
        "warning": false,
        "fixable": false
      },
      {
        "start_line_no": 20,
        "start_line_pos": 1,
        "end_line_no": 20,
        "end_line_pos": 30,
        "description": "Expected newline at end of file.",
        "name": "LT12",
        "warning": true,
        "fixable": true
      }
    ]
  }
]
JSON

SQLFLUFF_PARSE_OUT="$TESTRUN_TMPDIR/sqlfluff-parsed.jsonl"
python3 "$PARSE_SQLFLUFF" "$SQLFLUFF_SYNTHETIC" "/repo" > "$SQLFLUFF_PARSE_OUT"

# Test 8: output is valid JSONL
INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID=$((INVALID + 1))
  fi
done < "$SQLFLUFF_PARSE_OUT"
if [[ $INVALID -eq 0 ]]; then
  pass "parse-sqlfluff.py output is valid JSONL"
else
  fail "parse-sqlfluff.py output has $INVALID invalid JSON lines"
fi

# Test 10: properties.tool = "sqlfluff"
if grep -q '"tool":"sqlfluff"' "$SQLFLUFF_PARSE_OUT"; then
  pass "parse-sqlfluff.py sets properties.tool = sqlfluff"
else
  fail "parse-sqlfluff.py missing properties.tool = sqlfluff"
fi

# Test 12: SECURITY DEFINER description -> dm/security-definer-function
if grep -q '"check_id":"dm/security-definer-function"' "$SQLFLUFF_PARSE_OUT"; then
  pass "parse-sqlfluff.py maps SECURITY DEFINER description -> dm/security-definer-function"
else
  fail "parse-sqlfluff.py did NOT map SECURITY DEFINER description -> dm/security-definer-function"
fi

# ---------------------------------------------------------------------------
# Test 14: Fixture repo graceful-degradation path (squawk/sqlfluff absent)
#          emits coverage_gap notes for migration directory
# ---------------------------------------------------------------------------
printf '\nTest 14: Fixture repo graceful-degradation (tools absent)\n'

if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  pass "Test 14: spine fixture run skipped -- bash < 4 (spine requires bash 4+; ubuntu CI will run this)"
else
  SPINE_OUT="$TESTRUN_TMPDIR/spine-dm-graceful.jsonl"
  set +e
  PATH="$RESTRICTED_PATH" bash "${SPINE_DIR}/run.sh" \
    --repo "$FIXTURE_REPO" \
    --tools "squawk,sqlfluff" \
    --output "$SPINE_OUT" \
    2>/dev/null
  SPINE_EXIT=$?
  set -e

  if [[ $SPINE_EXIT -eq 0 ]]; then
    pass "spine exits 0 for squawk,sqlfluff on fixture repo (tools absent)"
  else
    fail "spine exits $SPINE_EXIT (expected 0)"
  fi

  SKIP_OR_GAP="$(grep -c '"type":"skipped"\|"type":"coverage_gap"' "$SPINE_OUT" 2>/dev/null || printf '0')"
  if [[ "$SKIP_OR_GAP" -gt 0 ]]; then
    pass "spine emits $SKIP_OR_GAP skip/gap note(s) for absent tools on fixture repo"
  else
    fail "spine emits no skip/gap notes for absent tools on fixture repo"
  fi
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
