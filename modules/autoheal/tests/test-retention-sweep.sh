#!/usr/bin/env bash
# test-retention-sweep.sh
#
# Verifies bin/autoheal-retention.sh (plan.md §1.3, §5 Epic 12 +
# acceptance criterion "Retention sweep is idempotent").
#
# Fixture: three files at three age boundaries.
#   - 15 days old  → must remain untouched (younger than gzip_days=30)
#   - 45 days old  → must be gzipped (between gzip_days and delete_days)
#   - 75 days old  → must be deleted (older than delete_days=60)
#
# Idempotency: running the sweep a second time must produce no errors
# and no further changes to the on-disk state.
#
# Run: bash modules/autoheal/tests/test-retention-sweep.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RETENTION_SCRIPT="${MODULE_ROOT}/bin/autoheal-retention.sh"

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

assert_exists() {
    if [ -e "$1" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $2"
        echo "  missing path: $1"
    fi
}

assert_absent() {
    if [ ! -e "$1" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $2"
        echo "  unexpected path: $1"
    fi
}

if [ ! -f "${RETENTION_SCRIPT}" ]; then
    echo "FATAL: retention script missing at ${RETENTION_SCRIPT}"
    exit 1
fi

TMP=$(mktemp -d -t retention_test.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT

AUTOHEAL_DIR="${TMP}/autoheal"
mkdir -p "${AUTOHEAL_DIR}/events" \
         "${AUTOHEAL_DIR}/proposals" \
         "${AUTOHEAL_DIR}/digests" \
         "${AUTOHEAL_DIR}/applied" \
         "${AUTOHEAL_DIR}/sent"

# touch -t expects [[CC]YY]MMDDhhmm[.ss]. We compute three dates relative
# to today via python so the test is calendar-correct (handles month
# rollovers etc.).
dates_json="$(python3 - <<'PY'
import datetime, json
today = datetime.date.today()
out = {
    "d15": (today - datetime.timedelta(days=15)).strftime("%Y%m%d0000"),
    "d45": (today - datetime.timedelta(days=45)).strftime("%Y%m%d0000"),
    "d75": (today - datetime.timedelta(days=75)).strftime("%Y%m%d0000"),
    "iso15": (today - datetime.timedelta(days=15)).isoformat(),
    "iso45": (today - datetime.timedelta(days=45)).isoformat(),
    "iso75": (today - datetime.timedelta(days=75)).isoformat(),
}
print(json.dumps(out))
PY
)"

D15="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["d15"])')"
D45="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["d45"])')"
D75="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["d75"])')"
ISO15="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["iso15"])')"
ISO45="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["iso45"])')"
ISO75="$(printf '%s' "${dates_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["iso75"])')"

# Create fixture files across multiple subdirs so we exercise each one.
F_KEEP="${AUTOHEAL_DIR}/events/${ISO15}.jsonl"
F_GZIP_EVENTS="${AUTOHEAL_DIR}/events/${ISO45}.jsonl"
F_GZIP_PROPS="${AUTOHEAL_DIR}/proposals/${ISO45}.jsonl"
F_DELETE_DIGEST="${AUTOHEAL_DIR}/digests/${ISO75}.md"
F_DELETE_APPLIED="${AUTOHEAL_DIR}/applied/${ISO75}.jsonl"

echo '{"id":"e1","ts":"x"}' > "${F_KEEP}"
echo '{"id":"e2","ts":"x"}' > "${F_GZIP_EVENTS}"
echo '{"id":"p1","ts":"x"}' > "${F_GZIP_PROPS}"
echo '# digest' > "${F_DELETE_DIGEST}"
echo '{"id":"a1","ts":"x"}' > "${F_DELETE_APPLIED}"

# Backdate the file mtimes to the fixture ages.
touch -t "${D15}" "${F_KEEP}"
touch -t "${D45}" "${F_GZIP_EVENTS}" "${F_GZIP_PROPS}"
touch -t "${D75}" "${F_DELETE_DIGEST}" "${F_DELETE_APPLIED}"

# The deletion-phase files must START as .gz to exercise the delete
# branch (the sweep only deletes *.gz, not raw .jsonl). Gzip them
# without changing the mtime (gzip -n keeps the original-name field
# blank; -f overrides any existing .gz; touching after gzip preserves
# the fixture's age).
gzip -nf "${F_DELETE_DIGEST}" "${F_DELETE_APPLIED}"
touch -t "${D75}" "${F_DELETE_DIGEST}.gz" "${F_DELETE_APPLIED}.gz"

# Verify the fixture is in the expected starting shape.
assert_exists "${F_KEEP}"                "fixture: keep file exists"
assert_exists "${F_GZIP_EVENTS}"         "fixture: events gzip candidate exists"
assert_exists "${F_GZIP_PROPS}"          "fixture: proposals gzip candidate exists"
assert_exists "${F_DELETE_DIGEST}.gz"    "fixture: digest delete candidate exists (.gz)"
assert_exists "${F_DELETE_APPLIED}.gz"   "fixture: applied delete candidate exists (.gz)"

# ---------------------------------------------------------------------------
# Run 1: should gzip the 45-day files and delete the 75-day .gz files.
# ---------------------------------------------------------------------------

CCGM_AUTOHEAL_DIR="${AUTOHEAL_DIR}" \
CCGM_AUTOHEAL_RETENTION_GZIP="30" \
CCGM_AUTOHEAL_RETENTION_DELETE="60" \
    bash "${RETENTION_SCRIPT}" >"${TMP}/run1.out" 2>"${TMP}/run1.err"
rc=$?
assert_eq "${rc}" "0" "run1: exit code 0"

# 15-day file untouched (still raw).
assert_exists "${F_KEEP}"                "run1: 15-day file untouched"
assert_absent "${F_KEEP}.gz"             "run1: 15-day file NOT gzipped"

# 45-day files now gzipped.
assert_absent "${F_GZIP_EVENTS}"         "run1: 45-day events raw gone"
assert_exists "${F_GZIP_EVENTS}.gz"      "run1: 45-day events now .gz"
assert_absent "${F_GZIP_PROPS}"          "run1: 45-day proposals raw gone"
assert_exists "${F_GZIP_PROPS}.gz"       "run1: 45-day proposals now .gz"

# 75-day .gz files deleted.
assert_absent "${F_DELETE_DIGEST}.gz"    "run1: 75-day digest deleted"
assert_absent "${F_DELETE_APPLIED}.gz"   "run1: 75-day applied deleted"

# ---------------------------------------------------------------------------
# Run 2: idempotency. Same state in → same state out, no errors.
# ---------------------------------------------------------------------------

# Snapshot the file tree before run 2.
SNAP_BEFORE="$(find "${AUTOHEAL_DIR}" -type f | sort)"

CCGM_AUTOHEAL_DIR="${AUTOHEAL_DIR}" \
CCGM_AUTOHEAL_RETENTION_GZIP="30" \
CCGM_AUTOHEAL_RETENTION_DELETE="60" \
    bash "${RETENTION_SCRIPT}" >"${TMP}/run2.out" 2>"${TMP}/run2.err"
rc=$?
assert_eq "${rc}" "0" "run2: exit code 0 (idempotent)"

SNAP_AFTER="$(find "${AUTOHEAL_DIR}" -type f | sort)"

if [ "${SNAP_BEFORE}" = "${SNAP_AFTER}" ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: run2: idempotent (file tree changed on second run)"
    diff <(printf '%s\n' "${SNAP_BEFORE}") <(printf '%s\n' "${SNAP_AFTER}") | sed 's/^/    /' || true
fi

# stderr from run 2 must not contain any "failed" tokens (we're checking
# that idempotency does not generate noise).
if grep -qi 'failed' "${TMP}/run2.err"; then
    FAIL=$((FAIL + 1))
    echo "FAIL: run2: stderr contains 'failed' tokens"
    sed 's/^/    /' "${TMP}/run2.err"
else
    PASS=$((PASS + 1))
fi

echo ""
echo "test-retention-sweep.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
