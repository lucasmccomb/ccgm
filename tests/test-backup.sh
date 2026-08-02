#!/usr/bin/env bash
set -euo pipefail

# CCGM Backup/Restore Tests
# Verifies backup creation, restore, and cleanup operations

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()
TMPDIR=""
ORIG_HOME="$HOME"

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
  export HOME="$ORIG_HOME"
  if [ -n "$TMPDIR" ] && [ -d "$TMPDIR" ]; then
    rm -rf "$TMPDIR"
  fi
}
trap cleanup EXIT

echo "=== CCGM Backup/Restore Tests ==="
echo ""

# Source the backup library
# shellcheck source=../lib/backup.sh
source "$REPO_ROOT/lib/backup.sh"

# Create temp directory and mock HOME
TMPDIR=$(mktemp -d)
export HOME="$TMPDIR/fakehome"
mkdir -p "$HOME/.claude"

# --- Test 1: create_backup creates correct directory structure ---
echo "--- Test 1: Backup creates directory structure ---"

# Set up mock config files
TARGET_DIR="$HOME/.claude"
echo '{"key": "value"}' > "$TARGET_DIR/settings.json"
echo "# Claude MD" > "$TARGET_DIR/CLAUDE.md"
mkdir -p "$TARGET_DIR/rules"
echo "# Test rule" > "$TARGET_DIR/rules/test.md"
mkdir -p "$TARGET_DIR/hooks"
echo "#!/usr/bin/env python3" > "$TARGET_DIR/hooks/test-hook.py"
# Add a .ccgm file so backup captures hidden files too
echo "test-env" > "$TARGET_DIR/.ccgm.env"

backup_dir=$(create_backup "$TARGET_DIR")

if [ -n "$backup_dir" ] && [ -d "$backup_dir" ]; then
  pass "Backup directory created: $(basename "$backup_dir")"
else
  fail "Backup directory not created"
fi

# Check it has the ccgm- prefix with timestamp format
backup_name=$(basename "$backup_dir")
if [[ "$backup_name" =~ ^ccgm-[0-9]{8}-[0-9]{6}$ ]]; then
  pass "Backup directory name follows ccgm-YYYYMMDD-HHMMSS format"
else
  fail "Backup directory name '$backup_name' does not match expected format"
fi

# Check files were backed up
if [ -f "$backup_dir/settings.json" ]; then
  pass "settings.json backed up"
else
  fail "settings.json not found in backup"
fi

if [ -f "$backup_dir/CLAUDE.md" ]; then
  pass "CLAUDE.md backed up"
else
  fail "CLAUDE.md not found in backup"
fi

if [ -d "$backup_dir/rules" ] && [ -f "$backup_dir/rules/test.md" ]; then
  pass "rules/ directory backed up recursively"
else
  fail "rules/ directory not backed up correctly"
fi

if [ -d "$backup_dir/hooks" ] && [ -f "$backup_dir/hooks/test-hook.py" ]; then
  pass "hooks/ directory backed up recursively"
else
  fail "hooks/ directory not backed up correctly"
fi
echo ""

# --- Test 2: restore_backup reproduces original files ---
echo "--- Test 2: Restore reproduces original files ---"

# Create a fresh target to restore into
RESTORE_DIR="$TMPDIR/restored-claude"
mkdir -p "$RESTORE_DIR"

restore_backup "$backup_dir" "$RESTORE_DIR"

if [ -f "$RESTORE_DIR/settings.json" ]; then
  restored_content=$(cat "$RESTORE_DIR/settings.json")
  if [ "$restored_content" = '{"key": "value"}' ]; then
    pass "Restored settings.json content matches original"
  else
    fail "Restored settings.json content differs from original"
  fi
else
  fail "settings.json not found in restored directory"
fi

if [ -f "$RESTORE_DIR/CLAUDE.md" ]; then
  pass "CLAUDE.md restored"
else
  fail "CLAUDE.md not restored"
fi

if [ -f "$RESTORE_DIR/rules/test.md" ]; then
  pass "rules/test.md restored"
else
  fail "rules/test.md not restored"
fi

if [ -f "$RESTORE_DIR/hooks/test-hook.py" ]; then
  pass "hooks/test-hook.py restored"
else
  fail "hooks/test-hook.py not restored"
fi
echo ""

