#!/usr/bin/env bash
# test-doctor.sh
#
# bin/autoheal-doctor.py diagnoses the launchd job (#1099 item 3.5). A fake
# launchctl on PATH replays a fixture and records argv; the real launchctl is
# never called and the doctor never runs the repair itself.
#
# Run: bash modules/autoheal/tests/test-doctor.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCTOR="${MODULE_ROOT}/bin/autoheal-doctor.py"

PASS=0
FAIL=0
assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}
assert_has() {
    case "$1" in
        *"$2"*) PASS=$((PASS + 1)) ;;
        *) FAIL=$((FAIL + 1)); echo "FAIL: $3"; echo "  missing: $2"; echo "  in: $1" ;;
    esac
}
assert_lacks() {
    case "$1" in
        *"$2"*) FAIL=$((FAIL + 1)); echo "FAIL: $3"; echo "  unexpected: $2" ;;
        *) PASS=$((PASS + 1)) ;;
    esac
}

TMP="$(mktemp -d -t autoheal-doctor-test.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

REAL_HOME="${TMP}/realhome"     # stands in for the real $HOME
FOREIGN="${TMP}/foreign-home"   # a temp HOME an installer wrongly used
AH="${REAL_HOME}/.claude/autoheal"
FAKEBIN="${TMP}/fakebin"
LABEL="com.tester.ccgm.autoheal.daily"
mkdir -p "${AH}" "${FAKEBIN}" "${REAL_HOME}/Library/LaunchAgents" "${FOREIGN}/Library/LaunchAgents"
: > "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist"

cat > "${FAKEBIN}/launchctl" <<STUB
#!/usr/bin/env bash
echo "\$@" >> "${TMP}/launchctl.argv"
if [ "\$1" = "print" ] && [ -f "${TMP}/print.fixture" ]; then
    cat "${TMP}/print.fixture"
    exit 0
fi
echo "Could not find service" >&2
exit 113
STUB
chmod +x "${FAKEBIN}/launchctl"

# Manifest the install check reads: two plain targets under REAL_HOME/.claude, and a
# merge entry (settings.json) that is never a file of its own.
MANIFEST="${TMP}/module.json"
mkdir -p "${REAL_HOME}/.claude/bin" "${REAL_HOME}/.claude/lib"
: > "${REAL_HOME}/.claude/bin/one.sh"
: > "${REAL_HOME}/.claude/lib/two.json"
cat > "${MANIFEST}" <<'JSON'
{"name": "autoheal", "files": {
  "bin/one.sh": {"target": "bin/one.sh", "type": "script", "template": false},
  "lib/two.json": {"target": "lib/two.json", "type": "lib", "template": false},
  "settings.partial.json": {"target": "settings.json", "type": "config", "merge": true, "template": false}
}}
JSON

# fixture <plist-path> <script-path> <last-exit> [stderr-path]
fixture() {
    local errline=""
    [ -n "${4:-}" ] && errline="stderr path = $4"
    cat > "${TMP}/print.fixture" <<EOF
gui/501/${LABEL} = {
	active count = 0
	path = $1
	state = not running
	${errline}

	program = /bin/sh
	arguments = {
		/bin/sh
		-lc
		$2
	}

	last exit code = $3
}
EOF
}

# write_health <status> <hours-ago>
write_health() {
    python3 - "${AH}/health.json" "$1" "$2" <<'PY'
import datetime as dt
import json
import sys

path, status, hours = sys.argv[1], sys.argv[2], float(sys.argv[3])
then = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump({"status": status, "generated_at": then,
           "last_success_at": then if status == "ok" else None, "reasons": []}, open(path, "w"))
PY
}

run_doctor() {
    OUT="$(PATH="${FAKEBIN}:${PATH}" \
        CCGM_DOCTOR_REAL_HOME="${REAL_HOME}" \
        CCGM_AUTOHEAL_USERNAME="tester" \
        CCGM_AUTOHEAL_DIR="${AH}" \
        CCGM_DOCTOR_MANIFEST="${MANIFEST}" \
        python3 "${DOCTOR}" "$@" 2>&1)"
    RC=$?
}

