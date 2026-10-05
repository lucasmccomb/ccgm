#!/usr/bin/env bash
# test-heartbeat.sh
#
# autoheal-daily.sh writes ~/.claude/autoheal/health.json from an EXIT trap and
# exits non-zero when the analyze step fails (#1099 items 3.4 / B11). Stub steps
# stand in for the real ones; no API call, no launchctl (a fake records argv).
#
# Run: bash modules/autoheal/tests/test-heartbeat.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DAILY="${MODULE_ROOT}/bin/autoheal-daily.sh"

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

TMP="$(mktemp -d -t autoheal-heartbeat-test.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

BIN="${TMP}/bin"
FAKEBIN="${TMP}/fakebin"
AH="${TMP}/autoheal"
mkdir -p "${BIN}" "${FAKEBIN}" "${TMP}/logs" "${TMP}/home" "${AH}"

# A fake launchctl first on PATH: records argv, does nothing. The wrapper must
# never call it; the assertion at the end checks the record stays empty.
cat > "${FAKEBIN}/launchctl" <<STUB
#!/usr/bin/env bash
echo "\$@" >> "${TMP}/launchctl.argv"
exit 0
STUB
chmod +x "${FAKEBIN}/launchctl"

# stub <name> <exit-code> [extra shell]
stub() {
    printf '#!/usr/bin/env bash\n%s\nexit %s\n' "${3:-:}" "$2" > "${BIN}/autoheal-$1.sh"
    chmod +x "${BIN}/autoheal-$1.sh"
}
reset_stubs() {
    rm -f "${BIN}"/*.sh "${AH}/health.json" "${AH}/last-run.json" "${AH}/cost.log"
    for s in analyze auto-apply digest email publish retention; do stub "${s}" 0; done
}

# run_daily <config-json>  -> sets RC
run_daily() {
    rm -f "${TMP}/logs/"*
    printf '%s\n' "$1" > "${TMP}/config.json"
    PATH="${FAKEBIN}:${PATH}" \
    HOME="${TMP}/home" \
    CCGM_AUTOHEAL_DIR="${AH}" \
    CCGM_AUTOHEAL_CONFIG="${TMP}/config.json" \
    CCGM_AUTOHEAL_BIN_DIR="${BIN}" \
    CCGM_AUTOHEAL_LOGS_DIR="${TMP}/logs" \
    CCGM_AUTOHEAL_TODAY="2026-01-02" \
    CCGM_AUTOHEAL_HOOK_LIB="${MODULE_ROOT}/../hooks/lib" \
    bash "${DAILY}" 2>/dev/null
    RC=$?
}
# hj <python expression over d>
hj() {
    python3 -c "import json,sys; d=json.load(open('${AH}/health.json')); print($1)" 2>/dev/null || echo "MISSING"
}
nonzero() { [ "$1" -ne 0 ] && echo nonzero || echo zero; }

# 1. All steps ok -> status ok, exit 0, shared top-level shape present.
reset_stubs
run_daily '{}'
assert_eq "${RC}" "0" "ok: exit 0"
assert_eq "$(hj "d['status']")" "ok" "ok: status"
assert_eq "$(hj "all(k in d for k in ('generated_at','last_success_at','started_at','finished_at','reasons','steps'))")" "True" "ok: top-level fields"
assert_eq "$(hj "d['steps']['analyze']")" "0" "ok: analyze rc recorded"
assert_eq "$(hj "len(d['reasons'])")" "0" "ok: no reasons"
assert_eq "$(hj "d['last_success_at'] == d['finished_at']")" "True" "ok: last_success_at is this run"

# 2. Analyzer exits 127 (the 31-day failure) -> failed, wrapper exits non-zero.
reset_stubs
stub analyze 127
run_daily '{}'
assert_eq "$(nonzero "${RC}")" "nonzero" "analyze 127: wrapper exit non-zero"
assert_eq "$(hj "d['status']")" "failed" "analyze 127: status failed"
assert_eq "$(hj "d['reasons'][0]['code']")" "analyze_failed" "analyze 127: reason code"
assert_eq "$(hj "d['steps']['analyze']")" "127" "analyze 127: rc recorded"
assert_eq "$(hj "d['last_success_at']")" "None" "analyze 127: no success yet"

# 3. Analyzer killed mid-run (SIGKILL) -> failed, non-zero, health.json still written.
reset_stubs
stub analyze 0 'kill -9 $$'
run_daily '{}'
assert_eq "$(nonzero "${RC}")" "nonzero" "killed analyzer: exit non-zero"
assert_eq "$(hj "d['status']")" "failed" "killed analyzer: status failed"
assert_eq "$(hj "d['steps']['analyze']")" "137" "killed analyzer: rc 137"

# 4. A later step failing with a healthy analyzer -> partial, exit 0 (analyzer is the gate).
reset_stubs
stub digest 1
run_daily '{}'
assert_eq "${RC}" "0" "digest fails: exit 0"
assert_eq "$(hj "d['status']")" "partial" "digest fails: status partial"
assert_eq "$(hj "d['reasons'][0]['code']")" "step_failed" "digest fails: reason code"

# 5. Missing analyzer script (the wrapper cannot run it) -> failed, exit non-zero.
reset_stubs
rm -f "${BIN}/autoheal-analyze.sh"
run_daily '{}'
assert_eq "$(nonzero "${RC}")" "nonzero" "missing analyzer: exit non-zero"
assert_eq "$(hj "d['status']")" "failed" "missing analyzer: status failed"

# 6. Paused -> status paused, exit 0, counts as a success for staleness, no step ran.
reset_stubs
stub analyze 0 "echo ran >> ${TMP}/ran"
rm -f "${TMP}/ran"
run_daily '{"paused": true}'
assert_eq "${RC}" "0" "paused: exit 0"
assert_eq "$(hj "d['status']")" "paused" "paused: status"
assert_eq "$(hj "d['last_success_at'] is not None")" "True" "paused: counts as success"
assert_eq "$([ -f "${TMP}/ran" ] && echo ran || echo none)" "none" "paused: no step ran"

# 7. Daily cap: analyzer exits 2 AND records daily_cap_refused -> explicit non-failure.
reset_stubs
stub analyze 2 "printf '{\"date\":\"2026-01-02\",\"outcome\":\"daily_cap_refused\",\"rc\":2}\n' > ${AH}/last-run.json"
run_daily '{}'
assert_eq "${RC}" "0" "daily cap: exit 0"
assert_eq "$(hj "d['status']")" "ok" "daily cap: not a failure"
assert_eq "$(hj "d['outcome']")" "daily_cap_refused" "daily cap: explicit outcome"
assert_eq "$(hj "d['reasons'][0]['code']")" "daily_cap_reached" "daily cap: reason code"

# 8. Exit 2 with NO recorded refusal is not inferred to be a cap stop -> failed.
reset_stubs
stub analyze 2
run_daily '{}'
assert_eq "$(nonzero "${RC}")" "nonzero" "bare exit 2: exit non-zero"
assert_eq "$(hj "d['status']")" "failed" "bare exit 2: status failed"

# 9. A refusal recorded for another date does not excuse today's exit 2.
reset_stubs
stub analyze 2 "printf '{\"date\":\"2025-12-31\",\"outcome\":\"daily_cap_refused\",\"rc\":2}\n' > ${AH}/last-run.json"
run_daily '{}'
assert_eq "$(hj "d['status']")" "failed" "stale refusal date: still failed"

# 10. A last-run.json left by an earlier run never excuses a fresh failure.
reset_stubs
printf '{"date":"2026-01-02","outcome":"daily_cap_refused","rc":2}\n' > "${AH}/last-run.json"
stub analyze 2
run_daily '{}'
assert_eq "$(hj "d['status']")" "failed" "pre-existing refusal record cleared before analyze"

# 11. Calls and cost come from today's cost.log rows; last_success_at carries forward.
reset_stubs
stub analyze 0 "printf '2026-01-02\t10\t5\t0.250000\tm\n2026-01-02\t10\t5\t0.150000\tm\n2026-01-01\t1\t1\t9.000000\tm\n' >> ${AH}/cost.log"
run_daily '{}'
assert_eq "$(hj "d['calls']")" "2" "cost: calls today"
assert_eq "$(hj "round(d['cost_usd'],2)")" "0.4" "cost: spend today"
FIRST_OK="$(hj "d['last_success_at']")"
stub analyze 1
sleep 1
run_daily '{}'
assert_eq "$(hj "d['status']")" "failed" "carry-forward: now failed"
assert_eq "$(hj "d['last_success_at']")" "${FIRST_OK}" "carry-forward: last_success_at kept"

# 12. The wrapper never touched launchctl.
assert_eq "$([ -f "${TMP}/launchctl.argv" ] && echo called || echo untouched)" "untouched" "launchctl never called"

echo ""
echo "test-heartbeat.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