# --- Test 3: clean_backups keeps only N most recent ---
echo "--- Test 3: clean_backups keeps N most recent ---"

# Create several fake backup directories with distinct timestamps
BACKUP_BASE="$HOME/.claude/backups"
mkdir -p "$BACKUP_BASE"
# Clear any existing backups from test 1
rm -rf "$BACKUP_BASE"/ccgm-*

for i in 1 2 3 4 5; do
  bdir="$BACKUP_BASE/ccgm-2026040${i}-120000"
  mkdir -p "$bdir"
  echo "backup $i" > "$bdir/settings.json"
done

# Verify we have 5
count_before=$(ls -1d "$BACKUP_BASE"/ccgm-* 2>/dev/null | wc -l | tr -d ' ')
if [ "$count_before" -eq 5 ]; then
  pass "Created 5 test backups"
else
  fail "Expected 5 test backups, found $count_before"
fi

# Clean keeping only 2
clean_backups 2

count_after=$(ls -1d "$BACKUP_BASE"/ccgm-* 2>/dev/null | wc -l | tr -d ' ')
if [ "$count_after" -eq 2 ]; then
  pass "clean_backups(2) kept exactly 2 backups"
else
  fail "clean_backups(2) kept $count_after backups, expected 2"
fi

# Verify the two newest survive (ccgm-20260405 and ccgm-20260404)
if [ -d "$BACKUP_BASE/ccgm-20260405-120000" ] && [ -d "$BACKUP_BASE/ccgm-20260404-120000" ]; then
  pass "Newest two backups preserved"
else
  fail "Newest two backups not preserved correctly"
fi

# Verify oldest are gone
if [ ! -d "$BACKUP_BASE/ccgm-20260401-120000" ] && [ ! -d "$BACKUP_BASE/ccgm-20260402-120000" ] && [ ! -d "$BACKUP_BASE/ccgm-20260403-120000" ]; then
  pass "Oldest three backups removed"
else
  fail "Some old backups were not cleaned up"
fi
echo ""

# --- Test 4: Backup with no files to back up ---
echo "--- Test 4: Backup with no CCGM files ---"

EMPTY_DIR="$TMPDIR/empty-claude"
mkdir -p "$EMPTY_DIR"
# Directory exists but has no CCGM-managed files

backup_empty=$(create_backup "$EMPTY_DIR")

if [ -z "$backup_empty" ]; then
  pass "No backup created when no CCGM files exist"
else
  fail "Backup created unexpectedly for empty directory: $backup_empty"
fi
echo ""

# --- Test 5: Backup with nonexistent target directory ---
echo "--- Test 5: Backup with nonexistent target directory ---"

backup_nodir=$(create_backup "$TMPDIR/does-not-exist")

if [ -z "$backup_nodir" ]; then
  pass "No backup created for nonexistent directory"
else
  fail "Backup created unexpectedly for nonexistent directory: $backup_nodir"
fi
echo ""

# --- Test 6: Restore from nonexistent backup ---
echo "--- Test 6: Restore from nonexistent backup ---"

set +e
restore_output=$(restore_backup "$TMPDIR/no-such-backup" "$TMPDIR/restore-target" 2>&1)
restore_exit=$?
set -e

if [ $restore_exit -ne 0 ]; then
  pass "Restore from nonexistent backup returns non-zero exit"
else
  fail "Restore from nonexistent backup should return non-zero exit"
fi
echo ""

# --- Test 7: Backups are scoped to the install target (no cross-scope) ---
echo "--- Test 7: Backup scope isolation (global vs project) ---"

# Global target lives under $HOME/.claude; project target under a project dir.
GLOBAL_TARGET="$HOME/.claude"
PROJECT_DIR="$TMPDIR/project"
PROJECT_TARGET="$PROJECT_DIR/.claude"
mkdir -p "$PROJECT_TARGET"

# Distinct content per scope so we can detect cross-scope bleed.
echo '{"scope": "global"}' > "$GLOBAL_TARGET/settings.json"
echo '{"scope": "project"}' > "$PROJECT_TARGET/settings.json"

global_backup=$(create_backup "$GLOBAL_TARGET")
project_backup=$(create_backup "$PROJECT_TARGET")

