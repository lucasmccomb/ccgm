#!/usr/bin/env bash
# test-proposal-eval-gate.sh
#
# Tests the eval/regression harness (issue #705, epic #659) that gates
# autoheal proposal promotion. Two layers:
#
#   PART A — unit tests of lib/proposal-eval.py:
#     A1. An IMPROVING proposal (adds a narrow allow rule that resolves a
#         friction scenario, no regressions) passes (exit 0).
#     A2. A REGRESSING proposal (adds an over-broad rule that would
#         auto-allow a guard/deny scenario) fails (exit 1).
#     A3. A NO-IMPROVEMENT proposal (adds a rule that matches nothing in
#         the fixture set) fails (exit 1).
#     A4. An EMPTY proposal (no extractable allow rules) fails (exit 1).
#     A5. Token-prefix safety: a "git diff" rule must NOT subsume
#         "git difftool" (no regression on the difftool guard scenario).
#     A6. A dangerous broad rule ("Bash(sudo:*)" / "Bash(rm:*)") that hits
#         a deny scenario is a regression (exit 1).
#
#   PART B — integration with bin/autoheal-auto-apply.sh:
#     B1. A structurally-qualifying + eval-IMPROVING proposal IS applied
#         (branch + commit + applied record); summary eval_blocked=0.
#     B2. A structurally-qualifying but eval-REGRESSING proposal is
#         BLOCKED: no branch, no applied record, summary eval_blocked>=1,
#         applied=0.
#
# Run: bash modules/autoheal/tests/test-proposal-eval-gate.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EVAL_LIB="${MODULE_ROOT}/lib/proposal-eval.py"
AUTO_APPLY_SH="${MODULE_ROOT}/bin/autoheal-auto-apply.sh"
SCENARIOS="${SCRIPT_DIR}/fixtures/eval-scenarios.json"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1" expected="$2" label="$3"
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
    local haystack="$1" needle="$2" label="$3"
    case "${haystack}" in
        *"${needle}"*) PASS=$((PASS + 1)) ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
    esac
}

assert_not_contains() {
    local haystack="$1" needle="$2" label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  unexpected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
        *) PASS=$((PASS + 1)) ;;
    esac
}

# Sanity: the fixture set must exist.
if [ ! -f "${SCENARIOS}" ]; then
    echo "FAIL: scenarios fixture missing at ${SCENARIOS}"
    exit 1
fi
if [ ! -f "${EVAL_LIB}" ]; then
    echo "FAIL: eval lib missing at ${EVAL_LIB}"
    exit 1
fi

# ---------------------------------------------------------------------
# Helpers to build a single proposal record JSON to stdin of the eval CLI.
# We use `added_rules` (the explicit shortcut the lib supports) for the
# unit tests so the assertions focus on scoring, not diff parsing — except
# A5/A6 which we also exercise via a real diff to prove the diff path.
# ---------------------------------------------------------------------

# Run eval on a proposal built from an `added_rules` list. Runs in the
# CURRENT shell (no command-substitution subshell) so it can set the
# globals EVAL_OUT (JSON result) and EVAL_RC (exit code) reliably under
# `set -u`.
EVAL_OUT=""
EVAL_RC=0
run_eval_rules() {
    local rules_json="$1"
    local rec
    rec="$(python3 - "${rules_json}" <<'PY'
import json, sys
rules = json.loads(sys.argv[1])
print(json.dumps({"id": "p", "kind": "settings_allow_add", "added_rules": rules}))
PY
)"
    EVAL_OUT="$(printf '%s' "${rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
    EVAL_RC=$?
}

# ---------------------------------------------------------------------
# PART A — unit tests of the eval scoring.
# ---------------------------------------------------------------------

# A1: improving + no regression -> exit 0.
run_eval_rules '["Bash(git diff:*)"]'
assert_eq "${EVAL_RC}" "0" "A1: improving proposal passes eval (exit 0)"
assert_contains "${EVAL_OUT}" '"passed": true' "A1: result marks passed=true"
assert_contains "${EVAL_OUT}" '"improvements": 1' "A1: exactly 1 improvement (git diff)"
assert_contains "${EVAL_OUT}" '"regressions": 0' "A1: 0 regressions"

# A1b: multiple improvements still pass (git status + npm test).
run_eval_rules '["Bash(git status:*)", "Bash(npm test:*)"]'
assert_eq "${EVAL_RC}" "0" "A1b: two-improvement proposal passes"
assert_contains "${EVAL_OUT}" '"improvements": 2' "A1b: 2 improvements counted"

# A2: regressing proposal -> exit 1. "Bash(git:*)" auto-allows git push
# (a prompt-guard scenario) AND git commit -> regressions > 0.
run_eval_rules '["Bash(git:*)"]'
assert_eq "${EVAL_RC}" "1" "A2: over-broad git rule fails eval (exit 1)"
assert_contains "${EVAL_OUT}" '"passed": false' "A2: result marks passed=false"
# git:* improves git diff/status/log AND regresses git push/commit.
assert_contains "${EVAL_OUT}" '"regressions":' "A2: regressions reported"

