#!/usr/bin/env bash
set -euo pipefail

# CCGM Uninstall Settings-Preservation Tests
#
# Regression coverage for issue #661 (data-loss bug): uninstall must NOT delete
# the user's settings.json. settings.json is a MERGE target, not a CCGM-owned
# file. Uninstall must un-merge only the CCGM-contributed keys/entries and leave
# user-authored keys intact. The file is removed only if nothing of the user's
# remains (reduces to {}).
#
# These tests exercise unmerge_settings (lib/merge.sh) directly, then run a full
# install -> uninstall cycle to prove settings.json survives end-to-end.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()
TMPDIR=""

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

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for uninstall settings tests"
  exit 1
fi

echo "=== CCGM Uninstall Settings-Preservation Tests ==="
echo ""

# shellcheck source=../lib/merge.sh
source "$REPO_ROOT/lib/merge.sh"

TMPDIR=$(mktemp -d)

# ============================================================
# Unit tests for unmerge_settings
# ============================================================

# --- Test 1: User scalar keys survive un-merge ---
echo "--- Test 1: User scalar keys survive un-merge ---"

cat > "$TMPDIR/settings1.json" << 'JSON'
{
  "env": { "USER_SECRET": "keep-me" },
  "model": "opus",
  "permissions": { "allow": ["Bash(ccgm *)", "Read(user-only)"] }
}
JSON

# Exactly what CCGM contributed at install time.
cat > "$TMPDIR/partial1.json" << 'JSON'
{
  "model": "opus",
  "permissions": { "allow": ["Bash(ccgm *)"] }
}
JSON

unmerge_settings "$TMPDIR/settings1.json" "$TMPDIR/partial1.json"

if [ -f "$TMPDIR/settings1.json" ]; then
  pass "settings.json still exists after un-merge"
else
  fail "settings.json was deleted (data loss!) after un-merge"
fi

if jq -e '.env.USER_SECRET == "keep-me"' "$TMPDIR/settings1.json" >/dev/null 2>&1; then
  pass "User-authored env.USER_SECRET preserved"
else
  fail "User-authored env.USER_SECRET lost"
fi

if jq -e 'has("model") | not' "$TMPDIR/settings1.json" >/dev/null 2>&1; then
  pass "CCGM-contributed scalar key 'model' removed"
else
  fail "CCGM-contributed scalar key 'model' not removed"
fi

if jq -e '.permissions.allow == ["Read(user-only)"]' "$TMPDIR/settings1.json" >/dev/null 2>&1; then
  pass "CCGM allow entry removed, user allow entry preserved"
else
  fail "allow array not un-merged correctly: $(jq -c '.permissions.allow' "$TMPDIR/settings1.json")"
fi
echo ""

# --- Test 2: File removed only when it reduces to {} ---
echo "--- Test 2: File removed when nothing user-owned remains ---"

cat > "$TMPDIR/settings2.json" << 'JSON'
{
  "permissions": { "allow": ["Bash(ccgm *)"] }
}
JSON

cat > "$TMPDIR/partial2.json" << 'JSON'
{
  "permissions": { "allow": ["Bash(ccgm *)"] }
}
JSON

unmerge_settings "$TMPDIR/settings2.json" "$TMPDIR/partial2.json"

if [ ! -f "$TMPDIR/settings2.json" ]; then
  pass "Empty-after-unmerge settings.json removed"
else
  fail "settings.json should have been removed (only {} left): $(cat "$TMPDIR/settings2.json")"
fi
echo ""

# --- Test 3: User override of a CCGM key is preserved ---
echo "--- Test 3: User override of a CCGM-contributed value is preserved ---"

cat > "$TMPDIR/settings3.json" << 'JSON'
{ "model": "sonnet" }
JSON

# CCGM originally contributed model=opus; user later changed it to sonnet.
cat > "$TMPDIR/partial3.json" << 'JSON'
{ "model": "opus" }
JSON

unmerge_settings "$TMPDIR/settings3.json" "$TMPDIR/partial3.json"

if [ -f "$TMPDIR/settings3.json" ] && jq -e '.model == "sonnet"' "$TMPDIR/settings3.json" >/dev/null 2>&1; then
  pass "User-overridden value left untouched"
