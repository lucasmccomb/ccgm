#!/usr/bin/env bash
# Test suite for the `git branch` force-delete hard-block in auto-approve-bash.py
# (GitHub issue #907).
#
# Covers:
#   - is_force_branch_delete(): every spelling git accepts (-D, -d -f,
#     --delete --force, combined short flags, `git -C <path> branch -D`), and
#     the shapes that must NOT match (safe -d, --list, a grep pattern that
#     merely mentions the string).
#   - check_force_branch_delete(): names the offending SEGMENT, not the chain,
#     and points at the sanctioned worktree-sweep teardown path.
#   - The escape hatch (ALLOW_BRANCH_FORCE_DELETE) via env and inline.
#   - main(): hard-blocks (exit 2) in bypassPermissions mode, where the
#     settings.json pattern check never runs and Claude Code's own denial
#     message names the whole chain with no reason.
#
# Run: bash modules/hooks/tests/test-force-branch-delete.sh
# Exit 0 on success; non-zero on first failed assertion.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB="${MODULE_ROOT}/lib"
HOOK="${MODULE_ROOT}/hooks/auto-approve-bash.py"

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

py() {
    PYTHONPATH="${LIB}" python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('aab', '${HOOK}')
aab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aab)
$1
"
}

# ---------------------------------------------------------------------------
# 1. is_force_branch_delete: every force-delete spelling git accepts.
# ---------------------------------------------------------------------------
while IFS= read -r cmd; do
    [ -n "${cmd}" ] || continue
    out=$(py "print(aab.is_force_branch_delete('''${cmd}'''))")
    assert_eq "${out}" "True" "force-delete detected: ${cmd}"
done <<'EOF'
git branch -D feature/foo
git branch -D foo bar baz
git branch --delete --force foo
git branch --force --delete foo
git branch -d -f foo
git branch -f -d foo
git branch -Df foo
git branch -fd foo
git branch -d --force foo
git -C /repo branch -D foo
git -c core.pager=cat branch -D foo
EOF

# ---------------------------------------------------------------------------
# 2. is_force_branch_delete: shapes that must NOT be blocked.
# ---------------------------------------------------------------------------
while IFS= read -r cmd; do
    [ -n "${cmd}" ] || continue
    out=$(py "print(aab.is_force_branch_delete('''${cmd}'''))")
    assert_eq "${out}" "False" "not a force-delete: ${cmd}"
done <<'EOF'
git branch -d foo
git branch --delete foo
git branch --list
git branch -a
git branch feature/new
git checkout -b foo
git worktree remove .claude/worktrees/agent-x
echo git branch -D foo
grep -rn "branch -D" ~/.claude/rules/
git log --oneline -D
EOF

# ---------------------------------------------------------------------------
# 3. check_force_branch_delete: names the SEGMENT, not the whole chain.
#    This is the diagnostic the generic Claude Code denial loses.
# ---------------------------------------------------------------------------
CHAIN='git worktree remove .claude/worktrees/agent-abc && git worktree prune && git branch -D 907-foo'
out=$(py "
seg, reason = aab.check_force_branch_delete('''${CHAIN}''')
print(seg)
")
assert_eq "${out}" "git branch -D 907-foo" "offending segment identified from a teardown chain"

reason=$(py "
seg, reason = aab.check_force_branch_delete('''${CHAIN}''')
print(reason)
")
assert_contains "${reason}" "git branch -D 907-foo" "reason quotes the offending segment"
assert_contains "${reason}" "ONLY this segment is at fault" "reason says only one segment is at fault"
assert_contains "${reason}" "git worktree prune" "reason states the worktree commands are permitted"
assert_contains "${reason}" "worktree-sweep.sh --worktree" "reason names the per-unit teardown command"
assert_contains "${reason}" "worktree-sweep.sh --merged-branches" "reason names the leftover-branch command"
assert_contains "${reason}" "ALLOW_BRANCH_FORCE_DELETE=1" "reason names the escape hatch"

# A chain with no force-delete segment is untouched.
out=$(py "
seg, reason = aab.check_force_branch_delete('git worktree remove x && git worktree prune')
print(seg)
")
assert_eq "${out}" "None" "clean teardown chain is not flagged"

# ---------------------------------------------------------------------------
# 4. Escape hatch: env var and inline assignment.
# ---------------------------------------------------------------------------
out=$(ALLOW_BRANCH_FORCE_DELETE=1 py "
seg, reason = aab.check_force_branch_delete('git branch -D foo')
print(seg)
")
assert_eq "${out}" "None" "ALLOW_BRANCH_FORCE_DELETE=1 in env suppresses the block"

out=$(py "
seg, reason = aab.check_force_branch_delete('ALLOW_BRANCH_FORCE_DELETE=1 git branch -D foo')
print(seg)
")
assert_eq "${out}" "None" "inline ALLOW_BRANCH_FORCE_DELETE=1 suppresses the block"

out=$(ALLOW_BRANCH_FORCE_DELETE=0 py "
seg, reason = aab.check_force_branch_delete('git branch -D foo')
print(seg)
")
assert_eq "${out}" "git branch -D foo" "ALLOW_BRANCH_FORCE_DELETE=0 does not suppress the block"

# ---------------------------------------------------------------------------
# 5. main(): hard-blocks (exit 2) in bypass mode.
#    bypassPermissions is the mode this bug was reported in: there the pattern
#    check never runs, so a bypass-suppressible deny would produce no reason.
# ---------------------------------------------------------------------------
run_hook() {
    printf '{"tool_name":"Bash","tool_input":{"command":%s},"permission_mode":"%s"}' \
        "$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$1")" "$2" \
        | PYTHONPATH="${LIB}" python3 "${HOOK}"
}

stderr=$(run_hook "${CHAIN}" "bypassPermissions" 2>&1 >/dev/null)
rc=$?
assert_eq "${rc}" "2" "teardown chain hard-blocks (exit 2) in bypass mode"
assert_contains "${stderr}" "git branch -D 907-foo" "bypass-mode block names the offending segment"
assert_contains "${stderr}" "worktree-sweep.sh --worktree" "bypass-mode block names the way out"

stderr=$(run_hook "git branch --delete --force foo" "bypassPermissions" 2>&1 >/dev/null)
rc=$?
assert_eq "${rc}" "2" "--delete --force hard-blocks too (the deny pattern misses this spelling)"

stderr=$(run_hook "${CHAIN}" "default" 2>&1 >/dev/null)
rc=$?
assert_eq "${rc}" "2" "teardown chain hard-blocks in default mode as well"

# Safe delete and pure worktree teardown are untouched.
run_hook "git branch -d foo" "bypassPermissions" >/dev/null 2>&1
assert_eq "$?" "0" "safe git branch -d is not blocked"

run_hook "git worktree remove .claude/worktrees/agent-x && git worktree prune" "bypassPermissions" >/dev/null 2>&1
assert_eq "$?" "0" "worktree remove + prune is not blocked"

out=$(run_hook "ALLOW_BRANCH_FORCE_DELETE=1 git branch -D foo" "bypassPermissions" 2>&1)
assert_eq "$?" "0" "inline escape hatch reaches main()"
assert_not_contains "${out}" "Force-deleting" "escape hatch produces no block message"

echo ""
echo "test-force-branch-delete.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
