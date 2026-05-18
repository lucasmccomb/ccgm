#!/usr/bin/env bash
# Cross-clone file-lock concurrency test for hook_utils.file_locked_append.
#
# Spawns 4 Python processes appending different prefixed lines to the same
# JSONL path. Verifies:
#   - All writes land (union; no losses)
#   - No record is torn or interleaved (each line begins with the writer's prefix)
#   - Line count == sum of per-writer counts
#
# Run: bash modules/hooks/tests/test-cross-clone-file-lock.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB="${MODULE_ROOT}/lib"

WORKERS=4
LINES_PER_WORKER=200
TMP=$(mktemp -d -t ccfl.XXXXXX)
TARGET="${TMP}/events.jsonl"
trap 'rm -rf "${TMP}"' EXIT

PASS=0
FAIL=0

assert_eq() {
    local actual="$1"
    local expected="$2"
    local label="$3"
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected: ${expected}"
        echo "  actual:   ${actual}"
    fi
}

# Launch WORKERS Python workers in background.
for i in $(seq 0 $((WORKERS - 1))); do
    PYTHONPATH="${LIB}" python3 - "${i}" "${TARGET}" "${LINES_PER_WORKER}" <<'PY' &
import sys, hook_utils
wid, target, n = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
prefix = f"writer-{wid}"
for j in range(n):
    hook_utils.file_locked_append(target, f'{prefix} record-{j}')
PY
done
wait

# 1. Total line count matches.
actual_lines=$(wc -l < "${TARGET}" | tr -d ' ')
expected_lines=$((WORKERS * LINES_PER_WORKER))
assert_eq "${actual_lines}" "${expected_lines}" "total line count matches ${expected_lines}"

# 2. Every line starts with one of the four writer prefixes (no torn writes).
bad=$(awk '$1 !~ /^writer-[0-3]$/ { c++ } END { print c+0 }' "${TARGET}")
assert_eq "${bad}" "0" "no torn / mis-prefixed lines"

# 3. Per-writer count is exact (no losses, no duplicates).
for i in $(seq 0 $((WORKERS - 1))); do
    count=$(grep -c "^writer-${i} " "${TARGET}" || true)
    assert_eq "${count}" "${LINES_PER_WORKER}" "writer-${i} produced ${LINES_PER_WORKER} records"
done

echo ""
echo "test-cross-clone-file-lock.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
