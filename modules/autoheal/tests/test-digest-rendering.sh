#!/usr/bin/env bash
# test-digest-rendering.sh
#
# Verifies modules/autoheal/bin/autoheal-digest.sh against plan.md §5 Epic 7.
#
# Assertions:
#   1. 3 proposals -> digest contains 3 entries.
#   2. 7 proposals -> digest shows 5 + "+2 more" summary.
#   3. Empty proposals -> no digest written (unless --include-empty).
#   4. Backfill: 2 unemailed past days -> digest mentions them.
#   5. Redaction: a secret in rationale -> digest has [REDACTED:...].
#
# Each assertion runs against a freshly-prepared tmpdir, with env overrides
# pointing the script at synthetic state.
#
# Run: bash modules/autoheal/tests/test-digest-rendering.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"

DIGEST_SCRIPT="${MODULE_ROOT}/bin/autoheal-digest.sh"
LIB_DIR="${REPO_ROOT}/modules/hooks/lib"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-digest-test.XXXXXX)"

cleanup() {
    rm -rf "${TMPROOT}"
}
trap cleanup EXIT

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

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            PASS=$((PASS + 1))
            ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  missing: ${needle}"
            echo "  haystack first 400 chars: $(printf '%s' "${haystack}" | head -c 400)"
            ;;
    esac
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  unexpectedly present: ${needle}"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
}

count_proposal_entries() {
    # Count level-3 markdown headings in the rendered body.
    local body="$1"
    printf '%s\n' "${body}" | grep -c '^### '
}

write_proposal() {
    # Args: file, id, title, rationale, confidence, breadth, occurrences
    local out_file="$1"
    local pid="$2"
    local title="$3"
    local rationale="$4"
    local conf="$5"
    local breadth="$6"
    local occ="$7"

    jq -nc \
        --arg id "${pid}" \
        --arg title "${title}" \
        --arg rationale "${rationale}" \
        --argjson confidence "${conf}" \
        --argjson breadth_score "${breadth}" \
        --argjson occurrence_count "${occ}" \
        '{
            id: $id,
            kind: "settings_allow_add",
            title: $title,
            rationale: $rationale,
            confidence: $confidence,
            breadth_score: $breadth_score,
            occurrence_count: $occurrence_count,
            session_ids: ["sess-1", "sess-2"],
            proposed_diff_target: "modules/settings/settings.partial.json",
            proposed_diff: "+ allow Foo",
            fingerprint: ("sha256-" + $id),
            originating_clone: "test-clone",
            generated_at: "2026-05-18T08:00:00Z"
        }' >> "${out_file}"
}

