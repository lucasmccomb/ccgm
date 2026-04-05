#!/usr/bin/env bash
set -euo pipefail

# CCGM Settings Merge Tests
# Verifies that merge_settings handles JSON deep merging correctly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()
TMPDIR=""

# --- Helpers ---
pass() {
  PASS=$((PASS + 1))
  echo "  PASS: $1"
}

fail() {
  FAIL=$((FAIL + 1))
  ERRORS+=("$1")
  echo "  FAIL: $1"
}

cleanup() {
  if [ -n "$TMPDIR" ] && [ -d "$TMPDIR" ]; then
    rm -rf "$TMPDIR"
  fi
}
trap cleanup EXIT

# --- Check dependencies ---
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for merge tests"
  echo "  Install: brew install jq (macOS) or apt install jq (Linux)"
  exit 1
fi

echo "=== CCGM Settings Merge Tests ==="
echo ""

# Source the merge library
# shellcheck source=../lib/merge.sh
source "$REPO_ROOT/lib/merge.sh"

# Create temp directory
TMPDIR=$(mktemp -d)

# --- Test 1: Merging two objects with distinct keys ---
echo "--- Test 1: Distinct keys merge ---"

cat > "$TMPDIR/target.json" << 'JSON'
{
  "env": {
    "FOO": "bar"
  }
}
JSON

cat > "$TMPDIR/partial.json" << 'JSON'
{
  "projects": {
    "myProject": true
  }
}
JSON

merge_settings "$TMPDIR/target.json" "$TMPDIR/partial.json"
result=$(cat "$TMPDIR/target.json")

if echo "$result" | jq -e '.env.FOO == "bar"' > /dev/null 2>&1; then
  pass "Original key env.FOO preserved"
else
  fail "Original key env.FOO lost after merge"
fi

if echo "$result" | jq -e '.projects.myProject == true' > /dev/null 2>&1; then
  pass "New key projects.myProject added"
else
  fail "New key projects.myProject not merged"
fi
echo ""

# --- Test 2: Allow/deny array deduplication ---
echo "--- Test 2: Allow/deny array deduplication ---"

cat > "$TMPDIR/target2.json" << 'JSON'
{
  "permissions": {
    "allow": ["Bash(git *)", "Read"],
    "deny": ["Bash(rm -rf *)"]
  }
}
JSON

cat > "$TMPDIR/partial2.json" << 'JSON'
{
  "permissions": {
    "allow": ["Read", "Write", "Glob"],
    "deny": ["Bash(rm -rf *)", "Bash(shutdown *)"]
  }
}
JSON

merge_settings "$TMPDIR/target2.json" "$TMPDIR/partial2.json"
result2=$(cat "$TMPDIR/target2.json")

allow_count=$(echo "$result2" | jq '.permissions.allow | length')
# Should be 4: Bash(git *), Read, Write, Glob (Read deduplicated)
if [ "$allow_count" -eq 4 ]; then
  pass "Allow array deduplicated correctly ($allow_count entries)"
else
  fail "Allow array has $allow_count entries, expected 4"
fi

deny_count=$(echo "$result2" | jq '.permissions.deny | length')
# Should be 2: Bash(rm -rf *), Bash(shutdown *) (rm -rf deduplicated)
if [ "$deny_count" -eq 2 ]; then
  pass "Deny array deduplicated correctly ($deny_count entries)"
else
  fail "Deny array has $deny_count entries, expected 2"
fi

# Verify specific entries exist
if echo "$result2" | jq -e '.permissions.allow | index("Glob") != null' > /dev/null 2>&1; then
  pass "New allow entry 'Glob' present"
else
  fail "New allow entry 'Glob' missing"
fi
echo ""

# --- Test 3: Hooks arrays are concatenated ---
echo "--- Test 3: Hooks array concatenation ---"

cat > "$TMPDIR/target3.json" << 'JSON'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": ["python3 hook-a.py"]
      }
    ]
  }
}
JSON

