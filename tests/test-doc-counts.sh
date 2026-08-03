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

# TRACKED docs only, and that word is load-bearing (issue #922). Recursing the
# filesystem also reaches gitignored paths — notably docs/audits/, which holds
# historical audit reports that correctly quote the module count that was true
# on their audit date. Those are a record, not drift: the count in them is
# supposed to stay put, so a filesystem walk fires on them after every module
# addition, forever. Worse, being gitignored makes the result machine-dependent
# — green in CI and on a fresh clone, red only for whoever holds the report
# locally. A guard that disagrees with itself by machine is not a guard.
# tests/test-no-personal-data.sh excludes docs/audits for the same reason.
#
# git ls-files gives exactly the tracked set, so this needs no hardcoded
# directory name and covers any future gitignored doc path for free.
scanned_docs() {
  # Test seam: --self-test points this at fixtures instead of the real repo.
  if [ -n "${CCGM_DOC_SCAN_LIST:-}" ]; then
    printf '%s\n' "$CCGM_DOC_SCAN_LIST"
    return
  fi
  if git rev-parse --git-dir >/dev/null 2>&1; then
    git ls-files -- README.md CLAUDE.md docs | grep -E '\.md$' || true
    return
  fi
  # No git (tarball export): walk the same paths and drop gitignored-by-
  # convention dirs explicitly, so the check still runs and still skips audits.
  find README.md CLAUDE.md docs -name '*.md' -type f 2>/dev/null \
    | grep -v '/audits/' || true
}

check_no_wrong_count_phrasing() {
  local label="$1"
  shift
  local regex="$1"
  local found_wrong=0
  local matches files
  # -n for line numbers, -E for extended regex, over the tracked doc list.
  # Limited to Markdown at the repo root and under docs/ so module bodies that
  # legitimately discuss arbitrary counts are never scanned.
  files=$(scanned_docs)
  if [ -z "$files" ]; then
    ok "no tracked docs to scan for '$label'"
    return
  fi
  # $files is intentionally unquoted (word-split into arguments). /dev/null is
  # appended so grep always has >=2 file operands: that forces the file: prefix
  # the parser below needs, and stops grep reading stdin if the list is short.
  matches=$(grep -En "$regex" $files /dev/null 2>/dev/null || true)
  if [ -z "$matches" ]; then
    ok "no '$label' phrasing present (nothing to drift)"
    return
  fi
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    # Extract the first integer that the phrasing wraps.
    #
    # No pipe into `head -1`: under `set -o pipefail`, a downstream consumer
    # that exits after its first line (`head -1`) can SIGPIPE-kill an
    # upstream `grep` mid-write if more than one match/digit-run exists,
    # turning a successful extraction into a pipeline failure. This
    # assignment has no `|| true` guard, so under `set -e` that failure
    # would abort the entire test run silently partway through (see #943,
    # #945). Use herestrings for both greps -- neither is early-exiting
    # (`-oE` alone drains to EOF), so there is no live pipe left to race --
    # then take the first line with bash parameter expansion instead of a
    # piped `head -1`. (Named line_match/line_digits, not "matches", so this
    # per-line extraction never shadows the outer $matches the loop reads
    # its input from.)
    line_match=$(grep -oE "$regex" <<< "$line" || true)
    line_digits=$(grep -oE '[0-9]+' <<< "$line_match" || true)
    n="${line_digits%%$'\n'*}"
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

# --- (a2) self-test ---------------------------------------------------------
# Pins BOTH directions of the #922 fix: a gitignored audit report must not be
# scanned, AND the guard must still catch real drift in a doc that IS scanned.
# The second half matters most — an exclusion that quietly disables the check
# would otherwise look identical to a working one.
if [ "${1:-}" = "--self-test" ]; then
  echo "=== test-doc-counts self-test ==="
  ST_DIR="$(mktemp -d -t doccounts.XXXXXX)"
  trap 'rm -rf "$ST_DIR"' EXIT
  WRONG=$((MODULE_COUNT + 11))
  printf 'This repo is a collection of %s configuration modules.\n' "$WRONG" > "$ST_DIR/stale.md"
  printf 'This repo is a collection of %s configuration modules.\n' "$MODULE_COUNT" > "$ST_DIR/current.md"

  # 1. A scanned doc carrying a wrong count MUST fail.
  FAILURES=0
  CCGM_DOC_SCAN_LIST="$ST_DIR/stale.md" \
    check_no_wrong_count_phrasing "selftest stale" '[0-9]+ configuration modules' 2>/dev/null
  if [ "$FAILURES" -gt 0 ]; then
    echo "ok: self-test — stale count in a scanned doc still fails the guard"
  else
    echo "FAIL: self-test — guard did NOT catch a stale count; the check is inert" >&2
    exit 1
  fi

  # 2. A scanned doc carrying the right count must pass.
  FAILURES=0
  CCGM_DOC_SCAN_LIST="$ST_DIR/current.md" \
    check_no_wrong_count_phrasing "selftest current" '[0-9]+ configuration modules'
  if [ "$FAILURES" -ne 0 ]; then
    echo "FAIL: self-test — correct count reported as drift" >&2
    exit 1
  fi
  echo "ok: self-test — correct count passes"

  # 3. The real scan list includes tracked docs and excludes gitignored ones.
  #    docs/audits/ is gitignored, so a file dropped there must not be scanned.
  mkdir -p docs/audits
  ST_AUDIT="docs/audits/.doc-count-selftest-$$.md"
  printf 'Historical: a collection of %s configuration modules.\n' "$WRONG" > "$ST_AUDIT"
  trap 'rm -rf "$ST_DIR"; rm -f "$ST_AUDIT"' EXIT
  if [ -n "$(git check-ignore "$ST_AUDIT" 2>/dev/null)" ]; then
    LIST="$(scanned_docs)"
    case "$LIST" in
      *"$ST_AUDIT"*)
        echo "FAIL: self-test — gitignored $ST_AUDIT appeared in the scan list" >&2
        exit 1 ;;
    esac
    echo "ok: self-test — gitignored docs/audits file is not scanned"
    FAILURES=0
    check_no_wrong_count_phrasing "selftest audit-excluded" '[0-9]+ configuration modules' >/dev/null
    if [ "$FAILURES" -ne 0 ]; then
      echo "FAIL: self-test — a gitignored audit report still failed the guard" >&2
      exit 1
    fi
    echo "ok: self-test — a stale count inside docs/audits does not fail the run"
    case "$LIST" in
      *README.md*) echo "ok: self-test — tracked README.md is in the scan list" ;;
      *) echo "FAIL: self-test — tracked README.md missing from the scan list" >&2; exit 1 ;;
    esac
  else
    echo "ok: self-test — docs/audits not gitignored here; scan-list checks skipped"
  fi

  echo "test-doc-counts.sh --self-test: all checks passed"
  exit 0
