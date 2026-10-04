#!/usr/bin/env bash
# test-paused-flag.sh
#
# autoheal-daily.sh honours `paused: true` (user config or per-repo override):
# it logs "paused", runs no step, appends nothing to cost.log, and exits 0.
# A stub step records every run, so "no step ran" is checked directly.
#
# Run: bash modules/autoheal/tests/test-paused-flag.sh

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

TMP="$(mktemp -d -t autoheal-paused-test.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

BIN="${TMP}/bin"
mkdir -p "${BIN}" "${TMP}/logs" "${TMP}/home"
# Stub analyzer: records the run and appends a cost.log row, like the real one.
cat > "${BIN}/autoheal-analyze.sh" <<STUB
#!/usr/bin/env bash
echo ran >> "${TMP}/ran"
echo "row" >> "${TMP}/cost.log"
STUB
chmod +x "${BIN}/autoheal-analyze.sh"

# run_daily <config-json|-> [cwd]  -> sets RC; resets the run record.
run_daily() {
    rm -f "${TMP}/ran" "${TMP}/cost.log" "${TMP}/logs/"*
    if [ "$1" = "-" ]; then
        rm -f "${TMP}/config.json"
    else
        printf '%s\n' "$1" > "${TMP}/config.json"
    fi
    (
        cd "${2:-${TMP}}" || exit 99
        HOME="${TMP}/home" \
        CCGM_AUTOHEAL_CONFIG="${TMP}/config.json" \
        CCGM_AUTOHEAL_BIN_DIR="${BIN}" \
        CCGM_AUTOHEAL_LOGS_DIR="${TMP}/logs" \
        CCGM_AUTOHEAL_TODAY="2026-01-02" \
        CCGM_AUTOHEAL_HOOK_LIB="${MODULE_ROOT}/../hooks/lib" \
        bash "${DAILY}"
    )
    RC=$?
}
ran() { [ -f "${TMP}/ran" ] && echo yes || echo no; }
logged_paused() { grep -q '\] paused' "${TMP}/logs/autoheal-daily-2026-01-02.log" && echo yes || echo no; }

# 1. paused: true -> exit 0, "paused" logged, no step, no cost.log.
run_daily '{"paused": true}'
assert_eq "${RC}" "0" "paused: exit 0"
assert_eq "$(ran)" "no" "paused: no step ran"
assert_eq "$([ -f "${TMP}/cost.log" ] && echo yes || echo no)" "no" "paused: cost.log untouched"
assert_eq "$(logged_paused)" "yes" "paused: log says paused"

# 2. paused: false and absent key -> steps run.
run_daily '{"paused": false}'
assert_eq "$(ran)" "yes" "paused=false: step ran"
run_daily '{}'
assert_eq "$(ran)" "yes" "paused absent: step ran"

# 3. Missing and malformed config -> not paused (fail toward running, as before).
run_daily -
assert_eq "$(ran)" "yes" "missing config: step ran"
run_daily '{not json'
assert_eq "$(ran)" "yes" "malformed config: step ran"

# 4. A string "true" is not the boolean; only true pauses.
run_daily '{"paused": "true"}'
assert_eq "$(ran)" "yes" "paused=\"true\" (string): step ran"

# 5. Per-repo override: .autoheal/config.json found from cwd wins over user config.
REPO="${TMP}/repo"
mkdir -p "${REPO}/.autoheal" "${REPO}/sub/dir"
printf '{"paused": true}\n' > "${REPO}/.autoheal/config.json"
run_daily '{"paused": false}' "${REPO}/sub/dir"
assert_eq "$(ran)" "no" "per-repo paused=true overrides user paused=false"
printf '{"paused": false}\n' > "${REPO}/.autoheal/config.json"
run_daily '{"paused": true}' "${REPO}/sub/dir"
assert_eq "$(ran)" "yes" "per-repo paused=false overrides user paused=true"

echo ""
echo "test-paused-flag.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