cat > "$TMPDIR/partial3.json" << 'JSON'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": ["python3 hook-b.py"]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": ["python3 hook-c.py"]
      }
    ]
  }
}
JSON

merge_settings "$TMPDIR/target3.json" "$TMPDIR/partial3.json"
result3=$(cat "$TMPDIR/target3.json")

pre_count=$(echo "$result3" | jq '.hooks.PreToolUse | length')
if [ "$pre_count" -eq 2 ]; then
  pass "PreToolUse hooks concatenated ($pre_count entries)"
else
  fail "PreToolUse hooks has $pre_count entries, expected 2"
fi

if echo "$result3" | jq -e '.hooks.PostToolUse | length == 1' > /dev/null 2>&1; then
  pass "PostToolUse hooks added from partial"
else
  fail "PostToolUse hooks missing or wrong length"
fi
echo ""

# --- Test 4: Missing target file (should copy) ---
echo "--- Test 4: Missing target file ---"

cat > "$TMPDIR/partial4.json" << 'JSON'
{
  "permissions": {
    "allow": ["Read"]
  }
}
JSON

missing_target="$TMPDIR/nonexistent-target.json"
# Ensure it does not exist
rm -f "$missing_target"

merge_settings "$missing_target" "$TMPDIR/partial4.json"

if [ -f "$missing_target" ]; then
  pass "Target file created from partial"
else
  fail "Target file not created when missing"
fi

if jq -e '.permissions.allow[0] == "Read"' "$missing_target" > /dev/null 2>&1; then
  pass "Copied content matches partial"
else
  fail "Copied content does not match partial"
fi
echo ""

# --- Test 5: Invalid JSON input handling ---
echo "--- Test 5: Invalid JSON input ---"

cat > "$TMPDIR/valid-target.json" << 'JSON'
{"key": "value"}
JSON

echo "this is not json {{{" > "$TMPDIR/invalid-partial.json"

set +e
merge_output=$(merge_settings "$TMPDIR/valid-target.json" "$TMPDIR/invalid-partial.json" 2>&1)
merge_exit=$?
set -e

if [ $merge_exit -ne 0 ]; then
  pass "Merge with invalid partial returns non-zero exit"
else
  fail "Merge with invalid partial should return non-zero exit"
fi

# Verify original target is not corrupted
if jq -e '.key == "value"' "$TMPDIR/valid-target.json" > /dev/null 2>&1; then
  pass "Original target preserved after invalid merge attempt"
else
  fail "Original target corrupted after invalid merge attempt"
fi

# Test invalid target JSON
echo "broken json" > "$TMPDIR/invalid-target.json"

cat > "$TMPDIR/valid-partial.json" << 'JSON'
{"newkey": "newvalue"}
JSON

set +e
merge_output2=$(merge_settings "$TMPDIR/invalid-target.json" "$TMPDIR/valid-partial.json" 2>&1)
merge_exit2=$?
set -e

if [ $merge_exit2 -ne 0 ]; then
  pass "Merge with invalid target returns non-zero exit"
else
  fail "Merge with invalid target should return non-zero exit"
fi
echo ""

# --- Test 6: Missing partial file ---
echo "--- Test 6: Missing partial file ---"

cat > "$TMPDIR/target6.json" << 'JSON'
{"existing": true}
JSON

set +e
merge_output3=$(merge_settings "$TMPDIR/target6.json" "$TMPDIR/no-such-file.json" 2>&1)
merge_exit3=$?
set -e

if [ $merge_exit3 -ne 0 ]; then
  pass "Merge with missing partial returns non-zero exit"
else
  fail "Merge with missing partial should return non-zero exit"
fi
echo ""

# --- Summary ---
echo "==================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==================================="

if [ $FAIL -gt 0 ]; then
  echo ""
  echo "Failures:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  exit 1
fi

exit 0
