#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0
FAIL=0
FAILED_TESTS=()

for test_script in "$SCRIPT_DIR"/test-*.sh; do
  name=$(basename "$test_script")
  echo ""
  echo "=== Running $name ==="
  if bash "$test_script"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("$name")
  fi
done

# Per-module unit tests (pytest + shell).
if [[ -x "$SCRIPT_DIR/run-unit-tests.sh" ]]; then
  echo ""
  echo "=== Running run-unit-tests.sh ==="
  if bash "$SCRIPT_DIR/run-unit-tests.sh"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("run-unit-tests.sh")
  fi
fi

# /audit skill test suite (24 suites).
if [[ -x "$SCRIPT_DIR/run-audit-suite.sh" ]]; then
  echo ""
  echo "=== Running run-audit-suite.sh ==="
  if bash "$SCRIPT_DIR/run-audit-suite.sh"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("run-audit-suite.sh")
  fi
fi

echo ""
echo "=== Test Summary ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
if [[ $FAIL -gt 0 ]]; then
  echo "Failed tests:"
  for t in "${FAILED_TESTS[@]}"; do echo "  - $t"; done
  exit 1
fi
echo "All tests passed!"
