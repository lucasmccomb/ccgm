#!/usr/bin/env bash
# test-sched-foreign-home.sh
#
# Guards against the 2026-09-02 incident: an installer run under a temp HOME
# unloaded the real launchd job (labels are shared across HOMEs) and loaded one
# pointing into the temp dir.
#
# SAFETY: this test never calls the real launchctl. A fake `launchctl` sits
# first on PATH, records its argv, and the test aborts if the fake is not the
# one PATH resolves. Assertions read the fake's log.
#
# Covers sched_platform.install/uninstall, autoheal-install.sh and
# dream-install.sh:
#   1. Foreign HOME: refuse, exit non-zero, launchctl never called.
#   2. --no-schedule under a foreign HOME: installs files, launchctl never called.
#   3. Guard passes (CCGM_SCHED_ALLOW_FOREIGN_HOME=1, fake launchctl): bootstrap
#      runs, then `launchctl print` is checked against the plist just written.
#   4. A loaded path that differs from the plist (or a failed print) fails loudly.
#   5. HOME equal to the passwd home passes the guard (checked without side effects).
#
# Run: bash modules/hooks/tests/test-sched-foreign-home.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
LIB_DIR="${REPO_ROOT}/modules/hooks/lib"
AUTOHEAL_INSTALL="${REPO_ROOT}/modules/autoheal/bin/autoheal-install.sh"
DREAM_INSTALL="${REPO_ROOT}/modules/dreaming/bin/dream-install.sh"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; [ -n "${2:-}" ] && echo "$2" | sed 's/^/  /'; }

assert_eq() {
    if [ "$1" = "$2" ]; then pass; else fail "$3" "expected: $2
actual:   $1"; fi
}
assert_nonzero() {
    if [ "$1" -ne 0 ]; then pass; else fail "$2 (exit was 0)"; fi
}
assert_contains() {
    case "$1" in *"$2"*) pass ;; *) fail "$3" "missing: $2
in: $1" ;; esac
}

TMP="$(mktemp -d -t sched-foreign-home.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

FAKEBIN="${TMP}/fakebin"
mkdir -p "${FAKEBIN}"
export FAKE_LAUNCHCTL_LOG="${TMP}/launchctl.log"
export FAKE_LAUNCHCTL_STATE="${TMP}/launchctl.state"
cat > "${FAKEBIN}/launchctl" <<'FAKE'
#!/bin/bash
echo "$*" >> "${FAKE_LAUNCHCTL_LOG}"
case "$1" in
    bootstrap)
        echo "$3" > "${FAKE_LAUNCHCTL_STATE}"
        ;;
    print)
        case "${FAKE_PRINT_MODE:-match}" in
            match)
                printf '%s = {\n\tactive count = 0\n\tpath = %s\n\tstdout path = /x/out.log\n\truns = 1\n}\n' \
                    "$2" "$(cat "${FAKE_LAUNCHCTL_STATE}")"
                ;;
            stale)
                printf '%s = {\n\tpath = /nonexistent/stale-temp-home/other.plist\n\truns = 31\n}\n' "$2"
                ;;
            missing)
                echo "Could not find service" >&2
                exit 113
                ;;
        esac
        ;;
esac
exit 0
FAKE
chmod +x "${FAKEBIN}/launchctl"

export PATH="${FAKEBIN}:${PATH}"
if [ "$(command -v launchctl)" != "${FAKEBIN}/launchctl" ]; then
    echo "FATAL: fake launchctl is not first on PATH; refusing to run (would hit the real one)"
    exit 1
fi

new_home() { local h; h="$(mktemp -d "${TMP}/home.XXXXXX")"; mkdir -p "${h}/Library/LaunchAgents"; echo "${h}"; }
reset_log() { : > "${FAKE_LAUNCHCTL_LOG}"; rm -f "${FAKE_LAUNCHCTL_STATE}"; }
log_text() { cat "${FAKE_LAUNCHCTL_LOG}"; }

