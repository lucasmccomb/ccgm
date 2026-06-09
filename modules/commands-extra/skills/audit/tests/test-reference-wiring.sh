#!/usr/bin/env bash
# test-reference-wiring.sh
# Tests for Epic 0.3: reference doc wiring, 9-category coordination doc, contradiction fixes.
#
# Tests:
#   1. multi-agent-config.md assignment table includes ToS & Compliance and lists 9 categories
#   2. Every category prompt in SKILL.md contains a READ AND APPLY instruction
#   2b. Per-section: each ### Agent N section individually contains READ AND APPLY
#   3. Agent 7 (Documentation) marks JSDoc as NOT auto-fixable (aligns with fix-patterns.md)
#   4. Agent 5 (TypeScript/React) does not recommend array index as key (key-prop fix)
#   5. output-template.md does not contain hardcoded 'development' branch (genericized)
#   6. security-patterns.md still contains NODE_ENV=development (legitimate detection pattern)
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-reference-wiring.sh
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
  echo "  FAIL: $name${detail:+ -- $detail}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("$name${detail:+: $detail}")
}

# ---------------------------------------------------------------------------
# Resolve file paths (support running from repo root or test directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

SKILL_DOC="$SCRIPT_DIR/../SKILL.md"
MULTI_AGENT_DOC="$SCRIPT_DIR/../reference/multi-agent-config.md"
FIX_PATTERNS_DOC="$SCRIPT_DIR/../reference/fix-patterns.md"
OUTPUT_TEMPLATE_DOC="$SCRIPT_DIR/../reference/output-template.md"
SECURITY_PATTERNS_DOC="$SCRIPT_DIR/../reference/security-patterns.md"

# Fallback to repo-root-relative paths
for var in SKILL_DOC MULTI_AGENT_DOC FIX_PATTERNS_DOC OUTPUT_TEMPLATE_DOC SECURITY_PATTERNS_DOC; do
  file_var="${!var}"
  if [ ! -f "$file_var" ]; then
    case "$var" in
      SKILL_DOC)            eval "$var=modules/commands-extra/skills/audit/SKILL.md" ;;
      MULTI_AGENT_DOC)      eval "$var=modules/commands-extra/skills/audit/reference/multi-agent-config.md" ;;
      FIX_PATTERNS_DOC)     eval "$var=modules/commands-extra/skills/audit/reference/fix-patterns.md" ;;
      OUTPUT_TEMPLATE_DOC)  eval "$var=modules/commands-extra/skills/audit/reference/output-template.md" ;;
      SECURITY_PATTERNS_DOC) eval "$var=modules/commands-extra/skills/audit/reference/security-patterns.md" ;;
    esac
  fi
done

for var in SKILL_DOC MULTI_AGENT_DOC FIX_PATTERNS_DOC OUTPUT_TEMPLATE_DOC SECURITY_PATTERNS_DOC; do
  file_var="${!var}"
  if [ ! -f "$file_var" ]; then
    echo "ERROR: required file not found: $file_var" >&2
    exit 1
  fi
done

echo ""
echo "=== /audit reference wiring tests (Epic 0.3) ==="
echo "  SKILL.md:           $SKILL_DOC"
echo "  multi-agent-config: $MULTI_AGENT_DOC"
echo "  fix-patterns:       $FIX_PATTERNS_DOC"
echo "  output-template:    $OUTPUT_TEMPLATE_DOC"
echo "  security-patterns:  $SECURITY_PATTERNS_DOC"
echo ""

# ---------------------------------------------------------------------------
# TEST 1: multi-agent-config.md includes ToS & Compliance and lists 9 categories
# ---------------------------------------------------------------------------
echo "--- [1] multi-agent-config.md: 9 categories with ToS & Compliance ---"

set +e
TOS_IN_TABLE=$(grep -c 'ToS & Compliance\|Terms of Service' "$MULTI_AGENT_DOC" 2>/dev/null || true)
set -e

if [ "${TOS_IN_TABLE:-0}" -gt 0 ]; then
  pass "multi-agent-config.md references ToS & Compliance category"
