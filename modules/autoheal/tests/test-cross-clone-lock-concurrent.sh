#!/usr/bin/env bash
# test-cross-clone-lock-concurrent.sh
#
# Epic 12 cross-clone concurrency check.
#
# The substantive 4-writer concurrent fcntl.flock test for
# hook_utils.file_locked_append is owned by Epic 1 and lives at:
#
#     modules/hooks/tests/test-cross-clone-file-lock.sh
#
# That test verifies the union/no-loss/no-tear properties at the
# function level — and every autoheal hook that appends JSONL
# (permission-event-logger.py, failure-logger.py, user-correction-detector.py)
# and every analyzer-side append (bin/autoheal-analyze.sh's
# append_jsonl helper) routes through the SAME shape (or directly
# calls hook_utils.file_locked_append). Duplicating that test in
# autoheal/ would be redundant: the contract is enforced at the
# helper level, not at each call site.
#
# This script therefore delegates to the canonical test. It exists
# as a stub so the autoheal/run-all.sh aggregator and the Epic 12
# acceptance criteria still find a `test-cross-clone-lock-concurrent.sh`
# in the autoheal tests directory, and so that anyone scanning the
# autoheal test list sees the cross-clone concurrency check is
# accounted for.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CANONICAL_TEST="${REPO_ROOT}/modules/hooks/tests/test-cross-clone-file-lock.sh"

if [ ! -f "${CANONICAL_TEST}" ]; then
    echo "FAIL: canonical cross-clone file-lock test missing at ${CANONICAL_TEST}"
    echo "      Epic 12 relies on Epic 1's file_locked_append being tested."
    exit 1
fi

echo "Delegating to canonical test: ${CANONICAL_TEST}"
exec bash "${CANONICAL_TEST}"
