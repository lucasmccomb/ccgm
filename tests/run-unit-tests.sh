#!/usr/bin/env bash
#
# run-unit-tests.sh — run per-module unit tests across the CCGM repo.
#
# Discovers and runs:
#   - Python tests (modules/*/tests/test_*.py) via `python3 -m pytest`
#     (handles both unittest.TestCase and pytest assertion-style tests)
#   - Shell tests (modules/*/tests/test_*.sh) via `bash`
#
# Exits 0 if all suites pass, 1 otherwise.
#
# Top-level integration/structural tests (tests/test-*.sh) are run by
# tests/run-all.sh instead; this runner stays focused on module unit tests.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

PY_STATUS=0
SH_STATUS=0
SH_COUNT=0
SH_FAILED=()

echo "=== CCGM Unit Tests ==="
echo ""

# --- Python tests via pytest ---
echo "--- Python (pytest) ---"
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "  SKIP: pytest not importable. Install with: python3 -m pip install pytest"
    PY_STATUS=0
else
    # pytest discovers modules/*/tests/test_*.py automatically.
    if python3 -m pytest modules/ -q --no-header 2>&1; then
        PY_STATUS=0
    else
        PY_STATUS=1
    fi
fi
echo ""

# --- Shell tests ---
echo "--- Shell (bash) ---"
while IFS= read -r -d '' test_script; do
    SH_COUNT=$((SH_COUNT + 1))
    rel=${test_script#"$REPO_ROOT/"}
    if bash "$test_script" >/tmp/ccgm-test-$$.log 2>&1; then
        echo "  PASS: $rel"
    else
        echo "  FAIL: $rel"
        sed 's/^/    | /' /tmp/ccgm-test-$$.log
        SH_FAILED+=("$rel")
        SH_STATUS=1
    fi
    rm -f /tmp/ccgm-test-$$.log
done < <(find modules -path '*/tests/test_*.sh' -type f -print0 2>/dev/null)

if [ "$SH_COUNT" -eq 0 ]; then
    echo "  (no shell unit tests found)"
fi
echo ""

# --- Summary ---
echo "=== Summary ==="
if [ "$PY_STATUS" -eq 0 ]; then
    echo "  Python: OK"
else
    echo "  Python: FAILED (see output above)"
fi

if [ "$SH_STATUS" -eq 0 ]; then
    echo "  Shell:  $SH_COUNT suites, all passed"
else
    echo "  Shell:  $SH_COUNT suites, ${#SH_FAILED[@]} failed"
    for f in "${SH_FAILED[@]}"; do echo "    - $f"; done
fi

if [ "$PY_STATUS" -ne 0 ] || [ "$SH_STATUS" -ne 0 ]; then
    exit 1
fi
exit 0
