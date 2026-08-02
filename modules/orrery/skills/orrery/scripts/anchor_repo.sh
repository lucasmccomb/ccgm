#!/usr/bin/env bash
set -euo pipefail

# orrery anchor stage (plan section 3.1 stages 1 + 6, Epic 2).
#
# Usage:
#   anchor_repo.sh <repo-path>
#       Pins the target repo to its default-ref SHA, creates a uniquely-named
#       detached temp worktree at that SHA, derives the strict slug, creates
#       the chmod-700 output dir, and emits a single-line JSON anchor record
#       on stdout:
#         {"repo_path", "remote_url", "default_ref", "anchor_sha", "worktree",
#          "slug", "behind", "dirty", "no_remote", "visibility"}
#   anchor_repo.sh --teardown <repo-path> <worktree>
#       Removes the anchor worktree and prunes worktree metadata. Idempotent,
#       never fatal - the single entry point every exit path calls (stage 6).
#
# Exit codes: 0 success; 2 with a single-line JSON error object on an
# unreachable repo, a fetch failure, or an unsanitizable slug.
#
# Security notes:
#   C6 - remote_url userinfo (user[:token]@) is stripped BEFORE any output;
#        the raw URL is never echoed, not even in error messages.
#   C7 - the slug must match ^[a-z0-9][a-z0-9_-]*$ after sanitization or we
#        exit 2; it is derived from the repo directory basename only, so a
#        path-shaped argument can never smuggle separators into the slug.
#   R4 - the output dir ${ORRERY_HOME:-~/code/orrery}/{slug} is chmod 700.
#        $ORRERY_HOME overrides the output root without editing this module
#        (risk adrev2-014); unset, it defaults to ~/code/orrery.
#
# The run mutates the target repo in three ways - `git fetch origin`,
# `git remote set-head origin --auto` (refreshes the stale origin/HEAD
# symref after the fetch), and `git worktree add`. The worktree is the only
# durable side effect, so any failure after it is created triggers teardown
# from the error path.
#
# Portable: macOS bash 3.2 + BSD tools. Deterministic: no LLM or tool calls.

json_escape() {
  # Escape backslash and double quote for embedding in a JSON string.
  printf '%s' "$1" | LC_ALL=C sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

emit_error() {
  # $1 = message, $2 = repo path (may be empty). Single-line JSON, exit 2.
  printf '{"error":"%s","repo_path":"%s"}\n' \
    "$(json_escape "$1")" "$(json_escape "${2:-}")"
  exit 2
}

strip_userinfo() {
  # Remove any user[:token]@ userinfo before the host, for both
  # scheme://user:token@host/... and scp-like user@host:... URL forms.
  # Schemes are case-insensitive (RFC 3986), so the class allows A-Z too:
  # an HTTPS:// URL must strip exactly like https:// (review finding 3).
  printf '%s' "$1" | LC_ALL=C sed -e 's#^\([a-zA-Z][a-zA-Z0-9+.-]*://\)\{0,1\}[^/@]*@#\1#'
}

sanitize_slug() {
  # STRICT slug rule (security C7): lowercase, collapse every run of
  # non-[a-z0-9] to _, trim leading/trailing _, truncate to 64 chars.
  # The caller verifies the result against ^[a-z0-9][a-z0-9_-]*$.
  printf '%s' "$1" \
    | LC_ALL=C tr '[:upper:]' '[:lower:]' \
    | LC_ALL=C sed -e 's/[^a-z0-9]\{1,\}/_/g' -e 's/^_*//' -e 's/_*$//' \
    | LC_ALL=C cut -c1-64
}

teardown_worktree() {
  # Stage 6: idempotent, never fatal. $1 = repo, $2 = worktree path.
  git -C "$1" worktree remove --force "$2" >/dev/null 2>&1 || true
  git -C "$1" worktree prune >/dev/null 2>&1 || true
  # The worktree lives inside a private mktemp base dir; reclaim it when empty.
  rmdir "$(dirname "$2")" >/dev/null 2>&1 || true
  return 0
}

# --- teardown mode -----------------------------------------------------------
if [ "${1:-}" = "--teardown" ]; then
  if [ $# -ne 3 ]; then
    echo "usage: anchor_repo.sh --teardown <repo-path> <worktree>" >&2
    exit 2
  fi
  teardown_worktree "$2" "$3"
  exit 0
fi

if [ $# -ne 1 ]; then
  echo "usage: anchor_repo.sh <repo-path> | anchor_repo.sh --teardown <repo-path> <worktree>" >&2
  exit 2
fi
REPO_ARG="$1"

# --- validate the repo -------------------------------------------------------
# Control characters anywhere in the path would corrupt the single-line JSON
# output while exiting 0 (review finding 2). Reject them up front, and never
# echo the offending path back - emit_error must stay valid JSON.
case "$REPO_ARG" in
  *[[:cntrl:]]*)
    emit_error "repo path contains control characters" ""
    ;;
esac
if [ ! -d "$REPO_ARG" ]; then
  emit_error "repo path does not exist or is not a directory" "$REPO_ARG"
fi
# `cd --` so a repo dir name starting with `-` is never parsed as an option,
# and an unreadable dir fails through emit_error instead of aborting via
# set -e with a non-2 exit and no JSON (review finding 6).
if ! REPO="$(cd -- "$REPO_ARG" && pwd -P)"; then
  emit_error "repo path exists but could not be entered" "$REPO_ARG"
fi
case "$REPO" in
  *[[:cntrl:]]*)
    emit_error "resolved repo path contains control characters" ""
    ;;
esac
if ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  emit_error "not a git repository" "$REPO"
fi

# --- worktree prune FIRST ----------------------------------------------------
# A prior run killed before teardown leaves stale worktree metadata that a
# later worktree add can collide with.
git -C "$REPO" worktree prune >/dev/null 2>&1 || true

# --- slug (before the worktree exists, so a failure here needs no cleanup) ---
SLUG="$(sanitize_slug "$(basename "$REPO")")"
if ! printf '%s' "$SLUG" | LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9_-]*$'; then
  emit_error "repo directory name cannot be sanitized to a valid slug" "$REPO"