else
  fail "User override was clobbered or file removed"
fi
echo ""

# --- Test 4: deny array + nested hooks un-merge ---
echo "--- Test 4: deny array and hooks un-merge ---"

cat > "$TMPDIR/settings4.json" << 'JSON'
{
  "permissions": {
    "deny": ["Bash(rm -rf /)", "Bash(user-deny)"]
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": ["python3 ccgm-hook.py"] },
      { "matcher": "Bash", "hooks": ["python3 user-hook.py"] }
    ]
  }
}
JSON

cat > "$TMPDIR/partial4.json" << 'JSON'
{
  "permissions": {
    "deny": ["Bash(rm -rf /)"]
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": ["python3 ccgm-hook.py"] }
    ]
  }
}
JSON

unmerge_settings "$TMPDIR/settings4.json" "$TMPDIR/partial4.json"

if jq -e '.permissions.deny == ["Bash(user-deny)"]' "$TMPDIR/settings4.json" >/dev/null 2>&1; then
  pass "User deny entry preserved, CCGM deny entry removed"
else
  fail "deny array un-merge wrong: $(jq -c '.permissions.deny' "$TMPDIR/settings4.json")"
fi

if jq -e '.hooks.PreToolUse == [{ "matcher": "Bash", "hooks": ["python3 user-hook.py"] }]' "$TMPDIR/settings4.json" >/dev/null 2>&1; then
  pass "User hook preserved, CCGM hook removed"
else
  fail "hooks un-merge wrong: $(jq -c '.hooks.PreToolUse' "$TMPDIR/settings4.json")"
fi
echo ""

# --- Test 5: missing target is a no-op (no error) ---
echo "--- Test 5: missing target is a no-op ---"

set +e
unmerge_settings "$TMPDIR/does-not-exist.json" "$TMPDIR/partial1.json"
rc=$?
set -e
if [ $rc -eq 0 ]; then
  pass "Missing target returns 0 (no-op)"
else
  fail "Missing target should be a no-op, got rc=$rc"
fi
echo ""

# ============================================================
# End-to-end: install then uninstall preserves user settings.json
# ============================================================
echo "--- Test 6: Full install -> uninstall preserves user settings.json ---"

E2E_HOME="$TMPDIR/e2e"
mkdir -p "$E2E_HOME/.claude"

# User had a pre-existing settings.json with their own keys BEFORE installing CCGM.
cat > "$E2E_HOME/.claude/settings.json" << 'JSON'
{
  "env": { "MY_OWN_KEY": "do-not-delete" },
  "permissions": { "allow": ["Bash(my-own-tool *)"] }
}
JSON

export CCGM_NON_INTERACTIVE=1
export CCGM_USERNAME=testuser
export CCGM_CODE_DIR="$E2E_HOME/code"
export CCGM_TIMEZONE=UTC
export CCGM_DEFAULT_MODE=ask
export HOME="$E2E_HOME"

set +e
"$REPO_ROOT/start.sh" --preset standard --scope global </dev/null >/dev/null 2>&1
install_exit=$?
set -e

if [ $install_exit -eq 0 ]; then
  pass "Installer ran (standard preset)"
else
  fail "Installer failed with exit $install_exit"
fi

# Confirm CCGM merged its keys in alongside the user's.
if jq -e '.env.MY_OWN_KEY == "do-not-delete"' "$E2E_HOME/.claude/settings.json" >/dev/null 2>&1; then
  pass "User key survived install merge"
else
  fail "User key lost during install merge"
fi

# Now uninstall non-interactively.
export CCGM_NON_INTERACTIVE=1
set +e
"$REPO_ROOT/uninstall.sh" </dev/null >/dev/null 2>&1
uninstall_exit=$?
set -e

if [ -f "$E2E_HOME/.claude/settings.json" ]; then
  pass "settings.json survived uninstall (not deleted)"
else
  fail "settings.json DELETED by uninstall (data loss bug #661)"
fi

if [ -f "$E2E_HOME/.claude/settings.json" ] && \
   jq -e '.env.MY_OWN_KEY == "do-not-delete"' "$E2E_HOME/.claude/settings.json" >/dev/null 2>&1; then
  pass "User key survived uninstall un-merge"