# Each backup must land under its own scope's backups dir.
if [[ "$global_backup" == "$GLOBAL_TARGET/backups/"* ]]; then
  pass "Global backup written under global scope ($GLOBAL_TARGET/backups)"
else
  fail "Global backup not scoped to global target: $global_backup"
fi

if [[ "$project_backup" == "$PROJECT_TARGET/backups/"* ]]; then
  pass "Project backup written under project scope ($PROJECT_TARGET/backups)"
else
  fail "Project backup not scoped to project target: $project_backup"
fi

# A project backup must NOT appear in the global backups dir.
if [ -d "$GLOBAL_TARGET/backups" ] && ls -1d "$GLOBAL_TARGET/backups"/ccgm-* >/dev/null 2>&1; then
  # Global backups exist (expected); ensure none of them carry project content.
  cross_scope=false
  for b in "$GLOBAL_TARGET/backups"/ccgm-*; do
    if [ -f "$b/settings.json" ] && grep -q '"scope": "project"' "$b/settings.json"; then
      cross_scope=true
    fi
  done
  if [ "$cross_scope" = false ]; then
    pass "Global backups dir contains no project-scope content"
  else
    fail "Project content leaked into global backups dir"
  fi
else
  fail "Expected global backups dir to exist after global backup"
fi

# Restoring a project backup must reproduce project content, not global.
PROJECT_RESTORE="$TMPDIR/project-restore"
mkdir -p "$PROJECT_RESTORE"
restore_backup "$project_backup" "$PROJECT_RESTORE"
if [ -f "$PROJECT_RESTORE/settings.json" ] && grep -q '"scope": "project"' "$PROJECT_RESTORE/settings.json"; then
  pass "Project restore reproduces project-scope content"
else
  fail "Project restore did not reproduce project-scope content"
fi

# get_latest_backup must respect scope: project scope sees only project backups.
latest_project=$(get_latest_backup "$PROJECT_TARGET" 2>/dev/null || true)
if [ "$latest_project" = "$project_backup" ]; then
  pass "get_latest_backup scoped to project target returns project backup"
else
  fail "get_latest_backup project scope returned '$latest_project', expected '$project_backup'"
fi
echo ""

# --- Test 8: clean_backups respects scope ---
echo "--- Test 8: clean_backups scoped to install target ---"

SCOPE_BASE="$PROJECT_TARGET/backups"
# Clear and seed project-scope backups.
rm -rf "$SCOPE_BASE"/ccgm-*
for i in 1 2 3 4 5; do
  bdir="$SCOPE_BASE/ccgm-2026050${i}-120000"
  mkdir -p "$bdir"
  echo "scoped backup $i" > "$bdir/settings.json"
done

clean_backups 2 "$PROJECT_TARGET"

scoped_after=$(ls -1d "$SCOPE_BASE"/ccgm-* 2>/dev/null | wc -l | tr -d ' ')
if [ "$scoped_after" -eq 2 ]; then
  pass "clean_backups(2) scoped to project kept exactly 2 backups"
else
  fail "clean_backups scoped to project kept $scoped_after, expected 2"
fi
echo ""

# --- Test 9: project-scope backups dir is gitignored ---
echo "--- Test 9: project-scope backups gitignored ---"

GI_PROJECT="$TMPDIR/gi-project"
GI_TARGET="$GI_PROJECT/.claude"
mkdir -p "$GI_TARGET"
echo '{"scope": "gi-project"}' > "$GI_TARGET/settings.json"

gi_backup=$(create_backup "$GI_TARGET")
GI_BASE="$GI_TARGET/backups"

# A .gitignore must exist inside the backups dir and ignore everything.
if [ -f "$GI_BASE/.gitignore" ]; then
  pass "Project-scope backups dir has a .gitignore"
else
  fail "Project-scope backups dir is missing a .gitignore"
fi

if [ -f "$GI_BASE/.gitignore" ] && [ "$(cat "$GI_BASE/.gitignore")" = '*' ]; then
  pass "backups/.gitignore contains '*' (ignores all backup content)"
else
  fail "backups/.gitignore does not contain the expected '*' entry"
fi

