#!/usr/bin/env bash
# CCGM - Template expansion
# Replaces __PLACEHOLDER__ variables with values from .ccgm.env

# --- Portable in-place sed ---
# Usage: sed_inplace 'sed-script' file [file2 ...]
# macOS (BSD) sed requires -i '' (empty string as its own argument for the
# backup suffix); GNU sed (Linux) takes -i with no separate argument and
# would otherwise misparse a bare '' as the script and the real script as a
# filename. Centralized here so every caller picks the right form once,
# instead of re-deriving this detection at each call site.
# The -- before the script guards against a script or filename that starts
# with a dash: GNU sed permutes option scanning across the whole argument
# list by default, so a later "-name" argument gets misread as an unknown
# flag even though it is positional; BSD sed does not, but -- is a no-op
# for it. Exits non-zero (propagated to the caller) if sed itself fails.
sed_inplace() {
  local script="$1"
  shift
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' -- "$script" "$@"
  else
    sed -i -- "$script" "$@"
  fi
}

# --- Expand templates in a single file ---
# Usage: expand_templates "/path/to/file" "/path/to/.ccgm.env"
# Modifies the file in-place
expand_templates() {
  local file="$1"
  local env_file="$2"

  if [ ! -f "$file" ]; then
    echo "WARNING: Template file not found: $file" >&2
    return 1
  fi

  # Load env values
  local home_val="" username_val="" code_dir_val="" log_repo_val="" timezone_val="" default_mode_val=""

  # Per-module placeholders are data-driven: any CCGM_MODULE_* env entry whose
  # name ends in a __PLACEHOLDER__ token contributes one substitution. The env
  # name is CCGM_MODULE_<module>__<__PLACEHOLDER__> (see start.sh); the module
  # segment is irrelevant here, only the trailing __UPPER_SNAKE__ token matters.
  # Stored as parallel arrays (bash 3.2 has no associative arrays).
  local module_placeholders=()
  local module_values=()

  if [ -f "$env_file" ]; then
    # Read all values in a single pass instead of separate grep calls.
    local key value placeholder
    while IFS='=' read -r key value; do
      case "$key" in
        CCGM_HOME) home_val="$value" ;;
        CCGM_USERNAME) username_val="$value" ;;
        CCGM_CODE_DIR) code_dir_val="$value" ;;
        CCGM_LOG_REPO) log_repo_val="$value" ;;
        CCGM_TIMEZONE) timezone_val="$value" ;;
        CCGM_DEFAULT_MODE) default_mode_val="$value" ;;
        CCGM_MODULE_*)
          # Extract the trailing __UPPER_SNAKE__ token as the placeholder. The
          # body must start and end with an alphanumeric so the match does not
          # swallow the __ separator that joins <module> to <__PLACEHOLDER__>
          # (the key is CCGM_MODULE_<module>____PLACEHOLDER__ - four underscores).
          placeholder=$(printf '%s' "$key" | grep -oE '__[A-Z0-9]([A-Z0-9_]*[A-Z0-9])?__$' || true)
          if [ -n "$placeholder" ]; then
            module_placeholders+=("$placeholder")
            module_values+=("$value")
          fi
          ;;
      esac
    done < "$env_file"
  fi

  # Use sensible defaults for unset values
  home_val="${home_val:-$HOME}"
  code_dir_val="${code_dir_val:-$HOME/code}"
  default_mode_val="${default_mode_val:-ask}"

  # Escape sed-special characters in replacement values to prevent injection
  # Pipe (|) is our delimiter, ampersand (&) references the match, backslash (\) is escape
  _escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[|&\\]/\\&/g'
  }
  home_val="$(_escape_sed_replacement "$home_val")"
  username_val="$(_escape_sed_replacement "$username_val")"
  code_dir_val="$(_escape_sed_replacement "$code_dir_val")"
  log_repo_val="$(_escape_sed_replacement "$log_repo_val")"
  timezone_val="$(_escape_sed_replacement "$timezone_val")"
  default_mode_val="$(_escape_sed_replacement "$default_mode_val")"

  # Escape every per-module value the same way.
  local _i=0
  while [ $_i -lt ${#module_values[@]} ]; do
    module_values[$_i]="$(_escape_sed_replacement "${module_values[$_i]}")"
    _i=$((_i + 1))
  done

  # Perform replacements using sed
  # Use a different delimiter (|) in case paths contain /

  # Build sed expression
  local sed_expr=""
  sed_expr+="s|__HOME__|${home_val}|g;"
  if [ -n "$username_val" ]; then
    sed_expr+="s|__USERNAME__|${username_val}|g;"
  fi
  sed_expr+="s|__CODE_DIR__|${code_dir_val}|g;"
  if [ -n "$log_repo_val" ]; then
    sed_expr+="s|__LOG_REPO__|${log_repo_val}|g;"
  fi
  if [ -n "$timezone_val" ]; then
    sed_expr+="s|__TIMEZONE__|${timezone_val}|g;"
  fi
  sed_expr+="s|__DEFAULT_MODE__|${default_mode_val}|g;"

  # Append one substitution per declared per-module placeholder. The placeholder
  # token is fixed UPPER_SNAKE so it needs no escaping; only the value does
  # (already escaped above). Empty values are still substituted so the literal
  # __PLACEHOLDER__ never survives in an installed file.
  _i=0
  while [ $_i -lt ${#module_placeholders[@]} ]; do
    sed_expr+="s|${module_placeholders[$_i]}|${module_values[$_i]}|g;"
    _i=$((_i + 1))
  done

  # Apply sed in-place
  sed_inplace "$sed_expr" "$file"
}

# --- Check if a file has unexpanded templates ---
# Returns 0 if templates remain, 1 if clean
has_unexpanded_templates() {
  local file="$1"
  grep -qE '__[A-Z_]+__' "$file" 2>/dev/null
}

# --- List unexpanded templates in a file ---
list_unexpanded_templates() {
  local file="$1"
  grep -oE '__[A-Z_]+__' "$file" 2>/dev/null | sort -u
}

# --- Write .ccgm.env file ---
# Usage: write_env_file "/path/to/.ccgm.env" key1=val1 key2=val2 ...
write_env_file() {
  local env_file="$1"
  shift

  {
    echo "# CCGM configuration - generated $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# This file contains personal config. Do not commit to version control."
    echo ""
    for kv in "$@"; do
      echo "$kv"
    done
  } > "$env_file"
}
