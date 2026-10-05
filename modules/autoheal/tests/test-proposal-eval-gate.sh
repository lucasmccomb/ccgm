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
#     A4b. A rule_insert row from the drafting analyzer (markdown diff, no
#         allow-rules) fails too: this eval scores allow-rule proposals only.
#     A5. Token-prefix safety: a "git diff" rule must NOT subsume
#         "git difftool" (no regression on the difftool guard scenario).
#     A6. A dangerous broad rule ("Bash(sudo:*)" / "Bash(rm:*)") that hits
#         a deny scenario is a regression (exit 1).
#
#   The former PART B (the eval gate inside bin/autoheal-auto-apply.sh) is
#   gone: auto-apply now gates rule_insert rows on validate() and its own
#   criteria (#1099 Phase 4.2, test-auto-apply-gate.sh), and this allow-rule
#   eval no longer runs in the auto-apply path.
#
# Run: bash modules/autoheal/tests/test-proposal-eval-gate.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EVAL_LIB="${MODULE_ROOT}/lib/proposal-eval.py"
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
empty_rec='{"id":"p","kind":"settings_allow_add","diff":""}'
out="$(printf '%s' "${empty_rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
assert_eq "$?" "1" "A4: empty proposal fails (exit 1)"
assert_contains "${out}" "no allow-rules" "A4: reason explains no rules"

# A4b: a rule_insert row as the drafting analyzer writes it carries a diff to a
# markdown rule file. It has no allow-rules to score, so this eval refuses it
# rather than passing it by default.
ri_rec='{"id":"abc123def456","kind":"rule_insert","state":"ready","target":"modules/code-quality/rules/code-quality.md","diff":"--- a/modules/code-quality/rules/code-quality.md\n+++ b/modules/code-quality/rules/code-quality.md\n@@ -1,3 +1,4 @@\n # Code Quality\n+- Bash runs under zsh.\n \n x\n"}'
out="$(printf '%s' "${ri_rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
assert_eq "$?" "1" "A4b: analyzer rule_insert row fails the allow-rule eval (exit 1)"
assert_contains "${out}" "no allow-rules" "A4b: reason explains no rules"

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
print(json.dumps({"id": "p", "kind": "settings_allow_add", "diff": diff}))
PY
)"
out="$(printf '%s' "${diff_rec}" | python3 "${EVAL_LIB}" - "${SCENARIOS}" 2>&1)"
assert_eq "$?" "1" "A6c: over-broad rule parsed from real diff is blocked"
assert_contains "${out}" '"Bash(git:*)"' "A6c: rule extracted from the diff"


echo ""
echo "test-proposal-eval-gate.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
