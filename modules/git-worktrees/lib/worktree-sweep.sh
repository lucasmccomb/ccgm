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
# Usage: worktree-sweep.sh [--dry-run|-n] [--conservative] [--all] [-h|--help]
#   --dry-run       Report the classification and planned actions; remove nothing.
#   --conservative  Also PRESERVE clean worktrees whose branch has commits not on
#                   the origin default branch (keep in-progress-but-committed
#                   checkouts around). Default removes clean worktrees regardless,
#                   since their commits survive on the branch ref.
#   --all           Also sweep clean worktrees outside the two managed locations.
#   -h, --help      Print this header.
set -u

MODE="apply"
CONSERVATIVE=0
ALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) MODE="dry-run" ;;
    --conservative) CONSERVATIVE=1 ;;
    --all) ALL=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "worktree-sweep: unknown arg: $arg" >&2; exit 2 ;;
  esac
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

is_managed() {
  # True if the path lives under a managed worktree dir.
  case "$1" in
    */.claude/worktrees/*|*/.worktrees/*) return 0 ;;
    *) return 1 ;;
  esac
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
  local path="$CUR_PATH"
  local label="$path"
  if [ "$CUR_DETACHED" = "1" ]; then label="$label  (detached)"; else label="$label  [$CUR_BRANCH]"; fi

  # Already-gone directory: git prunable will drop the metadata.
  if [ "$CUR_PRUNABLE" = "1" ] || [ ! -d "$path" ]; then
    PRUNABLE=$((PRUNABLE+1)); return 0
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
  local note=""
  [ -n "$unmerged" ] && note=" (branch kept: $unmerged commit(s) not on $DEFAULT_REF; restore with 'git worktree add $path $CUR_BRANCH')"
  if [ "$MODE" = "dry-run" ]; then
    REMOVED_LINES="${REMOVED_LINES}  - $label -> WOULD REMOVE, ~$((kb/1024)) MB$note"$'\n'
    REMOVED=$((REMOVED+1)); RECLAIMED_KB=$((RECLAIMED_KB+kb)); return 0
  fi
  if git worktree remove "$path" 2>/dev/null; then
    REMOVED_LINES="${REMOVED_LINES}  - $label -> removed, ~$((kb/1024)) MB$note"$'\n'
    REMOVED=$((REMOVED+1)); RECLAIMED_KB=$((RECLAIMED_KB+kb))
  else
    # Non-force refused: git found something unsafe the checks missed. Never force.
    declare_preserved "  - $label -> PRESERVE (git refused non-force removal)"
  fi
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
$(git worktree list --porcelain)
EOF
process_record   # flush the final record

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
[ "$PRUNABLE" -gt 0 ] && echo "PRUNED $PRUNABLE worktree(s) whose directory was already gone."
echo "Done. $REMOVED removed, $PRESERVED preserved, $SKIPPED skipped."
