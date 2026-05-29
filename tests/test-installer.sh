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

# ============================================================
# Test 5: --add installs a single module into an existing setup
# ============================================================
echo "--- Test 5: --add single module ---"

TEST5_HOME="$TMPDIR/test5"
mkdir -p "$TEST5_HOME/.claude"
export HOME="$TEST5_HOME"
export CCGM_CODE_DIR="$TEST5_HOME/code"

# Base install: minimal preset, symlink mode
set +e
"$REPO_ROOT/start.sh" --link --preset minimal --scope global </dev/null >/dev/null 2>&1
base_exit=$?
set -e
if [ $base_exit -eq 0 ]; then
  pass "Base minimal install for --add test"
else
  fail "Base minimal install failed (exit $base_exit)"
fi

manifest="$TEST5_HOME/.claude/.ccgm-manifest.json"

# Precondition: shadcn not part of minimal
if [ ! -e "$TEST5_HOME/.claude/rules/shadcn.md" ]; then
  pass "Precondition: rules/shadcn.md absent before --add"
else
  fail "Precondition failed: rules/shadcn.md already present"
fi

# --- Add a simple dependency-free module ---
set +e
"$REPO_ROOT/start.sh" --add shadcn </dev/null >/dev/null 2>&1
add_exit=$?
set -e
if [ $add_exit -eq 0 ]; then
  pass "--add shadcn exited successfully"
else
  fail "--add shadcn exited with code $add_exit"
fi

if [ -e "$TEST5_HOME/.claude/rules/shadcn.md" ]; then
  pass "rules/shadcn.md installed after --add"
else
  fail "rules/shadcn.md missing after --add"
fi

if jq -e '.modules | index("shadcn")' "$manifest" >/dev/null 2>&1; then
  pass "Manifest includes shadcn after --add"
else
  fail "Manifest does not include shadcn"
fi

# Original modules preserved
if jq -e '.modules | index("git-workflow")' "$manifest" >/dev/null 2>&1; then
  pass "Manifest retains original modules (git-workflow)"
else
  fail "Manifest lost original modules after --add"
fi

# Link mode inherited from manifest (file is a symlink, base was --link)
if [ -L "$TEST5_HOME/.claude/rules/shadcn.md" ]; then
  pass "--add inherited link mode from manifest"
else
  fail "--add did not inherit link mode (expected symlink)"
fi

# --- Idempotency: re-add shadcn ---
mod_count_before=$(jq -r '.modules | length' "$manifest")
set +e
"$REPO_ROOT/start.sh" --add shadcn </dev/null >/dev/null 2>&1
readd_exit=$?
set -e
mod_count_after=$(jq -r '.modules | length' "$manifest")
if [ $readd_exit -eq 0 ] && [ "$mod_count_before" = "$mod_count_after" ]; then
  pass "--add shadcn is idempotent (exit 0, no duplicate module entry)"
else
  fail "--add shadcn not idempotent (exit $readd_exit, count $mod_count_before -> $mod_count_after)"
fi

# --- Dependency resolution: agent-native pulls in subagent-patterns ---
set +e
"$REPO_ROOT/start.sh" --add agent-native </dev/null >/dev/null 2>&1
dep_exit=$?
set -e
if [ $dep_exit -eq 0 ]; then
  pass "--add agent-native exited successfully"
else
  fail "--add agent-native exited with code $dep_exit"
fi
if [ -e "$TEST5_HOME/.claude/rules/agent-native.md" ] && [ -e "$TEST5_HOME/.claude/rules/subagent-patterns.md" ]; then
  pass "--add resolves dependencies (agent-native + subagent-patterns installed)"
else
  fail "--add did not resolve dependency subagent-patterns"
fi
if jq -e '.modules | index("subagent-patterns")' "$manifest" >/dev/null 2>&1; then
  pass "Manifest includes auto-resolved dependency subagent-patterns"
else
  fail "Manifest missing auto-resolved dependency"
fi

# --- Error: unknown module ---
set +e
"$REPO_ROOT/start.sh" --add no-such-module-xyz </dev/null >/dev/null 2>&1
unknown_exit=$?
set -e
if [ $unknown_exit -ne 0 ]; then
  pass "--add unknown module fails with non-zero exit"
else
  fail "--add unknown module unexpectedly succeeded"
fi

# --- Error: --add with no prior manifest ---
TEST5B_HOME="$TMPDIR/test5b"
mkdir -p "$TEST5B_HOME/.claude"
export HOME="$TEST5B_HOME"
set +e
"$REPO_ROOT/start.sh" --add shadcn </dev/null >/dev/null 2>&1
nomanifest_exit=$?
set -e
if [ $nomanifest_exit -ne 0 ]; then
  pass "--add with no existing manifest fails with non-zero exit"
else
  fail "--add with no manifest unexpectedly succeeded"
fi

# --- Error: --add combined with --preset is rejected ---
export HOME="$TEST5_HOME"
set +e
"$REPO_ROOT/start.sh" --add shadcn --preset minimal </dev/null >/dev/null 2>&1
combo_exit=$?
set -e
if [ $combo_exit -ne 0 ]; then
  pass "--add combined with --preset is rejected"
else
  fail "--add + --preset unexpectedly succeeded"
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