# 1. Job loaded from a foreign temp HOME, script missing there (the real failure).
GHOST="${FOREIGN}/.claude/autoheal/autoheal-daily.sh"
fixture "${FOREIGN}/Library/LaunchAgents/${LABEL}.plist" "${GHOST}" 127
printf 'ANTHROPIC_API_KEY=sk-ant-SECRETVALUE\n' > "${AH}/.env"
printf '2026-01-01\t10\t5\t0.250000\tclaude-sonnet-5\n2026-01-02\t20\t6\t0.500000\tclaude-sonnet-5\n' > "${AH}/cost.log"
write_health failed 40
run_doctor
assert_eq "${RC}" "1" "broken job: exit 1"
assert_has "${OUT}" "${GHOST}" "broken job: names the missing path"
assert_has "${OUT}" "missing" "broken job: says missing"
assert_has "${OUT}" "last exit code: 127" "broken job: last exit code"
assert_has "${OUT}" "launchctl bootout gui/" "broken job: bootout fix"
assert_has "${OUT}" "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "broken job: real plist in fix"
assert_has "${OUT}" "launchctl bootstrap gui/" "broken job: bootstrap fix"
assert_has "${OUT}" "failed" "broken job: heartbeat status"
assert_has "${OUT}" "40h" "broken job: heartbeat age"
assert_has "${OUT}" "ANTHROPIC_API_KEY: present" "broken job: key present"
assert_lacks "${OUT}" "SECRETVALUE" "broken job: key never printed"
assert_has "${OUT}" "2026-01-02	20	6	0.500000" "broken job: last cost row"

# 2. The doctor only reads: launchctl was asked to print, never to change anything.
assert_eq "$(grep -c -E '^(bootout|bootstrap|kickstart|load|unload|remove|enable)' "${TMP}/launchctl.argv")" "0" "no mutating launchctl call"
assert_has "$(cat "${TMP}/launchctl.argv")" "print gui/" "launchctl print used"

# 3. Healthy job: plist under real home, script exists, fresh heartbeat -> exit 0, no repair.
GOOD="${REAL_HOME}/.claude/autoheal/autoheal-daily.sh"
: > "${GOOD}"
fixture "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "${GOOD}" 0
write_health ok 2
run_doctor
assert_eq "${RC}" "0" "healthy: exit 0"
assert_lacks "${OUT}" "launchctl bootout" "healthy: no repair offered"

# 4. Not loaded at all -> exit 1, bootstrap only (nothing to boot out).
rm -f "${TMP}/print.fixture"
run_doctor
assert_eq "${RC}" "1" "not loaded: exit 1"
assert_has "${OUT}" "not loaded" "not loaded: says so"
assert_has "${OUT}" "launchctl bootstrap gui/" "not loaded: bootstrap fix"
assert_lacks "${OUT}" "launchctl bootout" "not loaded: no bootout"

# 5. Missing .env key, heartbeat and cost log are reported, not crashes.
fixture "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "${GOOD}" 0
rm -f "${AH}/health.json" "${AH}/.env" "${AH}/cost.log"
run_doctor
assert_eq "${RC}" "1" "no heartbeat: exit 1"
assert_has "${OUT}" "ANTHROPIC_API_KEY: missing" "no key: reported"
assert_has "${OUT}" "no health.json" "no heartbeat: reported"
assert_has "${OUT}" "no cost.log" "no cost log: reported"

# 6. Stale exit code after a repair. launchd keeps "last exit code = 127" until the
#    next scheduled fire. Evidence used: the mtime of the job's stderr file (a
#    failing launch writes there; a good run logs elsewhere) against
#    health.json generated_at. A good heartbeat newer than the stderr file
#    means the exit code predates it: reported as stale, not a problem.
ERRLOG="${TMP}/launchd.err.log"
printf 'sh: command not found\n' > "${ERRLOG}"
touch -t 202601010000 "${ERRLOG}"                 # the failure: long ago
fixture "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "${GOOD}" 127 "${ERRLOG}"
printf 'ANTHROPIC_API_KEY=sk-ant-x\n' > "${AH}/.env"
write_health ok 2                                  # the good run: 2h ago
run_doctor
assert_eq "${RC}" "0" "stale exit: not a problem, exit 0"
assert_has "${OUT}" "last exit code: 127" "stale exit: still shown"
assert_has "${OUT}" "predates the last good run at" "stale exit: says it predates the good run"
assert_has "${OUT}" "stderr" "stale exit: names the evidence used"
assert_lacks "${OUT}" "launchctl bootout" "stale exit: no repair offered"

# 7. Same exit code, but the failure is newer than the last good run: a real problem.
touch "${ERRLOG}"
write_health ok 30                                  # good run 30h ago, failure just now
run_doctor
assert_eq "${RC}" "1" "fresh failure after good run: exit 1"
assert_lacks "${OUT}" "predates the last good run" "fresh failure: not called stale"

# 8. A failed heartbeat never makes the exit code stale.
touch -t 202601010000 "${ERRLOG}"
write_health failed 2
run_doctor
assert_eq "${RC}" "1" "failed heartbeat: exit 1"
assert_lacks "${OUT}" "predates the last good run" "failed heartbeat: not stale"

# 9. No stderr path to compare: cannot prove staleness, so the exit code stays a problem.
fixture "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "${GOOD}" 127
write_health ok 2
run_doctor
assert_eq "${RC}" "1" "no stderr evidence: exit 1"
assert_lacks "${OUT}" "predates the last good run" "no stderr evidence: not stale"