fi

# --- remote detection + credential stripping BEFORE any output ---------------
NO_REMOTE=false
REMOTE_URL=""
# config --get (not remote get-url): get-url expands insteadOf rewrites, and
# the credential-bearing string to strip is the URL as configured.
# `config --get` exits 1 when the key is simply not set (git-config(1)) -
# that is a legitimate no-remote repo. Any other nonzero exit (unreadable or
# malformed config file, etc.) is a genuine read failure and must not be
# silently folded into the same no_remote path (review finding 7a).
GIT_CONFIG_RC=0
RAW_URL="$(git -C "$REPO" config --get remote.origin.url 2>/dev/null)" || GIT_CONFIG_RC=$?
if [ "$GIT_CONFIG_RC" -eq 0 ]; then
  REMOTE_URL="$(strip_userinfo "$RAW_URL")"
elif [ "$GIT_CONFIG_RC" -eq 1 ]; then
  NO_REMOTE=true
else
  emit_error "cannot read remote.origin.url from git config (exit $GIT_CONFIG_RC)" "$REPO"
fi
RAW_URL=""

# --- fetch + default ref resolution + SHA pin --------------------------------
DEFAULT_REF=""
if [ "$NO_REMOTE" = "false" ]; then
  if ! git -C "$REPO" fetch origin >/dev/null 2>&1; then
    emit_error "git fetch origin failed (remote: $REMOTE_URL)" "$REPO"
  fi
  # Refresh the origin/HEAD symref before reading it: a plain fetch neither
  # updates the symref nor prunes a renamed-away default branch, so a stale
  # symref would silently anchor the dead branch's old tip (review finding 1).
  # Tolerate failure - the fallback chain below then behaves as before.
  git -C "$REPO" remote set-head origin --auto >/dev/null 2>&1 || true
  ORIGIN_HEAD="$(git -C "$REPO" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$ORIGIN_HEAD" ]; then
    DEFAULT_REF="origin/${ORIGIN_HEAD#refs/remotes/origin/}"
  elif git -C "$REPO" show-ref --verify --quiet refs/remotes/origin/main; then
    DEFAULT_REF="origin/main"
  fi
fi
if [ -z "$DEFAULT_REF" ]; then
  # Local default branch: the no-remote case (flagged via no_remote), or a
  # remote whose origin/HEAD and origin/main are both unresolvable.
  DEFAULT_REF="$(git -C "$REPO" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  if [ -z "$DEFAULT_REF" ]; then
    DEFAULT_REF="HEAD"
  fi
fi

ANCHOR_SHA="$(git -C "$REPO" rev-parse --verify "$DEFAULT_REF^{commit}" 2>/dev/null || true)"
if [ -z "$ANCHOR_SHA" ]; then
  emit_error "cannot resolve default ref $DEFAULT_REF to a commit" "$REPO"