# Idempotent: a second backup must not duplicate or alter the entry.
gi_lines_before=$(wc -l < "$GI_BASE/.gitignore" | tr -d ' ')
sleep 1  # ensure a distinct ccgm-YYYYMMDD-HHMMSS timestamp for the 2nd backup
gi_backup2=$(create_backup "$GI_TARGET")
gi_lines_after=$(wc -l < "$GI_BASE/.gitignore" | tr -d ' ')

if [ "$gi_lines_before" = "$gi_lines_after" ] && [ "$(cat "$GI_BASE/.gitignore")" = '*' ]; then
  pass "Repeated backup does not duplicate the .gitignore entry"
else
  fail "Repeated backup changed .gitignore (before=$gi_lines_before after=$gi_lines_after)"
fi

# Two distinct backups should have been created (sanity that we exercised it twice).
if [ -n "$gi_backup" ] && [ -n "$gi_backup2" ] && [ "$gi_backup" != "$gi_backup2" ]; then
  pass "Two distinct project-scope backups created"
else
  fail "Expected two distinct project-scope backups (got '$gi_backup' and '$gi_backup2')"
fi
echo ""

# --- Test 10: global-scope backups are NOT gitignored ---
echo "--- Test 10: global-scope backups unaffected ---"

# Clean any prior global backups, then create a fresh global-scope backup.
rm -rf "$HOME/.claude/backups"/ccgm-*
echo '{"scope": "global-gi"}' > "$HOME/.claude/settings.json"
global_gi_backup=$(create_backup "$HOME/.claude")

if [ ! -f "$HOME/.claude/backups/.gitignore" ]; then
  pass "Global-scope backups dir has no .gitignore (irrelevant for ~/.claude)"
else
  fail "Global-scope backups dir unexpectedly got a .gitignore"
fi
echo ""

# --- Test 11: Dynamic coverage backs up skills/ and agents/ (issue #917 case) ---
echo "--- Test 11: Dynamic coverage - skills/ and agents/ ---"

DYN_TARGET="$TMPDIR/dyn-claude"
mkdir -p "$DYN_TARGET/skills/orrery"
mkdir -p "$DYN_TARGET/agents"
echo "# Orrery skill" > "$DYN_TARGET/skills/orrery/SKILL.md"
echo "# Orrery scout agent" > "$DYN_TARGET/agents/orrery-scout.md"

dyn_backup=$(create_backup "$DYN_TARGET")

if [ -f "$dyn_backup/skills/orrery/SKILL.md" ]; then
  pass "skills/orrery/SKILL.md backed up"
else
  fail "skills/orrery/SKILL.md not found in backup"
fi

if [ -f "$dyn_backup/agents/orrery-scout.md" ]; then
  pass "agents/orrery-scout.md backed up"
else
  fail "agents/orrery-scout.md not found in backup"
fi
echo ""

# --- Test 12: lib/, bin/, output-styles/ backed up when present ---
echo "--- Test 12: lib/, bin/, output-styles/ backed up ---"

LBO_TARGET="$TMPDIR/lbo-claude"
mkdir -p "$LBO_TARGET/lib" "$LBO_TARGET/bin" "$LBO_TARGET/output-styles"
echo "# lib file" > "$LBO_TARGET/lib/helper.sh"
echo "# bin file" > "$LBO_TARGET/bin/tool.sh"
echo "# style file" > "$LBO_TARGET/output-styles/custom.md"

lbo_backup=$(create_backup "$LBO_TARGET")

if [ -f "$lbo_backup/lib/helper.sh" ]; then
  pass "lib/ backed up"
else
  fail "lib/ not found in backup"
fi

if [ -f "$lbo_backup/bin/tool.sh" ]; then
  pass "bin/ backed up"
else
  fail "bin/ not found in backup"
fi

if [ -f "$lbo_backup/output-styles/custom.md" ]; then
  pass "output-styles/ backed up"
else
  fail "output-styles/ not found in backup"
fi
echo ""

# --- Test 13: restore_backup round-trips the newly-covered paths ---
echo "--- Test 13: restore round-trips skills/, agents/, lib/, bin/ ---"

RESTORE_DYN="$TMPDIR/restored-dyn"
mkdir -p "$RESTORE_DYN"
restore_backup "$dyn_backup" "$RESTORE_DYN"

if [ -f "$RESTORE_DYN/skills/orrery/SKILL.md" ] && [ "$(cat "$RESTORE_DYN/skills/orrery/SKILL.md")" = "# Orrery skill" ]; then
  pass "Restored skills/orrery/SKILL.md content matches original"