run_digest() {
    # Args: proposals_dir digests_dir sent_dir config_file today [extra args]
    local proposals_dir="$1"; shift
    local digests_dir="$1"; shift
    local sent_dir="$1"; shift
    local config_file="$1"; shift
    local today="$1"; shift
    CCGM_AUTOHEAL_PROPOSALS_DIR="${proposals_dir}" \
    CCGM_AUTOHEAL_DIGESTS_DIR="${digests_dir}" \
    CCGM_AUTOHEAL_SENT_DIR="${sent_dir}" \
    CCGM_AUTOHEAL_CONFIG="${config_file}" \
    CCGM_AUTOHEAL_TODAY="${today}" \
    CCGM_AUTOHEAL_LIB_DIR="${LIB_DIR}" \
        bash "${DIGEST_SCRIPT}" "$@"
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [ ! -f "${DIGEST_SCRIPT}" ]; then
    echo "FATAL: digest script not present: ${DIGEST_SCRIPT}"
    exit 1
fi
if [ ! -f "${LIB_DIR}/hook_utils.py" ]; then
    echo "FATAL: hook_utils.py not present: ${LIB_DIR}/hook_utils.py"
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "FATAL: jq is required"
    exit 1
fi

# ---------------------------------------------------------------------------
# Assertion 1: 3 proposals -> 3 entries.
# ---------------------------------------------------------------------------

CASE1="${TMPROOT}/case1"
mkdir -p "${CASE1}/proposals" "${CASE1}/digests" "${CASE1}/sent"
TODAY1="2026-05-18"
PROPS1="${CASE1}/proposals/${TODAY1}.jsonl"
write_proposal "${PROPS1}" "prop_a" "Allow supabase CLI" "Saw 5 approvals this week." 7 2 5
write_proposal "${PROPS1}" "prop_b" "Allow wrangler dev" "Frequent permission ask." 6 2 4
write_proposal "${PROPS1}" "prop_c" "Allow gh pr view" "Read-only command." 5 1 3

run_digest "${CASE1}/proposals" "${CASE1}/digests" "${CASE1}/sent" \
    "${CASE1}/config-missing.json" "${TODAY1}" >/dev/null 2>&1
ASSERT1_EXIT=$?
assert_eq "${ASSERT1_EXIT}" "0" "case1: digest exits 0"

DIGEST1="${CASE1}/digests/${TODAY1}.md"
if [ -f "${DIGEST1}" ]; then
    PASS=$((PASS + 1))
    BODY1="$(cat "${DIGEST1}")"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: case1: digest file not written: ${DIGEST1}"
    BODY1=""
fi
N1="$(count_proposal_entries "${BODY1}")"
assert_eq "${N1}" "3" "case1: 3 entries rendered"
assert_contains "${BODY1}" "prop_a" "case1: contains prop_a"
assert_contains "${BODY1}" "prop_b" "case1: contains prop_b"
assert_contains "${BODY1}" "prop_c" "case1: contains prop_c"
assert_contains "${BODY1}" "/autoheal-apply prop_a" "case1: apply hint for prop_a"
assert_contains "${BODY1}" "/autoheal-toggle" "case1: footer has /autoheal-toggle"
assert_contains "${BODY1}" "/autoheal-snooze" "case1: footer has /autoheal-snooze"
assert_contains "${BODY1}" "/autoheal-apply list" "case1: footer has /autoheal-apply list"
assert_not_contains "${BODY1}" "+0 more" "case1: no spurious '+N more'"

# ---------------------------------------------------------------------------
# Assertion 2: 7 proposals -> 5 + "+2 more"
# ---------------------------------------------------------------------------

CASE2="${TMPROOT}/case2"
mkdir -p "${CASE2}/proposals" "${CASE2}/digests" "${CASE2}/sent"
TODAY2="2026-05-18"
PROPS2="${CASE2}/proposals/${TODAY2}.jsonl"
write_proposal "${PROPS2}" "prop_1" "T1" "R1" 9 1 1
write_proposal "${PROPS2}" "prop_2" "T2" "R2" 8 1 1
write_proposal "${PROPS2}" "prop_3" "T3" "R3" 7 1 1
write_proposal "${PROPS2}" "prop_4" "T4" "R4" 6 1 1
write_proposal "${PROPS2}" "prop_5" "T5" "R5" 5 1 1
write_proposal "${PROPS2}" "prop_6" "T6" "R6" 4 1 1
write_proposal "${PROPS2}" "prop_7" "T7" "R7" 3 1 1

run_digest "${CASE2}/proposals" "${CASE2}/digests" "${CASE2}/sent" \
    "${CASE2}/config-missing.json" "${TODAY2}" >/dev/null 2>&1
DIGEST2="${CASE2}/digests/${TODAY2}.md"
BODY2="$(cat "${DIGEST2}" 2>/dev/null || echo "")"

N2="$(count_proposal_entries "${BODY2}")"
assert_eq "${N2}" "5" "case2: cap renders 5 entries"
assert_contains "${BODY2}" "+2 more" "case2: '+2 more' summary present"
assert_contains "${BODY2}" "see \`/autoheal-digest ${TODAY2}\`" "case2: summary links to date command"
# Sort order: confidence desc -> prop_1, prop_2, prop_3, prop_4, prop_5 are shown
# (prop_6, prop_7 hidden).
assert_contains "${BODY2}" "prop_1" "case2: top-confidence shown"
assert_not_contains "${BODY2}" "prop_6" "case2: prop_6 hidden (over cap)"
assert_not_contains "${BODY2}" "prop_7" "case2: prop_7 hidden (over cap)"

# ---------------------------------------------------------------------------
# Assertion 3: Empty proposals -> no digest written; --include-empty writes.
# ---------------------------------------------------------------------------

CASE3="${TMPROOT}/case3"
mkdir -p "${CASE3}/proposals" "${CASE3}/digests" "${CASE3}/sent"
TODAY3="2026-05-18"
# No proposals file at all.

run_digest "${CASE3}/proposals" "${CASE3}/digests" "${CASE3}/sent" \
    "${CASE3}/config-missing.json" "${TODAY3}" >/dev/null 2>&1
ASSERT3A_EXIT=$?
assert_eq "${ASSERT3A_EXIT}" "0" "case3: empty exits 0"
DIGEST3="${CASE3}/digests/${TODAY3}.md"
if [ -f "${DIGEST3}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: case3: digest file unexpectedly written for empty proposals"
else
    PASS=$((PASS + 1))
fi

# With --include-empty, the file should be written.
run_digest "${CASE3}/proposals" "${CASE3}/digests" "${CASE3}/sent" \
    "${CASE3}/config-missing.json" "${TODAY3}" --include-empty >/dev/null 2>&1
if [ -f "${DIGEST3}" ]; then
    PASS=$((PASS + 1))
    BODY3="$(cat "${DIGEST3}")"
    assert_contains "${BODY3}" "No proposals for today" "case3: include-empty body says no proposals"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: case3: digest file not written with --include-empty"
fi

# ---------------------------------------------------------------------------
# Assertion 4: Backfill: 2 unemailed past days mentioned.
# ---------------------------------------------------------------------------

CASE4="${TMPROOT}/case4"
mkdir -p "${CASE4}/proposals" "${CASE4}/digests" "${CASE4}/sent"
TODAY4="2026-05-18"
YESTERDAY4="2026-05-17"
TWO_DAYS_AGO4="2026-05-16"

# Today's proposals so the digest is rendered.
write_proposal "${CASE4}/proposals/${TODAY4}.jsonl" "prop_today" "Today's title" "Today's rationale" 6 2 3

# Past days have proposals but NO sent flag -> they should appear in backfill.
write_proposal "${CASE4}/proposals/${YESTERDAY4}.jsonl" "prop_y" "Yesterday's" "..." 6 2 3
write_proposal "${CASE4}/proposals/${TWO_DAYS_AGO4}.jsonl" "prop_two" "Two days ago" "..." 6 2 3

run_digest "${CASE4}/proposals" "${CASE4}/digests" "${CASE4}/sent" \
    "${CASE4}/config-missing.json" "${TODAY4}" >/dev/null 2>&1
BODY4="$(cat "${CASE4}/digests/${TODAY4}.md" 2>/dev/null || echo "")"

assert_contains "${BODY4}" "Backfill" "case4: backfill section present"
assert_contains "${BODY4}" "${YESTERDAY4}" "case4: backfill mentions yesterday"
assert_contains "${BODY4}" "${TWO_DAYS_AGO4}" "case4: backfill mentions two-days-ago"

# Now write sent flags for both and confirm they disappear.
: > "${CASE4}/sent/${YESTERDAY4}-aaaaaaaaaaaa.flag"
: > "${CASE4}/sent/${TWO_DAYS_AGO4}-bbbbbbbbbbbb.flag"
rm -f "${CASE4}/digests/${TODAY4}.md"
run_digest "${CASE4}/proposals" "${CASE4}/digests" "${CASE4}/sent" \
    "${CASE4}/config-missing.json" "${TODAY4}" >/dev/null 2>&1
BODY4B="$(cat "${CASE4}/digests/${TODAY4}.md" 2>/dev/null || echo "")"
assert_not_contains "${BODY4B}" "${YESTERDAY4}" "case4: backfill omits yesterday after sent flag"

# ---------------------------------------------------------------------------
# Assertion 5: Redaction of secret-shaped string in rationale.
# ---------------------------------------------------------------------------

CASE5="${TMPROOT}/case5"
mkdir -p "${CASE5}/proposals" "${CASE5}/digests" "${CASE5}/sent"
TODAY5="2026-05-18"
PROPS5="${CASE5}/proposals/${TODAY5}.jsonl"

# GitHub PAT shape: ghp_ followed by >=30 alnums.
LEAKY_SECRET="ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
write_proposal "${PROPS5}" "prop_redact" \
    "Title leaking ${LEAKY_SECRET}" \
    "Saw token ${LEAKY_SECRET} in tool input" \
    7 2 3

run_digest "${CASE5}/proposals" "${CASE5}/digests" "${CASE5}/sent" \
    "${CASE5}/config-missing.json" "${TODAY5}" >/dev/null 2>&1
BODY5="$(cat "${CASE5}/digests/${TODAY5}.md" 2>/dev/null || echo "")"

assert_contains "${BODY5}" "[REDACTED:github_pat]" "case5: digest contains [REDACTED:github_pat]"
assert_not_contains "${BODY5}" "${LEAKY_SECRET}" "case5: raw secret not in digest"

# ---------------------------------------------------------------------------
# Assertion 6: digest_enabled: false short-circuits before writing.
# ---------------------------------------------------------------------------

CASE6="${TMPROOT}/case6"
mkdir -p "${CASE6}/proposals" "${CASE6}/digests" "${CASE6}/sent"
TODAY6="2026-05-18"
write_proposal "${CASE6}/proposals/${TODAY6}.jsonl" "prop_x" "T" "R" 7 2 3

CONFIG6="${CASE6}/config.json"
echo '{"digest_enabled": false}' > "${CONFIG6}"

run_digest "${CASE6}/proposals" "${CASE6}/digests" "${CASE6}/sent" \
    "${CONFIG6}" "${TODAY6}" >/dev/null 2>&1
if [ -f "${CASE6}/digests/${TODAY6}.md" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: case6: digest_enabled:false should suppress digest write"
else
    PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-digest-rendering.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
