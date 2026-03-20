#!/usr/bin/env bash
set -euo pipefail

# CCGM Symlink Mode Tests
# Verifies that --link creates symlinks for non-template files
# and copies for template files

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
  echo "ERROR: jq is required for link mode tests"
  exit 1
fi

echo "=== CCGM Symlink Mode Tests ==="
echo ""

TMPDIR=$(mktemp -d)
LINK_HOME="$TMPDIR/link-home"
mkdir -p "$LINK_HOME/.claude"

# Run installer in link mode with minimal preset
export CCGM_NON_INTERACTIVE=1
export CCGM_USERNAME=linktest
export CCGM_CODE_DIR="$LINK_HOME/code"
export CCGM_TIMEZONE=UTC
export CCGM_DEFAULT_MODE=ask
export HOME="$LINK_HOME"

echo "--- Installing with --link --preset minimal ---"
set +e
"$REPO_ROOT/start.sh" --link --preset minimal --scope global </dev/null 2>&1
installer_exit=$?
set -e

if [ $installer_exit -eq 0 ]; then
  pass "Link-mode installer exited successfully"
else
  fail "Link-mode installer exited with code $installer_exit"
fi
echo ""

# --- Test: Non-template files should be symlinks ---
echo "--- Checking symlinks for non-template files ---"

# autonomy module has template=false
autonomy_rule="$LINK_HOME/.claude/rules/autonomy.md"
if [ -L "$autonomy_rule" ]; then
  pass "rules/autonomy.md is a symlink"

  # Verify it points to the correct source
  link_target=$(readlink "$autonomy_rule")
  expected_target="$REPO_ROOT/modules/autonomy/rules/autonomy.md"
  if [ "$link_target" = "$expected_target" ]; then
    pass "rules/autonomy.md points to correct source"
  else
    fail "rules/autonomy.md points to '$link_target', expected '$expected_target'"
  fi
elif [ -f "$autonomy_rule" ]; then
  fail "rules/autonomy.md is a regular file, expected symlink"
else
  fail "rules/autonomy.md does not exist"
fi

# git-workflow module has template=false
git_rule="$LINK_HOME/.claude/rules/git-workflow.md"
if [ -L "$git_rule" ]; then
  pass "rules/git-workflow.md is a symlink"

  link_target=$(readlink "$git_rule")
  expected_target="$REPO_ROOT/modules/git-workflow/rules/git-workflow.md"
  if [ "$link_target" = "$expected_target" ]; then
    pass "rules/git-workflow.md points to correct source"
  else
    fail "rules/git-workflow.md points to '$link_target', expected '$expected_target'"
  fi
elif [ -f "$git_rule" ]; then
  fail "rules/git-workflow.md is a regular file, expected symlink"
else
  fail "rules/git-workflow.md does not exist"
fi
echo ""

# --- Test: Link mode with standard preset (includes templates) ---
echo "--- Installing with --link --preset standard ---"

LINK2_HOME="$TMPDIR/link-home-2"
mkdir -p "$LINK2_HOME/.claude"
export HOME="$LINK2_HOME"
export CCGM_CODE_DIR="$LINK2_HOME/code"

set +e
"$REPO_ROOT/start.sh" --link --preset standard --scope global </dev/null 2>&1
installer_exit=$?
set -e

if [ $installer_exit -eq 0 ]; then
  pass "Link-mode installer exited successfully (standard)"
else
  fail "Link-mode installer exited with code $installer_exit (standard)"
fi

# Template files should be regular files (copies), not symlinks.
# hooks/enforce-git-workflow.py has template=true in hooks module.json
hook_file="$LINK2_HOME/.claude/hooks/enforce-git-workflow.py"
if [ -f "$hook_file" ] && [ ! -L "$hook_file" ]; then
  pass "hooks/enforce-git-workflow.py is a regular file (template - correctly copied)"
elif [ -L "$hook_file" ]; then
  fail "hooks/enforce-git-workflow.py is a symlink (should be copy because template=true)"
else
  fail "hooks/enforce-git-workflow.py does not exist"
fi

# Non-template hooks should be symlinks
hook_issue="$LINK2_HOME/.claude/hooks/enforce-issue-workflow.py"
if [ -L "$hook_issue" ]; then
  pass "hooks/enforce-issue-workflow.py is a symlink (non-template)"
elif [ -f "$hook_issue" ]; then
  fail "hooks/enforce-issue-workflow.py is a regular file, expected symlink"
else
  fail "hooks/enforce-issue-workflow.py does not exist"
fi

# Non-template rule files should be symlinks
code_quality="$LINK2_HOME/.claude/rules/autonomy.md"
if [ -L "$code_quality" ]; then
  pass "rules/autonomy.md is a symlink (standard, non-template)"
elif [ -f "$code_quality" ]; then
  fail "rules/autonomy.md is a regular file, expected symlink"
else
  fail "rules/autonomy.md does not exist"
fi

# Command files (non-template) should be symlinks
commit_cmd="$LINK2_HOME/.claude/commands/commit.md"
if [ -L "$commit_cmd" ]; then
  pass "commands/commit.md is a symlink (non-template)"
elif [ -f "$commit_cmd" ]; then
  fail "commands/commit.md is a regular file, expected symlink"
else
  fail "commands/commit.md does not exist"
fi
echo ""

# --- Test: Manifest records link mode ---
echo "--- Checking manifest linkMode ---"
manifest="$LINK2_HOME/.claude/.ccgm-manifest.json"
if [ -f "$manifest" ]; then
  link_mode=$(jq -r '.linkMode' "$manifest" 2>/dev/null)
  if [ "$link_mode" = "true" ]; then
    pass "Manifest linkMode=true"
  else
    fail "Manifest linkMode='$link_mode', expected 'true'"
  fi
else
  fail "Manifest not found"
fi
echo ""

# Restore HOME
export HOME="$TMPDIR/link-home"

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
