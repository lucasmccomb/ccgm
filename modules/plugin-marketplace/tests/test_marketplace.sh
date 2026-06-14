#!/usr/bin/env bash
set -euo pipefail

# Shell smoke test for the plugin-marketplace module (issue #703).
# Runs without pytest so CI's run-unit-tests.sh shell pass covers it too:
#   1. generator --check must be clean (committed output in sync with module.json)
#   2. JSON-schema validator must pass on the committed output
#   3. if `claude` is available, `claude plugin validate` the marketplace manifest

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

GEN="modules/plugin-marketplace/lib/gen_marketplace.py"
VAL="modules/plugin-marketplace/lib/validate_marketplace.py"

echo "--- generator --check ---"
python3 "$GEN" --check

echo "--- validate_marketplace.py ---"
python3 "$VAL"

echo "--- claude plugin validate (optional) ---"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate .claude-plugin/marketplace.json --strict
else
  echo "  SKIP: claude CLI not on PATH (validator above covers structure)"
fi

echo "test_marketplace.sh: all checks passed"