else
  fail "User key lost during uninstall"
fi

if [ -f "$E2E_HOME/.claude/settings.json" ] && \
   jq -e '.permissions.allow == ["Bash(my-own-tool *)"]' "$E2E_HOME/.claude/settings.json" >/dev/null 2>&1; then
  pass "User allow entry survived, CCGM allow entries un-merged"
else
  fail "User allow entry not preserved cleanly after uninstall: $(jq -c '.permissions.allow // "MISSING"' "$E2E_HOME/.claude/settings.json" 2>/dev/null)"
fi
echo ""

# --- Test 7: Legacy manifest (settings.json in files[], no mergedFiles[]) ---
# Users who installed with a pre-#661 CCGM have settings.json recorded in
# files[]. Uninstall must still refuse to delete it (defense-in-depth).
echo "--- Test 7: Legacy manifest does not delete settings.json ---"

LEGACY_HOME="$TMPDIR/legacy"
mkdir -p "$LEGACY_HOME/.claude/rules"
echo '{"env":{"LEGACY_USER_KEY":"keep"}}' > "$LEGACY_HOME/.claude/settings.json"
echo "ccgm rule" > "$LEGACY_HOME/.claude/rules/some-ccgm-rule.md"
cat > "$LEGACY_HOME/.claude/.ccgm-manifest.json" << JSON
{
  "version": "1.0.0",
  "scope": "global",
  "modules": ["settings"],
  "files": [
    "$LEGACY_HOME/.claude/settings.json",
    "$LEGACY_HOME/.claude/rules/some-ccgm-rule.md"
  ]
}
JSON

export CCGM_NON_INTERACTIVE=1
export HOME="$LEGACY_HOME"
set +e
"$REPO_ROOT/uninstall.sh" </dev/null >/dev/null 2>&1
set -e

if [ -f "$LEGACY_HOME/.claude/settings.json" ] && \
   jq -e '.env.LEGACY_USER_KEY == "keep"' "$LEGACY_HOME/.claude/settings.json" >/dev/null 2>&1; then
  pass "Legacy settings.json preserved (not deleted)"
else
  fail "Legacy settings.json DELETED (data loss for pre-#661 installs)"
fi

if [ ! -f "$LEGACY_HOME/.claude/rules/some-ccgm-rule.md" ]; then
  pass "Legacy CCGM-owned rule file still removed"
else
  fail "Legacy CCGM-owned rule file not removed"
fi
echo ""

# ============================================================
# Shell alias removal (issue #949)
#
# uninstall.sh used to strip ccgm/ccgms aliases with a hardcoded BSD-style
# `sed -i ''`, which GNU sed (Linux) misparses: it reads the empty string as
# the sed script and the real script as a filename, and errors out. These
# tests exercise remove_ccgm_alias_lines (uninstall.sh) directly against a
# scratch rc file, never the real ~/.zshrc or ~/.bashrc. uninstall.sh is
# sourced rather than executed, so main() never runs - see the
# BASH_SOURCE guard at the bottom of uninstall.sh.
# ============================================================
echo "--- Test 8: Alias removal strips aliases + comment header, leaves everything else untouched ---"

ALIAS_TMPDIR="$TMPDIR/alias-test"
mkdir -p "$ALIAS_TMPDIR"
RC_FILE="$ALIAS_TMPDIR/.zshrc"

# Mirrors what start.sh's alias step actually writes: unrelated content,
# then a blank line + CCGM comment header + both alias lines, then more
# unrelated content after.
cat > "$RC_FILE" << 'ZSHRC'
export PATH="$PATH:/usr/local/bin"
alias ll="ls -la"

# CCGM - Claude Code launchers
alias ccgm="claude --dangerously-skip-permissions"
alias ccgms="claude /startup --dangerously-skip-permissions"

export EDITOR=vim
ZSHRC

# Everything that should survive removal, byte for byte, in order. The
# blank line CCGM appended ahead of its comment header is not cleaned up
# (out of scope for #949), so it remains here too, alongside the blank line
# that already followed the alias block.
cat > "$ALIAS_TMPDIR/expected.zshrc" << 'ZSHRC'
export PATH="$PATH:/usr/local/bin"
alias ll="ls -la"


