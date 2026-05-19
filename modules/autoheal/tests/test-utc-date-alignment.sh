#!/usr/bin/env bash
# test-utc-date-alignment.sh
#
# Regression test for issue #520: the autoheal daily/digest chain must
# key on UTC dates (matching the events/proposals/digests filenames
# written by the hooks and analyzer), not on local date. When the host
# is in a westerly timezone late in the local day, the UTC day has
# already rolled — using `date +%Y-%m-%d` would silently look for
# yesterday's files and miss today's UTC-dated content.
#
# Three assertions:
#   1. Default invocation (no CCGM_AUTOHEAL_TODAY) writes daily log +
#      digest under today's UTC date.
#   2. Forcing TZ=America/Adak (UTC-9/-10) where local trails UTC still
#      finds today's UTC-dated proposals and writes today's UTC-dated
#      digest — proving the chain is TZ-immune.
#   3. CCGM_AUTOHEAL_TODAY override still wins.
#
# Run: bash modules/autoheal/tests/test-utc-date-alignment.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"

DAILY_SCRIPT="${MODULE_ROOT}/bin/autoheal-daily.sh"
DIGEST_SCRIPT="${MODULE_ROOT}/bin/autoheal-digest.sh"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-utc.XXXXXX)"

cleanup() {
    rm -rf "${TMPROOT}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

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

assert_file_exists() {
    local path="$1"
    local label="$2"
    if [ -f "${path}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected file: ${path}"
    fi
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for f in "${DAILY_SCRIPT}" "${DIGEST_SCRIPT}"; do
    if [ ! -f "${f}" ]; then
        echo "FATAL: missing required file: ${f}"
        exit 1
    fi
done

for tool in python3 jq; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "FATAL: ${tool} required on PATH"
        exit 1
    fi
done

# UTC date computed identically to how the source scripts now compute it.
UTC_TODAY="$(date -u +%Y-%m-%d)"

# ---------------------------------------------------------------------------
# Helper: seed a minimal proposals file so the digest has something to render.
# Mirrors the shape produced by autoheal-analyze.sh (id, title, kind,
# confidence, breadth_score, occurrence_count, session_ids, rationale).
# ---------------------------------------------------------------------------

seed_proposals() {
    local autoheal_dir="$1"
    local day_iso="$2"
    mkdir -p "${autoheal_dir}/proposals"
    cat > "${autoheal_dir}/proposals/${day_iso}.jsonl" <<EOF
{"id":"prop-utc-test-01","title":"UTC alignment regression seed","kind":"settings_allow_add","confidence":9,"breadth_score":1,"occurrence_count":3,"session_ids":["sess-utc-1"],"rationale":"Synthetic proposal for issue #520 regression test."}
EOF
}

# ---------------------------------------------------------------------------
# Assertion 1: Default invocation — daily log uses today's UTC date.
# ---------------------------------------------------------------------------
#
# Invoke autoheal-daily.sh with a fresh, empty autoheal/logs dir and no
# CCGM_AUTOHEAL_TODAY override. Assert: a daily log file named
# autoheal-daily-${UTC_TODAY}.log is created (no LOCAL-dated file). The
# inner steps (analyzer, digest, etc.) are best-effort and may exit 0
# with no work — that's fine. We assert ONLY on the log filename
# because the filename is what proves the date computation.

A1_HOME="${TMPROOT}/a1"
A1_AUTOHEAL="${A1_HOME}/.claude/autoheal"
A1_LOGS="${A1_HOME}/.claude/logs"
mkdir -p "${A1_AUTOHEAL}/events" "${A1_AUTOHEAL}/proposals" \
         "${A1_AUTOHEAL}/digests" "${A1_AUTOHEAL}/sent" "${A1_LOGS}"
# Empty config disables anything optional (resend, webhook).
printf '{}\n' > "${A1_AUTOHEAL}/config.json"

env \
    HOME="${A1_HOME}" \
    CCGM_AUTOHEAL_DIR="${A1_AUTOHEAL}" \
    CCGM_AUTOHEAL_LOGS_DIR="${A1_LOGS}" \
    bash "${DAILY_SCRIPT}" >/dev/null 2>&1 || true

assert_file_exists "${A1_LOGS}/autoheal-daily-${UTC_TODAY}.log" \
    "assertion 1: daily log named with UTC date (${UTC_TODAY})"

# Belt-and-braces: confirm no LOCAL-dated log was created when local != UTC.
LOCAL_TODAY="$(date +%Y-%m-%d)"
if [ "${LOCAL_TODAY}" != "${UTC_TODAY}" ]; then
    if [ ! -f "${A1_LOGS}/autoheal-daily-${LOCAL_TODAY}.log" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: assertion 1: LOCAL-dated log (${LOCAL_TODAY}) wrongly created alongside UTC log"
    fi
fi

# Confirm the log header line itself states the UTC date — proves the
# value flowed all the way through to the start banner, not just the
# filename.
HEADER="$(head -n 1 "${A1_LOGS}/autoheal-daily-${UTC_TODAY}.log" 2>/dev/null || echo "")"
case "${HEADER}" in
    *"autoheal-daily start (${UTC_TODAY})"*)
        PASS=$((PASS + 1))
        ;;
    *)
        FAIL=$((FAIL + 1))
        echo "FAIL: assertion 1: daily log header missing UTC date"
        echo "  header: ${HEADER}"
        ;;
esac

# ---------------------------------------------------------------------------
# Assertion 2: TZ=America/Adak (UTC-9/-10) — chain still keys on UTC.
# ---------------------------------------------------------------------------
#
# Adak local trails UTC by 9 or 10 hours, so for ~40% of the day local
# and UTC are different dates. We use the digest script directly (rather
# than the whole daily wrapper) because it's the simplest stage that
# proves the chain looks up files by the right date — it reads
# proposals/{date}.jsonl and writes digests/{date}.md, both date-keyed.
#
# Setup: seed proposals at UTC-today. Run digest under TZ=America/Adak.
# Assert: digest file appears at UTC-today, not at local-today. If we
# get a digest under Adak-local-today, the chain has the bug we are
# fixing.

A2_AUTOHEAL="${TMPROOT}/a2/autoheal"
mkdir -p "${A2_AUTOHEAL}/proposals" "${A2_AUTOHEAL}/digests" \
         "${A2_AUTOHEAL}/sent"
printf '{}\n' > "${A2_AUTOHEAL}/config.json"
seed_proposals "${A2_AUTOHEAL}" "${UTC_TODAY}"

env \
    TZ="America/Adak" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${A2_AUTOHEAL}/proposals" \
    CCGM_AUTOHEAL_DIGESTS_DIR="${A2_AUTOHEAL}/digests" \
    CCGM_AUTOHEAL_SENT_DIR="${A2_AUTOHEAL}/sent" \
    CCGM_AUTOHEAL_CONFIG="${A2_AUTOHEAL}/config.json" \
    bash "${DIGEST_SCRIPT}" >/dev/null 2>&1 || true

assert_file_exists "${A2_AUTOHEAL}/digests/${UTC_TODAY}.md" \
    "assertion 2: digest written under UTC date even when TZ=America/Adak"

# What is "local today" inside the Adak TZ? Compute and verify the
# alt-named digest was NOT created.
ADAK_TODAY="$(TZ=America/Adak date +%Y-%m-%d)"
if [ "${ADAK_TODAY}" != "${UTC_TODAY}" ]; then
    if [ ! -f "${A2_AUTOHEAL}/digests/${ADAK_TODAY}.md" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: assertion 2: Adak-local-dated digest (${ADAK_TODAY}) wrongly written"
    fi
else
    # The local Adak date happens to equal UTC right now; the negative
    # check is a no-op. Don't fail the assertion — but record that we
    # could not exercise the cross-date case at this moment.
    echo "NOTE: assertion 2: TZ=America/Adak local date equals UTC right now (${UTC_TODAY}); cross-date case not exercised this run."
fi

# ---------------------------------------------------------------------------
# Assertion 3: CCGM_AUTOHEAL_TODAY override is honored.
# ---------------------------------------------------------------------------
#
# Set CCGM_AUTOHEAL_TODAY to an arbitrary historical date and confirm the
# daily log filename reflects it. This guards the override path that
# tests depend on.

A3_HOME="${TMPROOT}/a3"
A3_AUTOHEAL="${A3_HOME}/.claude/autoheal"
A3_LOGS="${A3_HOME}/.claude/logs"
mkdir -p "${A3_AUTOHEAL}/events" "${A3_AUTOHEAL}/proposals" \
         "${A3_AUTOHEAL}/digests" "${A3_AUTOHEAL}/sent" "${A3_LOGS}"
printf '{}\n' > "${A3_AUTOHEAL}/config.json"

OVERRIDE_DATE="2026-01-15"
env \
    HOME="${A3_HOME}" \
    CCGM_AUTOHEAL_DIR="${A3_AUTOHEAL}" \
    CCGM_AUTOHEAL_LOGS_DIR="${A3_LOGS}" \
    CCGM_AUTOHEAL_TODAY="${OVERRIDE_DATE}" \
    bash "${DAILY_SCRIPT}" >/dev/null 2>&1 || true

assert_file_exists "${A3_LOGS}/autoheal-daily-${OVERRIDE_DATE}.log" \
    "assertion 3: CCGM_AUTOHEAL_TODAY override honored (${OVERRIDE_DATE})"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "=== test-utc-date-alignment.sh ==="
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"

if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
