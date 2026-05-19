#!/usr/bin/env bash
# Test suite for modules/autoheal/bin/autoheal-auto-apply.sh
#
# Covers the auto-apply confidence gate (plan.md §3.7) end-to-end. The
# test builds a temp CCGM clone (a freshly init'd git repo with the same
# layout the real apply path expects: start.sh at the root, tests/
# directory with test-modules.sh + test-no-personal-data.sh, and a
# modules/settings/settings.partial.json that the fixture diff modifies).
#
# Then it stages 6 proposals into proposals/{today}.jsonl, runs the
# script with auto_apply_enabled: true, and asserts:
#
#   - The 1 qualifying proposal (confidence 9, breadth 1, kind
#     settings_allow_add, target modules/settings/) gets a feature branch
#     autoheal/auto/{id} + commit + applied/{today}.jsonl record.
#   - The 5 rejecting proposals get NO branch and NO applied-success
#     record. The rejection reasons are:
#       a. confidence 8 (below the >=9 cutoff)
#       b. breadth 2 (above the <=1 cutoff)
#       c. kind hook_narrow (wrong kind)
#       d. target outside modules/settings/ (wrong dir)
#       e. snoozed_until in the future
#       f. auto_apply_blocked: true
#     (Six rejection axes give us six separate misses; combined with the
#     one accept, that is seven fixtures total. The plan says 5 reject +
#     1 accept; we widen to 6 reject to cover snooze AND blocked
#     explicitly. Both belong to the gate.)
#
# Plus the "switch is off" axis:
#   - auto_apply_enabled: false → no proposals applied even if all qualify.
#
# Run: bash modules/autoheal/tests/test-auto-apply-gate.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
AUTO_APPLY_SH="${MODULE_ROOT}/bin/autoheal-auto-apply.sh"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"

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
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
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
            echo "  unexpected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
}

# ---------------------------------------------------------------------
# Build the sandbox.
#
# A fake CCGM clone needs:
#   - start.sh (used by _resolve_clone_root to anchor)
#   - tests/test-modules.sh        (apply path runs these)
#   - tests/test-no-personal-data.sh
#   - modules/settings/settings.partial.json (target of fixture diff)
#   - .git initialized with a main branch + initial commit so
#     `git apply` and `git checkout -b` work.
# ---------------------------------------------------------------------

CLONE_ROOT="$(mktemp -d -t autoapply_clone.XXXXXX)"
PROPOSALS_DIR="$(mktemp -d -t autoapply_proposals.XXXXXX)"
APPLIED_DIR="$(mktemp -d -t autoapply_applied.XXXXXX)"
LOGS_DIR="$(mktemp -d -t autoapply_logs.XXXXXX)"
CONFIG_DIR="$(mktemp -d -t autoapply_config.XXXXXX)"
trap 'rm -rf "${CLONE_ROOT}" "${PROPOSALS_DIR}" "${APPLIED_DIR}" "${LOGS_DIR}" "${CONFIG_DIR}"' EXIT

CONFIG_FILE="${CONFIG_DIR}/config.json"
TODAY="2026-05-18"
PROPOSALS_FILE="${PROPOSALS_DIR}/${TODAY}.jsonl"
APPLIED_FILE="${APPLIED_DIR}/${TODAY}.jsonl"

# Seed the fake clone.
touch "${CLONE_ROOT}/start.sh"
mkdir -p "${CLONE_ROOT}/tests"
mkdir -p "${CLONE_ROOT}/modules/settings"

cat > "${CLONE_ROOT}/tests/test-modules.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "${CLONE_ROOT}/tests/test-modules.sh"

cat > "${CLONE_ROOT}/tests/test-no-personal-data.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "${CLONE_ROOT}/tests/test-no-personal-data.sh"

# Initial settings file the fixture diff edits.
cat > "${CLONE_ROOT}/modules/settings/settings.partial.json" <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(git status)"
    ]
  }
}
EOF

(
    cd "${CLONE_ROOT}"
    git init -q -b main
    git config user.email "test@example.invalid"
    git config user.name "test"
    git config commit.gpgsign false
    # Defeat global core.hooksPath so the user's pre-commit / pre-push
    # hooks do not run inside the sandbox. The apply-path commits must
    # succeed in CI as well.
    git config core.hooksPath "${CLONE_ROOT}/.git/empty-hooks"
    mkdir -p "${CLONE_ROOT}/.git/empty-hooks"
    git add -A
    git commit -q -m "init"
)

# ---------------------------------------------------------------------
# Build the fixture proposals.
#
# The QUALIFY proposal carries a real unified diff that appends one new
# allow entry to settings.partial.json. We construct the diff with python
# and inline it into the JSONL so the test does not depend on a separate
# fixture file (and so the literal `--- a/...` markers are not chopped
# by shell quoting).
# ---------------------------------------------------------------------

