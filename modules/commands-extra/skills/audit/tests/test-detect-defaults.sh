#!/usr/bin/env bash
# test-detect-defaults.sh
# Unit tests for Epic 0.1: genericized stack/branch/clone detection in /audit skill
#
# Tests:
#   1. Base-branch detector returns "main" on a main-only repo fixture
#   2. Package manager detection returns correct manager for each lockfile type
#   3. Fix-mode conflict path halts+reports (no silent --ours)
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-detect-defaults.sh
# Exit: 0 = all pass, non-zero = failure

set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

pass() {
  local name="$1"
  echo "  PASS: $name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  local name="$1"
  local detail="${2:-}"
  echo "  FAIL: $name${detail:+ — $detail}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("$name${detail:+: $detail}")
}

# ---------------------------------------------------------------------------
# Helper: portable base-branch detector (mirrors SKILL.md logic)
# ---------------------------------------------------------------------------
detect_base_branch() {
  local repo_dir="$1"
  local branch
  branch=$(git -C "$repo_dir" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's|refs/remotes/origin/||' \
    || true)
  if [ -z "$branch" ]; then
    branch="main"
  fi
  echo "$branch"
}

# ---------------------------------------------------------------------------
# Helper: package manager detector (mirrors SKILL.md logic)
# ---------------------------------------------------------------------------
detect_pkg_manager() {
  local repo_dir="$1"
  if [ -f "$repo_dir/bun.lockb" ]; then
    echo "bun"
  elif [ -f "$repo_dir/pnpm-lock.yaml" ]; then
    echo "pnpm"
  elif [ -f "$repo_dir/yarn.lock" ]; then
    echo "yarn"
  elif [ -f "$repo_dir/package-lock.json" ]; then
    echo "npm"
  else
    echo "npm"
  fi
}

# ---------------------------------------------------------------------------
# Fixture setup
# ---------------------------------------------------------------------------
TMPDIR_ROOT=$(mktemp -d)
trap 'rm -rf "$TMPDIR_ROOT"' EXIT

echo ""
echo "=== /audit detect-defaults unit tests ==="
echo ""

# ---------------------------------------------------------------------------
# TEST 1: Base-branch detector returns "main" on main-only remote
# ---------------------------------------------------------------------------
echo "--- [1] Base-branch detection ---"

FIXTURE_REPO="$TMPDIR_ROOT/fixture-repo"
FIXTURE_REMOTE="$TMPDIR_ROOT/fixture-remote"

# Create a bare "remote" with only a main branch
mkdir -p "$FIXTURE_REMOTE"
git init --bare --quiet "$FIXTURE_REMOTE"

# Create a local clone of the bare remote
git clone --quiet "$FIXTURE_REMOTE" "$FIXTURE_REPO" 2>/dev/null || true
cd "$FIXTURE_REPO"
git checkout --quiet -b main 2>/dev/null || git checkout --quiet main 2>/dev/null || true
# Create an initial commit so the branch exists on remote
git commit --allow-empty --quiet -m "init"
git push --quiet origin main 2>/dev/null || true
git remote set-head origin --auto 2>/dev/null || true
cd - > /dev/null

DETECTED_BRANCH=$(detect_base_branch "$FIXTURE_REPO")
if [ "$DETECTED_BRANCH" = "main" ]; then
  pass "base-branch detector returns 'main' for main-only remote"
else
  fail "base-branch detector returns 'main' for main-only remote" "got: '$DETECTED_BRANCH'"
fi

# Test fallback when no remote HEAD is set (e.g., unborn remote)
FIXTURE_ORPHAN="$TMPDIR_ROOT/fixture-orphan"
git init --quiet "$FIXTURE_ORPHAN"
DETECTED_FALLBACK=$(detect_base_branch "$FIXTURE_ORPHAN")
if [ "$DETECTED_FALLBACK" = "main" ]; then
  pass "base-branch detector falls back to 'main' when no remote HEAD"
else
  fail "base-branch detector falls back to 'main' when no remote HEAD" "got: '$DETECTED_FALLBACK'"
fi

# ---------------------------------------------------------------------------
# TEST 2: Package manager detection for each lockfile type
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] Package manager detection ---"

for pm in bun pnpm yarn npm; do
  FIXTURE_PM="$TMPDIR_ROOT/fixture-pm-$pm"
  mkdir -p "$FIXTURE_PM"
  case "$pm" in
    bun)  touch "$FIXTURE_PM/bun.lockb" ;;
    pnpm) touch "$FIXTURE_PM/pnpm-lock.yaml" ;;
    yarn) touch "$FIXTURE_PM/yarn.lock" ;;
    npm)  touch "$FIXTURE_PM/package-lock.json" ;;
  esac
  DETECTED_PM=$(detect_pkg_manager "$FIXTURE_PM")
  case "$pm" in
    bun)  lockfile="bun.lockb" ;;
    pnpm) lockfile="pnpm-lock.yaml" ;;
    yarn) lockfile="yarn.lock" ;;
    npm)  lockfile="package-lock.json" ;;
  esac
  if [ "$DETECTED_PM" = "$pm" ]; then
    pass "detects '$pm' when $lockfile present"
  else
    fail "detects '$pm' from lockfile ($lockfile)" "got: '$DETECTED_PM'"
  fi
done

# No lockfile → falls back to npm
FIXTURE_NO_PM="$TMPDIR_ROOT/fixture-no-pm"
mkdir -p "$FIXTURE_NO_PM"
DETECTED_NO_PM=$(detect_pkg_manager "$FIXTURE_NO_PM")
if [ "$DETECTED_NO_PM" = "npm" ]; then
  pass "falls back to 'npm' when no lockfile present"
else
  fail "falls back to 'npm' when no lockfile present" "got: '$DETECTED_NO_PM'"
