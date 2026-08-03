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

# ============================================================
# Test 6: --add a module with per-module placeholders expands them
# ============================================================
echo "--- Test 6: --add expands CCGM_MODULE_* placeholders ---"

TEST6_HOME="$TMPDIR/test6"
mkdir -p "$TEST6_HOME/.claude"
export HOME="$TEST6_HOME"
export CCGM_CODE_DIR="$TEST6_HOME/code"

# Base install so a manifest + .ccgm.env exist.
set +e
"$REPO_ROOT/start.sh" --preset minimal --scope global </dev/null >/dev/null 2>&1
base6_exit=$?
set -e
if [ $base6_exit -eq 0 ]; then
  pass "Base minimal install for placeholder --add test"
else
  fail "Base minimal install failed (exit $base6_exit)"
fi

env6="$TEST6_HOME/.claude/.ccgm.env"

# Seed per-module config the way the interactive installer would have. The key
# shape is CCGM_MODULE_<module>__<__PLACEHOLDER__> (four underscores).
{
  echo "CCGM_MODULE_remote-server____REMOTE_HOST__=10.20.30.40"
  echo "CCGM_MODULE_remote-server____REMOTE_USER__=ops"
  echo "CCGM_MODULE_remote-server____REMOTE_ALIAS__=lab-box"
} >> "$env6"

set +e
"$REPO_ROOT/start.sh" --add remote-server </dev/null >/dev/null 2>&1
add6_exit=$?
set -e
if [ $add6_exit -eq 0 ]; then
  pass "--add remote-server (with seeded config) exited successfully"
else
  fail "--add remote-server exited with code $add6_exit"
fi

onremote="$TEST6_HOME/.claude/commands/onremote.md"
if [ -f "$onremote" ]; then
  pass "commands/onremote.md installed after --add"

  if grep -qE '__[A-Z_]+__' "$onremote"; then
    fail "onremote.md still has leftover placeholders: $(grep -oE '__[A-Z_]+__' "$onremote" | sort -u | tr '\n' ' ')"
  else
    pass "onremote.md has no leftover __PLACEHOLDER__"
  fi

  if grep -q "10.20.30.40" "$onremote" && grep -q "ops" "$onremote" && grep -q "lab-box" "$onremote"; then
    pass "onremote.md contains expanded host/user/alias values"
  else
    fail "onremote.md missing expected expanded values"
  fi
else
  fail "commands/onremote.md missing after --add"
fi
echo ""

# ============================================================
# Test 7: --add FAILS when a declared placeholder is unwired
# ============================================================
echo "--- Test 7: --add fails on leftover placeholder ---"

TEST7_HOME="$TMPDIR/test7"
mkdir -p "$TEST7_HOME/.claude"
export HOME="$TEST7_HOME"
export CCGM_CODE_DIR="$TEST7_HOME/code"

set +e
"$REPO_ROOT/start.sh" --preset minimal --scope global </dev/null >/dev/null 2>&1
base7_exit=$?
set -e
if [ $base7_exit -eq 0 ]; then
  pass "Base minimal install for fail-on-leftover test"
else
  fail "Base minimal install failed (exit $base7_exit)"
fi

# Note: NO CCGM_MODULE_remote-server__* entries seeded, so onremote.md's
# placeholders cannot be expanded -> install must fail.
set +e
add7_out=$("$REPO_ROOT/start.sh" --add remote-server </dev/null 2>&1)
add7_exit=$?
set -e
if [ $add7_exit -ne 0 ]; then
  pass "--add with unwired placeholders fails with non-zero exit"
else
  fail "--add with unwired placeholders unexpectedly succeeded"
fi

# Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
# producer if grep exits on its first match before the producer finishes
# writing, turning a successful match into a reported failure (see #943,
# #945). A herestring has no second process to race against.
if grep -qiE "unexpanded placeholder" <<< "$add7_out"; then
  pass "Failure message names the unexpanded placeholder"
