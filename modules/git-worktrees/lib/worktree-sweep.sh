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
# KEY SAFETY FACT: removing a clean worktree never loses committed work - the
# branch ref stays in the parent .git; only the working-tree checkout (and its
# build artifacts) are removed. Re-create the checkout later with
# `git worktree add <path> <branch>`. So a clean worktree is always safe.
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

# Walk `git worktree list --porcelain`. Records are blank-line separated. The
# FIRST record is always the main checkout - skip it.
FIRST=1
CUR_PATH=""
CUR_BRANCH=""
CUR_DETACHED=0
CUR_LOCKED=0
CUR_PRUNABLE=0

process_record() {
  [ -z "$CUR_PATH" ] && return 0
  if [ "$FIRST" = "1" ]; then FIRST=0; return 0; fi   # main checkout
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
  # From here the worktree is CLEAN.
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
    "worktree "*) process_record; CUR_PATH="${line#worktree }"; CUR_BRANCH=""; CUR_DETACHED=0; CUR_LOCKED=0; CUR_PRUNABLE=0 ;;
    "branch "*)   CUR_BRANCH="${line#branch refs/heads/}" ;;
    "detached")   CUR_DETACHED=1 ;;
    "locked"*)    CUR_LOCKED=1 ;;
    "prunable"*)  CUR_PRUNABLE=1 ;;
    "bare")       CUR_PATH="" ;;   # never touch a bare repo entry
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