else
  fail "multi-agent-config.md must include ToS & Compliance in the agent assignments" \
    "did not find 'ToS & Compliance' or 'Terms of Service' in $MULTI_AGENT_DOC"
fi

# Count distinct categories listed in the Agent Assignments table.
# The nine canonical categories (case-insensitive):
EXPECTED_CATEGORIES=(
  "Security"
  "Dependencies"
  "ToS"
  "Code Quality"
  "TypeScript"
  "Architecture"
  "Performance"
  "Testing"
  "Documentation"
)
MISSING_CATEGORIES=()
for cat in "${EXPECTED_CATEGORIES[@]}"; do
  set +e
  FOUND=$(grep -ic "$cat" "$MULTI_AGENT_DOC" 2>/dev/null || true)
  set -e
  if [ "${FOUND:-0}" -eq 0 ]; then
    MISSING_CATEGORIES+=("$cat")
  fi
done

if [ "${#MISSING_CATEGORIES[@]}" -eq 0 ]; then
  pass "multi-agent-config.md mentions all 9 audit categories"
else
  fail "multi-agent-config.md is missing categories" \
    "missing: ${MISSING_CATEGORIES[*]}"
fi

# Verify "9 categories" or an equivalent count statement is present
set +e
NINE_CATS=$(grep -c '9 \(audit \)\?categor\|nine categor' "$MULTI_AGENT_DOC" 2>/dev/null || true)
set -e
if [ "${NINE_CATS:-0}" -gt 0 ]; then
  pass "multi-agent-config.md explicitly states 9 categories"
else
  fail "multi-agent-config.md should state the total category count (9)" \
    "add a sentence like '9 audit categories are distributed across 4 agents'"
fi

# ---------------------------------------------------------------------------
# TEST 2: Every category prompt in SKILL.md contains a READ AND APPLY instruction
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] SKILL.md: every category prompt wires its reference doc ---"

# The 9 agent headers we expect in the Category Prompts section
AGENT_HEADERS=(
  "Agent 1: Security Audit"
  "Agent 2: Dependencies Audit"
  "Agent 3: Code Quality Audit"
  "Agent 4: Architecture Audit"
  "Agent 5: TypeScript/React Audit"
  "Agent 6: Testing Audit"
  "Agent 7: Documentation Audit"
  "Agent 8: Performance Audit"
  "Agent 9: Terms of Service"
)

# Global count check: "READ AND APPLY" must appear at least once per agent.
set +e
READ_APPLY_COUNT=$(grep -c 'READ AND APPLY' "$SKILL_DOC" 2>/dev/null || true)
set -e

if [ "${READ_APPLY_COUNT:-0}" -ge "${#AGENT_HEADERS[@]}" ]; then
  pass "SKILL.md contains READ AND APPLY instructions for all ${#AGENT_HEADERS[@]} agent prompts (found ${READ_APPLY_COUNT})"
else
  fail "SKILL.md needs READ AND APPLY instructions for all ${#AGENT_HEADERS[@]} agent prompts" \
    "found only ${READ_APPLY_COUNT:-0} occurrences"
fi

# Verify each specific agent header is present (guards against stray header renames)
for header in "${AGENT_HEADERS[@]}"; do
  set +e
  FOUND=$(grep -c "$header" "$SKILL_DOC" 2>/dev/null || true)
  set -e
  if [ "${FOUND:-0}" -gt 0 ]; then
    pass "SKILL.md contains agent header: '$header'"
  else
    fail "SKILL.md is missing agent header: '$header'" \
      "ensure the Category Prompts section contains this header"
  fi
done

# ---------------------------------------------------------------------------
# TEST 2b: Per-section READ AND APPLY verification
# For EACH ### Agent N section, assert that a READ AND APPLY line appears
# between that header and the next ### Agent header (or end of file).
# This catches the case where occurrences cluster under one agent while
# another agent's section has none.
# ---------------------------------------------------------------------------
echo ""
echo "--- [2b] SKILL.md: per-section READ AND APPLY verification ---"