fi

# --- behind + dirty ----------------------------------------------------------
# Never fabricate a 0: a rev-list failure (e.g. an orphan local branch with a
# remote configured) must be distinguishable from a legitimate zero-commits-
# behind result (review finding 7b). BEHIND holds the bare JSON token to
# emit - either a decimal count or the literal `null`.
if REV_COUNT="$(git -C "$REPO" rev-list --count "HEAD..$ANCHOR_SHA" 2>/dev/null)"; then
  BEHIND="$(printf '%s' "$REV_COUNT" | tr -cd '0-9')"
  if [ -z "$BEHIND" ]; then
    BEHIND=null
  fi
else
  BEHIND=null
fi
DIRTY=false
if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then
  DIRTY=true
fi

# --- detached temp worktree (uniquely named) ---------------------------------
CLEANUP_WT=""
on_exit() {
  STATUS=$?
  if [ "$STATUS" -ne 0 ] && [ -n "$CLEANUP_WT" ]; then
    # Error path after the worktree exists: tear it down (stage 6).
    teardown_worktree "$REPO" "$CLEANUP_WT"
  fi
}
trap on_exit EXIT

# A mktemp failure must fail through emit_error, not abort via set -e with a
# non-2 exit and no JSON (review finding 6).
if ! WT_BASE="$(mktemp -d "${TMPDIR:-/tmp}/orrery-anchor-${SLUG}.XXXXXX" 2>/dev/null)"; then
  emit_error "mktemp failed to create a temp worktree directory" "$REPO"
fi
WT="$WT_BASE/wt"
# TMPDIR is caller-controlled and flows straight into WT; a control character
# there reproduces the exit-0-with-invalid-JSON shape the repo-path guard
# above closed (delta re-review residual). Reject before mutating anything.
case "$WT" in
  *[[:cntrl:]]*)
    rmdir "$WT_BASE" >/dev/null 2>&1 || true
    emit_error "resolved worktree path contains control characters" "$REPO"
    ;;
esac
if ! git -C "$REPO" worktree add --detach "$WT" "$ANCHOR_SHA" >/dev/null 2>&1; then
  rmdir "$WT_BASE" >/dev/null 2>&1 || true
  emit_error "git worktree add failed" "$REPO"
fi
CLEANUP_WT="$WT"

# --- repo visibility (gh-based, never fatal) ---------------------------------
VISIBILITY="unknown"
OWNER_REPO=""
case "$REMOTE_URL" in
  *github.com/*|*github.com:*)
    OWNER_REPO="$(printf '%s' "$REMOTE_URL" \
      | LC_ALL=C sed -e 's#^.*github\.com[:/]##' -e 's#\.git$##' -e 's#/*$##' \
      | cut -d/ -f1,2)"
    ;;
esac
if [ -n "$OWNER_REPO" ] && command -v gh >/dev/null 2>&1; then
  IS_PRIVATE="$(gh repo view "$OWNER_REPO" --json isPrivate --jq .isPrivate 2>/dev/null || true)"
  case "$IS_PRIVATE" in
    true)  VISIBILITY="private" ;;
    false) VISIBILITY="public" ;;
  esac
fi

# --- output dir (security R4) ------------------------------------------------
OUT_DIR="${ORRERY_HOME:-$HOME/code/orrery}/$SLUG"
if ! mkdir -p "$OUT_DIR" 2>/dev/null; then
  emit_error "cannot create output dir $OUT_DIR" "$REPO"
fi
if ! chmod 700 "$OUT_DIR" 2>/dev/null; then
  emit_error "cannot chmod 700 output dir $OUT_DIR" "$REPO"
fi

# --- single-line JSON anchor record ------------------------------------------
printf '{"repo_path":"%s","remote_url":"%s","default_ref":"%s","anchor_sha":"%s","worktree":"%s","slug":"%s","behind":%s,"dirty":%s,"no_remote":%s,"visibility":"%s"}\n' \
  "$(json_escape "$REPO")" \
  "$(json_escape "$REMOTE_URL")" \
  "$(json_escape "$DEFAULT_REF")" \
  "$ANCHOR_SHA" \
  "$(json_escape "$WT")" \
  "$SLUG" \
  "$BEHIND" \
  "$DIRTY" \
  "$NO_REMOTE" \
  "$VISIBILITY"
exit 0