else
  fail "Failure message did not mention unexpanded placeholder"
fi
echo ""

# ============================================================
# Test 8: CCGM_NON_INTERACTIVE honors declared configPrompt defaults
# (#918 regression pin: identity's personalizeIdentity declares
# default "no" with options ["yes","no"] - options[0] is "yes". Before
# the fix, non-interactive mode silently ran the identity
# personalization block with unchosen answers.)
# ============================================================
echo "--- Test 8: non-interactive mode honors declared defaults (identity) ---"

TEST8_HOME="$TMPDIR/test8"
mkdir -p "$TEST8_HOME/.claude"
export HOME="$TEST8_HOME"
export CCGM_CODE_DIR="$TEST8_HOME/code"

set +e
"$REPO_ROOT/start.sh" --preset standard --scope global </dev/null >/dev/null 2>&1
install8_exit=$?
set -e
if [ $install8_exit -eq 0 ]; then
  pass "Installer exited successfully (standard preset, test 8)"
else
  fail "Installer exited with code $install8_exit (standard preset, test 8)"
fi

env8="$TEST8_HOME/.claude/.ccgm.env"
if [ -f "$env8" ]; then
  # The declared default ("no") must win, not options[0] ("yes").
  if grep -q "^CCGM_MODULE_identity__personalizeIdentity=no$" "$env8"; then
    pass "identity__personalizeIdentity resolved to declared default 'no', not options[0] 'yes'"
  else
    fail "identity__personalizeIdentity did not resolve to 'no' (options[0] leaked through)"
  fi

  # Because personalizeIdentity correctly resolved to "no", the
  # personalization follow-up block must never have run, so none of its
  # invented answers should be present.
  if grep -qE "^CCGM_MODULE_identity__(role|expertise|communication|building|values)=" "$env8"; then
    fail "Identity personalization block ran under non-interactive mode with unchosen answers"
  else
    pass "Identity personalization block did not run (no invented role/communication/values)"
  fi
else
  fail ".ccgm.env not found for test 8"
fi
echo ""

# ============================================================
# Test 9: ui_choose --default edge cases (unit-level, direct)
#
# Sourced directly rather than run through the full installer -
# Test 8 above already pins the end-to-end identity case (a
# non-options[0] default winning). These cover the remaining
# ui_choose contract points from #918 that don't need a full
# installer run to exercise.
# ============================================================
echo "--- Test 9: ui_choose --default edge cases ---"

# shellcheck source=../lib/ui.sh
source "$REPO_ROOT/lib/ui.sh"
export CCGM_NON_INTERACTIVE=1

# No declared default -> falls back to options[0] (regression guard: the
# five call sites that never pass --default must be unaffected).
result=$(ui_choose "Where to install?" "global" "project" "both")
if [ "$result" = "global" ]; then
  pass "ui_choose with no --default returns options[0] ('global')"
else
  fail "ui_choose with no --default returned '$result', expected 'global'"
fi

# Declared default is options[0] -> unaffected (regression guard for the
# common case, where a manifest's default happens to match options[0]).
result=$(ui_choose --default "minimal" "Select preset" "minimal" "standard" "full" "team")
if [ "$result" = "minimal" ]; then
  pass "ui_choose --default matching options[0] returns 'minimal'"
else
  fail "ui_choose --default matching options[0] returned '$result', expected 'minimal'"
fi

# Declared default is an empty string -> treated as "no default declared",
# falls back to options[0] silently (no warning; an empty default is not a
# manifest typo).
default_stderr="$TMPDIR/test9-empty-default-stderr.log"
result=$(ui_choose --default "" "Pick one" "first" "second" 2>"$default_stderr")
if [ "$result" = "first" ]; then
  pass "ui_choose --default '' (empty) returns options[0] ('first')"
else
  fail "ui_choose --default '' (empty) returned '$result', expected 'first'"
fi
if [ -s "$default_stderr" ]; then
  fail "ui_choose --default '' (empty) unexpectedly printed a warning"
