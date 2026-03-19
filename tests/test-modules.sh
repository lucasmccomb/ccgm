#!/usr/bin/env bash
set -euo pipefail

# CCGM Module Validation Tests
# Validates all modules have correct structure and metadata

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
ERRORS=()

# --- Helpers ---
pass() {
  PASS=$((PASS + 1))
  echo "  PASS: $1"
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

# --- Test: All file paths in files map point to existing files ---
echo "--- Checking file references ---"
for mod_dir in "$REPO_ROOT"/modules/*/; do
  [ ! -d "$mod_dir" ] && continue
  mod_name=$(basename "$mod_dir")
  manifest="$mod_dir/module.json"
  [ ! -f "$manifest" ] && continue
  jq empty "$manifest" 2>/dev/null || continue

  while IFS= read -r src_path; do
    full_path="$mod_dir/$src_path"
    if [ -f "$full_path" ]; then
      pass "$mod_name: file exists '$src_path'"
    else
      fail "$mod_name: referenced file missing '$src_path' (expected at $full_path)"
    fi
  done < <(jq -r '.files | keys[]' "$manifest" 2>/dev/null)
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
