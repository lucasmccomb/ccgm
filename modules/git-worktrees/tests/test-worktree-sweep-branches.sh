#!/usr/bin/env bash
# Test suite for worktree-sweep.sh branch cleanup (GitHub issue #907).
#
# The loop this closes: this repo family squash-merges, so after a merge the
# feature branch is not an ancestor of main and `git branch -d` refuses it. That
# pushes agents to `git branch -D`, which is denied. The sweep is the permitted
# path — it verifies the default branch already contains the work, then deletes.
#
# Covers:
#   - A squash-merged branch is detected as absorbed and deleted (the core case).
#   - A normally-merged branch is deleted.
#   - An UNMERGED branch is kept, with the restore hint. Nothing is discarded.
#   - --keep-branches restores the pre-#907 behavior.
#   - --dry-run deletes nothing.
#   - --worktree scopes the sweep to one unit and rejects a non-worktree path.
#   - --merged-branches cleans a leftover branch whose worktree is already gone,
#     never the default branch, never a branch checked out somewhere.
#   - A dirty worktree is preserved and its branch is never touched.
#
# Run: bash modules/git-worktrees/tests/test-worktree-sweep-branches.sh
# Exit 0 on success; non-zero if any assertion failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP="$(cd "${SCRIPT_DIR}/../lib" && pwd)/worktree-sweep.sh"

PASS=0
FAIL=0

# Isolate from the user's git config: a global core.hooksPath would run this
# machine's pre-commit hooks inside the fixtures, and a machine with no
# configured identity would fail commit-tree with "empty ident name not allowed".
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@localhost
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@localhost

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

TMPROOT="$(mktemp -d -t wtsweep.XXXXXX)"
trap 'rm -rf "${TMPROOT}"' EXIT

# Builds a repo with an origin, so DEFAULT_REF resolves to origin/main exactly
# as it does in a real clone. Echoes the working-clone path.
new_repo() {
    local name="$1" root="${TMPROOT}/$1"
    mkdir -p "${root}"
    git init -q --bare "${root}/origin.git" -b main
    git clone -q "${root}/origin.git" "${root}/work" 2>/dev/null
    (
        cd "${root}/work"
        echo seed > seed.txt
        git add . && git commit -qm init && git push -q origin main
    )
    echo "${root}/work"
}

# Creates branch $2 with a commit, checked out in a worktree under
# .claude/worktrees/$2, in repo $1.
add_worktree_branch() {
    local repo="$1" branch="$2"
    git -C "${repo}" worktree add -q -b "${branch}" ".claude/worktrees/${branch}" main
    (
        cd "${repo}/.claude/worktrees/${branch}"
        echo "${branch}" > "${branch}.txt"
        git add . && git commit -qm "work on ${branch}"
        echo "more" >> "${branch}.txt"
        git add . && git commit -qm "more work on ${branch}"
    )
}

# Squash-merges branch $2 into main and pushes, the way a squash-merged PR lands.
squash_merge() {
    local repo="$1" branch="$2"
    git -C "${repo}" checkout -q main
    git -C "${repo}" merge -q --squash "${branch}"
    git -C "${repo}" commit -qm "squashed ${branch} (#1)"
    git -C "${repo}" push -q origin main
}

sweep() { ( cd "$1" && shift && bash "${SWEEP}" "$@" 2>&1 ); }

# ---------------------------------------------------------------------------
# 1. Squash-merged branch: worktree removed AND branch deleted.
#    `git branch -d` refuses this branch; that refusal is the whole bug.
# ---------------------------------------------------------------------------
R="$(new_repo squash)"
add_worktree_branch "${R}" "907-squashed"
squash_merge "${R}" "907-squashed"

# Establish the premise: safe delete really does refuse a squash-merged branch.
git -C "${R}" branch -d 907-squashed >/dev/null 2>&1
assert_eq "$?" "1" "premise: git branch -d refuses a squash-merged branch"

out="$(sweep "${R}")"
assert_contains "${out}" "branch 907-squashed deleted" "squash-merged branch is deleted"
branches="$(git -C "${R}" branch --format='%(refname:short)')"
assert_eq "$(printf '%s\n' "${branches}" | grep -c '907-squashed')" "0" "squash-merged branch is gone from the ref list"
assert_eq "$([ -d "${R}/.claude/worktrees/907-squashed" ] && echo present || echo gone)" "gone" "worktree directory removed"

# ---------------------------------------------------------------------------
# 2. Normally-merged branch is deleted too.
# ---------------------------------------------------------------------------
R="$(new_repo merged)"
add_worktree_branch "${R}" "907-merged"
git -C "${R}" checkout -q main
git -C "${R}" merge -q --no-ff -m "merge 907-merged" 907-merged
git -C "${R}" push -q origin main
out="$(sweep "${R}")"
assert_contains "${out}" "branch 907-merged deleted" "normally-merged branch is deleted"

# ---------------------------------------------------------------------------
# 3. Unmerged branch: worktree removed, branch KEPT. No commit is discarded.
# ---------------------------------------------------------------------------
R="$(new_repo unmerged)"
add_worktree_branch "${R}" "907-unmerged"
out="$(sweep "${R}")"
assert_contains "${out}" "branch 907-unmerged KEPT" "unmerged branch is kept"
assert_contains "${out}" "nothing discarded" "report states nothing was discarded"
assert_contains "${out}" "git worktree add" "kept branch carries the restore hint"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-unmerged >/dev/null && echo exists || echo gone)" \
          "exists" "unmerged branch still exists after the sweep"

