#!/usr/bin/env bash
# Test modules/autoheal/bin/permission-audit.sh.
#
# Verifies (per plan.md §5 Epic 5):
#   - Default run against the in-tree CCGM state mentions every hook by name
#   - Each hook gets a classification (one of bypass-suppressible /
#     bypass-retained / legacy)
#   - Deny count is reported
#   - --format json produces valid JSON (pipe through `jq -e .`)
#   - Fixture run with --hooks-dir + --settings-file overrides correctly
#     classifies the 3 fixture hooks
#
# Run: bash modules/autoheal/tests/test-permission-audit.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
AUDIT="${MODULE_ROOT}/bin/permission-audit.sh"

HOOKS_DIR="${REPO_ROOT}/modules/hooks/hooks"
SETTINGS_FILE="${REPO_ROOT}/modules/settings/settings.base.json"

FIXTURE_HOOKS_DIR="${MODULE_ROOT}/tests/fixtures/audit-hooks"
FIXTURE_SETTINGS="${MODULE_ROOT}/tests/fixtures/audit-settings.json"

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
            echo "FAIL: ${label} (missing: ${needle})"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [ ! -x "${AUDIT}" ]; then
    echo "FATAL: audit script not executable: ${AUDIT}"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "FATAL: jq is required for this test"
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Default text run against in-tree paths.
# ---------------------------------------------------------------------------

TEXT_OUTPUT="$(bash "${AUDIT}" --hooks-dir "${HOOKS_DIR}" --settings-file "${SETTINGS_FILE}" --format text 2>&1)"
TEXT_EXIT=$?
assert_eq "${TEXT_EXIT}" "0" "text run exits 0"

# Mentions the headers.
assert_contains "${TEXT_OUTPUT}" "Hook classification" "text run has Hook classification section"
assert_contains "${TEXT_OUTPUT}" "Deny list"           "text run has Deny list section"
assert_contains "${TEXT_OUTPUT}" "Misalignments"       "text run has Misalignments section"
assert_contains "${TEXT_OUTPUT}" "Summary"             "text run has Summary section"

# Mentions every .py hook in the hooks dir by name.
while IFS= read -r hook_path; do
    hook_name="$(basename "${hook_path}")"
    assert_contains "${TEXT_OUTPUT}" "${hook_name}" "text run mentions ${hook_name}"
done < <(find "${HOOKS_DIR}" -maxdepth 1 -name "*.py" -type f | sort)

# Reports deny count (non-zero in current state).
assert_contains "${TEXT_OUTPUT}" "count: " "text run reports deny count"

# Specific classifications we know are stable post-Epic-1.
assert_contains "${TEXT_OUTPUT}" "check-careful.py" "mentions check-careful.py"
# Each line containing check-careful should also carry bypass-suppressible.
careful_line="$(printf '%s\n' "${TEXT_OUTPUT}" | grep '^check-careful.py' || true)"
assert_contains "${careful_line}" "bypass-suppressible" "check-careful.py is bypass-suppressible"

mig_line="$(printf '%s\n' "${TEXT_OUTPUT}" | grep '^check-migration-timestamps.py' || true)"
assert_contains "${mig_line}" "bypass-retained" "check-migration-timestamps.py is bypass-retained"

# ---------------------------------------------------------------------------
# 2. JSON mode produces valid JSON.
# ---------------------------------------------------------------------------

JSON_OUTPUT="$(bash "${AUDIT}" --hooks-dir "${HOOKS_DIR}" --settings-file "${SETTINGS_FILE}" --format json 2>&1)"
JSON_EXIT=$?
assert_eq "${JSON_EXIT}" "0" "json run exits 0"

if printf '%s' "${JSON_OUTPUT}" | jq -e . >/dev/null 2>&1; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: json run output is not valid JSON"
fi

# Top-level fields.
for field in hooks_dir settings_file hooks deny_count misalignments summary; do
    if printf '%s' "${JSON_OUTPUT}" | jq -e ".${field}" >/dev/null 2>&1; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: json missing top-level field: ${field}"
    fi
done

