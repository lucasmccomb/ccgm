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
