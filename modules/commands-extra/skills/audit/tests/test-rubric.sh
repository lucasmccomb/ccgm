#!/usr/bin/env bash
# test-rubric.sh — Tests for severity-rubric.json and lint-rubric.py
#
# Tests:
#   1. Rubric is valid JSON (python3 json.load)
#   2. lint-rubric.py passes on the real rubric file (enum + structure validation)
#   3. lint-rubric.py rejects a rubric with an invalid severity value
#   4. lint-rubric.py rejects a rubric with a missing required key
#   5. lint-rubric.py rejects a check_id that doesn't match the naming pattern
#   6. Orphan-check-id gate: a pack.json with a check_id absent from the rubric fails
#   7. Orphan-check-id gate: a pack.json with all check_ids in the rubric passes
#   8. Orphan-check-id gate: zero packs present passes trivially
#
# Orphan-check-id gate documentation:
#   This gate enforces that every check_id shipped in packs/**/pack.json has a
#   corresponding entry in schemas/severity-rubric.json. With zero packs the gate
#   passes trivially. As pack epics land they add both the pack.json check definition
#   AND a rubric entry; CI catches any pack that ships without a rubric entry.
#
# Exit: 0 if all pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUBRIC="$SKILL_ROOT/schemas/severity-rubric.json"
LINTER="$SKILL_ROOT/scripts/lint-rubric.py"

PASS=0
FAIL=0

# Colour helpers (no external deps)
_GREEN='\033[0;32m'
_RED='\033[0;31m'
_RESET='\033[0m'

pass() { echo -e "${_GREEN}PASS${_RESET}: $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${_RED}FAIL${_RESET}: $1"; FAIL=$((FAIL + 1)); }

# Single temp directory for all ephemeral fixtures; cleaned on exit.
TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# ── helper: run linter against a temporary rubric file ──────────────────────
run_linter_on() {
    local tmp_rubric="$1"
    shift
    python3 "$LINTER" --rubric "$tmp_rubric" "$@"
}

# Empty packs dir used for tests that only exercise rubric validation
PACKS_EMPTY="$TMPROOT/packs-empty"
mkdir -p "$PACKS_EMPTY"

# ── test 1: real rubric is valid JSON ────────────────────────────────────────
if python3 -c "import json, sys; json.load(open('$RUBRIC'))" 2>/dev/null; then
    pass "rubric parses as valid JSON"
else
    fail "rubric is not valid JSON"
fi

# ── test 2: lint-rubric passes on the real file ──────────────────────────────
if run_linter_on "$RUBRIC" --packs-dir "$PACKS_EMPTY" >/dev/null 2>&1; then
    pass "lint-rubric passes on real severity-rubric.json"
else
    fail "lint-rubric reports errors on real severity-rubric.json"
fi

# ── test 3: invalid severity enum rejected ───────────────────────────────────
BAD_SEVERITY="$TMPROOT/bad-severity.json"
cat > "$BAD_SEVERITY" <<'EOF'
{
  "checks": {
    "security/example-check": {
      "severity": "blocker",
      "confidence": "high",
      "fix_confidence": "low"
    }
  }
}
EOF
if ! run_linter_on "$BAD_SEVERITY" --packs-dir "$PACKS_EMPTY" >/dev/null 2>&1; then
    pass "lint-rubric rejects invalid severity enum 'blocker'"
else
    fail "lint-rubric should have rejected invalid severity enum 'blocker'"
fi

# ── test 4: missing required key rejected ────────────────────────────────────
MISSING_KEY="$TMPROOT/missing-key.json"
cat > "$MISSING_KEY" <<'EOF'
{
  "checks": {
    "security/example-check": {
      "severity": "high",
      "confidence": "medium"
    }
  }
}
EOF
if ! run_linter_on "$MISSING_KEY" --packs-dir "$PACKS_EMPTY" >/dev/null 2>&1; then
    pass "lint-rubric rejects entry missing 'fix_confidence'"
else
    fail "lint-rubric should have rejected entry missing 'fix_confidence'"
fi

# ── test 5: bad check_id format rejected ─────────────────────────────────────
BAD_ID="$TMPROOT/bad-id.json"
cat > "$BAD_ID" <<'EOF'
{
  "checks": {
    "SecurityHardcodedSecret": {
      "severity": "critical",
      "confidence": "medium",
      "fix_confidence": "low"
    }
  }
}
EOF
if ! run_linter_on "$BAD_ID" --packs-dir "$PACKS_EMPTY" >/dev/null 2>&1; then
    pass "lint-rubric rejects check_id not matching namespace/name pattern"
else
    fail "lint-rubric should have rejected check_id 'SecurityHardcodedSecret' (no namespace)"
fi

# ── test 6: orphan check-id gate — pack check missing from rubric fails ──────
PACKS_ORPHAN="$TMPROOT/packs-orphan"
mkdir -p "$PACKS_ORPHAN"
cat > "$PACKS_ORPHAN/pack.json" <<'EOF'
{
  "checks": [
    { "check_id": "my-pack/orphan-check-not-in-rubric" }
  ]
}
EOF
if ! run_linter_on "$RUBRIC" --packs-dir "$PACKS_ORPHAN" >/dev/null 2>&1; then
    pass "orphan-check-id gate: pack check absent from rubric is rejected"
else
    fail "orphan-check-id gate: should have rejected pack check_id absent from rubric"
fi

# ── test 7: orphan check-id gate — pack check present in rubric passes ───────
PACKS_KNOWN="$TMPROOT/packs-known"
mkdir -p "$PACKS_KNOWN"
# Use a check_id that is definitely in the rubric
cat > "$PACKS_KNOWN/pack.json" <<'EOF'
{
  "checks": [
    { "check_id": "security/hardcoded-secret" }
  ]
}
EOF
if run_linter_on "$RUBRIC" --packs-dir "$PACKS_KNOWN" >/dev/null 2>&1; then
    pass "orphan-check-id gate: pack check_id present in rubric passes"
else
    fail "orphan-check-id gate: should have passed for check_id 'security/hardcoded-secret'"
fi

# ── test 8: orphan check-id gate — zero packs passes trivially ───────────────
if run_linter_on "$RUBRIC" --packs-dir "$PACKS_EMPTY" >/dev/null 2>&1; then
    pass "orphan-check-id gate: zero packs passes trivially"
else
    fail "orphan-check-id gate: zero packs should pass trivially"
fi

# ── summary ──────────────────────────────────────────────────────────────────
echo
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
