#!/usr/bin/env bash
#
# Pinning tests for ccgm-skillify-check.
#
# Run:
#   bash modules/skillify/tests/test_skillify_check.sh
#
# Exits 0 on success, 1 on any failure.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_BIN="$SCRIPT_DIR/../bin/ccgm-skillify-check"

if [ ! -x "$CHECK_BIN" ]; then
    echo "FAIL: $CHECK_BIN is not executable" >&2
    exit 1
fi

PASS=0
FAIL=0

_assert_exit() {
    local label=$1 expected=$2 actual=$3
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
        echo "  PASS: $label (exit $actual)"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: $label — expected exit $expected, got $actual"
    fi
}

# Fresh sandbox: empty HOME and CWD-style commands dirs, so the tests
# are reproducible on any machine regardless of the user's actual skills.
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

mkdir -p "$SANDBOX/home/.claude/commands"
mkdir -p "$SANDBOX/project/.claude/commands"

# Seed one skill so collision detection has something to hit.
cat > "$SANDBOX/home/.claude/commands/existing-skill.md" <<'EOF'
# /existing-skill - fake skill for testing
EOF

run_check() {
    # Run the check with HOME + CWD overrides for isolation.
    (cd "$SANDBOX/project" && HOME="$SANDBOX/home" bash "$CHECK_BIN" "$@")
}

# --- Test 1: exit 3 on missing arg ---
run_check >/dev/null 2>&1
_assert_exit "no args -> exit 3" 3 $?

# --- Test 2: exit 3 on invalid kebab-case ---
run_check "Bad_Name" >/dev/null 2>&1
_assert_exit "invalid kebab-case -> exit 3" 3 $?

run_check "UPPER" >/dev/null 2>&1
_assert_exit "uppercase -> exit 3" 3 $?

run_check "ends-with-dash-" >/dev/null 2>&1
_assert_exit "trailing dash -> exit 3" 3 $?

# --- Test 3: exit 0 on fresh name ---
run_check "totally-fresh-name" >/dev/null 2>&1
_assert_exit "fresh name -> exit 0" 0 $?

# --- Test 4: exit 1 on exact collision ---
run_check "existing-skill" >/dev/null 2>&1
_assert_exit "exact collision -> exit 1" 1 $?

# --- Test 5: exit 2 on fuzzy match (shares token ≥ 4 chars) ---
run_check "existing-variant" >/dev/null 2>&1
_assert_exit "fuzzy match via shared token -> exit 2" 2 $?

# --- Test 6: short tokens don't cause false fuzzy matches ---
# 'new-ai' shares 'ai' (2 chars) with existing names potentially, but the
# minimum token length is 4, so 'ai' should not trigger a fuzzy hit.
run_check "new-ai" >/dev/null 2>&1
_assert_exit "short tokens don't false-match -> exit 0" 0 $?

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