# A3: no-improvement proposal -> exit 1. A rule matching nothing in fixtures.
run_eval_rules '["Bash(yarn build:*)"]'
assert_eq "${EVAL_RC}" "1" "A3: no-improvement proposal fails (exit 1)"
assert_contains "${EVAL_OUT}" '"improvements": 0' "A3: 0 improvements"
assert_contains "${EVAL_OUT}" '"regressions": 0' "A3: 0 regressions (harmless miss)"
assert_contains "${EVAL_OUT}" "no improvement" "A3: reason explains zero improvement"

# A4: empty proposal (no extractable rules) -> exit 1.
empty_rec='{"id":"p","kind":"settings_allow_add","proposed_diff":""}'
out="$(printf '%s' "${empty_rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
assert_eq "$?" "1" "A4: empty proposal fails (exit 1)"
assert_contains "${out}" "no allow-rules" "A4: reason explains no rules"

# A5: token-prefix safety. "Bash(git diff:*)" must NOT auto-allow
# "git difftool" (the difftool guard scenario expects prompt). Already
# covered by A1 passing (0 regressions) but assert the detail explicitly.
run_eval_rules '["Bash(git diff:*)"]'
difftool_verdict="$(printf '%s' "${EVAL_OUT}" | python3 -c "
import json, sys
r = json.loads(sys.stdin.read())
for d in r['details']:
    if d['scenario_id'] == 'git-difftool-collision':
        print('auto_allowed' if d['auto_allowed'] else 'left_alone')
        break
")"
assert_eq "${difftool_verdict}" "left_alone" \
    "A5: 'git diff' rule does NOT subsume 'git difftool' (token-prefix safety)"

# A6: dangerous broad rule hits a deny scenario -> regression, exit 1.
# "Bash(sudo:*)" auto-allows "sudo rm -rf /var" (deny). "Bash(rm:*)"
# auto-allows "rm -rf /" (deny).
run_eval_rules '["Bash(sudo:*)"]'
assert_eq "${EVAL_RC}" "1" "A6a: sudo rule blocked by deny-scenario regression"
run_eval_rules '["Bash(rm:*)"]'
assert_eq "${EVAL_RC}" "1" "A6b: rm rule blocked by deny-scenario regression"

# A6c: the regression path also fires when extracting rules from a real
# unified diff (not just the added_rules shortcut). Build a diff that adds
# an over-broad "Bash(git:*)" rule.
diff_rec="$(python3 <<'PY'
import json
diff = (
    "--- a/modules/settings/settings.partial.json\n"
    "+++ b/modules/settings/settings.partial.json\n"
    "@@ -1,5 +1,6 @@\n"
    " {\n"
    "   \"permissions\": {\n"
    "     \"allow\": [\n"
    "+      \"Bash(git:*)\",\n"
    "       \"Bash(git status)\"\n"
    "     ]\n"
    "   }\n"
    " }\n"
)
print(json.dumps({"id": "p", "kind": "settings_allow_add", "proposed_diff": diff}))
PY
)"
out="$(printf '%s' "${diff_rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
assert_eq "$?" "1" "A6c: over-broad rule parsed from real diff is blocked"
assert_contains "${out}" '"Bash(git:*)"' "A6c: rule extracted from the diff"

# ---------------------------------------------------------------------
# PART B — integration: the gate inside autoheal-auto-apply.sh.
#
# Build a fake CCGM clone (same shape as test-auto-apply-gate.sh) and run
# the real script with auto_apply_enabled: true. Two proposals, both
# structurally qualifying (confidence 9, breadth 1, settings_allow_add,
# target under modules/settings/): one eval-IMPROVING, one eval-REGRESSING.
# ---------------------------------------------------------------------

CLONE_ROOT="$(mktemp -d -t evalgate_clone.XXXXXX)"
PROPOSALS_DIR="$(mktemp -d -t evalgate_proposals.XXXXXX)"
APPLIED_DIR="$(mktemp -d -t evalgate_applied.XXXXXX)"
LOGS_DIR="$(mktemp -d -t evalgate_logs.XXXXXX)"
CONFIG_DIR="$(mktemp -d -t evalgate_config.XXXXXX)"
trap 'rm -rf "${CLONE_ROOT}" "${PROPOSALS_DIR}" "${APPLIED_DIR}" "${LOGS_DIR}" "${CONFIG_DIR}"' EXIT

CONFIG_FILE="${CONFIG_DIR}/config.json"
TODAY="2026-06-14"
PROPOSALS_FILE="${PROPOSALS_DIR}/${TODAY}.jsonl"
APPLIED_FILE="${APPLIED_DIR}/${TODAY}.jsonl"
LOG_FILE="${LOGS_DIR}/autoheal-auto-apply-${TODAY}.log"

touch "${CLONE_ROOT}/start.sh"
mkdir -p "${CLONE_ROOT}/tests" "${CLONE_ROOT}/modules/settings"
cat > "${CLONE_ROOT}/tests/test-modules.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "${CLONE_ROOT}/tests/test-no-personal-data.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "${CLONE_ROOT}/tests/test-modules.sh" "${CLONE_ROOT}/tests/test-no-personal-data.sh"

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
    git config core.hooksPath "${CLONE_ROOT}/.git/empty-hooks"
    mkdir -p "${CLONE_ROOT}/.git/empty-hooks"
    git add -A
    git commit -q -m "init"
)