# ---------------------------------------------------------------------------
# 4. --keep-branches restores the pre-#907 behavior.
# ---------------------------------------------------------------------------
R="$(new_repo keepflag)"
add_worktree_branch "${R}" "907-keep"
squash_merge "${R}" "907-keep"
out="$(sweep "${R}" --keep-branches)"
assert_contains "${out}" "--keep-branches" "--keep-branches is reported"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-keep >/dev/null && echo exists || echo gone)" \
          "exists" "--keep-branches leaves an absorbed branch alone"

# ---------------------------------------------------------------------------
# 5. --dry-run changes nothing.
# ---------------------------------------------------------------------------
R="$(new_repo dryrun)"
add_worktree_branch "${R}" "907-dry"
squash_merge "${R}" "907-dry"
out="$(sweep "${R}" --dry-run)"
assert_contains "${out}" "WOULD BE DELETED" "dry-run reports the planned branch delete"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-dry >/dev/null && echo exists || echo gone)" \
          "exists" "dry-run does not delete the branch"
assert_eq "$([ -d "${R}/.claude/worktrees/907-dry" ] && echo present || echo gone)" \
          "present" "dry-run does not remove the worktree"

# ---------------------------------------------------------------------------
# 6. --worktree scopes the sweep to one unit; a sibling is untouched.
# ---------------------------------------------------------------------------
R="$(new_repo scoped)"
add_worktree_branch "${R}" "907-one"
add_worktree_branch "${R}" "907-two"
squash_merge "${R}" "907-one"
squash_merge "${R}" "907-two"
out="$(sweep "${R}" --worktree "${R}/.claude/worktrees/907-one")"
assert_contains "${out}" "branch 907-one deleted" "--worktree tears down the named unit"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-two >/dev/null && echo exists || echo gone)" \
          "exists" "--worktree leaves the sibling branch alone"
assert_eq "$([ -d "${R}/.claude/worktrees/907-two" ] && echo present || echo gone)" \
          "present" "--worktree leaves the sibling worktree alone"

# A path that is not a worktree of this repo is a hard error, not a silent no-op.
( cd "${R}" && bash "${SWEEP}" --worktree "${R}" >/dev/null 2>&1 )
assert_eq "$?" "2" "--worktree rejects the main checkout"
( cd "${R}" && bash "${SWEEP}" --worktree "${TMPROOT}/nope" >/dev/null 2>&1 )
assert_eq "$?" "2" "--worktree rejects a nonexistent path"

# ---------------------------------------------------------------------------
# 7. --merged-branches: the recovery path when the worktree is already gone.
# ---------------------------------------------------------------------------
R="$(new_repo leftover)"
add_worktree_branch "${R}" "907-leftover"
add_worktree_branch "${R}" "907-still-open"
squash_merge "${R}" "907-leftover"
# Simulate the agent having removed the worktree by hand and then stalling on
# the branch delete — exactly the state the reported incident left behind.
git -C "${R}" worktree remove ".claude/worktrees/907-leftover"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-leftover >/dev/null && echo exists || echo gone)" \
          "exists" "leftover branch survives a bare worktree removal"

out="$(sweep "${R}" --merged-branches)"
assert_contains "${out}" "907-leftover (no worktree) deleted" "--merged-branches deletes the leftover branch"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-leftover >/dev/null && echo exists || echo gone)" \
          "gone" "leftover branch is gone"
assert_eq "$(git -C "${R}" rev-parse --verify -q main >/dev/null && echo exists || echo gone)" \
          "exists" "--merged-branches never deletes the default branch"

# Without --merged-branches the leftover branch is left alone.
R="$(new_repo leftover2)"
add_worktree_branch "${R}" "907-left2"
squash_merge "${R}" "907-left2"
git -C "${R}" worktree remove ".claude/worktrees/907-left2"
out="$(sweep "${R}")"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-left2 >/dev/null && echo exists || echo gone)" \
          "exists" "leftover branch untouched without --merged-branches"

# An unmerged branch with no worktree is never deleted, even with the flag.
R="$(new_repo leftover3)"
add_worktree_branch "${R}" "907-left3"
git -C "${R}" worktree remove --force ".claude/worktrees/907-left3"
out="$(sweep "${R}" --merged-branches)"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-left3 >/dev/null && echo exists || echo gone)" \
          "exists" "--merged-branches keeps an unmerged branch"

# ---------------------------------------------------------------------------
# 8. A dirty worktree is preserved and its branch is never touched.
# ---------------------------------------------------------------------------
R="$(new_repo dirty)"
add_worktree_branch "${R}" "907-dirty"
squash_merge "${R}" "907-dirty"
echo "uncommitted" > "${R}/.claude/worktrees/907-dirty/scratch.txt"
out="$(sweep "${R}")"
assert_contains "${out}" "PRESERVE (uncommitted or untracked changes)" "dirty worktree is preserved"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-dirty >/dev/null && echo exists || echo gone)" \
          "exists" "branch of a preserved worktree is never deleted"

# ---------------------------------------------------------------------------
# 9. A stale prunable entry (directory deleted out from under git) is cleaned up.
# ---------------------------------------------------------------------------
R="$(new_repo prunable)"
add_worktree_branch "${R}" "907-prunable"
squash_merge "${R}" "907-prunable"
rm -rf "${R}/.claude/worktrees/907-prunable"
out="$(sweep "${R}")"
assert_contains "${out}" "907-prunable" "prunable entry's branch is reported"
assert_eq "$(git -C "${R}" rev-parse --verify -q 907-prunable >/dev/null && echo exists || echo gone)" \
          "gone" "prunable entry's absorbed branch is deleted"

echo ""
echo "test-worktree-sweep-branches.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
