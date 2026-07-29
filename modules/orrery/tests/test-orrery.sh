#!/usr/bin/env bash
set -euo pipefail

# orrery module test runner (plan Epic 1).
#
# Layers:
#   unit  - pytest over tests/unit/ (when test_*.py files exist)
#   e2e   - every tests/e2e/test-*.sh
#
# ORRERY_STRICT=1 (plan section 4) makes every skippable condition a hard
# FAILURE instead of a skip: pytest absent, browser binary absent (enforced
# inside test-embed-browser.sh), zero tests discovered. Without the flag a
# green run could mean "the suite silently ran nothing". Both CI jobs set it.
#
# Portable: macOS bash 3.2 + BSD tools.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS_DIR="$MODULE_DIR/tests"
STRICT="${ORRERY_STRICT:-0}"

echo "=== orrery test suite (ORRERY_STRICT=$STRICT) ==="

FAILURES=0
LAYERS_RAN=""
LAYERS_SKIPPED=""

# --- unit layer (pytest) ----------------------------------------------------
UNIT_DIR="$TESTS_DIR/unit"
UNIT_COUNT=0
if [ -d "$UNIT_DIR" ]; then
  UNIT_COUNT="$(find "$UNIT_DIR" -name 'test_*.py' -type f | wc -l | tr -d ' ')"
fi

PYTEST_OK=0
if python3 -m pytest --version >/dev/null 2>&1; then
  PYTEST_OK=1
fi

if [ "$PYTEST_OK" = "0" ]; then
  if [ "$STRICT" = "1" ]; then
    echo "FAIL: pytest is not available and ORRERY_STRICT=1 treats that as a failure, not a skip" >&2
    FAILURES=$((FAILURES + 1))
  else
    echo "skip: pytest not available - unit layer skipped (ORRERY_STRICT=1 makes this a failure)"
    LAYERS_SKIPPED="$LAYERS_SKIPPED unit"
  fi
elif [ "$UNIT_COUNT" = "0" ]; then
  echo "unit layer: no test_*.py files under tests/unit yet (nothing to run)"
else
  echo "--- unit layer: pytest over $UNIT_COUNT file(s) ---"
  if python3 -m pytest "$UNIT_DIR" -q; then
    LAYERS_RAN="$LAYERS_RAN unit"
  else
    echo "FAIL: unit layer (pytest)" >&2
    FAILURES=$((FAILURES + 1))
  fi
fi

# --- e2e layer --------------------------------------------------------------
E2E_COUNT=0
for t in "$TESTS_DIR"/e2e/test-*.sh; do
  [ -f "$t" ] || continue
  E2E_COUNT=$((E2E_COUNT + 1))
  name="$(basename "$t")"
  echo "--- e2e: $name ---"
  if bash "$t"; then
    LAYERS_RAN="$LAYERS_RAN $name"
  else
    echo "FAIL: $name" >&2
    FAILURES=$((FAILURES + 1))
  fi
done

# --- zero-tests-discovered guard --------------------------------------------
TOTAL_DISCOVERED=$((UNIT_COUNT + E2E_COUNT))
if [ "$TOTAL_DISCOVERED" = "0" ]; then
  if [ "$STRICT" = "1" ]; then
    echo "FAIL: zero tests discovered and ORRERY_STRICT=1 treats that as a failure, not a pass" >&2
    FAILURES=$((FAILURES + 1))
  else
    echo "skip: zero tests discovered (ORRERY_STRICT=1 makes this a failure)"
  fi
fi

# --- report -----------------------------------------------------------------
echo ""
echo "layers ran:$LAYERS_RAN"
if [ -n "$LAYERS_SKIPPED" ]; then
  echo "layers skipped:$LAYERS_SKIPPED"
fi
if [ "$FAILURES" -gt 0 ]; then
  echo "test-orrery.sh: $FAILURES failure(s)"
  exit 1
fi
echo "test-orrery.sh: all layers green"
