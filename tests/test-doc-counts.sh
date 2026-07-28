#!/usr/bin/env bash
set -euo pipefail

# CCGM Doc-Count + Preset-Coverage Guard
#
# Derives the true module count and per-preset membership FROM THE REPO, then
# fails if:
#   (a) any committed module-count claim in docs disagrees with reality, or
#   (b) the `full` preset count claim in docs disagrees with presets/full.json, or
#   (c) any stable, non-allowlisted module sits in zero presets, or
#   (d) any preset references a module that does not exist, or
#   (e) the allowlist contains a stale entry (a module that IS in a preset).
#
# Nothing here is hardcoded to a number — truth comes from modules/*/module.json
# and presets/*.json. Portable: bash 3.2, BSD/GNU grep, no GNU-only flags.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v jq >/dev/null 2>&1; then
  echo "FAIL: jq is required for tests/test-doc-counts.sh" >&2
  exit 1
fi

FAILURES=0
fail() {
  echo "FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}
ok() {
  echo "ok: $1"
}

# --- Derive truth -----------------------------------------------------------

# Module count = number of modules/*/module.json
MODULE_COUNT=$(find modules -mindepth 2 -maxdepth 2 -name module.json | wc -l | tr -d ' ')
echo "Derived module count: $MODULE_COUNT"

# full preset length
FULL_PRESET_COUNT=$(jq 'length' presets/full.json)
echo "Derived full-preset count: $FULL_PRESET_COUNT"

# --- (a) module-count claims in docs ---------------------------------------
# Each entry: "file:regex-with-COUNT-placeholder". The literal token __N__ in
# the pattern stands for the derived module count. The check greps for the
# pattern with the real count substituted; absence => drifted or removed claim.

check_count_claim() {
  local file="$1" template="$2" expected="$3"
  local needle
  needle=$(printf '%s' "$template" | sed "s/__N__/$expected/g")
  if [ ! -f "$file" ]; then
    fail "expected file $file not found (count claim cannot be verified)"
    return
  fi
  if grep -qF "$needle" "$file"; then
    ok "$file count claim matches $expected (\"$needle\")"
  else
    # Surface what the file currently says for the same phrase prefix.
    local prefix
    prefix=$(printf '%s' "$template" | sed 's/__N__.*//')
    local current
    current=$(grep -n "$prefix" "$file" | head -3 || true)
    fail "$file does not contain expected count claim \"$needle\". Current lines matching \"$prefix\":
$current"
  fi
}

check_count_claim "CLAUDE.md"               "It contains __N__ modules"          "$MODULE_COUNT"
check_count_claim "CLAUDE.md"               "# __N__ self-contained modules"     "$MODULE_COUNT"
check_count_claim "README.md"               "all __N__ modules"                  "$MODULE_COUNT"
check_count_claim "README.md"               "collection of __N__ configuration modules" "$MODULE_COUNT"
check_count_claim "docs/modules.md"         "CCGM contains __N__ modules"        "$MODULE_COUNT"
check_count_claim "docs/getting-started.md" "all __N__ modules"                  "$MODULE_COUNT"

# --- (a2) generic stale-count phrasings anywhere in tracked docs -------------
# Catch the "N configuration modules" and "collection of N ... modules" classes
# regardless of which doc they appear in, so a wrong number cannot slip in via a
# phrasing the explicit list above does not cover. Any match whose number is NOT
# the derived MODULE_COUNT fails.
check_no_wrong_count_phrasing() {
  local label="$1"
  shift
  local regex="$1"
  local found_wrong=0
  local matches
  # -R over the docs we ship; -n for line numbers; -E for extended regex.
  # Limit to Markdown docs at the repo root and under docs/ to avoid scanning
  # module bodies that legitimately discuss arbitrary counts.
  matches=$(grep -REn "$regex" README.md CLAUDE.md docs 2>/dev/null || true)
  if [ -z "$matches" ]; then
    ok "no '$label' phrasing present (nothing to drift)"
    return
  fi
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    # Extract the first integer that the phrasing wraps.
    n=$(printf '%s' "$line" | grep -oE "$regex" | grep -oE '[0-9]+' | head -1)
    if [ -n "$n" ] && [ "$n" != "$MODULE_COUNT" ]; then
      fail "stale '$label' count ($n, expected $MODULE_COUNT): $line"
      found_wrong=1
    fi
  done <<EOF
$matches
EOF
  if [ "$found_wrong" -eq 0 ]; then
    ok "all '$label' phrasings use $MODULE_COUNT"
  fi
}

check_no_wrong_count_phrasing "N configuration modules" \
  '[0-9]+ configuration modules'
check_no_wrong_count_phrasing "collection of N ... modules" \
  'collection of [0-9]+ [a-zA-Z]+ modules'

# --- (b) full preset count claim in docs -----------------------------------
check_count_claim "README.md"               "**full** | __N__ modules"           "$FULL_PRESET_COUNT"
check_count_claim "docs/getting-started.md" "**full** | __N__ modules"           "$FULL_PRESET_COUNT"

# --- Build the set of modules referenced by any preset ----------------------
PRESET_MEMBERS=$(cat presets/*.json | jq -r '.[]' | sort -u)

# All real module names
ALL_MODULES=$(find modules -mindepth 2 -maxdepth 2 -name module.json \
  | sed 's#^modules/##; s#/module.json$##' | sort)

# --- (d) preset references a non-existent module ----------------------------
ORPHANS=$(comm -13 <(printf '%s\n' "$ALL_MODULES") <(printf '%s\n' "$PRESET_MEMBERS") || true)
if [ -n "$ORPHANS" ]; then
  fail "preset(s) reference modules that do not exist:
$ORPHANS"
else
  ok "every preset member is a real module"
fi

# --- Load allowlist (bare module names; strip comments/blanks) --------------
ALLOWLIST_FILE="tests/preset-coverage-allowlist.txt"
ALLOWLIST=""
if [ -f "$ALLOWLIST_FILE" ]; then
  ALLOWLIST=$(grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST_FILE" \
    | sed 's/[[:space:]]*$//' | sort -u || true)
fi

# --- (c) stable, non-allowlisted modules in zero presets --------------------
ZERO_PRESET=$(comm -23 <(printf '%s\n' "$ALL_MODULES") <(printf '%s\n' "$PRESET_MEMBERS") || true)

UNCOVERED=""
while IFS= read -r mod; do
  [ -n "$mod" ] || continue
  # beta and deprecated modules are auto-excluded
  status=$(jq -r '.status // "stable"' "modules/$mod/module.json")
  if [ "$status" = "beta" ] || [ "$status" = "deprecated" ]; then
    ok "$mod in zero presets but status=$status (auto-excluded)"
    continue
  fi
  # allowlisted?
  if printf '%s\n' "$ALLOWLIST" | grep -qx "$mod"; then
    ok "$mod in zero presets but allowlisted"
    continue
  fi
  UNCOVERED="$UNCOVERED $mod"
done <<EOF
$ZERO_PRESET
EOF

if [ -n "$(printf '%s' "$UNCOVERED" | tr -d ' ')" ]; then
  fail "stable module(s) in zero presets and not allowlisted:$UNCOVERED
  -> add each to a preset in presets/*.json, OR add to $ALLOWLIST_FILE with a reason."
else
  ok "every stable module is in a preset or beta/allowlisted"
fi

# --- (e) stale allowlist entries -------------------------------------------
# A module that is allowlisted but also appears in a preset, or no longer exists.
STALE=""
while IFS= read -r mod; do
  [ -n "$mod" ] || continue
  if [ ! -d "modules/$mod" ]; then
    STALE="$STALE $mod(missing-module)"
    continue
  fi
  if printf '%s\n' "$PRESET_MEMBERS" | grep -qx "$mod"; then
    STALE="$STALE $mod(now-in-preset)"
  fi
done <<EOF
$ALLOWLIST
EOF

if [ -n "$(printf '%s' "$STALE" | tr -d ' ')" ]; then
  fail "stale allowlist entries in $ALLOWLIST_FILE:$STALE
  -> remove these entries; they are covered or no longer exist."
else
  ok "no stale allowlist entries"
fi

# --- (f) README module catalog is alphabetical and complete -----------------
# The catalog is a lookup table, so its row order is load-bearing: a module
# appended at the bottom is a module nobody can find. Pull the rows bounded by
# the catalog header separator (the presets and memory tables also start rows
# with "| **", so an unbounded grep would sweep them in).

CATALOG_NAMES=$(awk '
  index($0, "|--------|----------|-------------|--------------|") == 1 { in_tbl = 1; next }
  in_tbl && index($0, "| **") == 1 {
    line = $0
    sub(/^\| \*\*/, "", line)
    sub(/\*\*.*$/, "", line)
    print line
    next
  }
  in_tbl { exit }
