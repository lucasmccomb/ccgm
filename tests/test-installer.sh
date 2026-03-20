#!/usr/bin/env bash
set -euo pipefail

# CCGM Installer Integration Tests
# Runs the installer in an isolated temp directory with non-interactive mode

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
  echo "ERROR: jq is required for installer tests"
  exit 1
fi

echo "=== CCGM Installer Integration Tests ==="
echo ""

# Create temp directory as fake HOME
TMPDIR=$(mktemp -d)
FAKE_HOME="$TMPDIR/home"
mkdir -p "$FAKE_HOME/.claude"

# ============================================================
# Test 1: Minimal preset (global scope)
# ============================================================
echo "--- Test 1: Minimal preset, global scope ---"

TEST1_HOME="$TMPDIR/test1"
mkdir -p "$TEST1_HOME/.claude"

# Run installer non-interactively
export CCGM_NON_INTERACTIVE=1
export CCGM_USERNAME=testuser
export CCGM_CODE_DIR="$TEST1_HOME/code"
export CCGM_TIMEZONE=UTC
export CCGM_DEFAULT_MODE=ask
export HOME="$TEST1_HOME"

# Run installer with minimal preset
set +e
"$REPO_ROOT/start.sh" --preset minimal --scope global </dev/null 2>&1
installer_exit=$?
set -e

if [ $installer_exit -eq 0 ]; then
  pass "Installer exited successfully (minimal preset)"
else
  fail "Installer exited with code $installer_exit (minimal preset)"
fi

# Check .ccgm.env was created
if [ -f "$TEST1_HOME/.claude/.ccgm.env" ]; then
  pass ".ccgm.env exists"
else
  fail ".ccgm.env missing"
fi

