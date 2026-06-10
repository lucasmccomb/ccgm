#!/usr/bin/env bash
# test-reference-wiring.sh
# Tests that reference docs are genuinely wired into the pack registry (no orphan reference docs,
# no orphan pack pointers), and that key policy statements live inside the pack checks.md files.
#
# Tests:
#   1. multi-agent-config.md assignment table includes ToS & Compliance and lists 9 categories
#   2. Each of the 9 pack checks.md files contains >=1 READ AND APPLY referencing an existing
#      reference doc (per-pack expected doc mapping checked).
#   2b. The READ AND APPLY lines are non-trivially present: count >= 1 per pack and all referenced
#       reference docs actually exist on disk.
#   3. packs/documentation/checks.md states JSDoc/documentation findings are NOT auto-fixable
#      (human-authorship rationale required).
#   4. packs/typescript-react/checks.md states missing-key-prop is NOT auto-fixable
#      (array-index anti-pattern rationale required).
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
PACKS_DIR="$SCRIPT_DIR/../packs"
REFERENCE_DIR="$SCRIPT_DIR/../reference"

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

# Resolve PACKS_DIR and REFERENCE_DIR if they didn't resolve above
if [ ! -d "$PACKS_DIR" ]; then
  PACKS_DIR="modules/commands-extra/skills/audit/packs"
fi
if [ ! -d "$REFERENCE_DIR" ]; then
  REFERENCE_DIR="modules/commands-extra/skills/audit/reference"
fi

for var in SKILL_DOC MULTI_AGENT_DOC FIX_PATTERNS_DOC OUTPUT_TEMPLATE_DOC SECURITY_PATTERNS_DOC; do
  file_var="${!var}"
  if [ ! -f "$file_var" ]; then
    echo "ERROR: required file not found: $file_var" >&2
    exit 1
  fi
done

echo ""
echo "=== /audit reference wiring tests (pack-registry architecture) ==="
echo "  SKILL.md:           $SKILL_DOC"
echo "  multi-agent-config: $MULTI_AGENT_DOC"
echo "  fix-patterns:       $FIX_PATTERNS_DOC"
echo "  output-template:    $OUTPUT_TEMPLATE_DOC"
echo "  security-patterns:  $SECURITY_PATTERNS_DOC"
echo "  packs dir:          $PACKS_DIR"
echo "  reference dir:      $REFERENCE_DIR"
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
# TEST 2: Each of the 9 pack checks.md files contains >=1 READ AND APPLY
#         referencing an existing reference doc (per-pack expected mapping).
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] Pack checks.md files: each wires >=1 READ AND APPLY reference doc ---"

# Per-pack expected reference docs (space-separated for each pack).
# Each pack must contain at least one READ AND APPLY pointing to one of its listed docs.
declare -A PACK_EXPECTED_REFS
PACK_EXPECTED_REFS["security"]="security-patterns.md"
PACK_EXPECTED_REFS["code-quality"]="code-quality.md fix-patterns.md"
PACK_EXPECTED_REFS["architecture"]="architecture.md"
PACK_EXPECTED_REFS["dependencies"]="fix-patterns.md"
PACK_EXPECTED_REFS["documentation"]="fix-patterns.md"
PACK_EXPECTED_REFS["performance"]="fix-patterns.md"
PACK_EXPECTED_REFS["testing"]="fix-patterns.md"
PACK_EXPECTED_REFS["tos-compliance"]="fix-patterns.md"
PACK_EXPECTED_REFS["typescript-react"]="fix-patterns.md"

NINE_PACKS=(security code-quality architecture dependencies documentation performance testing tos-compliance typescript-react)