fi

# Priority: bun wins over npm if both present (bun.lockb checked first)
FIXTURE_BUN_AND_NPM="$TMPDIR_ROOT/fixture-bun-npm"
mkdir -p "$FIXTURE_BUN_AND_NPM"
touch "$FIXTURE_BUN_AND_NPM/bun.lockb" "$FIXTURE_BUN_AND_NPM/package-lock.json"
DETECTED_PRIORITY=$(detect_pkg_manager "$FIXTURE_BUN_AND_NPM")
if [ "$DETECTED_PRIORITY" = "bun" ]; then
  pass "bun takes priority over npm when both lockfiles present"
else
  fail "bun takes priority over npm when both lockfiles present" "got: '$DETECTED_PRIORITY'"
fi

# ---------------------------------------------------------------------------
# TEST 3: Fix-mode conflict path halts and reports, no --ours
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] Fix-mode merge conflict: halt-and-report ---"

# Verify the SKILL.md does NOT contain 'git checkout --ours' (the old silent resolution)
SKILL_FILE="$(dirname "$0")/../SKILL.md"
if [ ! -f "$SKILL_FILE" ]; then
  # Try a path relative to the repo root (for running from repo root)
  SKILL_FILE="modules/commands-extra/skills/audit/SKILL.md"
fi

if [ -f "$SKILL_FILE" ]; then
  # --ours must not appear as an instruction (no "NEVER" prohibition needed in SKILL.md —
  # the old instruction was removed entirely; the new code uses git merge --abort)
  if grep -q 'git checkout --ours' "$SKILL_FILE"; then
    fail "SKILL.md must not contain 'git checkout --ours' (removed; replaced with halt-and-report)" \
      "found in $SKILL_FILE"
  else
    pass "SKILL.md does not contain 'git checkout --ours'"
  fi

  # Verify the halt-and-report keyword is present
  if grep -q 'merge-conflicts.md' "$SKILL_FILE"; then
    pass "SKILL.md references merge-conflicts.md (conflict report path)"
  else
    fail "SKILL.md must reference merge-conflicts.md as the conflict report path"
  fi

  if grep -q 'git merge --abort' "$SKILL_FILE"; then
    pass "SKILL.md contains 'git merge --abort' (conflict abort step)"
  else
    fail "SKILL.md must contain 'git merge --abort' in conflict handling"
  fi
else
  fail "SKILL.md not found — run test from repo root or skill directory" "tried: $SKILL_FILE"
fi

# Verify multi-agent-config.md also documents the halt-and-report behavior
CONFIG_FILE="$(dirname "$0")/../reference/multi-agent-config.md"
if [ ! -f "$CONFIG_FILE" ]; then
  CONFIG_FILE="modules/commands-extra/skills/audit/reference/multi-agent-config.md"
fi

if [ -f "$CONFIG_FILE" ]; then
  # Check that --ours only appears in a prohibition context, not as an instruction
  # A line that uses --ours without "NEVER" before it on the same line is the old behaviour
  if grep 'git checkout --ours' "$CONFIG_FILE" | grep -qv 'NEVER'; then
    fail "multi-agent-config.md must not instruct 'git checkout --ours' (use NEVER... to prohibit it)" \
      "found in $CONFIG_FILE"
  else
    pass "multi-agent-config.md does not instruct 'git checkout --ours' (prohibition wording is correct)"
  fi

  if grep -q 'HALT\|halt' "$CONFIG_FILE"; then
    pass "multi-agent-config.md documents halt behavior on conflict"
  else
    fail "multi-agent-config.md must document halt behavior on conflict"
  fi
else
  fail "multi-agent-config.md not found" "tried: $CONFIG_FILE"
fi

# Verify fix-patterns.md is consistent (no --ours reference)
FIX_FILE="$(dirname "$0")/../reference/fix-patterns.md"
if [ ! -f "$FIX_FILE" ]; then
  FIX_FILE="modules/commands-extra/skills/audit/reference/fix-patterns.md"
fi

if [ -f "$FIX_FILE" ]; then
  if grep -q 'git checkout --ours' "$FIX_FILE"; then
    fail "fix-patterns.md must not contain 'git checkout --ours'" \
      "found in $FIX_FILE"
  else
    pass "fix-patterns.md does not contain 'git checkout --ours'"
  fi
else
  fail "fix-patterns.md not found" "tried: $FIX_FILE"
fi

# ---------------------------------------------------------------------------
# TEST 4: Verify no grep -oP usage remains (GNU-only, not portable to macOS BSD grep)
# ---------------------------------------------------------------------------
echo ""
echo "--- [4] Portable grep: no grep -oP ---"

AUDIT_SKILL_DIR="$(dirname "$0")/.."
# Fall back to module path for running from repo root
if [ ! -f "$AUDIT_SKILL_DIR/SKILL.md" ]; then
  AUDIT_SKILL_DIR="modules/commands-extra/skills/audit"
fi

if [ -d "$AUDIT_SKILL_DIR" ]; then
  set +e
  # Exclude this test file itself — it contains the string in comments/checks
  GNU_GREP_HITS=$(grep -rn 'grep -oP' "$AUDIT_SKILL_DIR" 2>/dev/null \
    | grep -v 'test-detect-defaults.sh' || true)
  set -e
  if [ -z "$GNU_GREP_HITS" ]; then
    pass "no 'grep -oP' (GNU-only) found in audit skill source files"
  else
    fail "found 'grep -oP' (GNU-only) in audit skill — replace with sed -E or awk" \
      "$GNU_GREP_HITS"
  fi
else
  fail "audit skill directory not found" "tried: $AUDIT_SKILL_DIR"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="
if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo "Failures:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  echo ""
  exit 1
fi
echo ""
exit 0
