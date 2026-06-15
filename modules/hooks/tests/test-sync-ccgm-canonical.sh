#!/usr/bin/env bash
# CI wrapper for the sync-ccgm-canonical hook's python unit tests.
#
# CI runs only modules/hooks/tests/*.sh (see .github/workflows/test.yml), so the
# python test file beside this one (test_sync_ccgm_canonical.py) was never
# executed on the runner -- which is how the start-anchored matcher bug (#728)
# shipped undetected. This wrapper runs those tests and propagates their exit
# code so the hook is actually gated.
#
# Run: bash modules/hooks/tests/test-sync-ccgm-canonical.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/test_sync_ccgm_canonical.py" -v
STATUS=$?

if [ "${STATUS}" -eq 0 ]; then
  echo "test-sync-ccgm-canonical.sh: passed"
else
  echo "test-sync-ccgm-canonical.sh: FAILED (exit ${STATUS})"
fi
exit "${STATUS}"
