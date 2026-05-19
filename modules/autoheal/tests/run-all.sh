#!/usr/bin/env bash
# run-all.sh
#
# Aggregator for the autoheal module test suite (Epic 8). Discovers and
# runs every `test-*.sh` under `modules/autoheal/tests/`, prints a
# per-script pass/fail summary, and exits 0 only if every script passed.
#
# Why a per-module aggregator: the repo-level `tests/run-all.sh` runs
# top-level structural tests, and `tests/run-unit-tests.sh` discovers
# `test_*.sh` under `modules/*/tests/` (underscore prefix, pytest-style).
# Autoheal's tests use the `test-*.sh` (dash) naming. This aggregator
# bridges the gap so contributors can run "every autoheal test" with
# one command, without having to discover all the test files.
#
# Run: bash modules/autoheal/tests/run-all.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS_COUNT=0
FAIL_COUNT=0
FAILED_SCRIPTS=()

# Collect tests deterministically: sorted lexically.
mapfile -t TEST_SCRIPTS < <(
    find "${SCRIPT_DIR}" -maxdepth 1 -type f -name 'test-*.sh' | sort
)

if [ "${#TEST_SCRIPTS[@]}" -eq 0 ]; then
    echo "No tests found in ${SCRIPT_DIR}"
    exit 1
fi

echo "=== Running ${#TEST_SCRIPTS[@]} autoheal test scripts ==="

for test_script in "${TEST_SCRIPTS[@]}"; do
    name="$(basename "${test_script}")"
    # Skip ourselves to avoid recursion.
    if [ "${name}" = "run-all.sh" ]; then
        continue
    fi
    echo ""
    echo "--- ${name} ---"
    if bash "${test_script}"; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_SCRIPTS+=("${name}")
    fi
done

echo ""
echo "=== Autoheal test summary ==="
echo "  Passed: ${PASS_COUNT}"
echo "  Failed: ${FAIL_COUNT}"

if [ "${FAIL_COUNT}" -gt 0 ]; then
    echo "  Failed scripts:"
    for s in "${FAILED_SCRIPTS[@]}"; do
        echo "    - ${s}"
    done
    exit 1
fi

echo "  All autoheal tests passed."
exit 0