SYS="$(uname -s)"
PY_RUN() { # PY_RUN <home> <python code>; prints "rc|stdout+stderr"
    local h="$1"; shift
    local out rc
    out="$(HOME="${h}" PYTHONPATH="${LIB_DIR}" python3 -c "$1" 2>&1)"; rc=$?
    echo "${rc}|${out}"
}

# sched_platform's launchd branch only runs on Darwin.
if [ "${SYS}" != "Darwin" ]; then
    echo "Skipping (uname -s = ${SYS}): launchd paths are macOS-only"
    echo "test-sched-foreign-home.sh: 0 passed, 0 failed"
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Foreign HOME refuses; launchctl is never called.
# ---------------------------------------------------------------------------
reset_log
H="$(new_home)"
res="$(PY_RUN "${H}" "
import sched_platform
sched_platform.install_scheduled_job('com.ccgmtest.foreign', 'echo hi', 4, 30)
")"
assert_nonzero "${res%%|*}" "sched_platform.install_scheduled_job refuses under a foreign HOME"
assert_contains "${res#*|}" "ForeignHomeError" "install raises ForeignHomeError"
assert_contains "${res#*|}" "--no-schedule" "refusal message names --no-schedule"
assert_eq "$(log_text)" "" "install under foreign HOME: launchctl not called"
assert_eq "$([ -e "${H}/Library/LaunchAgents/com.ccgmtest.foreign.plist" ] && echo yes || echo no)" "no" "install under foreign HOME writes no plist"

res="$(PY_RUN "${H}" "
import sched_platform
sched_platform.uninstall_scheduled_job('com.ccgmtest.foreign')
")"
assert_nonzero "${res%%|*}" "sched_platform.uninstall_scheduled_job refuses under a foreign HOME"
assert_eq "$(log_text)" "" "uninstall under foreign HOME: launchctl not called"

# Both installers, twice each (the incident ran them twice: the second run
# found the first run's plist and booted out the label).
for inst in "${AUTOHEAL_INSTALL}" "${DREAM_INSTALL}"; do
    name="$(basename "${inst}")"
    reset_log
    H="$(new_home)"
    for run in 1 2; do
        out="$(HOME="${H}" CCGM_AUTOHEAL_USERNAME=ccgmtest CCGM_DREAMING_USERNAME=ccgmtest bash "${inst}" 2>&1)"; rc=$?
        assert_nonzero "${rc}" "${name} run ${run} under foreign HOME refuses"
        assert_contains "${out}" "not the real home" "${name} run ${run} prints the reason"
    done
    assert_eq "$(log_text)" "" "${name} under foreign HOME: launchctl not called"
done

# ---------------------------------------------------------------------------
# 2. --no-schedule installs files without touching the scheduler.
# ---------------------------------------------------------------------------
for spec in "${AUTOHEAL_INSTALL}:.claude/autoheal/config.json" "${DREAM_INSTALL}:.claude/dreaming/config.json"; do
    inst="${spec%%:*}"; cfg="${spec#*:}"
    name="$(basename "${inst}")"
    reset_log
    H="$(new_home)"
    for run in 1 2; do
        out="$(HOME="${H}" CCGM_AUTOHEAL_USERNAME=ccgmtest CCGM_DREAMING_USERNAME=ccgmtest bash "${inst}" --no-schedule 2>&1)"; rc=$?
        assert_eq "${rc}" "0" "${name} --no-schedule run ${run} exits 0"
    done
    assert_eq "$([ -f "${H}/${cfg}" ] && echo yes || echo no)" "yes" "${name} --no-schedule wrote ${cfg}"
    assert_eq "$(log_text)" "" "${name} --no-schedule: launchctl not called"
    assert_eq "$(ls "${H}/Library/LaunchAgents")" "" "${name} --no-schedule: no plist written"
done

out="$(HOME="$(new_home)" bash "${AUTOHEAL_INSTALL}" --bogus 2>&1)"; rc=$?
assert_eq "${rc}" "2" "unknown flag exits 2"