build_proposals() {
    python3 - "${PROPOSALS_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]

# Unified diff: add a new line to the allow array. The diff is anchored
# on the existing content (3 lines of context) so `git apply` accepts it
# against the seeded settings.partial.json.
diff_qualify = (
    "--- a/modules/settings/settings.partial.json\n"
    "+++ b/modules/settings/settings.partial.json\n"
    "@@ -1,7 +1,8 @@\n"
    " {\n"
    "   \"permissions\": {\n"
    "     \"allow\": [\n"
    "-      \"Bash(git status)\"\n"
    "+      \"Bash(git status)\",\n"
    "+      \"Bash(git diff)\"\n"
    "     ]\n"
    "   }\n"
    " }\n"
)

base = {
    "kind": "settings_allow_add",
    "title": "stub",
    "rationale": "stub",
    "confidence": 9,
    "breadth_score": 1,
    "occurrence_count": 3,
    "session_ids": ["s1", "s2"],
    "proposed_diff_target": "modules/settings/settings.partial.json",
    "proposed_diff": diff_qualify,
    "fingerprint": "stub",
    "originating_clone": "test-clone",
    "generated_at": "2026-05-18T00:00:00Z",
}


def with_id(**overrides):
    rec = dict(base)
    rec.update(overrides)
    return rec


records = [
    with_id(id="prop_qualify_01"),
    with_id(id="prop_lowconf_02", confidence=8),
    with_id(id="prop_breadth_03", breadth_score=2),
    with_id(id="prop_kind_04", kind="hook_narrow"),
    with_id(
        id="prop_target_05",
        proposed_diff_target="modules/hooks/hooks/enforce-git-workflow.py",
    ),
    with_id(id="prop_snooze_06", snoozed_until="2099-01-01T00:00:00Z"),
    with_id(id="prop_blocked_07", auto_apply_blocked=True),
]

with open(path, "w", encoding="utf-8") as fh:
    for r in records:
        fh.write(json.dumps(r) + "\n")

print(len(records))
PY
}

PROP_COUNT="$(build_proposals)"
assert_eq "${PROP_COUNT}" "7" "fixture proposal count"

# ---------------------------------------------------------------------
# Test 1: auto_apply_enabled: false → no applies at all.
# ---------------------------------------------------------------------

cat > "${CONFIG_FILE}" <<'EOF'
{ "auto_apply_enabled": false }
EOF

# Wipe the applied file before each run so we measure THIS run only.
rm -f "${APPLIED_FILE}"

out=$(
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}" \
    CCGM_AUTOHEAL_LOGS_DIR="${LOGS_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE_ROOT}" \
    bash "${AUTO_APPLY_SH}" 2>&1
)
rc=$?
assert_eq "${rc}" "0" "test 1: script exits 0 with autoapply off"
assert_contains "${out}" "auto_apply_enabled=false" \
    "test 1: stderr notes the disabled flag"

# No applied file should be created (or it should be empty).
if [ -s "${APPLIED_FILE}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: test 1: applied file should be empty when autoapply is off"
    echo "  contents:"
    cat "${APPLIED_FILE}"
else
    PASS=$((PASS + 1))
fi

# Branch with the auto-apply prefix must NOT exist.
branches=$(cd "${CLONE_ROOT}" && git branch --list 'autoheal/auto/*')
assert_eq "${branches}" "" "test 1: no autoheal/auto/* branches when autoapply is off"

# ---------------------------------------------------------------------
# Test 2: auto_apply_enabled: true → only the qualifying proposal applies.
# ---------------------------------------------------------------------

cat > "${CONFIG_FILE}" <<'EOF'
{ "auto_apply_enabled": true }
EOF

# Reset clone working tree to clean main before the gated run. The first
# test did not modify state, so this is precautionary.
(
    cd "${CLONE_ROOT}"
    git checkout -q main
    git clean -fdq
)
rm -f "${APPLIED_FILE}"

out=$(
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}" \
    CCGM_AUTOHEAL_LOGS_DIR="${LOGS_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE_ROOT}" \
    bash "${AUTO_APPLY_SH}" 2>&1
)
rc=$?
assert_eq "${rc}" "0" "test 2: script exits 0 with autoapply on"

# Summary line must show 7 evaluated, 1 qualified, 1 applied, 0 failed.
assert_contains "${out}" "evaluated=7 qualified=1" \
    "test 2: summary reports 7 evaluated, 1 qualified"
assert_contains "${out}" "applied=1 failed=0" \
    "test 2: summary reports 1 applied, 0 failed"

