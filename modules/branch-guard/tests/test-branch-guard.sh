#!/usr/bin/env bash
# Tests for branch-guard.py — the hard PreToolUse gate that blocks work on a
# repo's default branch (main/master) BEFORE the first edit, not at commit time.
#
# Exit-code contract under test: 2 = hard block (bypass-proof), 0 = allowed.
#
# Run: bash modules/branch-guard/tests/test-branch-guard.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/branch-guard.py"

PASS=0
FAIL=0

# The gate must be tested with a clean slate: an inherited ALLOW_MAIN_COMMIT
# would silently flip every deny-case to allow.
unset ALLOW_MAIN_COMMIT

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
    if printf '%s' "${haystack}" | grep -qF -- "${needle}"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  missing: ${needle}"
        echo "  in:      ${haystack}"
    fi
}

TMP=$(mktemp -d -t branch-guard.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT
# Resolve /tmp symlinks (macOS /tmp -> /private/tmp) so path assertions in the
# hook (which resolves symlinks) compare against the same canonical form.
TMP="$(cd "${TMP}" && pwd -P)"

make_repo() {
    # $1 = path, $2 = initial branch
    git init -q -b "$2" "$1"
    git -C "$1" config user.email a@b
    git -C "$1" config user.name a
    # Hermetic fixtures: don't run the user's global pre-commit hooks.
    git -C "$1" config core.hooksPath /dev/null
    (cd "$1" && touch seed && git add seed && git commit -q -m init)
}

# run_hook TOOL TOOL_INPUT_PYDICT CWD
# Feeds the hook a PreToolUse envelope on stdin, running with cwd=CWD.
# Returns the hook's exit code; stderr is captured in $HOOK_STDERR.
HOOK_STDERR=""
run_hook() {
    local tool="$1" tin="$2" cwd="$3"
    local errfile="${TMP}/stderr.txt"
    (
        cd "${cwd}" || exit 99
        python3 -c "
import json, sys
payload = {
    'session_id': 'test',
    'tool_name': '${tool}',
    'tool_input': ${tin},
    'permission_mode': 'default',
    'cwd': '${cwd}',
}
sys.stdout.write(json.dumps(payload))
" | python3 "${HOOK}" 2>"${errfile}"
    )
    local rc=$?
    HOOK_STDERR="$(cat "${errfile}" 2>/dev/null || true)"
    return $rc
}

# ─── Fixtures ────────────────────────────────────────────────────────
R_MAIN="${TMP}/repo-main";           make_repo "${R_MAIN}" main
R_FEAT="${TMP}/repo-feature";        make_repo "${R_FEAT}" main
git -C "${R_FEAT}" checkout -q -b feature/x
R_MASTER="${TMP}/repo-master";       make_repo "${R_MASTER}" master
R_SRC="${TMP}/repo-src";             make_repo "${R_SRC}" main
R_CLONE="${TMP}/repo-clone";         git clone -q "${R_SRC}" "${R_CLONE}"
R_CLONE_FEAT="${TMP}/repo-clone-feat"; git clone -q "${R_SRC}" "${R_CLONE_FEAT}"
git -C "${R_CLONE_FEAT}" checkout -q -b feature/y
R_MERGE="${TMP}/repo-merge";         make_repo "${R_MERGE}" main
touch "$(git -C "${R_MERGE}" rev-parse --absolute-git-dir)/MERGE_HEAD"
R_REBASE="${TMP}/repo-rebase";       make_repo "${R_REBASE}" main
mkdir -p "$(git -C "${R_REBASE}" rev-parse --absolute-git-dir)/rebase-merge"
R_DETACHED="${TMP}/repo-detached";   make_repo "${R_DETACHED}" main
git -C "${R_DETACHED}" checkout -q --detach
R_UNBORN="${TMP}/repo-unborn";       git init -q -b main "${R_UNBORN}"
NONREPO="${TMP}/plain";              mkdir -p "${NONREPO}"

# ─── File tools: the gate fires BEFORE the first edit ────────────────

# 1. Edit inside a repo on main → hard block (exit 2).
run_hook Edit "{'file_path': '${R_MAIN}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_MAIN}"
assert_eq "$?" "2" "Edit on main is hard-blocked"

# 2. The denial teaches the branch-first workflow.
assert_contains "${HOOK_STDERR}" "git fetch origin && git checkout -b" "denial includes branch-creation command"
assert_contains "${HOOK_STDERR}" "origin/main" "denial names the actual default branch"
assert_contains "${HOOK_STDERR}" "feature" "denial lists the branch <type> vocabulary"
assert_contains "${HOOK_STDERR}" "ALLOW_MAIN_COMMIT=1" "denial documents the escape hatch"

# 3. Same edit on a feature branch → allowed.
run_hook Edit "{'file_path': '${R_FEAT}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_FEAT}"
assert_eq "$?" "0" "Edit on feature branch is allowed"

# 4. Write of a NEW nested path (dirs do not exist yet) on main → blocked.
run_hook Write "{'file_path': '${R_MAIN}/new/dir/file.txt', 'content': 'x'}" "${R_MAIN}"
assert_eq "$?" "2" "Write of new nested path on main is hard-blocked"

# 5. NotebookEdit on main → blocked.
run_hook NotebookEdit "{'notebook_path': '${R_MAIN}/nb.ipynb', 'new_source': 'x'}" "${R_MAIN}"
assert_eq "$?" "2" "NotebookEdit on main is hard-blocked"

# 6. Filesystem-MCP write on main → blocked.
run_hook mcp__filesystem__write_file "{'path': '${R_MAIN}/mcp.txt', 'content': 'x'}" "${R_MAIN}"
assert_eq "$?" "2" "mcp__filesystem__write_file on main is hard-blocked"

# 7. Edit targeting a file OUTSIDE any repo → allowed even though cwd is a main repo.
run_hook Edit "{'file_path': '${NONREPO}/notes.md', 'old_string': 'a', 'new_string': 'b'}" "${R_MAIN}"
assert_eq "$?" "0" "Edit of non-repo file is allowed (file's repo is checked, not cwd)"

# 8. ALLOW_MAIN_COMMIT=1 env var escape hatch → allowed.
(
    export ALLOW_MAIN_COMMIT=1
    run_hook Edit "{'file_path': '${R_MAIN}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_MAIN}"
)
assert_eq "$?" "0" "ALLOW_MAIN_COMMIT=1 env bypasses the file gate"

# ─── Bash: mutating git commands ─────────────────────────────────────

# 9-12. git add / commit / apply / stage on main → blocked.
run_hook Bash "{'command': 'git add .'}" "${R_MAIN}"
assert_eq "$?" "2" "git add on main is hard-blocked"
run_hook Bash "{'command': 'git commit -m \"#1: x\"'}" "${R_MAIN}"
assert_eq "$?" "2" "git commit on main is hard-blocked"
run_hook Bash "{'command': 'git apply fix.patch'}" "${R_MAIN}"
assert_eq "$?" "2" "git apply on main is hard-blocked"
run_hook Bash "{'command': 'git stage seed'}" "${R_MAIN}"
assert_eq "$?" "2" "git stage on main is hard-blocked"

# 13. Non-mutating git and non-git commands on main → allowed.
run_hook Bash "{'command': 'git status'}" "${R_MAIN}"
assert_eq "$?" "0" "git status on main is allowed"
run_hook Bash "{'command': 'ls -la'}" "${R_MAIN}"
assert_eq "$?" "0" "non-git command on main is allowed"

# 14. Branch creation itself must never be blocked (it is the way out).
run_hook Bash "{'command': 'git fetch origin && git checkout -b feature/z origin/main'}" "${R_CLONE}"
assert_eq "$?" "0" "git checkout -b on main is allowed (the escape route)"

# 15. git add on a feature branch → allowed.
run_hook Bash "{'command': 'git add .'}" "${R_FEAT}"
assert_eq "$?" "0" "git add on feature branch is allowed"

# 16. Inline ALLOW_MAIN_COMMIT=1 prefix → allowed.
run_hook Bash "{'command': 'ALLOW_MAIN_COMMIT=1 git add .'}" "${R_MAIN}"
assert_eq "$?" "0" "inline ALLOW_MAIN_COMMIT=1 bypasses the Bash gate"

# 17. Compound command with a mutating segment → blocked.
run_hook Bash "{'command': 'touch y && git add y'}" "${R_MAIN}"
assert_eq "$?" "2" "compound command with git add on main is hard-blocked"

# 18. git -C <main-repo> from an unrelated cwd → blocked (checks the -C target).
run_hook Bash "{'command': 'git -C ${R_MAIN} add seed'}" "${NONREPO}"
assert_eq "$?" "2" "git -C targeting a main repo is hard-blocked"

# 19. git push is NOT this hook's job (enforce-git-workflow owns it) → no decision.
run_hook Bash "{'command': 'git push origin main'}" "${R_MAIN}"
assert_eq "$?" "0" "git push is left to enforce-git-workflow"

# ─── Default-branch detection variants ───────────────────────────────

# 20. master as default branch → blocked on master.
run_hook Edit "{'file_path': '${R_MASTER}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_MASTER}"
assert_eq "$?" "2" "Edit on master (master-default repo) is hard-blocked"

# 21. Cloned repo (origin/HEAD set) on main → blocked.
run_hook Edit "{'file_path': '${R_CLONE}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_CLONE}"
assert_eq "$?" "2" "Edit on main in a clone (origin/HEAD) is hard-blocked"

# 22. Cloned repo on a feature branch → allowed.
run_hook Edit "{'file_path': '${R_CLONE_FEAT}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_CLONE_FEAT}"
assert_eq "$?" "0" "Edit on feature branch in a clone is allowed"

# ─── Exempt git states ───────────────────────────────────────────────

# 23. Merge in progress on main → allowed (conflict resolution must work).
run_hook Edit "{'file_path': '${R_MERGE}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_MERGE}"
assert_eq "$?" "0" "Edit during in-progress merge is allowed"
run_hook Bash "{'command': 'git add seed'}" "${R_MERGE}"
assert_eq "$?" "0" "git add during in-progress merge is allowed"

# 24. Rebase in progress → allowed.
run_hook Edit "{'file_path': '${R_REBASE}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_REBASE}"
assert_eq "$?" "0" "Edit during in-progress rebase is allowed"

# 25. Detached HEAD → allowed (not on the default branch).
run_hook Edit "{'file_path': '${R_DETACHED}/seed', 'old_string': 'a', 'new_string': 'b'}" "${R_DETACHED}"
assert_eq "$?" "0" "Edit on detached HEAD is allowed"

# 26. Unborn HEAD (fresh git init, no commits) → allowed so bootstrap works.
run_hook Write "{'file_path': '${R_UNBORN}/first.txt', 'content': 'x'}" "${R_UNBORN}"
assert_eq "$?" "0" "Write on unborn HEAD (fresh init) is allowed"

# ─── Robustness ──────────────────────────────────────────────────────

# 27. Malformed stdin → allow (fail-open, never wedge the session).
printf 'not json' | python3 "${HOOK}" >/dev/null 2>&1
assert_eq "$?" "0" "malformed stdin fails open"

# 28. Unknown tool → allow.
run_hook Glob "{'pattern': '*.py'}" "${R_MAIN}"
assert_eq "$?" "0" "unrelated tool is ignored"

echo ""
echo "test-branch-guard.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
