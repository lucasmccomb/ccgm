#!/usr/bin/env bash
# CCGM - Module discovery, validation, and dependency resolution

# Requires: CCGM_ROOT to be set (repo root directory)

# --- Discover all modules ---
# Prints one module name per line
discover_modules() {
  local modules_dir="${CCGM_ROOT}/modules"
  local mod
  for mod in "$modules_dir"/*/; do
    if [ -f "$mod/module.json" ]; then
      basename "$mod"
    fi
  done | sort
}

# --- Read module.json field via jq ---
# Usage: _module_field "module-name" ".fieldPath"
_module_field() {
  local name="$1"
  local field="$2"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if [ ! -f "$manifest" ]; then
    return 1
  fi

  if command -v jq &>/dev/null; then
    jq -r "$field // empty" "$manifest" 2>/dev/null
  else
    # Minimal JSON parsing fallback for simple fields
    _json_field_fallback "$manifest" "$field"
  fi
}

# --- Minimal JSON field extraction without jq ---
# Handles simple top-level string fields and arrays
_json_field_fallback() {
  local file="$1"
  local field="$2"

  # Strip jq-style dot prefix
  field="${field#.}"

  case "$field" in
    name|displayName|description|category)
      grep -o "\"$field\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" | \
        sed "s/\"$field\"[[:space:]]*:[[:space:]]*\"//" | sed 's/"$//'
      ;;
    "dependencies[]"|"scope[]"|"tags[]")
      local arr_name="${field%\[\]}"
      # Extract array content between [ and ]
      local in_array=0
      local content=""
      while IFS= read -r line; do
        if [[ "$line" =~ \"$arr_name\"[[:space:]]*:[[:space:]]*\[ ]]; then
          in_array=1
          content="${line#*[}"
        elif [ $in_array -eq 1 ]; then
          content+="$line"
        fi
        if [ $in_array -eq 1 ] && [[ "$line" =~ \] ]]; then
          break
        fi
      done < "$file"
      # Extract quoted strings from content
      echo "$content" | grep -o '"[^"]*"' | tr -d '"'
      ;;
  esac
}

# --- Get module info (human-readable) ---
# Usage: get_module_info "module-name"
get_module_info() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if [ ! -f "$manifest" ]; then
    echo "Module not found: $name"
    return 1
  fi

  local display_name desc category

  if command -v jq &>/dev/null; then
    display_name=$(jq -r '.displayName' "$manifest")
    desc=$(jq -r '.description' "$manifest")
    category=$(jq -r '.category' "$manifest")
    local deps
    deps=$(jq -r '.dependencies | if length > 0 then join(", ") else "none" end' "$manifest")
    local scope
    scope=$(jq -r '.scope | join(", ")' "$manifest")
    local file_count
    file_count=$(jq -r '.files | length' "$manifest")

    echo "$display_name ($name)"
    echo "  Category: $category"
    echo "  Scope: $scope"
    echo "  Dependencies: $deps"
    echo "  Files: $file_count"
    echo "  $desc"
  else
    display_name=$(_module_field "$name" ".displayName")
    desc=$(_module_field "$name" ".description")
    echo "${display_name:-$name}"
    echo "  $desc"
  fi
}

# --- Get module display name ---
get_module_display_name() {
  local name="$1"
  _module_field "$name" ".displayName"
}

# --- Get module description ---
get_module_description() {
  local name="$1"
  _module_field "$name" ".description"
}

# --- Get module dependencies ---
# Returns one dependency per line
get_module_dependencies() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if command -v jq &>/dev/null; then
    jq -r '.dependencies[]?' "$manifest" 2>/dev/null
  else
    _module_field "$name" ".dependencies[]"
  fi
}

# --- Get module scope ---
# Returns "global", "project", or both (one per line)
get_module_scope() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if command -v jq &>/dev/null; then
    jq -r '.scope[]?' "$manifest" 2>/dev/null
  else
    _module_field "$name" ".scope[]"
  fi
}

# --- Get module files ---
# Returns JSON object of files (requires jq)
# Each line: source_path|target|type|template|merge
get_module_files() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if command -v jq &>/dev/null; then
    jq -r '.files | to_entries[] | "\(.key)|\(.value.target)|\(.value.type)|\(.value.template // false)|\(.value.merge // false)"' "$manifest" 2>/dev/null
  else
    echo "ERROR: jq required for file listing" >&2
    return 1
  fi
}

# --- Get config prompts ---
# Returns JSON array of config prompts (requires jq)
# Each line: key|prompt|default|options
get_module_config_prompts() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"

  if command -v jq &>/dev/null; then
    jq -r '.configPrompts[]? | "\(.key)|\(.prompt)|\(.default // "")|\(.options // [] | join(","))"' "$manifest" 2>/dev/null
  else
    echo "ERROR: jq required for config prompts" >&2
    return 1
  fi
}

# --- Validate module ---
# Returns 0 if valid, 1 if invalid
validate_module() {
  local name="$1"
  local manifest="${CCGM_ROOT}/modules/${name}/module.json"
  local errors=0

  if [ ! -d "${CCGM_ROOT}/modules/${name}" ]; then
    echo "Module directory not found: modules/$name"
    return 1
  fi

  if [ ! -f "$manifest" ]; then
    echo "module.json not found for: $name"
    return 1
  fi

  # Validate JSON syntax
  if command -v jq &>/dev/null; then
    if ! jq empty "$manifest" 2>/dev/null; then
      echo "Invalid JSON in module.json for: $name"
      return 1
    fi

    # Check required fields
    local mod_name
    mod_name=$(jq -r '.name' "$manifest")
    if [ "$mod_name" != "$name" ]; then
      echo "Module name mismatch: directory=$name, manifest=$mod_name"
      errors=$((errors + 1))
    fi

    # Check files exist
    while IFS='|' read -r src target type template merge; do
      local full_src="${CCGM_ROOT}/modules/${name}/${src}"
      if [ ! -f "$full_src" ]; then
        echo "Missing file: modules/$name/$src"
        errors=$((errors + 1))
      fi
    done < <(get_module_files "$name")

    # Check dependencies exist
    while IFS= read -r dep; do
      if [ ! -d "${CCGM_ROOT}/modules/${dep}" ]; then
        echo "Missing dependency: $dep (required by $name)"
        errors=$((errors + 1))
      fi
    done < <(get_module_dependencies "$name")
  fi

  return $errors
}

# --- Resolve dependencies ---
# Takes a newline-separated list of module names on stdin or as args
# Outputs the full list including all transitive dependencies (topologically sorted)
resolve_dependencies() {
  local input_modules=()

  if [ $# -gt 0 ]; then
    input_modules=("$@")
  else
    while IFS= read -r mod; do
      [ -n "$mod" ] && input_modules+=("$mod")
    done
  fi

  # Build resolved list with dependency-first ordering
  local resolved=()
  local visited=()

  _resolve_visit() {
    local mod="$1"
    local v

    # Already resolved?
    # Use ${arr[@]+...} pattern for bash 3.x compatibility (empty array = unbound)
    for v in ${resolved[@]+"${resolved[@]}"}; do
      [ "$v" = "$mod" ] && return 0
    done

    # Cycle detection
    for v in ${visited[@]+"${visited[@]}"}; do
      if [ "$v" = "$mod" ]; then
        echo "WARNING: Circular dependency detected: $mod" >&2
        return 0
      fi
    done
    visited+=("$mod")

    # Validate module exists
    if [ ! -f "${CCGM_ROOT}/modules/${mod}/module.json" ]; then
      echo "WARNING: Module not found: $mod" >&2
      return 1
    fi

    # Resolve dependencies first
    while IFS= read -r dep; do
      [ -n "$dep" ] && _resolve_visit "$dep"
    done < <(get_module_dependencies "$mod")

    resolved+=("$mod")
  }

  for mod in ${input_modules[@]+"${input_modules[@]}"}; do
    _resolve_visit "$mod"
  done

  printf '%s\n' ${resolved[@]+"${resolved[@]}"}
}

# --- Load preset ---
# Usage: load_preset "standard" -> prints module names (one per line)
load_preset() {
  local preset_name="$1"
  local preset_file="${CCGM_ROOT}/presets/${preset_name}.json"

  if [ ! -f "$preset_file" ]; then
    echo "Preset not found: $preset_name" >&2
    return 1
  fi

  if command -v jq &>/dev/null; then
    jq -r '.[]' "$preset_file"
  else
    # Fallback: parse simple JSON array
    tr -d '[]" \n' < "$preset_file" | tr ',' '\n'
  fi
}

# --- List presets ---
list_presets() {
  local preset
  for preset in "${CCGM_ROOT}"/presets/*.json; do
    if [ -f "$preset" ]; then
      local name
      name=$(basename "$preset" .json)
      local count
      if command -v jq &>/dev/null; then
        count=$(jq -r 'length' "$preset")
      else
        count=$(tr -d '[]" \n' < "$preset" | tr ',' '\n' | wc -l | tr -d ' ')
      fi
      echo "$name ($count modules)"
    fi
  done
}