fi

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
  # Herestring, not a pipe: `producer | grep -qx` can SIGPIPE-kill the
  # producer if grep exits on its first match before the producer finishes
  # writing, turning a successful match into a reported failure (see #943,
  # #945). A herestring has no second process to race against.
  if grep -qx "$mod" <<< "$ALLOWLIST"; then
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
  # Herestring, not a pipe: see the identical rationale on the allowlist
  # check above (#943, #945).
  if grep -qx "$mod" <<< "$PRESET_MEMBERS"; then
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
  index($0, "|--------|----------|----------|-------------|--------------|") == 1 { in_tbl = 1; next }
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

# --- (f2) README catalog Commands column matches module.json ----------------
# The Commands column is pure fact, derived from each module.json files[] block.
# A module that gains a command without surfacing it in the catalog fails here,
# so the column cannot silently fall behind the modules it describes.

CATALOG_CMD_DIFF=$(python3 - <<'PYEOF'
import json, pathlib, re, sys

def declared(mod):
    d = json.load(open(f"modules/{mod}/module.json"))
    out = set()
    for f in d.get("files", {}):
        if f.startswith("commands/") and f.endswith(".md"):
            out.add(pathlib.Path(f).stem)
        elif f.startswith("skills/") and f.endswith("SKILL.md"):
            out.add(pathlib.Path(f).parts[1])
    return sorted(out)

lines = pathlib.Path("README.md").read_text().split("\n")
SEP = "|--------|----------|----------|-------------|--------------|"
try:
    s = lines.index(SEP)
except ValueError:
    print("catalog separator not found; the column layout changed")
    sys.exit(0)

e = s + 1
problems = []
while e < len(lines) and lines[e].startswith("| **"):
    cells = [c.strip() for c in lines[e].strip().strip("|").split(" | ")]
    name = re.match(r"\*\*([^*]+)\*\*", cells[0]).group(1)
    want = ", ".join("`/" + c + "`" for c in declared(name)) or "-"
    if len(cells) != 5:
        problems.append(f"{name}: row has {len(cells)} cells, expected 5")
    elif cells[2] != want:
        problems.append(f"{name}: column says [{cells[2]}], module.json declares [{want}]")
    e += 1

for p in problems:
    print(p)
PYEOF
)

if [ -n "$CATALOG_CMD_DIFF" ]; then
  fail "README catalog Commands column disagrees with module.json:
$CATALOG_CMD_DIFF
  -> update the Commands cell so it lists every command and skill the module installs."
else
  ok "README catalog Commands column matches every module.json"
fi

# --- (f3) README catalog Dependencies column matches module.json ------------
# Same shape as (f2): the Dependencies column is pure fact, derived from each
# module.json's own dependencies[] array. A module whose deps change without
# the catalog row following fails here.

CATALOG_DEP_DIFF=$(python3 - <<'PYEOF'
import json, pathlib, re, sys

def declared(mod):
    d = json.load(open(f"modules/{mod}/module.json"))
    return list(d.get("dependencies", []))

lines = pathlib.Path("README.md").read_text().split("\n")
SEP = "|--------|----------|----------|-------------|--------------|"
try:
    s = lines.index(SEP)
except ValueError:
    print("catalog separator not found; the column layout changed")
    sys.exit(0)

e = s + 1
problems = []
while e < len(lines) and lines[e].startswith("| **"):
    cells = [c.strip() for c in lines[e].strip().strip("|").split(" | ")]
    name = re.match(r"\*\*([^*]+)\*\*", cells[0]).group(1)
    want = ", ".join(declared(name)) or "-"
    if len(cells) != 5:
        # Already reported by the (f2) cell-count check above; skip here.
        pass
    elif cells[4] != want:
        problems.append(f"{name}: column says [{cells[4]}], module.json declares [{want}]")
    e += 1

for p in problems:
    print(p)
PYEOF
)

if [ -n "$CATALOG_DEP_DIFF" ]; then
  fail "README catalog Dependencies column disagrees with module.json:
$CATALOG_DEP_DIFF
  -> update the Dependencies cell so it lists every entry in the module's dependencies[] array."
else
  ok "README catalog Dependencies column matches every module.json"
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