for pack_dir in "${NINE_PACKS[@]}"; do
  checks_file="$PACKS_DIR/$pack_dir/checks.md"
  if [ ! -f "$checks_file" ]; then
    fail "pack $pack_dir: checks.md not found at $checks_file"
    continue
  fi

  set +e
  READ_APPLY_COUNT=$(grep -c 'READ AND APPLY' "$checks_file" 2>/dev/null || true)
  set -e

  if [ "${READ_APPLY_COUNT:-0}" -ge 1 ]; then
    pass "pack $pack_dir: contains $READ_APPLY_COUNT READ AND APPLY instruction(s)"
  else
    fail "pack $pack_dir: no READ AND APPLY found in $checks_file" \
      "add 'READ AND APPLY: ~/.claude/skills/audit/reference/<doc>.md' inside check blocks"
    continue
  fi

  # Check that at least one of the expected reference docs is referenced
  expected_refs="${PACK_EXPECTED_REFS[$pack_dir]:-}"
  found_expected=0
  for ref_doc in $expected_refs; do
    set +e
    REF_FOUND=$(grep -c "READ AND APPLY.*$ref_doc" "$checks_file" 2>/dev/null || true)
    set -e
    if [ "${REF_FOUND:-0}" -ge 1 ]; then
      found_expected=1
      break
    fi
  done

  if [ "$found_expected" -eq 1 ]; then
    pass "pack $pack_dir: references expected doc(s) ($expected_refs)"
  else
    fail "pack $pack_dir: expected READ AND APPLY referencing one of: $expected_refs" \
      "found READ AND APPLY lines but none match the expected reference docs"
  fi
done

# ---------------------------------------------------------------------------
# TEST 2b: READ AND APPLY lines exist inside check blocks AND
#          all referenced reference docs exist on disk.
# ---------------------------------------------------------------------------
echo ""
echo "--- [2b] Pack checks.md files: READ AND APPLY lines reference existing docs ---"

for pack_dir in "${NINE_PACKS[@]}"; do
  checks_file="$PACKS_DIR/$pack_dir/checks.md"
  if [ ! -f "$checks_file" ]; then
    fail "pack $pack_dir (2b): checks.md not found"
    continue
  fi

  # Extract all referenced doc names from READ AND APPLY lines
  # Pattern: READ AND APPLY: ~/.claude/skills/audit/reference/<doc>.md
  set +e
  REFERENCED_DOCS=$(grep 'READ AND APPLY' "$checks_file" 2>/dev/null \
    | sed 's|.*reference/||' \
    | sed 's|\.md.*||' \
    | sort -u || true)
  set -e

  if [ -z "$REFERENCED_DOCS" ]; then
    fail "pack $pack_dir (2b): no READ AND APPLY lines found"
    continue
  fi

  all_exist=1
  while IFS= read -r doc_name; do
    [ -z "$doc_name" ] && continue
    ref_path="$REFERENCE_DIR/${doc_name}.md"
    if [ -f "$ref_path" ]; then
      pass "pack $pack_dir (2b): referenced doc '${doc_name}.md' exists on disk"
    else
      fail "pack $pack_dir (2b): referenced doc '${doc_name}.md' does NOT exist at $ref_path" \
        "create the reference doc or update the READ AND APPLY pointer"
      all_exist=0
    fi
  done <<< "$REFERENCED_DOCS"
done

# ---------------------------------------------------------------------------
# TEST 3: packs/documentation/checks.md states JSDoc is NOT auto-fixable
#         (human-authorship rationale must be present)
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] packs/documentation/checks.md: JSDoc is NOT auto-fixable ---"

DOC_CHECKS="$PACKS_DIR/documentation/checks.md"
if [ ! -f "$DOC_CHECKS" ]; then
  fail "documentation checks.md not found at $DOC_CHECKS"
