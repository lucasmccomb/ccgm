#!/usr/bin/env bash
# CCGM audit spine -- shared path-exclusion helpers (SOURCED, not executed).
#
# Reads the canonical excluded-dir list (exclude-dirs.txt) into the array
# CCGM_EXCLUDE_DIRS and provides functions that render that list into each
# file-walking tool's own flag dialect.  This is the PERFORMANCE half of the
# #1 fix: tools never scan node_modules / stale worktrees in the first place.
# exclude.py is the correctness backstop (post-filter) for anything that slips.
#
# Bash-3.2-portable: no associative arrays, no namerefs, no mapfile -d.
# Functions that must "return" an array populate a caller-named array via the
# conventional `eval`-free pattern of printing nothing and assigning a global.
#
# Usage in a wrapper:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=exclude.sh
#   . "$SCRIPT_DIR/exclude.sh"
#   ccgm_eslint_ignore_args        # populates CCGM_FLAGS=(--ignore-pattern ... )
#   eslint "${CCGM_FLAGS[@]}" ...

# Resolve our own directory even when sourced.
_CCGM_EXCLUDE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CCGM_EXCLUDE_LIST="$_CCGM_EXCLUDE_DIR/exclude-dirs.txt"
_CCGM_EXCLUDE_GLOBS="$_CCGM_EXCLUDE_DIR/exclude-file-globs.txt"

# Read a one-entry-per-line list file into the array named by $1 (comments and
# blank lines stripped). Bash-3.2-portable (no namerefs): appends via eval-free
# `read -r` loop targeting a temporary, then assigns the caller's array.
_ccgm_read_list() {
  local _file="$1"
  CCGM_LIST_RESULT=()
  [[ -f "$_file" ]] || return 0
  local _line
  while read -r _line || [[ -n "$_line" ]]; do
    _line="${_line%%#*}"                          # strip comments
    _line="${_line#"${_line%%[![:space:]]*}"}"    # ltrim
    _line="${_line%"${_line##*[![:space:]]}"}"    # rtrim
    [[ -z "$_line" ]] && continue
    CCGM_LIST_RESULT+=("$_line")
  done < "$_file"
}

# Canonical excluded directory NAMES.
# The length guard keeps the empty-array assignment nounset-safe on bash 3.2,
# where "${arr[@]}" on an empty array errors under `set -u`.
CCGM_EXCLUDE_DIRS=()
_ccgm_read_list "$_CCGM_EXCLUDE_LIST"
if [[ ${#CCGM_LIST_RESULT[@]} -gt 0 ]]; then
  CCGM_EXCLUDE_DIRS=("${CCGM_LIST_RESULT[@]}")
else
  # Fallback (mirrors exclude.py): never leave the dir list empty, so the
  # unguarded `for d in "${CCGM_EXCLUDE_DIRS[@]}"` loops below stay nounset-safe
  # on bash 3.2 and exclusion degrades gracefully if the list file is missing.
  CCGM_EXCLUDE_DIRS=(node_modules .git .claude .audit dist build)
fi

# Canonical excluded file-name GLOBS (e.g. *.min.js) -- caught by basename
# regardless of directory, so a committed client/public/js-dos/foo.min.js is
# excluded even though none of its path segments is an excluded dir name.
CCGM_EXCLUDE_FILE_GLOBS=()
_ccgm_read_list "$_CCGM_EXCLUDE_GLOBS"
if [[ ${#CCGM_LIST_RESULT[@]} -gt 0 ]]; then
  CCGM_EXCLUDE_FILE_GLOBS=("${CCGM_LIST_RESULT[@]}")
fi

# Each function below sets the global array CCGM_FLAGS to the tool-specific
# exclusion flags.  Callers read CCGM_FLAGS immediately after calling.

# eslint: --ignore-pattern globs (work with --no-config-lookup).  Match both
# top-level (<dir>/**) and nested (**/<dir>/**) occurrences, plus file globs
# (**/*.min.js) so vendored minified files outside an excluded dir are skipped.
ccgm_eslint_ignore_args() {
  CCGM_FLAGS=()
  local d g
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--ignore-pattern "$d/**" --ignore-pattern "**/$d/**")
  done
  if [[ ${#CCGM_EXCLUDE_FILE_GLOBS[@]} -gt 0 ]]; then
    for g in "${CCGM_EXCLUDE_FILE_GLOBS[@]}"; do
      CCGM_FLAGS+=(--ignore-pattern "**/$g")
    done
  fi
}

# bandit: -x / --exclude takes one comma-separated list of path globs.
# Sets CCGM_BANDIT_EXCLUDE to that comma list (empty if no dirs).
ccgm_bandit_exclude_csv() {
  CCGM_BANDIT_EXCLUDE=""
  local d
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    if [[ -z "$CCGM_BANDIT_EXCLUDE" ]]; then
      CCGM_BANDIT_EXCLUDE="*/$d/*"
    else
      CCGM_BANDIT_EXCLUDE="$CCGM_BANDIT_EXCLUDE,*/$d/*"
    fi
  done
}

# trivy: --skip-dirs takes a doublestar glob, repeatable; --skip-files for the
# vendored minified file globs.
ccgm_trivy_skip_args() {
  CCGM_FLAGS=()
  local d g
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--skip-dirs "**/$d/**" --skip-dirs "$d/**")
  done
  if [[ ${#CCGM_EXCLUDE_FILE_GLOBS[@]} -gt 0 ]]; then
    for g in "${CCGM_EXCLUDE_FILE_GLOBS[@]}"; do
      CCGM_FLAGS+=(--skip-files "**/$g")
    done
  fi
}

# checkov: --skip-path takes a regex, repeatable.
ccgm_checkov_skip_args() {
  CCGM_FLAGS=()
  local d esc
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    esc="${d//./\\.}"
    CCGM_FLAGS+=(--skip-path "(^|/)$esc(/|$)")
  done
}

# semgrep: --exclude takes a path/basename glob, repeatable (dirs + file globs).
ccgm_semgrep_exclude_args() {
  CCGM_FLAGS=()
  local d g
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--exclude "$d")
  done
  if [[ ${#CCGM_EXCLUDE_FILE_GLOBS[@]} -gt 0 ]]; then
    for g in "${CCGM_EXCLUDE_FILE_GLOBS[@]}"; do
      CCGM_FLAGS+=(--exclude "$g")
    done
  fi
}

# find(1): prune predicate elements for find-based wrappers.  Emits
#   -name <dir> -prune -o
# pairs into CCGM_FIND_PRUNE so a wrapper can splice them into its find call:
#   find "$root" \( CCGM_FIND_PRUNE -false \) -o -type f ... -print0
ccgm_find_prune_args() {
  CCGM_FIND_PRUNE=()
  local d first=1
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    if [[ $first -eq 1 ]]; then
      first=0
    else
      CCGM_FIND_PRUNE+=(-o)
    fi
    CCGM_FIND_PRUNE+=(-name "$d")
  done
}