else
  fail "Restored skills/orrery/SKILL.md missing or content differs"
fi

if [ -f "$RESTORE_DYN/agents/orrery-scout.md" ] && [ "$(cat "$RESTORE_DYN/agents/orrery-scout.md")" = "# Orrery scout agent" ]; then
  pass "Restored agents/orrery-scout.md content matches original"
else
  fail "Restored agents/orrery-scout.md missing or content differs"
fi

RESTORE_LBO="$TMPDIR/restored-lbo"
mkdir -p "$RESTORE_LBO"
restore_backup "$lbo_backup" "$RESTORE_LBO"

if [ -f "$RESTORE_LBO/lib/helper.sh" ] && [ "$(cat "$RESTORE_LBO/lib/helper.sh")" = "# lib file" ]; then
  pass "Restored lib/helper.sh content matches original"
else
  fail "Restored lib/helper.sh missing or content differs"
fi

if [ -f "$RESTORE_LBO/bin/tool.sh" ] && [ "$(cat "$RESTORE_LBO/bin/tool.sh")" = "# bin file" ]; then
  pass "Restored bin/tool.sh content matches original"
else
  fail "Restored bin/tool.sh missing or content differs"
fi
echo ""

# --- Test 14: retention still prunes to N with dynamic-coverage backups ---
echo "--- Test 14: clean_backups prunes dynamic-coverage backups to N ---"

RET_TARGET="$TMPDIR/ret-claude"
RET_BASE="$RET_TARGET/backups"
mkdir -p "$RET_BASE"
rm -rf "$RET_BASE"/ccgm-*

for i in 1 2 3 4 5 6; do
  bdir="$RET_BASE/ccgm-2026060${i}-120000"
  mkdir -p "$bdir/skills"
  echo "skill snapshot $i" > "$bdir/skills/test.md"
done

ret_count_before=$(ls -1d "$RET_BASE"/ccgm-* 2>/dev/null | wc -l | tr -d ' ')
if [ "$ret_count_before" -eq 6 ]; then
  pass "Created 6 dynamic-coverage backups"
else
  fail "Expected 6 backups before pruning, found $ret_count_before"
fi

clean_backups 5 "$RET_TARGET"

ret_count_after=$(ls -1d "$RET_BASE"/ccgm-* 2>/dev/null | wc -l | tr -d ' ')
if [ "$ret_count_after" -eq 5 ]; then
  pass "clean_backups(5) pruned dynamic-coverage backups to 5"
else
  fail "clean_backups(5) kept $ret_count_after backups, expected 5"
fi

if [ -d "$RET_BASE/ccgm-20260606-120000" ] && [ -f "$RET_BASE/ccgm-20260606-120000/skills/test.md" ]; then
  pass "Newest dynamic-coverage backup (skills/) preserved after pruning"
else
  fail "Newest dynamic-coverage backup not preserved correctly"
fi
echo ""

# --- Test 15: project-scope backups with dynamic coverage stay scoped ---
echo "--- Test 15: project-scope backup isolation with dynamic coverage ---"

DYN_PROJECT_DIR="$TMPDIR/dyn-project"
DYN_PROJECT_TARGET="$DYN_PROJECT_DIR/.claude"
mkdir -p "$DYN_PROJECT_TARGET/skills/orrery"
echo "# project orrery skill" > "$DYN_PROJECT_TARGET/skills/orrery/SKILL.md"

rm -rf "$HOME/.claude/backups"/ccgm-*
dyn_project_backup=$(create_backup "$DYN_PROJECT_TARGET")

if [[ "$dyn_project_backup" == "$DYN_PROJECT_TARGET/backups/"* ]]; then
  pass "Dynamic-coverage project backup written under project scope"
else
  fail "Dynamic-coverage project backup not scoped to project target: $dyn_project_backup"
fi

if [ -f "$dyn_project_backup/skills/orrery/SKILL.md" ]; then
  pass "Project-scope skills/orrery/SKILL.md backed up"
else
  fail "Project-scope skills/orrery/SKILL.md not found in backup"
fi

