#!/usr/bin/env bash
# test-command-skill-parity.sh
# Parity tests for Epic 0.2: reconcile /audit command stub with SKILL.md.
#
# Tests:
#   1. Command doc contains no severity term outside {critical, high, medium, low}
#   2. Every flag named in the command doc exists in SKILL.md's mode-detection list
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-command-skill-parity.sh
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
# Resolve file paths (support running from repo root or test directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

COMMAND_DOC="$SCRIPT_DIR/../../../commands/audit.md"
SKILL_DOC="$SCRIPT_DIR/../SKILL.md"

# Fallback to repo-root-relative paths
if [ ! -f "$COMMAND_DOC" ]; then
  COMMAND_DOC="modules/commands-extra/commands/audit.md"
fi
if [ ! -f "$SKILL_DOC" ]; then
  SKILL_DOC="modules/commands-extra/skills/audit/SKILL.md"
fi

if [ ! -f "$COMMAND_DOC" ]; then
  echo "ERROR: command doc not found — expected at: $COMMAND_DOC" >&2
  exit 1
fi
if [ ! -f "$SKILL_DOC" ]; then
  echo "ERROR: SKILL.md not found — expected at: $SKILL_DOC" >&2
  exit 1
fi

echo ""
echo "=== /audit command-skill parity tests ==="
echo "  Command doc: $COMMAND_DOC"
echo "  Skill doc:   $SKILL_DOC"
echo ""

# ---------------------------------------------------------------------------
# TEST 1: Command doc contains no severity term outside {critical, high, medium, low}
# ---------------------------------------------------------------------------
echo "--- [1] Severity vocabulary in command doc ---"

# Allowed severity words (case-insensitive). Words that are NOT in this list are stray.
# The old doc used: CRITICAL, WARNING, INFO — WARNING and INFO are the phantoms.
STRAY_SEVERITIES=()

# Check for stray severity terms that should NOT appear as severity labels.
# The old command doc used uppercase labels: CRITICAL, WARNING, INFO.
# We look for these uppercase forms as standalone words (not lowercased "warning" in prose).
# We explicitly exclude: "critical" in lowercase (allowed as a severity word), and
# common prose uses of the word (e.g. "error handling", "warning message").
for term in CRITICAL WARNING WARN INFO ERROR; do
  # Match the exact uppercase form as a whole word, without -i (case-sensitive).
  set +e
  HITS=$(grep -n "\b${term}\b" "$COMMAND_DOC" 2>/dev/null || true)
  set -e
  if [ -n "$HITS" ]; then
    STRAY_SEVERITIES+=("$term")
    echo "    stray term '$term' (uppercase severity label) found:"
    while IFS= read -r line; do
      echo "      $line"
    done <<< "$HITS"
  fi
done

