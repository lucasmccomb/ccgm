#!/usr/bin/env bash
#
# run-audit-suite.sh — run the /audit skill test suite.
#
# Discovers and runs all test-*.sh files under
# modules/commands-extra/skills/audit/tests/.
#
# All tests are designed to be CI-safe:
#   - Spine tools absent -> graceful skip (no FAIL)
#   - bash < 4 (macOS system shell) -> spine-calling tests skip cleanly
#   - shellcheck absent -> shell safety tests skip cleanly
#
# Exits 0 if all suites pass, 1 otherwise.
#
# Called by:
#   tests/run-all.sh (after run-unit-tests.sh)
#   .github/workflows/test.yml (both ubuntu and macos jobs)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AUDIT_TESTS_DIR="$REPO_ROOT/modules/commands-extra/skills/audit/tests"

cd "$REPO_ROOT"

PASS=0
FAIL=0
FAILED=()

echo "=== /audit skill test suite ==="
echo "  Discovering: ${AUDIT_TESTS_DIR}/test-*.sh"
echo ""

# Collect test scripts (sorted for deterministic order)
TEST_SCRIPTS=()
while IFS= read -r -d '' f; do
    TEST_SCRIPTS+=("$f")
done < <(find "$AUDIT_TESTS_DIR" -maxdepth 1 -name 'test-*.sh' -type f -print0 2>/dev/null | sort -z)

if [ "${#TEST_SCRIPTS[@]}" -eq 0 ]; then
    echo "  ERROR: no test-*.sh files found in $AUDIT_TESTS_DIR" >&2
    exit 1
fi

echo "  Found ${#TEST_SCRIPTS[@]} test suite(s)"
echo ""

for test_script in "${TEST_SCRIPTS[@]}"; do
    rel="${test_script#"$REPO_ROOT/"}"
    LOG="/tmp/ccgm-audit-test-$$.log"
    if bash "$test_script" > "$LOG" 2>&1; then
        echo "  PASS: $rel"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $rel"
        sed 's/^/    | /' "$LOG"
        FAILED+=("$rel")
        FAIL=$((FAIL + 1))
    fi
    rm -f "$LOG"
done

echo ""
echo "=== /audit suite summary: ${PASS} passed, ${FAIL} failed ==="

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo ""
    echo "Failed suites:"
    for f in "${FAILED[@]}"; do
        echo "  - $f"
    done
    exit 1
fi

exit 0
