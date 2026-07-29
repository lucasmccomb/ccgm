#!/usr/bin/env bash
# worktree-sweep.sh - repo-wide safe worktree janitor.
#
# Enumerates every worktree of the current repo, classifies each as CLEAN
# (safe to remove) or PRESERVE (unsaved work / in-progress operation / locked),
# removes ONLY the clean ones with a NON-FORCE `git worktree remove`, prunes
# stale metadata, and prints a report. It NEVER forces, so git's own refusal on
# a modified-or-untracked worktree is a second safety gate on top of the
# classification. See modules/git-worktrees/rules/git-worktrees.md.
#
# KEY SAFETY FACT: removing a clean ON-BRANCH worktree never loses committed
# work - the branch ref stays in the parent .git; only the working-tree checkout
# (and its build artifacts) are removed. Re-create it later with
# `git worktree add <path> <branch>`. A DETACHED worktree has no branch ref, so
# if it carries commits reachable from no other ref, removal would orphan them -
# those are preserved, not removed.
#
# By default it only touches worktrees under the two managed locations,
# `.claude/worktrees/` (harness `isolation:"worktree"` default) and `.worktrees/`
# (legacy module location), plus prunable entries whose directory is already
# gone. Worktrees elsewhere are reported but left alone unless --all is given.
#
# BRANCH CLEANUP: after removing a worktree, its branch is deleted IFF the default
# branch already contains the branch's work - either a normal merge (the branch is
# an ancestor) or a SQUASH merge (the branch's tree, replayed on the merge base,
# is patch-equivalent to something already upstream). A branch that fails both
# tests is kept and reported, so no unmerged commit is ever discarded. This is the
# permitted path that `git branch -D` is not: agents cannot run `git branch -D`
# (it is denied, and hard-blocked by auto-approve-bash.py), and `git branch -d`
# refuses squash-merged branches, so without this there is no way to finish a
# teardown after a squash merge (GitHub issue #907).
#
# Usage: worktree-sweep.sh [--dry-run|-n] [--conservative] [--all]
#                          [--worktree <path>] [--keep-branches] [--merged-branches]
#                          [-h|--help]
#   --dry-run          Report the classification and planned actions; change nothing.
#   --conservative     Also PRESERVE clean worktrees whose branch has commits not on
#                      the origin default branch (keep in-progress-but-committed
#                      checkouts around). Default removes clean worktrees regardless,
#                      since their commits survive on the branch ref.
#   --all              Also sweep clean worktrees outside the two managed locations.
#   --worktree <path>  Scope the sweep to ONE worktree - the per-unit teardown for
#                      lifecycle step 4. Implies --all for that path.
#   --keep-branches    Never delete branches; only remove worktrees (pre-#907 behavior).
#   --merged-branches  Also delete local branches with no worktree at all whose work
#                      the default branch already contains. Recovers the leftover
#                      branch when a worktree was removed by hand earlier.
#   -h, --help         Print this header.
set -u

MODE="apply"
CONSERVATIVE=0
ALL=0
KEEP_BRANCHES=0
MERGED_BRANCHES=0
ONLY_WORKTREE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) MODE="dry-run" ;;
    --conservative) CONSERVATIVE=1 ;;
    --all) ALL=1 ;;
    --keep-branches) KEEP_BRANCHES=1 ;;
    --merged-branches) MERGED_BRANCHES=1 ;;
    --worktree)
      shift
      [ $# -gt 0 ] || { echo "worktree-sweep: --worktree needs a path" >&2; exit 2; }
      ONLY_WORKTREE="$1"; ALL=1 ;;
    --worktree=*)
      ONLY_WORKTREE="${1#--worktree=}"; ALL=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "worktree-sweep: unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "worktree-sweep: not inside a git repository" >&2
  exit 2
fi

CWD_WT="$(git rev-parse --show-toplevel)"

# Best-effort default-branch ref, for the unmerged-commit note in the report.
DEFAULT_REF=""
if git show-ref --verify --quiet refs/remotes/origin/HEAD 2>/dev/null; then
  DEFAULT_REF="$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null)"
fi
if [ -z "$DEFAULT_REF" ] && git show-ref --verify --quiet refs/remotes/origin/main 2>/dev/null; then
  DEFAULT_REF="origin/main"
