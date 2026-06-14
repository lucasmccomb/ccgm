#!/usr/bin/env bash
# Test the pruned deny list shape in modules/settings/settings.base.json.
#
# Verifies (per plan.md §5 Epic 2):
#   - Exactly 13 deny entries
#   - The 4 force-push-main duplicates were removed
#   - The 13 surviving entries are the expected ones
#   - JSON parses cleanly
#
# Run: bash modules/settings/tests/test-deny-list-prune.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SETTINGS="${MODULE_ROOT}/settings.base.json"

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

assert_absent() {
    local pattern="$1"
    local label="$2"
    if jq -e ".permissions.deny | any(. == \"${pattern}\")" "${SETTINGS}" > /dev/null; then
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label} (entry still present: ${pattern})"
    else
        PASS=$((PASS + 1))
    fi
}

assert_present() {
    local pattern="$1"
    local label="$2"
    if jq -e ".permissions.deny | any(. == \"${pattern}\")" "${SETTINGS}" > /dev/null; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label} (entry missing: ${pattern})"
    fi
}

assert_allow_absent() {
    local pattern="$1"
    local label="$2"
    if jq -e ".permissions.allow | any(. == \"${pattern}\")" "${SETTINGS}" > /dev/null; then
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label} (dangerous allow entry still present: ${pattern})"
    else
        PASS=$((PASS + 1))
    fi
}

# 0. JSON validity (cheap precondition; the assertions below rely on jq).
if ! jq -e . "${SETTINGS}" > /dev/null; then
    echo "FATAL: settings.base.json is not valid JSON"
    exit 1
fi

# 1. Length is exactly 13.
deny_len=$(jq '.permissions.deny | length' "${SETTINGS}")
assert_eq "${deny_len}" "13" "deny list has exactly 13 entries"

# 2. The 4 force-push-main duplicates are gone (subsumed by check-careful.py
#    after Epic 1).
assert_absent "Bash(git push --force main:*)"                  "removed: --force main"
assert_absent "Bash(git push -f main:*)"                        "removed: -f main"
assert_absent "Bash(git push --force-with-lease origin main:*)" "removed: --force-with-lease origin main"
assert_absent "Bash(git push -f origin main:*)"                 "removed: -f origin main"

# 3. The canonical force-push-main deny survives as defense-in-depth.
assert_present "Bash(git push --force origin main:*)" "kept canonical: --force origin main"

# 4. Other deny entries survive (not regressed).
for entry in \
    "Bash(rm -rf:*)" \
    "Bash(rm -r:*)" \
    "Bash(git reset --hard:*)" \
    "Bash(git clean:*)" \
    "Bash(git branch -D:*)" \
    "Bash(docker rm:*)" \
    "Bash(docker rmi:*)" \
    "Bash(docker system prune:*)" \
    "Bash(kubectl delete:*)" \
    "Bash(DROP:*)" \
    "Bash(TRUNCATE:*)" \
    "Bash(DELETE FROM:*)"; do
    assert_present "${entry}" "kept: ${entry}"
done

# 5. No accidental allow-list regression: at least 800 allow entries (was ~800).
allow_len=$(jq '.permissions.allow | length' "${SETTINGS}")
if [ "${allow_len}" -ge 800 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: allow list shrank (was ~800, now ${allow_len})"
fi

# 6. Dangerous broad shell-escape / privilege-escalation prefixes are NOT
#    auto-allowed (#665). sudo/su/doas escalate privilege; eval/exec smuggle
#    denied commands past the prefix matcher (e.g. eval "rm -rf /" defeats the
#    Bash(rm -rf:*) deny). They must fall through to defaultMode (ask).
assert_allow_absent "Bash(sudo:*)" "no auto-allow: sudo"
assert_allow_absent "Bash(su:*)"   "no auto-allow: su"
assert_allow_absent "Bash(doas:*)" "no auto-allow: doas"
assert_allow_absent "Bash(eval:*)" "no auto-allow: eval"
assert_allow_absent "Bash(exec:*)" "no auto-allow: exec"

# 7. Deny-beats-allow invariant: no command is simultaneously present in the
#    deny list and the allow list. Claude Code lets deny win, but an entry in
#    both is a contradictory signal and a maintenance hazard.
overlap=$(jq -r '
    (.permissions.allow) as $a
    | .permissions.deny | map(select(. as $d | $a | any(. == $d))) | join(", ")
' "${SETTINGS}")
assert_eq "${overlap}" "" "deny-beats-allow: no allow/deny overlap"

echo ""
echo "test-deny-list-prune.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