# Check .ccgm-manifest.json was created
if [ -f "$TEST1_HOME/.claude/.ccgm-manifest.json" ]; then
  pass ".ccgm-manifest.json exists"

  # Verify manifest contents
  manifest_preset=$(jq -r '.preset' "$TEST1_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
  if [ "$manifest_preset" = "minimal" ]; then
    pass "Manifest shows preset=minimal"
  else
    fail "Manifest preset is '$manifest_preset', expected 'minimal'"
  fi

  manifest_scope=$(jq -r '.scope' "$TEST1_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
  if [ "$manifest_scope" = "global" ]; then
    pass "Manifest shows scope=global"
  else
    fail "Manifest scope is '$manifest_scope', expected 'global'"
  fi

  # Minimal preset = autonomy + git-workflow
  mod_count=$(jq -r '.modules | length' "$TEST1_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
  if [ "$mod_count" -ge 2 ]; then
    pass "Manifest has $mod_count modules (>= 2 expected)"
  else
    fail "Manifest has $mod_count modules (expected >= 2)"
  fi
else
  fail ".ccgm-manifest.json missing"
fi

# Check that autonomy rule file was created
if [ -f "$TEST1_HOME/.claude/rules/autonomy.md" ]; then
  pass "rules/autonomy.md created"
else
  fail "rules/autonomy.md missing"
fi

# Check that git-workflow rule file was created
if [ -f "$TEST1_HOME/.claude/rules/git-workflow.md" ]; then
  pass "rules/git-workflow.md created"
else
  fail "rules/git-workflow.md missing"
fi
echo ""

# ============================================================
# Test 2: Standard preset (global scope)
# ============================================================
echo "--- Test 2: Standard preset, global scope ---"

TEST2_HOME="$TMPDIR/test2"
mkdir -p "$TEST2_HOME/.claude"
export HOME="$TEST2_HOME"
export CCGM_CODE_DIR="$TEST2_HOME/code"

set +e
"$REPO_ROOT/start.sh" --preset standard --scope global </dev/null 2>&1
installer_exit=$?
set -e

if [ $installer_exit -eq 0 ]; then
  pass "Installer exited successfully (standard preset)"
else
  fail "Installer exited with code $installer_exit (standard preset)"
fi

# Standard = autonomy, git-workflow, hooks, settings, commands-core
if [ -f "$TEST2_HOME/.claude/.ccgm-manifest.json" ]; then
  pass ".ccgm-manifest.json exists (standard)"

  mod_count=$(jq -r '.modules | length' "$TEST2_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
  if [ "$mod_count" -ge 5 ]; then
    pass "Standard preset has $mod_count modules (>= 5 expected)"
  else
    fail "Standard preset has $mod_count modules (expected >= 5)"
  fi
else
  fail ".ccgm-manifest.json missing (standard)"
fi

# Check hooks were installed
if [ -f "$TEST2_HOME/.claude/hooks/enforce-git-workflow.py" ]; then
  pass "hooks/enforce-git-workflow.py created"
else
  fail "hooks/enforce-git-workflow.py missing"
fi

# Check commands were installed
if [ -f "$TEST2_HOME/.claude/commands/commit.md" ]; then
  pass "commands/commit.md created"
else
  fail "commands/commit.md missing"
fi

# Check settings.json exists (merged from settings module)
if [ -f "$TEST2_HOME/.claude/settings.json" ]; then
  pass "settings.json created"

  if jq empty "$TEST2_HOME/.claude/settings.json" 2>/dev/null; then
    pass "settings.json is valid JSON"
  else
    fail "settings.json is invalid JSON"
  fi
else
  fail "settings.json missing"
fi
echo ""

# ============================================================
# Test 3: Full preset (global scope)
# ============================================================
echo "--- Test 3: Full preset, global scope ---"

TEST3_HOME="$TMPDIR/test3"
mkdir -p "$TEST3_HOME/.claude"
export HOME="$TEST3_HOME"
export CCGM_CODE_DIR="$TEST3_HOME/code"

set +e
"$REPO_ROOT/start.sh" --preset full --scope global </dev/null 2>&1
installer_exit=$?
set -e

if [ $installer_exit -eq 0 ]; then
  pass "Installer exited successfully (full preset)"
else
  fail "Installer exited with code $installer_exit (full preset)"
fi

if [ -f "$TEST3_HOME/.claude/.ccgm-manifest.json" ]; then
  pass ".ccgm-manifest.json exists (full)"

  mod_count=$(jq -r '.modules | length' "$TEST3_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
  if [ "$mod_count" -ge 10 ]; then
    pass "Full preset has $mod_count modules (>= 10 expected)"
  else
    fail "Full preset has $mod_count modules (expected >= 10)"
  fi
else
  fail ".ccgm-manifest.json missing (full)"
fi

# Check that many different file types were created
expected_files=(
  "rules/autonomy.md"
  "rules/git-workflow.md"
  "rules/code-quality.md"
  "rules/common-mistakes.md"
  "rules/browser-automation.md"
  "rules/supabase.md"
  "rules/cloudflare.md"
  "commands/commit.md"
  "commands/xplan.md"
  "log-system.md"
  "multi-agent-system.md"
  "github-repo-protocols.md"
)

for ef in "${expected_files[@]}"; do
  if [ -f "$TEST3_HOME/.claude/$ef" ]; then
    pass "$ef created (full)"
  else
    fail "$ef missing (full)"
  fi
done
echo ""

# ============================================================
# Test 4: .ccgm.env has expected values
# ============================================================
echo "--- Test 4: .ccgm.env values ---"

env_file="$TEST3_HOME/.claude/.ccgm.env"
if [ -f "$env_file" ]; then
  if grep -q "^CCGM_USERNAME=testuser$" "$env_file"; then
    pass ".ccgm.env has CCGM_USERNAME=testuser"
  else
    fail ".ccgm.env missing or wrong CCGM_USERNAME"
  fi

  if grep -q "^CCGM_TIMEZONE=UTC$" "$env_file"; then
    pass ".ccgm.env has CCGM_TIMEZONE=UTC"
  else
    fail ".ccgm.env missing or wrong CCGM_TIMEZONE"
  fi

  if grep -q "^CCGM_DEFAULT_MODE=ask$" "$env_file"; then
    pass ".ccgm.env has CCGM_DEFAULT_MODE=ask"
  else
    fail ".ccgm.env missing or wrong CCGM_DEFAULT_MODE"
  fi
else
  fail ".ccgm.env not found for value check"
fi
echo ""

# Restore HOME
export HOME="$TMPDIR/home"

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
