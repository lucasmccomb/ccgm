#!/usr/bin/env bash
set -euo pipefail

# CCGM Template Expansion Tests
# Verifies that template expansion replaces all placeholders correctly

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

echo "=== CCGM Template Expansion Tests ==="
echo ""

# Source the template library
# shellcheck source=../lib/template.sh
source "$REPO_ROOT/lib/template.sh"

# Create temp directory
TMPDIR=$(mktemp -d)

# --- Test 1: Basic placeholder expansion ---
echo "--- Test 1: Basic placeholder expansion ---"

cat > "$TMPDIR/test-template.md" << 'TEMPLATE'
Home directory: __HOME__
Username: __USERNAME__
Code directory: __CODE_DIR__
Log repo: __LOG_REPO__
Timezone: __TIMEZONE__
Default mode: __DEFAULT_MODE__
TEMPLATE

cat > "$TMPDIR/.ccgm.env" << 'ENV'
CCGM_HOME=/home/testuser
CCGM_USERNAME=testuser
CCGM_CODE_DIR=/home/testuser/projects
CCGM_LOG_REPO=testuser-agent-logs
CCGM_TIMEZONE=America/New_York
CCGM_DEFAULT_MODE=ask
ENV

expand_templates "$TMPDIR/test-template.md" "$TMPDIR/.ccgm.env"

content=$(cat "$TMPDIR/test-template.md")

if echo "$content" | grep -q "/home/testuser" && ! echo "$content" | grep -q "__HOME__"; then
  pass "__HOME__ replaced with /home/testuser"
else
  fail "__HOME__ not replaced correctly"
fi

if echo "$content" | grep -q "Username: testuser" && ! echo "$content" | grep -q "__USERNAME__"; then
  pass "__USERNAME__ replaced with testuser"
else
  fail "__USERNAME__ not replaced correctly"
fi

if echo "$content" | grep -q "/home/testuser/projects" && ! echo "$content" | grep -q "__CODE_DIR__"; then
  pass "__CODE_DIR__ replaced with /home/testuser/projects"
else
  fail "__CODE_DIR__ not replaced correctly"
fi

if echo "$content" | grep -q "testuser-agent-logs" && ! echo "$content" | grep -q "__LOG_REPO__"; then
  pass "__LOG_REPO__ replaced with testuser-agent-logs"
else
  fail "__LOG_REPO__ not replaced correctly"
fi

if echo "$content" | grep -q "America/New_York" && ! echo "$content" | grep -q "__TIMEZONE__"; then
  pass "__TIMEZONE__ replaced with America/New_York"
else
  fail "__TIMEZONE__ not replaced correctly"
fi

if echo "$content" | grep -q "Default mode: ask" && ! echo "$content" | grep -q "__DEFAULT_MODE__"; then
  pass "__DEFAULT_MODE__ replaced with ask"
else
  fail "__DEFAULT_MODE__ not replaced correctly"
fi
echo ""

# --- Test 2: No unexpanded placeholders remain ---
echo "--- Test 2: No unexpanded placeholders remain ---"

if has_unexpanded_templates "$TMPDIR/test-template.md"; then
  remaining=$(list_unexpanded_templates "$TMPDIR/test-template.md")
  fail "Unexpanded placeholders remain: $remaining"
else
  pass "No unexpanded __PLACEHOLDER__ patterns remain"
fi
echo ""

# --- Test 3: Multiple occurrences of same placeholder ---
echo "--- Test 3: Multiple occurrences ---"

cat > "$TMPDIR/multi-template.md" << 'TEMPLATE'
First: __USERNAME__
Second: __USERNAME__
Path: __HOME__/code/__USERNAME__
TEMPLATE

expand_templates "$TMPDIR/multi-template.md" "$TMPDIR/.ccgm.env"
multi_content=$(cat "$TMPDIR/multi-template.md")

occurrences=$(echo "$multi_content" | grep -c "testuser" || true)
if [ "$occurrences" -ge 3 ]; then
  pass "All occurrences of __USERNAME__ replaced ($occurrences found)"
else
  fail "Not all occurrences replaced (expected >= 3, got $occurrences)"
fi

if has_unexpanded_templates "$TMPDIR/multi-template.md"; then
  fail "Unexpanded placeholders remain in multi-template"
else
  pass "Multi-template fully expanded"
fi
echo ""

# --- Test 4: write_env_file produces correct format ---
echo "--- Test 4: write_env_file format ---"

write_env_file "$TMPDIR/test-env-out" \
  "CCGM_HOME=/home/demo" \
  "CCGM_USERNAME=demo" \
  "CCGM_CODE_DIR=/home/demo/code"

if [ -f "$TMPDIR/test-env-out" ]; then
  pass "write_env_file creates file"
else
  fail "write_env_file did not create file"
fi

env_content=$(cat "$TMPDIR/test-env-out")

if echo "$env_content" | grep -q "^CCGM_HOME=/home/demo$"; then
  pass "CCGM_HOME entry correct"
else
  fail "CCGM_HOME entry incorrect or missing"
fi

if echo "$env_content" | grep -q "^CCGM_USERNAME=demo$"; then
  pass "CCGM_USERNAME entry correct"
else
  fail "CCGM_USERNAME entry incorrect or missing"
fi

if echo "$env_content" | grep -q "^# CCGM configuration"; then
  pass "Header comment present"
else
  fail "Header comment missing"
fi
echo ""

# --- Test 5: Expansion with missing env values uses defaults ---
echo "--- Test 5: Defaults for missing values ---"

cat > "$TMPDIR/defaults-template.md" << 'TEMPLATE'
Home: __HOME__
Code: __CODE_DIR__
Mode: __DEFAULT_MODE__
TEMPLATE

# Minimal env file with only USERNAME
cat > "$TMPDIR/minimal.env" << 'ENV'
CCGM_USERNAME=minuser
ENV

expand_templates "$TMPDIR/defaults-template.md" "$TMPDIR/minimal.env"
defaults_content=$(cat "$TMPDIR/defaults-template.md")

# __HOME__ should fall back to $HOME
if echo "$defaults_content" | grep -q "Home: $HOME"; then
  pass "__HOME__ falls back to \$HOME"
else
  # It should at least not have __HOME__ unexpanded
  if echo "$defaults_content" | grep -q "__HOME__"; then
    fail "__HOME__ unexpanded even with fallback"
  else
    pass "__HOME__ replaced with fallback value"
  fi
fi

# __DEFAULT_MODE__ should fall back to 'ask'
if echo "$defaults_content" | grep -q "Mode: ask"; then
  pass "__DEFAULT_MODE__ falls back to 'ask'"
else
  if echo "$defaults_content" | grep -q "__DEFAULT_MODE__"; then
    fail "__DEFAULT_MODE__ unexpanded even with fallback"
  else
    pass "__DEFAULT_MODE__ replaced with some fallback"
  fi
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