else
  # Check that the pack explicitly marks documentation as NOT auto-fixable
  set +e
  DOC_NOT_FIXABLE=$(grep -ic \
    'NOT auto.fixable\|not.*auto.*fix\|auto.fixable.*No\|auto_fixable.*false\|requires human' \
    "$DOC_CHECKS" 2>/dev/null || true)
  set -e

  if [ "${DOC_NOT_FIXABLE:-0}" -ge 1 ]; then
    pass "documentation pack: marks documentation findings as NOT auto-fixable"
  else
    fail "documentation pack: must explicitly state documentation findings are NOT auto-fixable" \
      "add 'NOT auto-fixable' or 'requires human-authored documentation' in checks.md"
  fi

  # Specifically check for JSDoc-related not-auto-fixable mention
  set +e
  JSDOC_MENTIONED=$(grep -ic 'jsdoc\|JSDoc' "$DOC_CHECKS" 2>/dev/null || true)
  set -e
  if [ "${JSDOC_MENTIONED:-0}" -ge 1 ]; then
    pass "documentation pack: mentions JSDoc in checks.md"
  else
    fail "documentation pack: should mention JSDoc in checks.md" \
      "the check for missing JSDoc on exports must be documented"
  fi

  # The NOT auto-fixable claim must appear in or near the documentation context
  set +e
  DOC_HUMAN_AUTHORED=$(grep -ic 'human.*authored\|human.*author\|auto.fixable.*No\|not.*auto.*fixable' \
    "$DOC_CHECKS" 2>/dev/null || true)
  set -e
  if [ "${DOC_HUMAN_AUTHORED:-0}" -ge 1 ]; then
    pass "documentation pack: states human-authored documentation requirement"
  else
    fail "documentation pack: should state that documentation requires human authorship" \
      "add rationale like 'NOT auto-fixable -- requires human-authored documentation'"
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
fi

# ---------------------------------------------------------------------------
# TEST 4: packs/typescript-react/checks.md states missing-key-prop is NOT auto-fixable
#         (array-index anti-pattern rationale required)
# ---------------------------------------------------------------------------
echo ""
echo "--- [4] packs/typescript-react/checks.md: missing-key-prop is NOT auto-fixable ---"

TS_CHECKS="$PACKS_DIR/typescript-react/checks.md"
if [ ! -f "$TS_CHECKS" ]; then
  fail "typescript-react checks.md not found at $TS_CHECKS"
else
  # Check that missing key prop is explicitly marked NOT auto-fixable
  set +e
  KEY_NOT_FIXABLE=$(grep -ic \
    'key.*NOT auto.fixable\|NOT auto.fixable.*key\|key.*not.*auto.*fix\|array.*index.*anti.pattern\|auto_fixable.*false' \
    "$TS_CHECKS" 2>/dev/null || true)
  set -e

  if [ "${KEY_NOT_FIXABLE:-0}" -ge 1 ]; then
    pass "typescript-react pack: marks missing-key-prop as NOT auto-fixable"
  else
    fail "typescript-react pack: must explicitly mark missing-key-prop as NOT auto-fixable" \
      "add 'NOT auto-fixable' and array-index anti-pattern rationale in checks.md"
  fi

  # The array-index anti-pattern must be mentioned
  set +e
  ARRAY_INDEX_MENTIONED=$(grep -ic 'array.*index\|index.*key\|anti.pattern' \
    "$TS_CHECKS" 2>/dev/null || true)
  set -e
  if [ "${ARRAY_INDEX_MENTIONED:-0}" -ge 1 ]; then
    pass "typescript-react pack: documents array-index-as-key anti-pattern"
  else
    fail "typescript-react pack: should document why array index as key is an anti-pattern" \
      "add rationale about stable unique identifiers vs array index"
  fi

  # Confirm key prop check exists (not just a random mention)
  set +e
  KEY_PROP_CHECK=$(grep -ic 'key.*prop\|missing.*key\|typescript/missing-key-prop' \
    "$TS_CHECKS" 2>/dev/null || true)
  set -e
  if [ "${KEY_PROP_CHECK:-0}" -ge 1 ]; then
    pass "typescript-react pack: has a key-prop check defined in checks.md"
  else
    fail "typescript-react pack: should have a key-prop check defined" \
      "add 'typescript/missing-key-prop' check or equivalent"
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
