#!/usr/bin/env bash
# Test suite for modules/hooks/lib/sched_platform.py.
#
# Verifies:
#   - macOS install/uninstall round-trip writes/removes a plist
#   - list_scheduled_jobs reflects file state
#   - Linux raises NotImplementedError (via monkeypatched _platform.system)
#
# Run: bash modules/hooks/tests/test-platform.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB="${MODULE_ROOT}/lib"

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
    local cond="$1"
    local label="$2"
    if [ "${cond}" = "True" ] || [ "${cond}" = "true" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label} (got ${cond})"
    fi
}

py() {
    PYTHONPATH="${LIB}" python3 -c "$1"
}

SYS=$(uname -s)

# 1. Linux stub raises NotImplementedError with a clear message.
#    Monkeypatch _platform.system to lie about the OS.
out=$(py "
import sched_platform
sched_platform._platform.system = lambda: 'Linux'
try:
    sched_platform.install_scheduled_job('test.label', 'echo hi', 12, 0)
    print('SHOULD_HAVE_RAISED')
except NotImplementedError as e:
    print('Linux scheduling is a v2 plug-in point.' in str(e))
")
assert_true "${out}" "Linux raises NotImplementedError with v2 message"

out=$(py "
import sched_platform
sched_platform._platform.system = lambda: 'Linux'
for fn in (sched_platform.uninstall_scheduled_job, sched_platform.list_scheduled_jobs):
    try:
        fn('test.label') if fn is sched_platform.uninstall_scheduled_job else fn()
        print('SHOULD_HAVE_RAISED')
        break
    except NotImplementedError:
        pass
else:
    print('ok')
")
assert_eq "${out}" "ok" "Linux uninstall + list also raise"

# 2. Unsupported OS path.
out=$(py "
import sched_platform
sched_platform._platform.system = lambda: 'Plan9'
try:
    sched_platform.install_scheduled_job('x', 'echo', 0, 0)
    print('SHOULD_HAVE_RAISED')
except NotImplementedError as e:
    print('Plan9' in str(e))
")
assert_true "${out}" "Unsupported OS reports system name"

# 3. Reject invalid hour/minute.
out=$(py "
import sched_platform
try:
    sched_platform.install_scheduled_job('x', 'echo', 24, 0)
    print('SHOULD_HAVE_RAISED')
except ValueError:
    print('ok')
")
assert_eq "${out}" "ok" "Rejects hour=24"

out=$(py "
import sched_platform
try:
    sched_platform.install_scheduled_job('x', 'echo', 0, 60)
    print('SHOULD_HAVE_RAISED')
except ValueError:
    print('ok')
")
assert_eq "${out}" "ok" "Rejects minute=60"

# macOS-specific tests.
if [ "${SYS}" = "Darwin" ]; then
    LABEL="com.ccgm.test.platform.$$"
    PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

    # 4. install -> plist file exists.
    py "
import sched_platform
sched_platform.install_scheduled_job('${LABEL}', 'echo hello', 4, 30)
"
    if [ -f "${PLIST}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: install wrote plist (missing: ${PLIST})"
    fi

    # 5. list_scheduled_jobs sees the new label.
    out=$(py "
import sched_platform
print('${LABEL}' in sched_platform.list_scheduled_jobs())
")
    assert_true "${out}" "list_scheduled_jobs sees installed label"

    # 6. uninstall -> plist gone.
    py "
import sched_platform
sched_platform.uninstall_scheduled_job('${LABEL}')
"
    if [ ! -f "${PLIST}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: uninstall removed plist (still present: ${PLIST})"
        rm -f "${PLIST}"
    fi

    # 7. uninstall non-existent is a no-op.
    out=$(py "
import sched_platform
sched_platform.uninstall_scheduled_job('${LABEL}.never-existed')
print('ok')
")
    assert_eq "${out}" "ok" "Uninstall tolerates missing label"

    # 8. Install is idempotent (second install replaces first).
    out=$(py "
import sched_platform
sched_platform.install_scheduled_job('${LABEL}', 'echo first', 4, 30)
sched_platform.install_scheduled_job('${LABEL}', 'echo second', 5, 30)
import plistlib
data = plistlib.load(open(sched_platform._plist_path('${LABEL}'), 'rb'))
print(data['StartCalendarInterval']['Hour'])
print('echo second' in data['ProgramArguments'][-1])
")
    assert_eq "$(echo "${out}" | sed -n 1p)" "5" "Idempotent install: second wins (hour)"
    assert_true "$(echo "${out}" | sed -n 2p)" "Idempotent install: second wins (command)"

    # Cleanup.
    py "
import sched_platform
sched_platform.uninstall_scheduled_job('${LABEL}')
"
else
    echo "Skipping macOS-only tests (uname -s = ${SYS})"
fi

echo ""
echo "test-platform.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