for header in "${AGENT_HEADERS[@]}"; do
  # Use awk to extract lines from this agent's header up to (not including)
  # the next "### Agent" header.
  set +e
  SECTION_CONTENT=$(awk \
    -v hdr="### $header" \
    'BEGIN{found=0}
     $0 ~ hdr {found=1; next}
     found && /^### Agent / {exit}
     found {print}
    ' "$SKILL_DOC" 2>/dev/null || true)
  set -e

  if [ -z "$SECTION_CONTENT" ]; then
    fail "per-section: could not extract section for '$header'" \
      "header may be missing or malformed in SKILL.md"
  else
    set +e
    SECTION_READ_APPLY=$(echo "$SECTION_CONTENT" | grep -c 'READ AND APPLY' 2>/dev/null || true)
    set -e
    if [ "${SECTION_READ_APPLY:-0}" -gt 0 ]; then
      pass "per-section: '$header' contains READ AND APPLY"
    else
      fail "per-section: '$header' is missing a READ AND APPLY instruction" \
        "add 'READ AND APPLY: ~/.claude/skills/audit/reference/<doc>.md' inside this agent's prompt block"
    fi
  fi
done

# ---------------------------------------------------------------------------
# TEST 3: Agent 7 (Documentation) marks JSDoc as NOT auto-fixable
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] SKILL.md Agent 7: JSDoc is NOT auto-fixable (aligns with fix-patterns.md) ---"

# Extract the Agent 7 section and verify it does NOT recommend auto-fixing JSDoc
set +e
AGENT7_BLOCK=$(awk '/### Agent 7: Documentation Audit/,/### Agent [89]/' "$SKILL_DOC" 2>/dev/null || true)
set -e

if [ -z "$AGENT7_BLOCK" ]; then
  fail "could not extract Agent 7 block from SKILL.md" \
    "check that '### Agent 7: Documentation Audit' header exists"
else
  # Check that the block does NOT claim JSDoc is auto-fixable.
  # The old anti-pattern was: "Missing JSDoc on exports (auto-fixable: generate from types)"
  # We look for the specific positive auto-fixable claim, not for "NOT auto-fixable" mentions.
  set +e
  JSDOC_AUTOFIXABLE=$(echo "$AGENT7_BLOCK" \
    | grep -i 'jsdoc' \
    | grep -iv 'NOT auto-fixable\|not.*auto.fix\|requires human' \
    | grep -ic 'auto-fixable\|auto.fix' 2>/dev/null || true)
  set -e

  if [ "${JSDOC_AUTOFIXABLE:-0}" -gt 0 ]; then
    fail "Agent 7 prompt marks JSDoc as auto-fixable — contradicts fix-patterns.md (documentation = No)" \
      "change to NOT auto-fixable with a note that it requires human authorship"
  else
    pass "Agent 7 prompt does not mark JSDoc as auto-fixable"
  fi

  # Check that it does positively say NOT auto-fixable
  set +e
  JSDOC_NOT_FIXABLE=$(echo "$AGENT7_BLOCK" | grep -ic 'JSDoc.*NOT auto-fixable\|NOT auto-fixable.*JSDoc\|JSDoc.*requires human' 2>/dev/null || true)
  set -e
  if [ "${JSDOC_NOT_FIXABLE:-0}" -gt 0 ]; then
    pass "Agent 7 prompt explicitly marks JSDoc as NOT auto-fixable"
  else
    fail "Agent 7 prompt should explicitly state JSDoc is NOT auto-fixable" \
      "add 'NOT auto-fixable' or 'requires human-authored documentation'"
  fi
fi

# Also confirm fix-patterns.md itself says documentation is not auto-fixable (reference check)
set +e
# shellcheck disable=SC2016  # literal backtick in pattern is intentional, not a variable
FIX_TABLE_DOC=$(grep -A1 '| `documentation`' "$FIX_PATTERNS_DOC" 2>/dev/null | head -2 || true)
set -e
if echo "$FIX_TABLE_DOC" | grep -q 'No\|no'; then
  pass "fix-patterns.md Fix Type Reference confirms documentation is not auto-fixable (No)"
else
  fail "fix-patterns.md Fix Type Reference should list documentation as 'No' for auto-fixable" \
    "check the fix_type table row for 'documentation'"
fi

# ---------------------------------------------------------------------------
# TEST 4: Agent 5 does NOT recommend array index as key prop
# ---------------------------------------------------------------------------
echo ""
echo "--- [4] SKILL.md Agent 5: no array-index-as-key recommendation ---"