# 10. Install check. Healthy launchd job and heartbeat, so the only problem is a module
#     file the installer never linked. The merge entry (settings.json) is not required.
fixture "${REAL_HOME}/Library/LaunchAgents/${LABEL}.plist" "${GOOD}" 0
write_health ok 2
printf 'ANTHROPIC_API_KEY=sk-ant-x\n' > "${AH}/.env"
run_doctor
assert_eq "${RC}" "0" "install complete: exit 0"
assert_has "${OUT}" "install: all 2 module files present" "install complete: counts the plain targets only"
rm "${REAL_HOME}/.claude/lib/two.json"
run_doctor
assert_eq "${RC}" "1" "missing module file: exit 1"
assert_has "${OUT}" "install: 1 of 2 module files missing" "missing module file: summary"
assert_has "${OUT}" "missing: lib/two.json" "missing module file: names the target"
assert_has "${OUT}" "./start.sh --add autoheal" "missing module file, no link-mode manifest: start.sh repair"
assert_lacks "${OUT}" "ln -s" "missing module file, copy mode: no ln -s"
printf '{"linkMode": true}\n' > "${REAL_HOME}/.claude/.ccgm-manifest.json"
run_doctor
RTMP="$(cd "${TMP}" && pwd -P)"
assert_has "${OUT}" "install repair (link mode" "link mode: per-target repair"
assert_has "${OUT}" "ln -s ${RTMP}/lib/two.json ${REAL_HOME}/.claude/lib/two.json" "link mode: ln -s canonical source to target"
assert_lacks "${OUT}" "start.sh" "link mode: no start.sh line"
assert_lacks "${OUT}" "launchctl bootstrap" "missing module file only: no launchd repair"
assert_lacks "${OUT}" "install_new_files" "no install_new_files mention"
assert_lacks "${OUT}" "ccgm_sync_install" "no ccgm_sync_install mention"
# A dangling symlink is missing too.
ln -s "${TMP}/nowhere" "${REAL_HOME}/.claude/lib/two.json"
run_doctor
assert_has "${OUT}" "missing: lib/two.json" "dangling symlink: counts as missing"
rm "${REAL_HOME}/.claude/lib/two.json"
: > "${REAL_HOME}/.claude/lib/two.json"

# A target or source that escapes is refused and flagged, never linked.
MANIFEST="${TMP}/escape-module.json"
cat > "${MANIFEST}" <<'JSON'
{"files": {
  "lib/two.json": {"target": "lib/two.json", "type": "lib", "template": false},
  "lib/ok.json": {"target": "../evil.json", "type": "lib", "template": false},
  "../outside.json": {"target": "lib/outside.json", "type": "lib", "template": false}
}}
JSON
rm -f "${REAL_HOME}/.claude/lib/two.json"
run_doctor
assert_eq "$(printf '%s\n' "${OUT}" | grep -c 'REFUSED')" "2" "escape: both escaping entries refused"
assert_eq "$(printf '%s\n' "${OUT}" | grep -c 'ln -s')" "1" "escape: only the contained entry is linked"
assert_lacks "${OUT}" "outside.json ${REAL_HOME}" "escape: escaping source never linked"
assert_eq "$(printf '%s\n' "${OUT}" | grep -c 'ln -s.*evil')" "0" "escape: escaping target never linked"
: > "${REAL_HOME}/.claude/lib/two.json"
rm -f "${REAL_HOME}/.claude/.ccgm-manifest.json"
MANIFEST="${TMP}/module.json"

# 11. No readable manifest: the check is skipped and does not fail the run.
MANIFEST="${TMP}/absent-module.json"
run_doctor
assert_eq "${RC}" "0" "no manifest: exit 0"
assert_has "${OUT}" "install: skipped" "no manifest: says skipped"

# 12. Default manifest (the module's own module.json) against an empty home: every real
#     plain target is reported missing, so the default path resolves and parses.
OUT="$(PATH="${FAKEBIN}:${PATH}" CCGM_DOCTOR_REAL_HOME="${TMP}/emptyhome" CCGM_AUTOHEAL_USERNAME=tester \
    CCGM_AUTOHEAL_DIR="${TMP}/emptyhome/.claude/autoheal" python3 "${DOCTOR}" 2>&1)"
assert_has "${OUT}" "module files missing under ${TMP}/emptyhome/.claude" "default manifest: read from the module"
assert_has "${OUT}" "missing: bin/autoheal-doctor.py" "default manifest: lists the doctor itself"
assert_lacks "${OUT}" "missing: settings.json" "default manifest: merge entry skipped"

echo ""
echo "test-doctor.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
