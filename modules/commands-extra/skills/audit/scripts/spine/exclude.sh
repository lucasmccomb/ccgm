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

# Canonical excluded directory NAMES.
CCGM_EXCLUDE_DIRS=()
if [[ -f "$_CCGM_EXCLUDE_LIST" ]]; then
  while read -r _ccgm_line || [[ -n "$_ccgm_line" ]]; do
    _ccgm_line="${_ccgm_line%%#*}"                              # strip comments
    _ccgm_line="${_ccgm_line#"${_ccgm_line%%[![:space:]]*}"}"   # ltrim
    _ccgm_line="${_ccgm_line%"${_ccgm_line##*[![:space:]]}"}"   # rtrim
    [[ -z "$_ccgm_line" ]] && continue
    CCGM_EXCLUDE_DIRS+=("$_ccgm_line")
  done < "$_CCGM_EXCLUDE_LIST"
fi

# Each function below sets the global array CCGM_FLAGS to the tool-specific
# exclusion flags.  Callers read CCGM_FLAGS immediately after calling.

# eslint: --ignore-pattern globs (work with --no-config-lookup).  Match both
# top-level (<dir>/**) and nested (**/<dir>/**) occurrences.
ccgm_eslint_ignore_args() {
  CCGM_FLAGS=()
  local d
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--ignore-pattern "$d/**" --ignore-pattern "**/$d/**")
  done
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

# trivy: --skip-dirs takes a doublestar glob, repeatable.
ccgm_trivy_skip_args() {
  CCGM_FLAGS=()
  local d
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--skip-dirs "**/$d/**" --skip-dirs "$d/**")
  done
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

# semgrep: --exclude takes a path/basename glob, repeatable.
ccgm_semgrep_exclude_args() {
  CCGM_FLAGS=()
  local d
  for d in "${CCGM_EXCLUDE_DIRS[@]}"; do
    CCGM_FLAGS+=(--exclude "$d")
  done
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