' README.md)

CATALOG_ROW_COUNT=$(printf '%s\n' "$CATALOG_NAMES" | grep -c . | tr -d ' ')

if [ "$CATALOG_ROW_COUNT" != "$MODULE_COUNT" ]; then
  fail "README module catalog has $CATALOG_ROW_COUNT rows, expected $MODULE_COUNT
  -> add or remove the catalog row so it matches modules/*/module.json."
else
  ok "README module catalog has one row per module ($MODULE_COUNT)"
fi

if [ "$CATALOG_NAMES" = "$(printf '%s\n' "$CATALOG_NAMES" | sort -f)" ]; then
  ok "README module catalog is sorted alphabetically"
else
  fail "README module catalog is not sorted alphabetically. First divergence:
$(diff <(printf '%s\n' "$CATALOG_NAMES") <(printf '%s\n' "$CATALOG_NAMES" | sort -f) | head -6)
  -> re-sort the catalog rows by module name."
fi

CATALOG_UNKNOWN=$(comm -13 <(printf '%s\n' "$ALL_MODULES") <(printf '%s\n' "$CATALOG_NAMES" | sort) || true)
CATALOG_MISSING=$(comm -23 <(printf '%s\n' "$ALL_MODULES") <(printf '%s\n' "$CATALOG_NAMES" | sort) || true)

if [ -n "$CATALOG_UNKNOWN" ] || [ -n "$CATALOG_MISSING" ]; then
  fail "README module catalog does not match modules/ on disk.
  listed but no such module:${CATALOG_UNKNOWN:- none}
  module exists but unlisted:${CATALOG_MISSING:- none}"
else
  ok "README module catalog lists exactly the modules on disk"
fi

# --- (g) command + hook count claims track the reference docs ---------------
# README advertises how many commands and hooks the reference docs cover. Derive
# both from the docs themselves so the advertised number cannot go stale.

COMMANDS_DOC_COUNT=$(grep -cE '^### /' docs/commands.md 2>/dev/null | tr -d ' ' || true)
HOOKS_DOC_COUNT=$(grep -cE '^### .*\.py$' docs/hooks.md 2>/dev/null | tr -d ' ' || true)
echo "Derived commands-doc count: $COMMANDS_DOC_COUNT"
echo "Derived hooks-doc count: $HOOKS_DOC_COUNT"

check_count_claim "README.md" "All __N__ slash commands" "$COMMANDS_DOC_COUNT"
check_count_claim "README.md" "All __N__ hooks explained" "$HOOKS_DOC_COUNT"

# --- Result -----------------------------------------------------------------
echo ""
if [ "$FAILURES" -gt 0 ]; then
  echo "test-doc-counts.sh: $FAILURES check(s) failed"
  exit 1
fi
echo "test-doc-counts.sh: all checks passed"