# find (not ls) here: the glob matches nothing in the expected case, and
# under `set -euo pipefail` an `ls` with no matches would abort the script.
global_backup_count=$(find "$HOME/.claude/backups" -maxdepth 1 -type d -name 'ccgm-*' 2>/dev/null | wc -l | tr -d ' ')
if [ "$global_backup_count" -eq 0 ]; then
  pass "No global-scope backup created for a project-scope backup"
else
  fail "Project-scope backup unexpectedly created $global_backup_count global-scope backup(s)"
fi
echo ""

# --- Test 16: non-CCGM directories are not swept into the backup ---
# Pins the manifest-derivation design decision: the backup set comes from
# module.json targets, not a directory listing of the target dir. This is
# what keeps ~/.claude/projects/ (session transcripts, memory) out of backups.
echo "--- Test 16: non-CCGM directory (projects/) is not backed up ---"

NONCCGM_TARGET="$TMPDIR/nonccgm-claude"
mkdir -p "$NONCCGM_TARGET/skills"
mkdir -p "$NONCCGM_TARGET/projects/some-project"
echo "# real skill" > "$NONCCGM_TARGET/skills/test.md"
echo "session transcript data" > "$NONCCGM_TARGET/projects/some-project/session.jsonl"

nonccgm_backup=$(create_backup "$NONCCGM_TARGET")

if [ -f "$nonccgm_backup/skills/test.md" ]; then
  pass "CCGM-managed skills/ backed up"
else
  fail "CCGM-managed skills/ not found in backup"
fi

if [ ! -e "$nonccgm_backup/projects" ]; then
  pass "Non-CCGM projects/ directory excluded from backup"
else
  fail "Non-CCGM projects/ directory was unexpectedly backed up"
fi
echo ""

# --- Test 17: unsafe manifest targets never reach the copy loop ---
# Regression test for the Stage 2 HIGH finding on issue #917: a manifest
# target like "./skills/foo.md" reduces via "${t%%/*}" to the literal
# segment ".", which -- unguarded -- would reach create_backup's copy loop
# and `cp -r` the in-progress backup directory into itself (backup_dir
# lives inside target_dir). "../x" reduces to "..", and "/abs/x" reduces to
# an empty segment. _backup_safe_segment must reject all three while still
# letting a legitimate sibling target through.
echo "--- Test 17: unsafe manifest targets (., .., empty, abs) are rejected ---"

FIXTURE_ROOT="$TMPDIR/fixture-root"
mkdir -p "$FIXTURE_ROOT/modules/weirdmod"
cat > "$FIXTURE_ROOT/modules/weirdmod/module.json" <<'JSON'
{
  "name": "weirdmod",
  "files": {
    "a": { "target": "./weird/file.md", "type": "doc" },
    "b": { "target": "../also-weird/file.md", "type": "doc" },
    "c": { "target": "/abs/weird/file.md", "type": "doc" },
    "d": { "target": "", "type": "doc" },
    "e": { "target": "skills/real/thing.md", "type": "doc" }
  }
}
JSON

fixture_paths=$(CCGM_ROOT="$FIXTURE_ROOT" managed_backup_paths 2>/dev/null)

if ! echo "$fixture_paths" | grep -qx '\.'; then
  pass "Derived path list does not contain a literal '.' segment"
else
  fail "Derived path list contains a dangerous literal '.' segment"
fi

if ! echo "$fixture_paths" | grep -qx '\.\.'; then
  pass "Derived path list does not contain a literal '..' segment"
else
  fail "Derived path list contains a dangerous literal '..' segment"
fi

if ! echo "$fixture_paths" | grep -qx ''; then
  pass "Derived path list does not contain an empty segment"
else
  fail "Derived path list contains an empty segment"
fi

if echo "$fixture_paths" | grep -qx 'skills'; then
  pass "Legitimate sibling target (skills/) still passes through"
else
  fail "Legitimate sibling target (skills/) was dropped by the safety filter"
fi
echo ""

# --- Test 18: create_backup survives a manifest with a "./..." target ---
# Proves the fix against the concrete crash, not just the filtered list:
# with the same weirdmod fixture as the manifest source, create_backup
# must complete with exit 0 and must not leave a nested
# backups/ccgm-*/backups/ccgm-*/... directory behind (the original crash
# signature -- cp -r recursing into the in-progress backup).
echo "--- Test 18: create_backup survives a manifest with a './...' target ---"

