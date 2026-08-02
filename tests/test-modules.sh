#!/usr/bin/env bash
set -euo pipefail

# CCGM Module Validation Tests
# Validates all modules have correct structure and metadata

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()

# Per-assertion PASS lines run into the thousands and, under heavy stdout on
# the macOS CI runner, a signal can interrupt a write mid-flush and surface as
# "echo: write error: Interrupted system call" (EINTR), failing the run
# spuriously. By default we stay quiet on success and only print failures plus
# the final summary, which keeps total writes small. Set VERBOSE=1 for the old
# per-assertion PASS output (used for local debugging).
VERBOSE="${VERBOSE:-0}"

# --- Helpers ---
pass() {
  PASS=$((PASS + 1))
  [ "$VERBOSE" = "1" ] && echo "  PASS: $1"
  return 0
}

fail() {
  FAIL=$((FAIL + 1))
  ERRORS+=("$1")
  echo "  FAIL: $1"
}

# Valid categories and scopes
VALID_CATEGORIES="core workflow commands patterns tech-specific"
VALID_SCOPES="global project"

# --- Check jq is available ---
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required for module validation"
  echo "  Install: brew install jq (macOS) or apt install jq (Linux)"
  exit 1
fi

echo "=== CCGM Module Validation ==="
echo ""

# --- Test: Every modules/* directory has a module.json ---
echo "--- Checking module directories ---"
module_count=0
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  module_count=$((module_count + 1))

  if [ -f "$mod_dir/module.json" ]; then
    pass "$mod_name has module.json"
  else
    fail "$mod_name is missing module.json"
  fi
done
echo ""
echo "  Found $module_count modules"
echo ""

# --- Test: Each module.json is valid JSON ---
echo "--- Validating JSON syntax ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue

  if jq empty "$manifest" 2>/dev/null; then
    pass "$mod_name: valid JSON"
  else
    fail "$mod_name: invalid JSON in module.json"
  fi
done
echo ""

# --- Test: Required fields exist ---
echo "--- Checking required fields ---"
REQUIRED_FIELDS="name displayName description category scope files"

for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  # Skip invalid JSON
  jq empty "$manifest" 2>/dev/null || continue

  for field in $REQUIRED_FIELDS; do
    has_field=$(jq --arg f "$field" 'has($f)' "$manifest" 2>/dev/null)
    if [ "$has_field" = "true" ]; then
      pass "$mod_name: has '$field' field"
    else
      fail "$mod_name: missing required field '$field'"
    fi
  done
done
echo ""

# --- Test: name matches directory name ---
echo "--- Checking name/directory match ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  json_name=$(jq -r '.name' "$manifest" 2>/dev/null)
  if [ "$json_name" = "$mod_name" ]; then
    pass "$mod_name: name matches directory"
  else
    fail "$mod_name: name mismatch (json='$json_name', dir='$mod_name')"
  fi
done
echo ""

# --- Test: category is valid ---
echo "--- Checking categories ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  category=$(jq -r '.category // ""' "$manifest" 2>/dev/null)
  valid=false
  for vc in $VALID_CATEGORIES; do
    if [ "$category" = "$vc" ]; then
      valid=true
      break
    fi
  done

  if [ "$valid" = true ]; then
    pass "$mod_name: valid category '$category'"
  else
    fail "$mod_name: invalid category '$category' (expected one of: $VALID_CATEGORIES)"
  fi
done
echo ""

# --- Test: scope is valid array of global/project ---
echo "--- Checking scopes ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  # scope must be an array
  scope_type=$(jq -r '.scope | type' "$manifest" 2>/dev/null)
  if [ "$scope_type" != "array" ]; then
    fail "$mod_name: scope must be an array, got '$scope_type'"
    continue
  fi

  scope_len=$(jq -r '.scope | length' "$manifest" 2>/dev/null)
  if [ "$scope_len" -eq 0 ]; then
    fail "$mod_name: scope array is empty"
    continue
  fi

  scope_valid=true
  while IFS= read -r s; do
    found=false
    for vs in $VALID_SCOPES; do
      if [ "$s" = "$vs" ]; then
        found=true
        break
      fi
    done
    if [ "$found" = false ]; then
      fail "$mod_name: invalid scope value '$s' (expected one of: $VALID_SCOPES)"
      scope_valid=false
    fi
  done < <(jq -r '.scope[]' "$manifest" 2>/dev/null)

  if [ "$scope_valid" = true ]; then
    pass "$mod_name: valid scope"
  fi
done
echo ""