# Every hook is in the hooks[] array.
JSON_HOOK_COUNT="$(printf '%s' "${JSON_OUTPUT}" | jq '.hooks | length')"
FS_HOOK_COUNT="$(find "${HOOKS_DIR}" -maxdepth 1 -name "*.py" -type f | wc -l | tr -d ' ')"
assert_eq "${JSON_HOOK_COUNT}" "${FS_HOOK_COUNT}" "json hooks[] length matches filesystem"

# summary.deny_entries matches the file's actual deny length.
ACTUAL_DENY="$(jq '.permissions.deny | length' "${SETTINGS_FILE}")"
JSON_DENY="$(printf '%s' "${JSON_OUTPUT}" | jq '.summary.deny_entries')"
assert_eq "${JSON_DENY}" "${ACTUAL_DENY}" "json summary.deny_entries matches settings"

# ---------------------------------------------------------------------------
# 3. Fixture run via override flags.
# ---------------------------------------------------------------------------

FIXTURE_TEXT="$(bash "${AUDIT}" --hooks-dir "${FIXTURE_HOOKS_DIR}" --settings-file "${FIXTURE_SETTINGS}" --format text 2>&1)"
FIXTURE_EXIT=$?
assert_eq "${FIXTURE_EXIT}" "0" "fixture run exits 0"

# All 3 fixture hooks present.
assert_contains "${FIXTURE_TEXT}" "fixture-suppressible.py" "fixture run mentions fixture-suppressible.py"
assert_contains "${FIXTURE_TEXT}" "fixture-retained.py"     "fixture run mentions fixture-retained.py"
assert_contains "${FIXTURE_TEXT}" "fixture-legacy.py"       "fixture run mentions fixture-legacy.py"

# Correct classifications.
supp_line="$(printf '%s\n' "${FIXTURE_TEXT}" | grep '^fixture-suppressible.py' || true)"
assert_contains "${supp_line}" "bypass-suppressible" "fixture-suppressible.py classified bypass-suppressible"

ret_line="$(printf '%s\n' "${FIXTURE_TEXT}" | grep '^fixture-retained.py' || true)"
assert_contains "${ret_line}" "bypass-retained" "fixture-retained.py classified bypass-retained"

leg_line="$(printf '%s\n' "${FIXTURE_TEXT}" | grep '^fixture-legacy.py' || true)"
assert_contains "${leg_line}" "legacy" "fixture-legacy.py classified legacy"

# Fixture JSON: summary counts match the 3-hook fixture set.
FIXTURE_JSON="$(bash "${AUDIT}" --hooks-dir "${FIXTURE_HOOKS_DIR}" --settings-file "${FIXTURE_SETTINGS}" --format json 2>&1)"
assert_eq "$(printf '%s' "${FIXTURE_JSON}" | jq '.summary.bypass_suppressible')" "1" "fixture summary bypass_suppressible=1"
assert_eq "$(printf '%s' "${FIXTURE_JSON}" | jq '.summary.bypass_retained')"     "1" "fixture summary bypass_retained=1"
assert_eq "$(printf '%s' "${FIXTURE_JSON}" | jq '.summary.legacy')"              "1" "fixture summary legacy=1"
assert_eq "$(printf '%s' "${FIXTURE_JSON}" | jq '.summary.deny_entries')"        "2" "fixture summary deny_entries=2"

# ---------------------------------------------------------------------------
# 4. Bad input handling.
# ---------------------------------------------------------------------------

BAD_HOOKS_OUTPUT="$(bash "${AUDIT}" --hooks-dir "/nonexistent-${RANDOM}" --settings-file "${SETTINGS_FILE}" 2>&1)"
BAD_HOOKS_EXIT=$?
if [ "${BAD_HOOKS_EXIT}" -ne 0 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: missing hooks dir should exit non-zero"
fi
assert_contains "${BAD_HOOKS_OUTPUT}" "hooks dir does not exist" "missing hooks dir prints clear error"

BAD_FMT_OUTPUT="$(bash "${AUDIT}" --hooks-dir "${HOOKS_DIR}" --settings-file "${SETTINGS_FILE}" --format yaml 2>&1)"
BAD_FMT_EXIT=$?
if [ "${BAD_FMT_EXIT}" -ne 0 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: invalid --format should exit non-zero"
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-permission-audit.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