WEIRD_TARGET="$TMPDIR/weird-claude"
mkdir -p "$WEIRD_TARGET/skills"
echo '{"key": "value"}' > "$WEIRD_TARGET/settings.json"
echo "real skill" > "$WEIRD_TARGET/skills/thing.md"

# Run in a subshell with set -euo pipefail, matching exactly how start.sh
# sources lib/backup.sh and calls create_backup. The subshell inherits the
# already-sourced functions from this script. set +e/-e brackets the call
# (same pattern as Test 6) so a regression here fails this assertion
# instead of aborting the whole suite.
set +e
( set -euo pipefail; CCGM_ROOT="$FIXTURE_ROOT" create_backup "$WEIRD_TARGET" >/dev/null )
weird_exit=$?
set -e

if [ "$weird_exit" -eq 0 ]; then
  pass "create_backup exits 0 with a manifest containing a './...' target"
else
  fail "create_backup exited $weird_exit with a manifest containing a './...' target"
fi

if [ -d "$WEIRD_TARGET/backups" ]; then
  nested_count=$(find "$WEIRD_TARGET/backups" -mindepth 1 -type d -name backups 2>/dev/null | wc -l | tr -d ' ')
else
  nested_count=0
fi

if [ "$nested_count" -eq 0 ]; then
  pass "No nested backups/ directory created inside the backup"
else
  fail "Found $nested_count nested backups/ directory(ies) -- the original crash signature"
fi
echo ""

# --- Test 19: no-jq fallback is scoped to the "files" object only ---
# Regression test for the Stage 2 MEDIUM finding: the grep-based fallback
# must not pick up a "target" key that lives outside files (e.g. a future
# configPrompts entry), unlike a bare `grep -o '"target"...'` over the
# whole manifest. _backup_files_block is what scopes it.
echo "--- Test 19: _backup_files_block excludes a decoy target outside files ---"

SCOPE_FIXTURE="$TMPDIR/scope-fixture.module.json"
cat > "$SCOPE_FIXTURE" <<'JSON'
{
  "name": "scopetest",
  "files": {
    "a": { "target": "real/path.md", "type": "doc" }
  },
  "configPrompts": [
    { "key": "x", "prompt": "p", "target": "unrelated-decoy" }
  ]
}
JSON

scope_targets=$(_backup_files_block "$SCOPE_FIXTURE" | grep -o '"target"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/^"target"[[:space:]]*:[[:space:]]*"//; s/"$//')

if echo "$scope_targets" | grep -qx 'real/path.md'; then
  pass "_backup_files_block includes the real files[].target"
else
  fail "_backup_files_block missed the real files[].target"
fi

if ! echo "$scope_targets" | grep -qx 'unrelated-decoy'; then
  pass "_backup_files_block excludes a decoy 'target' key outside files"
else
  fail "_backup_files_block leaked a decoy 'target' key outside files"
fi
echo ""

# --- Test 20: managed_backup_paths dedupes shared top-level segments ---
# Mutation-check regression for the Stage 2 LOW finding: changing
# `sort -u` to plain `sort` in managed_backup_paths must fail this test.
echo "--- Test 20: managed_backup_paths dedupes shared top-level segments ---"

DEDUPE_ROOT="$TMPDIR/dedupe-root"
mkdir -p "$DEDUPE_ROOT/modules/mod-a" "$DEDUPE_ROOT/modules/mod-b"
cat > "$DEDUPE_ROOT/modules/mod-a/module.json" <<'JSON'
{
  "name": "mod-a",
  "files": {
    "a": { "target": "skills/mod-a/one.md", "type": "doc" }
  }
}
JSON
cat > "$DEDUPE_ROOT/modules/mod-b/module.json" <<'JSON'
{
  "name": "mod-b",
  "files": {
    "a": { "target": "skills/mod-b/two.md", "type": "doc" }
  }
}
JSON

dedupe_output=$(CCGM_ROOT="$DEDUPE_ROOT" managed_backup_paths 2>/dev/null)
skills_count=$(echo "$dedupe_output" | grep -cx 'skills')

if [ "$skills_count" -eq 1 ]; then
  pass "managed_backup_paths lists 'skills' exactly once across two modules"
else
  fail "managed_backup_paths listed 'skills' $skills_count times, expected exactly 1"
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