# --- Test: manifest-existence gate - every files map entry resolves on disk ---
# For every module.json files[] key, assert the source path exists. Uses
# [ -e ], not [ -f ], so a symlink to a file or a directory both count as
# present - only a missing path (including a broken symlink) fails. This
# guards the declared -> disk direction (a stale or mistyped manifest entry
# pointing at a deleted/renamed file). It is the companion, not the fix, for
# #930's actual bug class - three code-quality rules shipped on disk with no
# files[] entry at all - which the disk -> declared "manifest completeness"
# check below catches, but only for lib/*.sh and commands/*.md today.
echo "--- Checking manifest-existence gate (files map -> source exists) ---"
declared_entries=0
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  while IFS= read -r src_path; do
    [ -z "$src_path" ] && continue
    declared_entries=$((declared_entries + 1))
    full_path="$mod_dir/$src_path"
    if [ -e "$full_path" ]; then
      pass "$mod_name: file exists '$src_path'"
    else
      fail "$mod_name: referenced file missing '$src_path' (expected at $full_path)"
    fi
  done < <(jq -r '.files | keys[]' "$manifest" 2>/dev/null)
done
echo ""
echo "  Checked $declared_entries declared files[] entries across $module_count modules"
echo ""

# --- Test: Manifest completeness - every shipped lib/command/rule is installed ---
# Reverse of the check above: ensure no lib/*.sh, commands/*.md, or rules/*.md
# sits on disk without a files[] entry, or it silently never installs. This is
# the direction that actually catches #930's bug class (a shipped file with no
# manifest entry at all) - the forward check above only catches the opposite
# (a manifest entry pointing at a file that isn't there).
#
# Two different kinds of file types are NOT scanned here, and they are not
# the same kind of "not scanned":
#   - Genuinely never installed: README.md, terraform/, packer/, tests/.
#     These have no files[] entry by design; a scan would just be noise.
#   - Installed, but not yet covered by this gate: hooks/*.py, skills/*,
#     agents/*, bin/*. Install location is driven purely by a files[]
#     entry's `target` (type is advisory metadata only - see
#     lib/modules.sh:189-190), so an undeclared hook or skill file fails to
#     install exactly as silently as an undeclared rule did before this PR.
#     Extending the scan to those subdirs is deliberately out of scope here;
#     rules were the demonstrated gap for #930.
echo "--- Checking manifest completeness (lib + commands + rules coverage) ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  # Collect declared source paths into a newline-delimited string.
  declared=$(jq -r '.files | keys[]' "$manifest" 2>/dev/null)

  shipped_count=0
  missing_count=0
  for subdir in lib commands rules; do
    [ -d "$mod_dir/$subdir" ] || continue
    # Match shell scripts in lib/, markdown in commands/ and rules/.
    if [ "$subdir" = "lib" ]; then
      pattern="*.sh"
    else
      pattern="*.md"
    fi
    while IFS= read -r abs_path; do
      [ -z "$abs_path" ] && continue
      rel_path="${abs_path#"$mod_dir"}"
      rel_path="${rel_path#/}"
      shipped_count=$((shipped_count + 1))
      if printf '%s\n' "$declared" | grep -qxF "$rel_path"; then
        :
      else
        fail "$mod_name: shipped '$rel_path' is not in module.json files[] (will never install)"
        missing_count=$((missing_count + 1))
      fi
    done < <(find "$mod_dir/$subdir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null)
  done

  if [ "$shipped_count" -gt 0 ] && [ "$missing_count" -eq 0 ]; then
    pass "$mod_name: all $shipped_count shipped lib/command/rule file(s) declared in manifest"
  fi
done
echo ""

# --- Test: Dependencies reference real modules ---
echo "--- Checking dependencies ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  dep_count=$(jq -r '.dependencies | length' "$manifest" 2>/dev/null)
  if [ "$dep_count" -eq 0 ]; then
    pass "$mod_name: no dependencies (ok)"
    continue
  fi

  while IFS= read -r dep; do
    if [ -d "$REPO_ROOT/modules/$dep" ] && [ -f "$REPO_ROOT/modules/$dep/module.json" ]; then
      pass "$mod_name: dependency '$dep' exists"
    else
      fail "$mod_name: dependency '$dep' does not exist"
    fi
  done < <(jq -r '.dependencies[]' "$manifest" 2>/dev/null)
done
echo ""

# --- Test: Presets reference real modules ---
echo "--- Checking presets ---"
for preset_file in "$REPO_ROOT"/presets/*.json; do
  [ ! -f "$preset_file" ] && continue
  preset_name=$(basename "$preset_file" .json)

  if ! jq empty "$preset_file" 2>/dev/null; then
    fail "preset '$preset_name': invalid JSON"
    continue
  fi

  pass "preset '$preset_name': valid JSON"

  while IFS= read -r mod; do
    if [ -d "$REPO_ROOT/modules/$mod" ]; then
      pass "preset '$preset_name': module '$mod' exists"
    else
      fail "preset '$preset_name': references non-existent module '$mod'"
    fi
  done < <(jq -r '.[]' "$preset_file" 2>/dev/null)
done
echo ""

# --- Summary ---
echo "==================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==================================="

if [ $FAIL -gt 0 ]; then
  echo ""
  echo "Failures:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  exit 1
fi

exit 0