fi
if [ -z "$DEFAULT_REF" ] && git show-ref --verify --quiet refs/remotes/origin/master 2>/dev/null; then
  DEFAULT_REF="origin/master"
fi
# Local fallback for a repo with no origin, so --conservative still works there.
if [ -z "$DEFAULT_REF" ] && git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
  DEFAULT_REF="main"
fi
if [ -z "$DEFAULT_REF" ] && git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
  DEFAULT_REF="master"
fi

# The main checkout (parent of the shared .git dir) must never be swept, no
# matter which worktree we run from. Empty for a bare repo (it has no checkout).
MAIN_CHECKOUT=""
_common_dir="$(git rev-parse --git-common-dir 2>/dev/null)"
if [ -n "$_common_dir" ] && [ "$(git rev-parse --is-bare-repository 2>/dev/null)" != "true" ]; then
  # pwd -P resolves symlinks so this matches git's canonical porcelain paths
  # (e.g. macOS /var -> /private/var), so the comparison in process_record holds.
  MAIN_CHECKOUT="$(cd "$_common_dir/.." 2>/dev/null && pwd -P)"
fi

# Short name of the default branch, so it is never a deletion candidate.
DEFAULT_BRANCH="${DEFAULT_REF#origin/}"

# Resolve --worktree to the same canonical form git reports, so the comparison
# in process_record holds (pwd -P collapses macOS /var -> /private/var).
if [ -n "$ONLY_WORKTREE" ]; then
  _resolved="$(cd "$ONLY_WORKTREE" 2>/dev/null && pwd -P)"
  if [ -z "$_resolved" ]; then
    echo "worktree-sweep: --worktree path does not exist: $ONLY_WORKTREE" >&2
    exit 2
  fi
  ONLY_WORKTREE="$_resolved"
  if ! git worktree list --porcelain | grep -qxF "worktree $ONLY_WORKTREE"; then
    echo "worktree-sweep: not a worktree of this repository: $ONLY_WORKTREE" >&2
    exit 2
  fi
  # The main checkout is listed like any other worktree but can never be torn
  # down. Refuse loudly rather than exiting 0 having done nothing.
  if [ -n "$MAIN_CHECKOUT" ] && [ "$ONLY_WORKTREE" = "$MAIN_CHECKOUT" ]; then
    echo "worktree-sweep: refusing to sweep the main checkout: $ONLY_WORKTREE" >&2
    exit 2
  fi
fi