if [ ${#STRAY_SEVERITIES[@]} -eq 0 ]; then
  pass "command doc contains no stray severity terms (CRITICAL/WARNING/WARN/INFO/ERROR not present)"
else
  fail "command doc contains stray severity terms outside {critical,high,medium,low}" \
    "found: ${STRAY_SEVERITIES[*]}"
fi

# Also confirm the allowed severities ARE present (at least critical and high must appear)
set +e
HAS_CRITICAL=$(grep -ic '\bcritical\b' "$COMMAND_DOC" 2>/dev/null || true)
HAS_HIGH=$(grep -ic '\bhigh\b' "$COMMAND_DOC" 2>/dev/null || true)
HAS_MEDIUM=$(grep -ic '\bmedium\b' "$COMMAND_DOC" 2>/dev/null || true)
HAS_LOW=$(grep -ic '\blow\b' "$COMMAND_DOC" 2>/dev/null || true)
set -e

if [ "${HAS_CRITICAL:-0}" -gt 0 ] && [ "${HAS_HIGH:-0}" -gt 0 ] && \
   [ "${HAS_MEDIUM:-0}" -gt 0 ] && [ "${HAS_LOW:-0}" -gt 0 ]; then
  pass "command doc mentions all four canonical severities (critical, high, medium, low)"
else
  fail "command doc must mention all four canonical severities" \
    "critical=${HAS_CRITICAL:-0} high=${HAS_HIGH:-0} medium=${HAS_MEDIUM:-0} low=${HAS_LOW:-0}"
fi

# ---------------------------------------------------------------------------
# TEST 2: Every flag in the command doc exists in SKILL.md's mode-detection list
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] Flags in command doc are present in SKILL.md mode-detection ---"

# Extract flags from the command doc's code block(s): lines starting with /audit --flag
# We collect distinct --<word> tokens from lines that match "/audit --".
set +e
CMD_FLAGS=$(grep '/audit --' "$COMMAND_DOC" \
  | grep -oE '\-\-[a-z-]+' \
  | sort -u || true)
set -e

if [ -z "$CMD_FLAGS" ]; then
  fail "command doc has no flag lines matching '/audit --' — cannot verify flags" ""
else
  pass "command doc contains flag lines to check"
fi

# For each flag found in the command doc, verify it appears somewhere in SKILL.md.
# SKILL.md's mode-detection section lists flags in the form:
#   `--single` -> ...
#   `--collect` -> ...
# but we do a broader search so minor formatting changes don't break the test.
while IFS= read -r flag; do
  [ -z "$flag" ] && continue
  set +e
  IN_SKILL=$(grep -c -- "$flag" "$SKILL_DOC" 2>/dev/null || true)
  set -e
  if [ "${IN_SKILL:-0}" -gt 0 ]; then
    pass "flag '$flag' from command doc exists in SKILL.md"
  else
    fail "flag '$flag' found in command doc but NOT in SKILL.md's mode-detection" \
      "check that '$flag' is a real skill flag or remove it from the command doc"
  fi
done <<< "$CMD_FLAGS"

# Confirm phantom flags are gone
echo ""
echo "--- [2b] Phantom flags no longer present in command doc ---"

for phantom in "--no-issues" "--no-fix"; do
  set +e
  IN_CMD=$(grep -c -- "$phantom" "$COMMAND_DOC" 2>/dev/null || true)
  set -e
  if [ "${IN_CMD:-0}" -gt 0 ]; then
    fail "phantom flag '$phantom' is still present in command doc — remove it" ""
  else
    pass "phantom flag '$phantom' is absent from command doc"
  fi
done

# Also check that the "/audit security" category-filter claim is gone
set +e
CATEGORY_FILTER=$(grep -c '/audit security' "$COMMAND_DOC" 2>/dev/null || true)
set -e
if [ "${CATEGORY_FILTER:-0}" -gt 0 ]; then
  fail "command doc still contains '/audit security' category-filter claim — the skill treats the arg as a PATH, not a category filter" ""
else
  pass "command doc does not claim '/audit security' (category-filter removed)"
fi


# ---------------------------------------------------------------------------
# TEST 2c: Every flag in SKILL.md mode-detection also exists in command doc (SKILL->CMD)
# ---------------------------------------------------------------------------
echo ""
echo "--- [2c] Flags in SKILL.md mode-detection are documented in command doc ---"

# Extract flags from SKILL.md's mode-detection / argument-parsing section.
# The mode-detection section lists flags as backtick-quoted items: `--single` -> ...
# Scope the extraction to the block between "Mode Detection" and "If NO flags are passed"
# to avoid picking up unrelated git flags from later sections.
set +e
SKILL_FLAGS=$(awk '/^### Mode Detection/,/^\*\*If NO flags are passed/' "$SKILL_DOC"   | grep -oE '[-][-][a-z-]+'   | sort -u || true)
set -e

if [ -z "$SKILL_FLAGS" ]; then
  fail "could not extract flags from SKILL.md mode-detection section — check extraction pattern" ""
else
  pass "SKILL.md mode-detection section contains flags to check"
fi

while IFS= read -r flag; do
  [ -z "$flag" ] && continue
  set +e
  IN_CMD=$(grep -c -- "$flag" "$COMMAND_DOC" 2>/dev/null || true)
  set -e
  if [ "${IN_CMD:-0}" -gt 0 ]; then
    pass "flag '$flag' from SKILL.md mode-detection is documented in command doc"
  else
    fail "flag '$flag' found in SKILL.md mode-detection but NOT documented in command doc" \
      "add '$flag' to the command doc's Usage section or remove it from SKILL.md"
  fi
done <<< "$SKILL_FLAGS"

# ---------------------------------------------------------------------------
# TEST 3: No phantom model note in command doc
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] No phantom model note in command doc ---"

set +e
MODEL_NOTE=$(grep -ic 'model.*sonnet\|sonnet.*model\|set model to' "$COMMAND_DOC" 2>/dev/null || true)
set -e
if [ "${MODEL_NOTE:-0}" -gt 0 ]; then
  fail "command doc still contains the phantom 'model:sonnet' note — SKILL.md does not specify a model for subagents" ""
else
  pass "command doc has no phantom model specification"
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