else
  pass "ui_choose --default '' (empty) printed no warning"
fi

# Declared default is not among the options -> falls back to options[0]
# AND warns to stderr (a manifest typo must not silently pick an
# unrelated value).
mismatch_stderr="$TMPDIR/test9-mismatch-stderr.log"
result=$(ui_choose --default "nonexistent" "Pick one" "first" "second" 2>"$mismatch_stderr")
if [ "$result" = "first" ]; then
  pass "ui_choose --default with an unmatched value returns options[0] ('first')"
else
  fail "ui_choose --default with an unmatched value returned '$result', expected 'first'"
fi
if grep -q "WARNING:" "$mismatch_stderr"; then
  pass "ui_choose --default with an unmatched value warns to stderr with 'WARNING:' (matches lib/*.sh sibling casing)"
else
  fail "ui_choose --default with an unmatched value did not print a 'WARNING:'-prefixed message: $(cat "$mismatch_stderr")"
fi
if grep -qi "warning" <<< "$result"; then
  fail "Warning text leaked into ui_choose's returned value"
else
  pass "Warning text did not leak into ui_choose's returned value"
fi

# --default with no value following it (the flag as the entire argument
# list) is a caller error, not "no default" - it must fail loudly (stderr
# message, non-zero exit), never silently return an empty string with
# exit 0. This holds under both -u (unbound $2) and non -u (silently
# empty $2) - the guard is arity-based, not reliant on shell options.
arity_stderr="$TMPDIR/test9-arity-stderr.log"
set +e
result=$(ui_choose --default 2>"$arity_stderr")
arity_exit=$?
set -e
if [ $arity_exit -ne 0 ]; then
  pass "ui_choose --default with no value exits non-zero (arity guard)"
else
  fail "ui_choose --default with no value exited 0 (expected non-zero)"
fi
if [ -z "$result" ]; then
  pass "ui_choose --default with no value returns empty stdout"
else
  fail "ui_choose --default with no value returned '$result' on stdout"
fi
if grep -q "ERROR:" "$arity_stderr"; then
  pass "ui_choose --default with no value prints an 'ERROR:'-prefixed message to stderr"
else
  fail "ui_choose --default with no value did not print an 'ERROR:'-prefixed message: $(cat "$arity_stderr")"
fi
echo ""

# ============================================================
# Test 10: interactive preset menu and --help preset list are both
# derived from presets/*.json via the shared list_preset_names() helper
# (lib/modules.sh) (#919)
#
# Before the fix, start.sh printed every presets/*.json file but then
# hardcoded both the ui_choose "Select preset" menu AND the --help
# "--preset <name>" line to "minimal standard full team" - cloud-agent
# was advertised in the printed list but unreachable from either. This
# proves both derived lists come from the same function that prints the
# list (so neither can diverge again), and covers the degenerate case
# of a preset filename containing a space (the glob must not
# word-split it into multiple entries).
#
# The whole test runs against an isolated scratch CCGM_ROOT under
# $TMPDIR, not the repo's real presets/ directory: it symlinks start.sh,
# lib/, and modules/, then builds its own presets/ (symlinks to the real
# preset files, plus a scratch preset with a space in its name). This
# means two concurrent runs of this suite cannot collide over the
# scratch file, and a mid-test abort cannot leave a stray *.json in the
# repo's committed presets/ - the scratch root is removed by the
# existing TMPDIR cleanup() trap like everything else under $TMPDIR,
# with no separate bookkeeping needed.
# ============================================================
echo "--- Test 10: interactive preset menu and --help match presets/*.json ---"

TEST10_HOME="$TMPDIR/test10"
mkdir -p "$TEST10_HOME/.claude"
export HOME="$TEST10_HOME"
export CCGM_CODE_DIR="$TEST10_HOME/code"
export CCGM_USERNAME=testuser
export CCGM_TIMEZONE=UTC
export CCGM_DEFAULT_MODE=ask