# ---------------------------------------------------------------------------
# 3. Guard satisfied (test hatch + fake launchctl): bootstrap, then print check.
# ---------------------------------------------------------------------------
export CCGM_SCHED_ALLOW_FOREIGN_HOME=1
reset_log
H="$(new_home)"
export FAKE_PRINT_MODE=match
res="$(PY_RUN "${H}" "
import sched_platform
sched_platform.install_scheduled_job('com.ccgmtest.ok', 'echo hi', 4, 30)
print('installed')
")"
assert_eq "${res%%|*}" "0" "install with a matching loaded path succeeds"
log="$(log_text)"
assert_contains "${log}" "bootstrap gui/$(id -u) ${H}/Library/LaunchAgents/com.ccgmtest.ok.plist" "bootstrap targets the plist just written"
assert_contains "${log}" "print gui/$(id -u)/com.ccgmtest.ok" "print verifies the label after bootstrap"
assert_eq "$(echo "${log}" | sed -n 1p | cut -d' ' -f1)" "bootstrap" "bootstrap runs before print"

# autoheal-install.sh end to end through the fake.
reset_log
H="$(new_home)"
out="$(HOME="${H}" CCGM_AUTOHEAL_USERNAME=ccgmtest bash "${AUTOHEAL_INSTALL}" 2>&1)"; rc=$?
assert_eq "${rc}" "0" "autoheal-install.sh with matching loaded path exits 0"
assert_contains "$(log_text)" "bootstrap gui/$(id -u) ${H}/Library/LaunchAgents/com.ccgmtest.ccgm.autoheal.daily.plist" "autoheal-install bootstraps its plist"

reset_log
H="$(new_home)"
out="$(HOME="${H}" CCGM_DREAMING_USERNAME=ccgmtest bash "${DREAM_INSTALL}" 2>&1)"; rc=$?
assert_eq "${rc}" "0" "dream-install.sh with matching loaded path exits 0"
assert_contains "$(log_text)" "bootstrap gui/$(id -u) ${H}/Library/LaunchAgents/com.ccgmtest.ccgm.dreaming.daily.plist" "dream-install bootstraps its plist"

# ---------------------------------------------------------------------------
# 4. Loaded path differs from the plist, or print fails: fail loudly.
# ---------------------------------------------------------------------------
for mode in stale missing; do
    export FAKE_PRINT_MODE="${mode}"
    reset_log
    H="$(new_home)"
    res="$(PY_RUN "${H}" "
import sched_platform
sched_platform.install_scheduled_job('com.ccgmtest.bad', 'echo hi', 4, 30)
")"
    assert_nonzero "${res%%|*}" "install fails when launchctl print is '${mode}'"
    assert_contains "${res#*|}" "is not loaded from" "'${mode}' failure message says which path mismatched"

    out="$(HOME="${H}" CCGM_AUTOHEAL_USERNAME=ccgmtest bash "${AUTOHEAL_INSTALL}" 2>&1)"; rc=$?
    assert_nonzero "${rc}" "autoheal-install.sh exits non-zero when print is '${mode}'"
    out="$(HOME="${H}" CCGM_DREAMING_USERNAME=ccgmtest bash "${DREAM_INSTALL}" 2>&1)"; rc=$?
    assert_nonzero "${rc}" "dream-install.sh exits non-zero when print is '${mode}'"
done
unset CCGM_SCHED_ALLOW_FOREIGN_HOME FAKE_PRINT_MODE

# ---------------------------------------------------------------------------
# 5. HOME equal to the passwd home passes the guard. Calls only the check, so
# nothing is written under the real home.
# ---------------------------------------------------------------------------
res="$(PYTHONPATH="${LIB_DIR}" python3 -c "
import os, pwd
os.environ['HOME'] = pwd.getpwuid(os.getuid()).pw_dir
import sched_platform
sched_platform._check_real_home('test')
print('allowed')
" 2>&1)"
assert_eq "${res}" "allowed" "real passwd home passes the guard"

echo ""
echo "test-sched-foreign-home.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
