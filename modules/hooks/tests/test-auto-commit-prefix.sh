#!/usr/bin/env bash
# Test that enforce-git-workflow.py accepts `#auto:` as a valid commit prefix
# (for autoheal's apply path) without weakening the issue-number rule.
#
# Run: bash modules/hooks/tests/test-auto-commit-prefix.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/enforce-git-workflow.py"

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

# Set up a temp git repo on a feature branch so the hook doesn't bail
# on "not a git repo" and so it doesn't trip the protected-branch rule.
TMP=$(mktemp -d -t auto-commit-prefix.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT
(
    cd "${TMP}" || exit
    git init -q -b feat-x
    git config user.email a@b
    git config user.name a
    touch x && git add x && git commit -q --allow-empty -m "init"
) || exit 1

run_hook() {
    local command="$1"
    local mode="${2:-default}"
    cd "${TMP}" || exit 1
    # Build JSON in Python so embedded quotes in `command` don't break the payload.
    python3 -c "
import json, sys
payload = {
    'session_id': 'test',
    'tool_name': 'Bash',
    'tool_input': {'command': '''${command}'''},
    'permission_mode': '${mode}',
    'cwd': '${TMP}',
}
sys.stdout.write(json.dumps(payload))
" | python3 "${HOOK}"
}

# 1. `#auto:` prefix is accepted (exit 0, no deny).
run_hook 'git commit -m "#auto: apply autoheal proposal abc123"' default >/dev/null 2>&1
assert_eq "$?" "0" "#auto: prefix is accepted"

# 2. `#42:` issue-number prefix still works.
run_hook 'git commit -m "#42: fix bug"' default >/dev/null 2>&1
assert_eq "$?" "0" "#42: issue prefix still works"

# 3. `sync:` prefix still works.
run_hook 'git commit -m "sync: update log"' default >/dev/null 2>&1
assert_eq "$?" "0" "sync: prefix still works"

# 4. A plain message WITHOUT any approved prefix is still hard-blocked.
run_hook 'git commit -m "oops bad message"' default >/dev/null 2>&1
assert_eq "$?" "2" "bad message still hard-blocks"

# 5. `#autoheal:` (note the longer prefix) does NOT match `#auto:` regex —
#    should still hard-block. (Guards against the regex being too greedy.)
run_hook 'git commit -m "#autoheal: should not match"' default >/dev/null 2>&1
# Actually `^#auto:` matches `#auto:` and `#autoheal:` would not match
# because the colon is required immediately after `auto`. Verify.
rc=$?
# `#autoheal:` does NOT have a colon after `auto`, so the regex `^#auto:`
# does NOT match — the message should be rejected.
assert_eq "${rc}" "2" "#autoheal: (no colon after auto) still blocked"

# 6. Module import probe: is_auto_commit is callable.
out=$(python3 -c "
import sys, importlib.util
spec = importlib.util.spec_from_file_location('hk', '${HOOK}')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print(callable(mod.is_auto_commit))
print(mod.is_auto_commit('#auto: hi'))
print(mod.is_auto_commit('#42: hi'))
print(mod.is_auto_commit('hello'))
")
assert_eq "$(echo "${out}" | sed -n 1p)" "True" "is_auto_commit is callable"
assert_eq "$(echo "${out}" | sed -n 2p)" "True" "is_auto_commit accepts #auto:"
assert_eq "$(echo "${out}" | sed -n 3p)" "False" "is_auto_commit rejects #42:"
assert_eq "$(echo "${out}" | sed -n 4p)" "False" "is_auto_commit rejects plain"

echo ""
echo "test-auto-commit-prefix.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