# Each rejected proposal should be tagged in the log with its reason.
LOG_FILE="${LOGS_DIR}/autoheal-auto-apply-${TODAY}.log"
log_content=$(cat "${LOG_FILE}" 2>/dev/null || echo "")
assert_contains "${log_content}" "prop_lowconf_02" "test 2: low-confidence skip logged"
assert_contains "${log_content}" "prop_breadth_03" "test 2: high-breadth skip logged"
assert_contains "${log_content}" "prop_kind_04"    "test 2: wrong-kind skip logged"
assert_contains "${log_content}" "prop_target_05"  "test 2: wrong-target skip logged"
assert_contains "${log_content}" "prop_snooze_06"  "test 2: snoozed skip logged"
assert_contains "${log_content}" "prop_blocked_07" "test 2: blocked skip logged"

# The qualifying proposal must have a feature branch + a commit.
branches=$(cd "${CLONE_ROOT}" && git branch --list 'autoheal/auto/prop_qualify_01')
assert_contains "${branches}" "autoheal/auto/prop_qualify_01" \
    "test 2: qualifying proposal got its autoheal/auto/* branch"

# The branch's commit message must match the apply-path format.
commit_msg=$(
    cd "${CLONE_ROOT}"
    git log -1 --format=%s autoheal/auto/prop_qualify_01 2>/dev/null || echo ""
)
expected_msg="#auto: apply autoheal proposal prop_qualify_01"
assert_eq "${commit_msg}" "${expected_msg}" \
    "test 2: commit message uses the #auto: prefix"

# The applied audit log must contain exactly one success record for the
# qualifying proposal and no records for the rejected ones.
if [ ! -f "${APPLIED_FILE}" ]; then
    FAIL=$((FAIL + 1))
    echo "FAIL: test 2: applied file was not created"
else
    success_count=$(grep -c '"proposal_id":"prop_qualify_01"' "${APPLIED_FILE}" || true)
    assert_eq "${success_count}" "1" \
        "test 2: applied/{today}.jsonl contains 1 record for prop_qualify_01"

    for rejected in prop_lowconf_02 prop_breadth_03 prop_kind_04 prop_target_05 prop_snooze_06 prop_blocked_07; do
        miss=$(grep -c "\"proposal_id\":\"${rejected}\"" "${APPLIED_FILE}" || true)
        assert_eq "${miss}" "0" \
            "test 2: applied/{today}.jsonl has NO record for ${rejected}"
    done

    # Method must be auto_apply for the success row.
    method=$(python3 -c "
import json
for line in open('${APPLIED_FILE}'):
    rec = json.loads(line)
    if rec.get('proposal_id') == 'prop_qualify_01':
        print(rec.get('method'))
        break
")
    assert_eq "${method}" "auto_apply" "test 2: applied record method=auto_apply"

    # tests_passed must be true; rolled_back false.
    tp=$(python3 -c "
import json
for line in open('${APPLIED_FILE}'):
    rec = json.loads(line)
    if rec.get('proposal_id') == 'prop_qualify_01':
        print(rec.get('tests_passed'))
        break
")
    assert_eq "${tp}" "True" "test 2: applied record tests_passed=true"

    rb=$(python3 -c "
import json
for line in open('${APPLIED_FILE}'):
    rec = json.loads(line)
    if rec.get('proposal_id') == 'prop_qualify_01':
        print(rec.get('rolled_back'))
        break
")
    assert_eq "${rb}" "False" "test 2: applied record rolled_back=false"
fi

# The settings.partial.json on the new branch must contain the new
# allow entry (proves the diff actually landed).
content=$(cd "${CLONE_ROOT}" && git show autoheal/auto/prop_qualify_01:modules/settings/settings.partial.json 2>/dev/null)
assert_contains "${content}" "Bash(git diff)" \
    "test 2: feature branch contains the applied diff"

# main must still be clean (no work leaked onto the trunk).
(
    cd "${CLONE_ROOT}"
    git checkout -q main
)
main_content=$(cat "${CLONE_ROOT}/modules/settings/settings.partial.json")
assert_not_contains "${main_content}" "Bash(git diff)" \
    "test 2: main branch is NOT modified by auto-apply"

# ---------------------------------------------------------------------
# Test 3: re-running auto-apply against the same proposals should not
# crash. The qualifying branch already exists, so apply-proposal.py
# refuses to recreate it. The failure is logged but the script exits 0.
# ---------------------------------------------------------------------

out=$(
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}" \
    CCGM_AUTOHEAL_LOGS_DIR="${LOGS_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE_ROOT}" \
    bash "${AUTO_APPLY_SH}" 2>&1
)
rc=$?
assert_eq "${rc}" "0" "test 3: re-run exits 0 even when branch already exists"
assert_contains "${out}" "applied=0 failed=1" \
    "test 3: re-run reports 1 failure (branch already exists)"

echo ""
echo "test-auto-apply-gate.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