# Two qualifying proposals:
#   prop_improving_01 adds "Bash(git diff)" (resolves git-diff-friction,
#     no regression -> eval PASS -> applied).
#   prop_regress_02 adds "Bash(git:*)" (broad: regresses git-push/commit
#     guards -> eval BLOCK -> not applied).
python3 - "${PROPOSALS_FILE}" <<'PY'
import json, sys
path = sys.argv[1]

diff_improving = (
    "--- a/modules/settings/settings.partial.json\n"
    "+++ b/modules/settings/settings.partial.json\n"
    "@@ -1,5 +1,6 @@\n"
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
diff_regress = (
    "--- a/modules/settings/settings.partial.json\n"
    "+++ b/modules/settings/settings.partial.json\n"
    "@@ -1,5 +1,6 @@\n"
    " {\n"
    "   \"permissions\": {\n"
    "     \"allow\": [\n"
    "-      \"Bash(git status)\"\n"
    "+      \"Bash(git status)\",\n"
    "+      \"Bash(git:*)\"\n"
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
    "fingerprint": "stub",
    "originating_clone": "test-clone",
    "generated_at": "2026-06-14T00:00:00Z",
}
recs = [
    {**base, "id": "prop_improving_01", "proposed_diff": diff_improving},
    {**base, "id": "prop_regress_02", "proposed_diff": diff_regress},
]
with open(path, "w", encoding="utf-8") as fh:
    for r in recs:
        fh.write(json.dumps(r) + "\n")
PY

cat > "${CONFIG_FILE}" <<'EOF'
{ "auto_apply_enabled": true }
EOF
rm -f "${APPLIED_FILE}"

out=$(
    CCGM_AUTOHEAL_CONFIG="${CONFIG_FILE}" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}" \
    CCGM_AUTOHEAL_LOGS_DIR="${LOGS_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE_ROOT}" \
    CCGM_AUTOHEAL_EVAL_SCENARIOS="${SCENARIOS}" \
    bash "${AUTO_APPLY_SH}" 2>&1
)
rc=$?

assert_eq "${rc}" "0" "B: script exits 0"
# Both proposals structurally qualify (2), one is eval-blocked, one applied.
assert_contains "${out}" "qualified=2" "B: summary reports 2 structurally qualified"
assert_contains "${out}" "eval_blocked=1" "B: summary reports 1 eval-blocked"
assert_contains "${out}" "applied=1 failed=0" "B: summary reports 1 applied, 0 failed"

log_content="$(cat "${LOG_FILE}" 2>/dev/null || echo "")"
assert_contains "${log_content}" "eval prop_improving_01: PASS" \
    "B: improving proposal logged as eval PASS"
assert_contains "${log_content}" "eval prop_regress_02: BLOCK" \
    "B: regressing proposal logged as eval BLOCK"
assert_contains "${log_content}" "block prop_regress_02" \
    "B: regressing proposal logged as blocked (not applied)"

# B1: the improving proposal got a branch + commit.
branches="$(cd "${CLONE_ROOT}" && git branch --list 'autoheal/auto/prop_improving_01')"
assert_contains "${branches}" "autoheal/auto/prop_improving_01" \
    "B1: improving proposal got its branch"

# B2: the regressing proposal got NO branch.
bad_branches="$(cd "${CLONE_ROOT}" && git branch --list 'autoheal/auto/prop_regress_02')"
assert_eq "${bad_branches}" "" "B2: regressing proposal got NO branch"

# B2: the regressing proposal has NO applied record.
if [ -f "${APPLIED_FILE}" ]; then
    miss="$(grep -c '"proposal_id":"prop_regress_02"' "${APPLIED_FILE}" || true)"
    assert_eq "${miss}" "0" "B2: no applied record for the regressing proposal"
    hit="$(grep -c '"proposal_id":"prop_improving_01"' "${APPLIED_FILE}" || true)"
    assert_eq "${hit}" "1" "B1: exactly 1 applied record for the improving proposal"
else
    FAIL=$((FAIL + 1))
    echo "FAIL: B: applied file not created"
fi

# main must be unchanged (neither diff leaked to trunk).
(cd "${CLONE_ROOT}" && git checkout -q main)
main_content="$(cat "${CLONE_ROOT}/modules/settings/settings.partial.json")"
assert_not_contains "${main_content}" "Bash(git diff)" "B: main not modified by improving apply"
assert_not_contains "${main_content}" "Bash(git:*)" "B: main not modified by blocked proposal"

echo ""
echo "test-proposal-eval-gate.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