scratch_root="$TMPDIR/test10-root"
mkdir -p "$scratch_root/presets"
ln -s "$REPO_ROOT/start.sh" "$scratch_root/start.sh"
ln -s "$REPO_ROOT/lib" "$scratch_root/lib"
ln -s "$REPO_ROOT/modules" "$scratch_root/modules"
for pf in "$REPO_ROOT"/presets/*.json; do
  [ -e "$pf" ] || continue
  ln -s "$pf" "$scratch_root/presets/$(basename "$pf")"
done
# A preset filename containing a space, present only in this test's
# isolated presets/ - never written to the real, shared directory.
echo '["autonomy"]' > "$scratch_root/presets/zz scratch test.json"

# Expected menu = list_preset_names()'s output for the scratch root - the
# exact same function start.sh itself calls, just pointed at the
# isolated presets/ built above instead of the real one.
expected10_presets=()
(
  CCGM_ROOT="$scratch_root"
  # shellcheck source=../lib/modules.sh
  source "$REPO_ROOT/lib/modules.sh"
  list_preset_names
) > "$TMPDIR/test10-expected.txt"
while IFS= read -r pname; do
  [ -n "$pname" ] && expected10_presets+=("$pname")
done < "$TMPDIR/test10-expected.txt"

# Capture the exact arguments start.sh passes to `ui_choose "Select
# preset" ...` via xtrace. CCGM_NON_INTERACTIVE makes ui_choose a
# pass-through that returns options[0] without touching a tty, so this
# is safe to run headlessly - we only need the trace to see the FULL
# menu it was offered, not what it happened to auto-pick. (The
# auto-picked preset, whichever one sorts first, may go on to fail
# later in this same run for unrelated reasons - e.g. a preset that
# includes a module with a required, unseeded placeholder - so this
# test does not assert on the installer's overall exit code.)
trace10="$TMPDIR/test10-trace.log"
bash -x "$scratch_root/start.sh" --scope global </dev/null >/dev/null 2>"$trace10" || true

menu10_line=$(grep -m1 "ui_choose 'Select preset'" "$trace10" || true)
if [ -n "$menu10_line" ]; then
  pass "Captured the 'Select preset' ui_choose invocation"
else
  fail "Did not find a 'Select preset' ui_choose invocation in the trace"
fi

menu10_presets=()
if [ -n "$menu10_line" ]; then
  menu10_args_src="${menu10_line#*ui_choose }"
  menu10_opts=()
  eval "menu10_opts=($menu10_args_src)"
  # First element is the prompt string ("Select preset"); the rest are
  # the actual menu options.
  menu10_presets=("${menu10_opts[@]:1}")
fi

if [ "${#menu10_presets[@]}" -eq "${#expected10_presets[@]}" ]; then
  pass "Preset menu offers ${#menu10_presets[@]} options (matches presets/*.json count)"
else
  fail "Preset menu offers ${#menu10_presets[@]} options, expected ${#expected10_presets[@]} (${expected10_presets[*]})"
fi

menu10_match=true
for i in "${!expected10_presets[@]}"; do
  if [ "${menu10_presets[$i]:-}" != "${expected10_presets[$i]}" ]; then
    menu10_match=false
  fi
done
if [ "$menu10_match" = true ]; then
  pass "Preset menu options exactly match presets/*.json basenames, in glob order (${expected10_presets[*]})"
else
  fail "Preset menu options (${menu10_presets[*]:-none}) do not match presets/*.json (${expected10_presets[*]})"
fi

# The exact bug #919 reported: cloud-agent is printed but not selectable.
menu10_cloud_agent_present=false
for opt in "${menu10_presets[@]}"; do
  [ "$opt" = "cloud-agent" ] && menu10_cloud_agent_present=true
done
if [ "$menu10_cloud_agent_present" = true ]; then
  pass "cloud-agent is present in the interactive preset menu"
else
  fail "cloud-agent is missing from the interactive preset menu (#919 regression)"
fi

# The scratch preset's space-bearing name must survive intact as a
# single menu option, not get word-split.
scratch_present=false
for opt in "${menu10_presets[@]}"; do
  [ "$opt" = "zz scratch test" ] && scratch_present=true
done
if [ "$scratch_present" = true ]; then
  pass "A preset filename containing a space appears intact as a single menu option"
else
  fail "A preset filename containing a space did not appear intact in the menu (${menu10_presets[*]:-none})"
fi

# --help's preset list is a second surface with the exact same class of
# bug (#919 follow-up): it must also be derived from presets/*.json (via
# the same list_preset_names() helper), not a second hand-maintained
# list. Reuses the isolated scratch root built above.
help10_out=$("$scratch_root/start.sh" --help 2>&1)
help10_line=$(echo "$help10_out" | grep -F -- "--preset <name>" || true)

help10_presets=()
if [ -n "$help10_line" ]; then
  # Extract the parenthesized, comma-separated list, e.g.
  # "  --preset <name>     Use preset (cloud-agent, full, minimal, ...)"
  help10_inner="${help10_line#*\(}"
  help10_inner="${help10_inner%\)*}"
  help10_raw=()
  IFS=',' read -ra help10_raw <<< "$help10_inner"
  for help10_item in "${help10_raw[@]}"; do
    # Trim leading/trailing whitespace left by the ", " separator.
    help10_item="${help10_item#"${help10_item%%[![:space:]]*}"}"
    help10_item="${help10_item%"${help10_item##*[![:space:]]}"}"
    help10_presets+=("$help10_item")
  done
fi

if [ -n "$help10_line" ]; then
  pass "Found the --help '--preset <name>' line"
else
  fail "Did not find a '--preset <name>' line in --help output"
fi

if [ "${#help10_presets[@]}" -eq "${#expected10_presets[@]}" ]; then
  pass "--help lists ${#help10_presets[@]} presets (matches presets/*.json count)"
else
  fail "--help lists ${#help10_presets[@]} presets, expected ${#expected10_presets[@]} (${expected10_presets[*]})"
fi

help10_match=true
for i in "${!expected10_presets[@]}"; do
  if [ "${help10_presets[$i]:-}" != "${expected10_presets[$i]}" ]; then
    help10_match=false
  fi
done
if [ "$help10_match" = true ]; then
  pass "--help preset list exactly matches presets/*.json basenames, in glob order (${expected10_presets[*]})"
else
  fail "--help preset list (${help10_presets[*]:-none}) does not match presets/*.json (${expected10_presets[*]})"
fi

help10_cloud_agent_present=false
for opt in "${help10_presets[@]}"; do
  [ "$opt" = "cloud-agent" ] && help10_cloud_agent_present=true
done
if [ "$help10_cloud_agent_present" = true ]; then
  pass "cloud-agent is present in the --help preset list"
else
  fail "cloud-agent is missing from the --help preset list (#919 regression)"
fi

echo ""

# ============================================================
# Test 11: ui_confirm under real /bin/bash (#931 regression)
#
# ${answer,,} is a bash-4 parameter expansion; under bash 3.2 (macOS's
# system /bin/bash) it is a hard abort ("bad substitution") mid-function,
# so ui_confirm never returns and NEITHER branch of a
# `ui_confirm ... && ... || ...` caller runs - `bash -n` does not catch
# this, because the expansion parses fine and only fails at expansion
# time. This drives the real interactive path (CCGM_NON_INTERACTIVE
# unset) under /bin/bash explicitly - not whatever bash resolves to on
# $PATH, which may be a newer Homebrew bash on a dev machine.
# ============================================================
echo "--- Test 11: ui_confirm under real /bin/bash (#931 regression) ---"

if [ -x /bin/bash ]; then
  unset CCGM_NON_INTERACTIVE

  set +e
  confirm_out=$(printf 'yes\n' | /bin/bash -c \
    "source '$REPO_ROOT/lib/ui.sh'; ui_confirm 'Proceed?' && echo CONFIRMED || echo DECLINED" 2>&1)
  set -e
  # Herestrings through this whole block -- see the identical rationale at
  # the top of the file (#943, #945).
  if grep -q "bad substitution" <<< "$confirm_out"; then
    fail "ui_confirm under /bin/bash hit a bash-4 'bad substitution' abort (answer: yes): $confirm_out"
  elif grep -q "CONFIRMED" <<< "$confirm_out"; then
    pass "ui_confirm under /bin/bash returns confirmed for 'yes'"
  else
    fail "ui_confirm under /bin/bash did not confirm 'yes': $confirm_out"
  fi

  set +e
  decline_out=$(printf 'no\n' | /bin/bash -c \
    "source '$REPO_ROOT/lib/ui.sh'; ui_confirm 'Proceed?' && echo CONFIRMED || echo DECLINED" 2>&1)
  set -e
  if grep -q "bad substitution" <<< "$decline_out"; then
    fail "ui_confirm under /bin/bash hit a bash-4 'bad substitution' abort (answer: no): $decline_out"
  elif grep -q "DECLINED" <<< "$decline_out"; then
    pass "ui_confirm under /bin/bash returns declined for 'no'"
  else
    fail "ui_confirm under /bin/bash did not decline 'no': $decline_out"
  fi

  set +e
  mixed_out=$(printf 'YES\n' | /bin/bash -c \
    "source '$REPO_ROOT/lib/ui.sh'; ui_confirm 'Proceed?' && echo CONFIRMED || echo DECLINED" 2>&1)
  set -e
  if grep -q "CONFIRMED" <<< "$mixed_out"; then
    pass "ui_confirm under /bin/bash lowercases mixed-case 'YES' before matching"
  else
    fail "ui_confirm under /bin/bash did not confirm mixed-case 'YES': $mixed_out"
  fi

  # A literal "-n" or "-e" answer must be REJECTED (re-prompt), not
  # silently accepted as empty input -> the default. Piping the invalid
  # answer followed by a real one, with a default that would produce a
  # DIFFERENT result than the real answer, distinguishes "took the
  # default on the first read" (bug) from "re-prompted, then read the
  # real answer" (correct): if the bug were present, the invalid answer
  # would resolve to the default before the second line is ever read.
  set +e
  dashn_out=$(printf -- '-n\nyes\n' | /bin/bash -c \
    "source '$REPO_ROOT/lib/ui.sh'; ui_confirm 'Proceed?' 'no' && echo CONFIRMED || echo DECLINED" 2>&1)
  set -e
  if grep -q "Please answer yes or no" <<< "$dashn_out"; then
    pass "ui_confirm under /bin/bash re-prompts on a literal '-n' answer instead of silently taking the default"
  else
    fail "ui_confirm under /bin/bash did not re-prompt on '-n' (silently took the default): $dashn_out"
  fi
  if grep -q "CONFIRMED" <<< "$dashn_out"; then
    pass "ui_confirm under /bin/bash accepts the real answer ('yes') after rejecting '-n'"
  else
    fail "ui_confirm under /bin/bash did not resolve to the real answer after '-n': $dashn_out"
  fi

  set +e
  dashe_out=$(printf -- '-e\nno\n' | /bin/bash -c \
    "source '$REPO_ROOT/lib/ui.sh'; ui_confirm 'Proceed?' 'yes' && echo CONFIRMED || echo DECLINED" 2>&1)
  set -e
  if grep -q "Please answer yes or no" <<< "$dashe_out"; then
    pass "ui_confirm under /bin/bash re-prompts on a literal '-e' answer instead of silently taking the default"
  else
    fail "ui_confirm under /bin/bash did not re-prompt on '-e' (silently took the default): $dashe_out"
  fi
  if grep -q "DECLINED" <<< "$dashe_out"; then
    pass "ui_confirm under /bin/bash accepts the real answer ('no') after rejecting '-e'"
  else
    fail "ui_confirm under /bin/bash did not resolve to the real answer after '-e': $dashe_out"
  fi

  export CCGM_NON_INTERACTIVE=1
else
  echo "  SKIP: /bin/bash not present on this system"
fi
echo ""

# ============================================================
# Test 12: update.sh's _install_missing under real /bin/bash (#931
# nameref regression)
#
# update.sh:132-133 used `local -n` namerefs to pass the missing-modules
# and missing-files arrays into _install_missing. Namerefs are bash
# 4.3+; under bash 3.2 `local -n` is a hard "invalid option" abort. The
# fix shares script-scope globals between _check_installed_drift and
# _install_missing instead - _install_missing only ever reads these
# arrays, never writes them back, so a plain global is simpler than any
# form of indirection would be. update.sh now guards its `main "$@"`
# call with a BASH_SOURCE-vs-$0 check so this test can source it
# directly (no live git fetch, no interactive flow) and drive the real
# code path.
# ============================================================
echo "--- Test 12: update.sh _install_missing under real /bin/bash (#931 nameref regression) ---"

if [ -x /bin/bash ]; then
  UPDATE_TEST_HOME="$TMPDIR/test12-update-home"
  mkdir -p "$UPDATE_TEST_HOME/.claude"
  cat > "$UPDATE_TEST_HOME/.claude/.ccgm-manifest.json" <<'MANIFEST_EOF'
{
  "preset": "minimal",
  "scope": "global",
  "linkMode": false,
  "modules": ["global-claude-md", "autonomy"],
  "files": []
}
MANIFEST_EOF

  set +e
  update_out=$(HOME="$UPDATE_TEST_HOME" CCGM_NON_INTERACTIVE=1 /bin/bash -c \
    "source '$REPO_ROOT/update.sh'; _check_installed_drift" 2>&1)
  update_exit=$?
  set -e

  if grep -qE "invalid option|bad substitution" <<< "$update_out"; then
    fail "update.sh's _install_missing hit a bash-4-only construct under /bin/bash: $update_out"
  elif [ $update_exit -ne 0 ]; then
    fail "update.sh's _check_installed_drift/_install_missing exited $update_exit under /bin/bash: $update_out"
  else
    pass "update.sh's _check_installed_drift/_install_missing ran clean under /bin/bash"
  fi

  # "minimal" preset (presets/minimal.json) is ["global-claude-md",
  # "autonomy", "git-workflow"]; the manifest above installs the first
  # two, so git-workflow is the missing module _install_missing must
  # pull in - exercising the "install files from missing modules" loop.
  if [ -f "$UPDATE_TEST_HOME/.claude/rules/git-workflow.md" ]; then
    pass "missing module (git-workflow) installed by _install_missing"
  else
    fail "missing module (git-workflow) was not installed"
  fi

  # global-claude-md and autonomy are already "installed" per the
  # manifest but have no files on disk in this fresh fake HOME, so their
  # files are detected as missing too - exercising the "fix missing
  # files in already-installed modules" loop.
  if [ -f "$UPDATE_TEST_HOME/.claude/CLAUDE.md" ] && \
     [ -f "$UPDATE_TEST_HOME/.claude/rules/autonomy.md" ] && \
     [ -f "$UPDATE_TEST_HOME/.claude/rules/confusion-protocol.md" ]; then
    pass "missing files in already-installed modules installed by _install_missing"
  else
    fail "missing files in already-installed modules were not all installed"
  fi

  if command -v jq &>/dev/null; then
    manifest_modules=$(jq -c '.modules | sort' "$UPDATE_TEST_HOME/.claude/.ccgm-manifest.json" 2>/dev/null)
    if [ "$manifest_modules" = '["autonomy","git-workflow","global-claude-md"]' ]; then
      pass "manifest updated with the newly installed module (git-workflow)"
    else
      fail "manifest modules after install were '$manifest_modules', expected git-workflow added"
    fi
  fi
else
  echo "  SKIP: /bin/bash not present on this system"
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
