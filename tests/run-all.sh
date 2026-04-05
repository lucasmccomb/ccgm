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
    ((PASS++))
  else
    ((FAIL++))
    FAILED_TESTS+=("$name")
  fi
done

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
