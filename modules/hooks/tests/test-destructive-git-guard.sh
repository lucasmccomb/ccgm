#!/usr/bin/env bash
# Test suite for the destructive-git guard in enforce-git-workflow.py
# (GitHub issue #1081).
#
# The guard blocks `git reset --hard`, `git clean -f*`, `git checkout .` /
# `git checkout -- <path>`, `git restore <path>` and `git branch -D` only when
# the command would destroy unsaved work, and allows them otherwise.
#
# Run: bash modules/hooks/tests/test-destructive-git-guard.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/enforce-git-workflow.py"

PASS=0
FAIL=0

assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}

TMP=$(mktemp -d -t destructive-git.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT

# A repo on a feature branch with a bare origin, one tracked file, clean tree.
new_repo() {
    local name="$1"
    git init -q --bare "${TMP}/${name}-origin.git"
    git init -q -b main "${TMP}/${name}"
    (
        cd "${TMP}/${name}" || exit 1
        git config user.email a@b
        git config user.name a
        git config core.hooksPath /dev/null
        git remote add origin "${TMP}/${name}-origin.git"
        echo one > tracked.txt
        echo "ignored.log" > .gitignore
        git add . && git commit -q -m init
        git push -q origin main
        git checkout -q -b feat-x
    )
    echo "${TMP}/${name}"
}

make_dirty()     { echo changed >> "$1/tracked.txt"; }
make_untracked() { echo new > "$1/untracked.txt"; }
make_ignored()   { echo junk > "$1/ignored.log"; }

# run_hook <repo> <command> [env assignment]  -> exit code
run_hook() {
    local repo="$1" command="$2" extra="${3:-}"
    (
        cd "${repo}" || exit 1
        [ -n "${extra}" ] && export "${extra?}"
        python3 -c "
import json, sys
sys.stdout.write(json.dumps({'session_id': 't', 'tool_name': 'Bash',
    'tool_input': {'command': sys.argv[1]}, 'cwd': sys.argv[2]}))
" "${command}" "${repo}" | python3 "${HOOK}" >/dev/null 2>&1
    )
    echo $?
}

expect() { # expect <0|2> <repo> <command> <label> [env]
    assert_eq "$(run_hook "$2" "$3" "${5:-}")" "$1" "$4"
}

# --- reset --hard ----------------------------------------------------------
R=$(new_repo reset)
expect 0 "$R" "git reset --hard origin/main" "reset --hard allowed on clean tree"
expect 0 "$R" "git fetch origin && git reset --hard origin/main" "sync recipe allowed on clean tree"
make_dirty "$R"
expect 2 "$R" "git reset --hard origin/main" "reset --hard blocked on dirty tree"
expect 2 "$R" "git reset --hard" "bare reset --hard blocked on dirty tree"
expect 0 "$R" "git reset --soft HEAD~1" "reset --soft allowed on dirty tree"
expect 0 "$R" "git reset --hard origin/main" "escape hatch (env) allows dirty reset" "ALLOW_DESTRUCTIVE_GIT=1"
expect 0 "$R" "ALLOW_DESTRUCTIVE_GIT=1 git reset --hard origin/main" "escape hatch (inline) allows dirty reset"
expect 0 "$R" "git status" "unrelated git command allowed"

# --- chained segments ------------------------------------------------------
expect 2 "$R" "git fetch origin && git reset --hard origin/main" "&& chain blocked"
expect 2 "$R" "echo hi; git reset --hard" "; chain blocked"
expect 2 "$R" "echo hi | git reset --hard" "| chain blocked"
expect 0 "$R" "echo 'git reset --hard'" "quoted mention is not a command"

# --- git -C ----------------------------------------------------------------
CLEAN=$(new_repo cclean)
expect 2 "$CLEAN" "git -C $R reset --hard origin/main" "-C targets the dirty repo"
expect 0 "$R" "git -C $CLEAN reset --hard origin/main" "-C targets the clean repo"

# --- checkout / restore ----------------------------------------------------
expect 2 "$R" "git checkout ." "checkout . blocked on dirty tree"
expect 2 "$R" "git checkout -- tracked.txt" "checkout -- path blocked when path dirty"
expect 0 "$R" "git checkout feat-x" "branch checkout allowed"
expect 2 "$R" "git restore tracked.txt" "restore blocked when path dirty"
expect 2 "$R" "git restore ." "restore . blocked on dirty tree"
expect 0 "$R" "git restore --staged tracked.txt" "restore --staged allowed"
C2=$(new_repo cr)
expect 0 "$C2" "git checkout ." "checkout . allowed on clean tree"
expect 0 "$C2" "git restore ." "restore . allowed on clean tree"
echo x > "$C2/other.txt"; (cd "$C2" && git add other.txt && git commit -q -m o)
make_dirty "$C2"
expect 0 "$C2" "git checkout -- other.txt" "checkout -- clean path allowed though another path is dirty"
expect 0 "$C2" "git restore other.txt" "restore clean path allowed though another path is dirty"

# --- clean -----------------------------------------------------------------
C3=$(new_repo clean)
expect 0 "$C3" "git clean -fd" "clean -fd allowed with nothing untracked"
make_ignored "$C3"
expect 0 "$C3" "git clean -fd" "clean -fd allowed when only ignored files exist"
expect 2 "$C3" "git clean -fdx" "clean -fdx blocked when ignored files exist"
make_untracked "$C3"
expect 2 "$C3" "git clean -f" "clean -f blocked with untracked files"
expect 2 "$C3" "git clean -fd" "clean -fd blocked with untracked files"
expect 2 "$C3" "git clean --force" "clean --force blocked with untracked files"
expect 0 "$C3" "git clean -n" "clean -n dry run allowed"
expect 0 "$C3" "git clean -nd" "clean -nd dry run allowed"

# --- branch -D -------------------------------------------------------------
B=$(new_repo branch)
(
    cd "$B" || exit 1
    git checkout -q -b pushed-b && echo p > p.txt && git add p.txt && git commit -q -m p
    git push -q origin pushed-b
    git checkout -q -b local-only && echo l > l.txt && git add l.txt && git commit -q -m l
    git checkout -q feat-x
)
expect 0 "$B" "git branch -D pushed-b" "branch -D of pushed branch allowed"
expect 2 "$B" "git branch -D local-only" "branch -D of never-pushed branch blocked"
expect 2 "$B" "git branch -D pushed-b local-only" "branch -D blocked if any branch never pushed"
expect 2 "$B" "git branch --delete --force local-only" "long-form force delete blocked"
expect 2 "$B" "git branch -d -f local-only" "-d -f blocked"
expect 0 "$B" "git branch -d local-only" "safe -d left to git"
expect 0 "$B" "git branch -D nonexistent" "missing branch allowed (git will error)"
expect 0 "$B" "git branch -D local-only" "escape hatch allows never-pushed delete" "ALLOW_DESTRUCTIVE_GIT=1"
expect 2 "$CLEAN" "git -C $B branch -D local-only" "-C honored for branch -D"

# squash-merged, never pushed: the work is on origin/main under a different commit
(
    cd "$B" || exit 1
    git checkout -q -b squashed && echo s > s.txt && git add s.txt && git commit -q -m s
    git checkout -q main && echo s > s.txt && git add s.txt && git commit -q -m "squash s" && git push -q origin main
    git checkout -q feat-x
)
expect 0 "$B" "git branch -D squashed" "squash-merged unpushed branch allowed"

# --- fail open -------------------------------------------------------------
NOREPO="${TMP}/not-a-repo"; mkdir -p "$NOREPO"
expect 0 "$NOREPO" "git reset --hard" "outside a git repo allowed (fail open)"

echo ""
echo "test-destructive-git-guard.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