export EDITOR=vim
ZSHRC

set +e
remove_out=$(bash -c "source '$REPO_ROOT/uninstall.sh'; remove_ccgm_alias_lines '$RC_FILE'" 2>&1)
remove_exit=$?
set -e

if [ $remove_exit -eq 0 ]; then
  pass "remove_ccgm_alias_lines reports success when aliases are present"
else
  fail "remove_ccgm_alias_lines failed on a file with aliases present: $remove_out"
fi

if ! grep -qE '^alias ccgm=' "$RC_FILE" && ! grep -qE '^alias ccgms=' "$RC_FILE"; then
  pass "ccgm and ccgms alias lines removed"
else
  fail "alias lines still present: $(grep -E '^alias ccgm' "$RC_FILE" || true)"
fi

if ! grep -qE '^# CCGM - ' "$RC_FILE"; then
  pass "CCGM comment header removed"
else
  fail "CCGM comment header still present: $(grep -E '^# CCGM - ' "$RC_FILE" || true)"
fi

if diff -q "$ALIAS_TMPDIR/expected.zshrc" "$RC_FILE" >/dev/null 2>&1; then
  pass "Every other line in the rc file is byte-identical to before"
else
  fail "Unrelated rc file content was altered: $(diff "$ALIAS_TMPDIR/expected.zshrc" "$RC_FILE" || true)"
fi
echo ""

echo "--- Test 9: Alias removal is idempotent on an already-clean file ---"

# Snapshot the already-cleaned file, then run removal again.
cp "$RC_FILE" "$ALIAS_TMPDIR/before-second-run.zshrc"

set +e
second_out=$(bash -c "source '$REPO_ROOT/uninstall.sh'; remove_ccgm_alias_lines '$RC_FILE'" 2>&1)
second_exit=$?
set -e

if [ $second_exit -eq 1 ]; then
  pass "Second run reports no-op (no CCGM aliases found) instead of erroring"
else
  fail "Second run on an already-clean file exited $second_exit (expected 1, no-op): $second_out"
fi

if diff -q "$ALIAS_TMPDIR/before-second-run.zshrc" "$RC_FILE" >/dev/null 2>&1; then
  pass "Running removal twice does not change an already-clean file"
else
  fail "Second run mutated an already-clean file: $(diff "$ALIAS_TMPDIR/before-second-run.zshrc" "$RC_FILE" || true)"
fi
echo ""

echo "--- Test 10: Alias removal is a no-op on a file with no CCGM aliases at all ---"

NO_ALIAS_RC="$ALIAS_TMPDIR/no-alias.zshrc"
cat > "$NO_ALIAS_RC" << 'ZSHRC'
export PATH="$PATH:/usr/local/bin"
alias ll="ls -la"
ZSHRC
cp "$NO_ALIAS_RC" "$ALIAS_TMPDIR/no-alias-before.zshrc"

set +e
bash -c "source '$REPO_ROOT/uninstall.sh'; remove_ccgm_alias_lines '$NO_ALIAS_RC'" >/dev/null 2>&1
no_alias_exit=$?
set -e

if [ $no_alias_exit -eq 1 ]; then
  pass "No-op reported for a file with no CCGM aliases"
else
  fail "Expected no-op (exit 1) for a file with no CCGM aliases, got $no_alias_exit"
fi

if diff -q "$ALIAS_TMPDIR/no-alias-before.zshrc" "$NO_ALIAS_RC" >/dev/null 2>&1; then
  pass "File with no CCGM aliases left untouched"
else
  fail "File with no CCGM aliases was modified"
fi
echo ""

# NOTE (platform coverage): this suite runs on macOS, so the assertions
# above only exercise sed_inplace's BSD (sed -i with an empty-string suffix
# argument) branch via lib/template.sh. The GNU branch (sed -i with no
# separate suffix argument - the actual bug issue #949 fixes) is exercised
# by CI's ubuntu-latest job, not by a local run on this machine.
echo "NOTE: local run exercises the BSD/macOS sed_inplace branch only;"
echo "the GNU/Linux branch is covered by CI's ubuntu-latest job."
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