set +e
AGENT5_BLOCK=$(awk '/### Agent 5: TypeScript\/React Audit/,/### Agent [6789]/' "$SKILL_DOC" 2>/dev/null || true)
set -e

if [ -z "$AGENT5_BLOCK" ]; then
  fail "could not extract Agent 5 block from SKILL.md" \
    "check that '### Agent 5: TypeScript/React Audit' header exists"
else
  # The old wording: "auto-fixable: add index as key"
  set +e
  INDEX_AS_KEY=$(echo "$AGENT5_BLOCK" | grep -ic 'add index as key\|index.*as.*key.*auto' 2>/dev/null || true)
  set -e
  if [ "${INDEX_AS_KEY:-0}" -gt 0 ]; then
    fail "Agent 5 prompt recommends using array index as key — this is an anti-pattern" \
      "keys should be stable unique IDs; remove 'add index as key' auto-fix recommendation"
  else
    pass "Agent 5 prompt does not recommend array index as React key"
  fi

  # Confirm missing key props are flagged as NOT auto-fixable
  set +e
  KEY_NOT_FIXABLE=$(echo "$AGENT5_BLOCK" | grep -ic 'key.*NOT auto-fixable\|NOT auto-fixable.*key\|key.*flag for.*review' 2>/dev/null || true)
  set -e
  if [ "${KEY_NOT_FIXABLE:-0}" -gt 0 ]; then
    pass "Agent 5 prompt marks missing key props as NOT auto-fixable (requires human review)"
  else
    fail "Agent 5 prompt should mark missing key props as NOT auto-fixable" \
      "add NOT auto-fixable with a note about stable unique IDs"
  fi
fi

# ---------------------------------------------------------------------------
# TEST 5: output-template.md has no hardcoded 'development' branch
# ---------------------------------------------------------------------------
echo ""
echo "--- [5] output-template.md: no hardcoded 'development' branch ---"

# 'development' is only legitimate in security-patterns.md (NODE_ENV=development).
# In output-template.md it should be gone; all occurrences should now use {base_branch}
# or similar placeholder.
set +e
DEV_IN_TEMPLATE=$(grep -n '\bdevelopment\b' "$OUTPUT_TEMPLATE_DOC" 2>/dev/null || true)
set -e

if [ -z "$DEV_IN_TEMPLATE" ]; then
  pass "output-template.md contains no hardcoded 'development' branch references"
else
  fail "output-template.md still contains 'development'" \
    "replace with {base_branch} or detected base branch placeholder"$'\n'"  $DEV_IN_TEMPLATE"
fi

# Confirm {base_branch} placeholder exists (the replacement value)
set +e
BASE_BRANCH_PLACEHOLDER=$(grep -c '{base_branch}' "$OUTPUT_TEMPLATE_DOC" 2>/dev/null || true)
set -e
if [ "${BASE_BRANCH_PLACEHOLDER:-0}" -gt 0 ]; then
  pass "output-template.md uses {base_branch} placeholder (${BASE_BRANCH_PLACEHOLDER} occurrences)"
else
  fail "output-template.md should use {base_branch} placeholder where 'development' was removed"
fi

# ---------------------------------------------------------------------------
# TEST 6: security-patterns.md still contains NODE_ENV=development (legitimate)
# ---------------------------------------------------------------------------
echo ""
echo "--- [6] security-patterns.md: NODE_ENV=development pattern is preserved ---"

set +e
NODE_ENV_DEV=$(grep -c 'NODE_ENV=development' "$SECURITY_PATTERNS_DOC" 2>/dev/null || true)
set -e
if [ "${NODE_ENV_DEV:-0}" -gt 0 ]; then
  pass "security-patterns.md preserves NODE_ENV=development detection pattern (legitimate)"
else
  fail "security-patterns.md should still contain NODE_ENV=development as an insecure config pattern to detect" \
    "do not remove legitimate detection patterns from security-patterns.md"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Results: $PASS_COUNT passed, $FAIL_COUNT failed ==="
if [ "${#FAILURES[@]}" -gt 0 ]; then
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
