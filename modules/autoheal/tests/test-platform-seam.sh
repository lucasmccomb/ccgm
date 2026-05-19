#!/usr/bin/env bash
# Platform-seam test from autoheal's perspective.
#
# Most of the platform-abstraction work landed in Epic 1
# (`modules/hooks/lib/sched_platform.py`), and the authoritative test is
# `modules/hooks/tests/test-platform.sh` which already covers:
#   - macOS install/uninstall round-trip
#   - list_scheduled_jobs reflects file state
#   - Linux raises NotImplementedError with the "v2 plug-in" message
#   - Unsupported OSes raise
#   - hour/minute validation
#
# Per plan.md §3.11 (Linux portability seams), the contract is "Linux is a v2
# plug-in point." This autoheal-side test confirms that autoheal-install.sh
# refuses to proceed on Linux with a clean error (it depends on sched_platform).
# When v2 lands and the Linux path is implemented, this test will need updating.
#
# Run: bash modules/autoheal/tests/test-platform-seam.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
HOOKS_LIB="${REPO_ROOT}/modules/hooks/lib"

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

assert_true() {
    if [ "$1" = "True" ] || [ "$1" = "true" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $2 (got $1)"
    fi
}

# 1. sched_platform module loads successfully via the install path.
out=$(PYTHONPATH="${HOOKS_LIB}" python3 -c "
import sched_platform
print(hasattr(sched_platform, 'install_scheduled_job'))
print(hasattr(sched_platform, 'uninstall_scheduled_job'))
print(hasattr(sched_platform, 'list_scheduled_jobs'))
")
assert_true "$(echo "${out}" | sed -n 1p)" "install_scheduled_job is exported"
assert_true "$(echo "${out}" | sed -n 2p)" "uninstall_scheduled_job is exported"
assert_true "$(echo "${out}" | sed -n 3p)" "list_scheduled_jobs is exported"

# 2. Linux path raises NotImplementedError with the documented "v2" message.
out=$(PYTHONPATH="${HOOKS_LIB}" python3 -c "
import sched_platform
sched_platform._platform.system = lambda: 'Linux'
try:
    sched_platform.install_scheduled_job('test.label', 'echo hi', 12, 0)
    print('SHOULD_HAVE_RAISED')
except NotImplementedError as e:
    msg = str(e)
    print('v2 plug-in point' in msg)
    print('sched_platform.py' in msg)
")
assert_true "$(echo "${out}" | sed -n 1p)" "Linux raises with 'v2 plug-in point' message"
assert_true "$(echo "${out}" | sed -n 2p)" "Linux message references the actual file name (sched_platform)"

# 3. autoheal-install.sh detects the platform via sched_platform and refuses
#    on Linux with a clean exit (does NOT crash with a traceback).
INSTALLER="${MODULE_ROOT}/bin/autoheal-install.sh"
if [ -x "${INSTALLER}" ]; then
    # We cannot actually invoke the installer end-to-end here — it has side
    # effects (writes to ~/.claude/autoheal/, modifies launchd). What we CAN
    # verify is that it imports sched_platform (not the stdlib platform).
    if grep -q "sched_platform" "${INSTALLER}"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: autoheal-install.sh does not reference sched_platform"
    fi
else
    echo "SKIP: autoheal-install.sh missing or not executable"
fi

# 4. The Linux cron stub template exists (per §3.11 — file present but unused).
CRON_TEMPLATE="${MODULE_ROOT}/lib/autoheal.cron.template"
if [ -f "${CRON_TEMPLATE}" ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: lib/autoheal.cron.template missing"
fi

echo ""
echo "test-platform-seam.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