is_managed() {
  # True if the path lives under a managed worktree dir.
  case "$1" in
    */.claude/worktrees/*|*/.worktrees/*) return 0 ;;
    *) return 1 ;;
  esac
}

branch_is_absorbed() {
  # True if the default branch already contains this branch's work, by EITHER
  # a normal merge or a squash merge. False on any error, so an unverifiable
  # branch is always kept.
  #
  # Squash detection: a squash merge rewrites the branch's commits into one new
  # commit, so the originals are not ancestors and their patch-ids do not match.
  # Replaying the branch's TREE as a single synthetic commit on the merge base
  # reproduces exactly what the squash produced, and `git cherry` then reports
  # it as already upstream ("-"). GIT_* identity is set explicitly because
  # `git commit-tree` fails with "empty ident name not allowed" on a machine or
  # CI runner with no configured git identity.
  local b="$1" base tree syn
  [ -n "$DEFAULT_REF" ] || return 1
  [ "$b" != "$DEFAULT_BRANCH" ] || return 1
  git show-ref --verify --quiet "refs/heads/$b" 2>/dev/null || return 1
  git merge-base --is-ancestor "refs/heads/$b" "$DEFAULT_REF" 2>/dev/null && return 0
  base="$(git merge-base "$DEFAULT_REF" "refs/heads/$b" 2>/dev/null)" || return 1
  [ -n "$base" ] || return 1
  tree="$(git rev-parse "refs/heads/$b^{tree}" 2>/dev/null)" || return 1
  syn="$(GIT_AUTHOR_NAME=worktree-sweep GIT_AUTHOR_EMAIL=worktree-sweep@localhost \
         GIT_COMMITTER_NAME=worktree-sweep GIT_COMMITTER_EMAIL=worktree-sweep@localhost \
         git commit-tree "$tree" -p "$base" -m _ 2>/dev/null)" || return 1
  [ -n "$syn" ] || return 1
  case "$(git cherry "$DEFAULT_REF" "$syn" 2>/dev/null)" in
    "-"*) return 0 ;;
  esac
  return 1
}

BRANCHES_DELETED=0
BRANCH_NOTE=""
BRANCH_LINES=""

# Snapshot the worktree table BEFORE pruning, so already-gone entries are still
# in it and their leftover branches can be cleaned. Then drop the stale metadata:
# git refuses to delete a branch a registered worktree still claims, so the claim
# has to go first. Pruning only ever touches entries whose directory is gone.
WT_LIST="$(git worktree list --porcelain)"
[ "$MODE" = "apply" ] && git worktree prune 2>/dev/null

cleanup_branch() {
  # Delete $1 if absorbed, else keep it. Sets BRANCH_NOTE to a report suffix.
  # Deliberately assigns a global instead of printing: a $(...) call site would
  # run this in a subshell and lose the BRANCHES_DELETED increment.
  local b="$1"
  BRANCH_NOTE=""
  [ -n "$b" ] || return 0
  if [ "$KEEP_BRANCHES" = "1" ]; then
    BRANCH_NOTE=" (branch $b kept: --keep-branches)"; return 0
  fi
  if ! branch_is_absorbed "$b"; then
    BRANCH_NOTE=" (branch $b KEPT: work not on ${DEFAULT_REF:-<unknown default>} - nothing discarded)"
    return 0
  fi
  if [ "$MODE" = "dry-run" ]; then
    BRANCH_NOTE=" (branch $b WOULD BE DELETED: already on $DEFAULT_REF)"
    BRANCHES_DELETED=$((BRANCHES_DELETED+1)); return 0
  fi
  if git branch -D "$b" >/dev/null 2>&1; then
    BRANCH_NOTE=" (branch $b deleted: already on $DEFAULT_REF)"
    BRANCHES_DELETED=$((BRANCHES_DELETED+1))
  else
    BRANCH_NOTE=" (branch $b kept: git refused the delete)"
  fi
}

in_progress_op() {
  # True if the worktree has a paused rebase/merge/cherry-pick/revert/bisect.
  wt="$1"
  for m in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG; do
    mp="$(git -C "$wt" rev-parse --git-path "$m" 2>/dev/null)"
    if [ -n "$mp" ] && [ -e "$mp" ]; then return 0; fi
  done
  return 1
}

REMOVED=0
RECLAIMED_KB=0
declare_preserved() { PRESERVED_LINES="${PRESERVED_LINES}$1"$'\n'; PRESERVED=$((PRESERVED+1)); }
PRESERVED=0
PRESERVED_LINES=""
REMOVED_LINES=""
SKIPPED=0
SKIPPED_LINES=""
PRUNABLE=0

# Walk `git worktree list --porcelain`. Records are blank-line separated.
CUR_PATH=""
CUR_BRANCH=""
CUR_DETACHED=0
CUR_LOCKED=0
CUR_PRUNABLE=0
CUR_BARE=0

process_record() {
  [ -z "$CUR_PATH" ] && return 0
  [ "$CUR_BARE" = "1" ] && return 0                                  # the bare repo itself is not a checkout
  if [ -n "$MAIN_CHECKOUT" ] && [ "$CUR_PATH" = "$MAIN_CHECKOUT" ]; then return 0; fi   # main checkout
  # --worktree scopes the whole sweep to one unit of work.
  if [ -n "$ONLY_WORKTREE" ] && [ "$CUR_PATH" != "$ONLY_WORKTREE" ]; then return 0; fi
  local path="$CUR_PATH"
  local label="$path"
  if [ "$CUR_DETACHED" = "1" ]; then label="$label  (detached)"; else label="$label  [$CUR_BRANCH]"; fi

  # Already-gone directory: git prunable will drop the metadata. Its branch is
  # still a teardown leftover, so it gets the same verified cleanup.
  if [ "$CUR_PRUNABLE" = "1" ] || [ ! -d "$path" ]; then
    PRUNABLE=$((PRUNABLE+1))
    if [ "$CUR_DETACHED" != "1" ] && [ -n "$CUR_BRANCH" ]; then
      cleanup_branch "$CUR_BRANCH"
      [ -n "$BRANCH_NOTE" ] && BRANCH_LINES="${BRANCH_LINES}  - ${CUR_BRANCH} (worktree already gone)${BRANCH_NOTE}"$'\n'
    fi
    return 0
  fi
  # Never touch the worktree we are standing in.
  if [ "$path" = "$CWD_WT" ]; then
    SKIPPED_LINES="${SKIPPED_LINES}  - $label -> current worktree (skipped)"$'\n'; SKIPPED=$((SKIPPED+1)); return 0
  fi
  # Preserve: locked.
  if [ "$CUR_LOCKED" = "1" ]; then
    declare_preserved "  - $label -> PRESERVE (locked; run 'git worktree unlock' if intended)"; return 0
  fi
  # Preserve: in-progress operation.
  if in_progress_op "$path"; then
    declare_preserved "  - $label -> PRESERVE (in-progress rebase/merge/cherry-pick)"; return 0
  fi
  # Preserve: uncommitted tracked changes or untracked non-ignored files.
  if [ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]; then
    declare_preserved "  - $label -> PRESERVE (uncommitted or untracked changes)"; return 0
  fi
  # Preserve: a detached-HEAD worktree whose commit is reachable from NO ref.
  # A branch worktree's commits survive removal on the branch ref, but a detached
  # HEAD has no ref - removing it orphans any commits made on top (gc-eligible).
  # If some branch/tag/remote already contains the tip (the common "parked at an
  # existing commit" case), removal is safe and we fall through.
  if [ "$CUR_DETACHED" = "1" ]; then
    local head_sha reached
    head_sha="$(git -C "$path" rev-parse HEAD 2>/dev/null)"
    reached="$(git -C "$path" for-each-ref --contains "$head_sha" --format='%(refname)' 2>/dev/null | head -1)"
    if [ -z "$reached" ]; then
      declare_preserved "  - $label -> PRESERVE (detached HEAD; commits reachable from no ref would be orphaned)"; return 0
    fi
  fi
  # From here the worktree is CLEAN and its committed work survives removal.
  local unmerged=""
  if [ -n "$DEFAULT_REF" ] && [ "$CUR_DETACHED" != "1" ]; then
    local n
    n="$(git -C "$path" rev-list --count "${DEFAULT_REF}..HEAD" 2>/dev/null || echo 0)"
    [ "$n" -gt 0 ] 2>/dev/null && unmerged="$n"
  fi
  # Conservative mode preserves clean-but-unmerged branch checkouts.
  if [ "$CONSERVATIVE" = "1" ] && [ -n "$unmerged" ]; then
    declare_preserved "  - $label -> PRESERVE (--conservative: $unmerged commit(s) not on $DEFAULT_REF)"; return 0
  fi
  # Only sweep managed locations unless --all.
  if [ "$ALL" != "1" ] && ! is_managed "$path"; then
    SKIPPED_LINES="${SKIPPED_LINES}  - $label -> clean, outside managed dirs (skipped; --all to include)"$'\n'; SKIPPED=$((SKIPPED+1)); return 0
  fi

  local kb; kb="$(du -sk "$path" 2>/dev/null | awk '{print $1}')"; [ -z "$kb" ] && kb=0
  if [ "$MODE" = "dry-run" ]; then
    branch_note_for "$path"
    REMOVED_LINES="${REMOVED_LINES}  - $label -> WOULD REMOVE, ~$((kb/1024)) MB${BRANCH_NOTE}"$'\n'
    REMOVED=$((REMOVED+1)); RECLAIMED_KB=$((RECLAIMED_KB+kb)); return 0
  fi
  if git worktree remove "$path" 2>/dev/null; then
    # Branch cleanup runs only AFTER the checkout is gone: git refuses to delete
    # a branch that a live worktree has checked out.
    branch_note_for "$path"
    REMOVED_LINES="${REMOVED_LINES}  - $label -> removed, ~$((kb/1024)) MB${BRANCH_NOTE}"$'\n'
    REMOVED=$((REMOVED+1)); RECLAIMED_KB=$((RECLAIMED_KB+kb))
  else
    # Non-force refused: git found something unsafe the checks missed. Never force.
    declare_preserved "  - $label -> PRESERVE (git refused non-force removal)"
  fi
}

branch_note_for() {
  # Resolve the branch decision for the record being processed, appending the
  # restore hint whenever the branch survives. $1 is the worktree path (for the
  # hint only).
  BRANCH_NOTE=""
  [ "$CUR_DETACHED" = "1" ] && return 0        # detached: no branch to clean up
  [ -n "$CUR_BRANCH" ] || return 0
  cleanup_branch "$CUR_BRANCH"
  case "$BRANCH_NOTE" in
    *"deleted:"*|*"WOULD BE DELETED"*) ;;
    "") ;;
    *) BRANCH_NOTE="${BRANCH_NOTE%)}; restore with 'git worktree add $1 $CUR_BRANCH')" ;;
  esac
}

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "worktree "*) process_record; CUR_PATH="${line#worktree }"; CUR_BRANCH=""; CUR_DETACHED=0; CUR_LOCKED=0; CUR_PRUNABLE=0; CUR_BARE=0 ;;
    "branch "*)   CUR_BRANCH="${line#branch refs/heads/}" ;;
    "detached")   CUR_DETACHED=1 ;;
    "locked"*)    CUR_LOCKED=1 ;;
    "prunable"*)  CUR_PRUNABLE=1 ;;
    "bare")       CUR_BARE=1 ;;   # the bare repo entry has no checkout; skip it
  esac
done <<EOF
${WT_LIST}
EOF
process_record   # flush the final record

# --merged-branches: leftover branches with no worktree at all. This is the
# recovery path when a worktree was removed by hand earlier, leaving a branch
# `git branch -d` will not delete because the PR was squash-merged. Only
# branches the default branch already contains are touched, and never one that
# is checked out anywhere.
if [ "$MERGED_BRANCHES" = "1" ] && [ "$KEEP_BRANCHES" != "1" ] && [ -n "$DEFAULT_REF" ]; then
  CHECKED_OUT="$(git worktree list --porcelain | sed -n 's/^branch refs\/heads\///p')"
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    [ "$b" = "$DEFAULT_BRANCH" ] && continue
    printf '%s\n' "$CHECKED_OUT" | grep -qxF "$b" && continue
    branch_is_absorbed "$b" || continue
    if [ "$MODE" = "dry-run" ]; then
      BRANCH_LINES="${BRANCH_LINES}  - $b (no worktree) WOULD BE DELETED: already on $DEFAULT_REF"$'\n'
      BRANCHES_DELETED=$((BRANCHES_DELETED+1))
    elif git branch -D "$b" >/dev/null 2>&1; then
      BRANCH_LINES="${BRANCH_LINES}  - $b (no worktree) deleted: already on $DEFAULT_REF"$'\n'
      BRANCHES_DELETED=$((BRANCHES_DELETED+1))
    fi
  done <<EOF
$(git for-each-ref --format='%(refname:short)' refs/heads)
EOF
fi

# Drop administrative state for worktrees whose directories are gone or removed.
if [ "$MODE" = "dry-run" ]; then
  echo "=== worktree-sweep (DRY RUN - nothing removed) ==="
else
  git worktree prune 2>/dev/null
  echo "=== worktree-sweep ==="
fi
[ -n "$DEFAULT_REF" ] && echo "default branch: $DEFAULT_REF"
echo ""
if [ "$REMOVED" -gt 0 ]; then
  echo "REMOVED ($REMOVED, ~$((RECLAIMED_KB/1024)) MB reclaimed):"
  printf "%s" "$REMOVED_LINES"
  echo ""
fi
if [ "$PRESERVED" -gt 0 ]; then
  echo "PRESERVED ($PRESERVED, unsaved work / in-progress / locked):"
  printf "%s" "$PRESERVED_LINES"
  echo ""
fi
if [ "$SKIPPED" -gt 0 ]; then
  echo "SKIPPED ($SKIPPED):"
  printf "%s" "$SKIPPED_LINES"
  echo ""
fi
if [ -n "$BRANCH_LINES" ]; then
  echo "BRANCHES (no live worktree):"
  printf "%s" "$BRANCH_LINES"
  echo ""
fi
[ "$PRUNABLE" -gt 0 ] && echo "PRUNED $PRUNABLE worktree(s) whose directory was already gone."
echo "Done. $REMOVED removed, $PRESERVED preserved, $SKIPPED skipped, $BRANCHES_DELETED branch(es) deleted."
