#!/usr/bin/env bash
# CCGM - Template expansion
# Replaces __PLACEHOLDER__ variables with values from .ccgm.env

# --- Load environment values ---
# Usage: load_env "/path/to/.ccgm.env"
# Sets global variables for template expansion
load_env() {
  local env_file="$1"
  if [ ! -f "$env_file" ]; then
    echo "WARNING: env file not found: $env_file" >&2
    return 1
  fi

  # Source the env file (it uses KEY=value format)
  # shellcheck disable=SC1090
  source "$env_file"
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
  local home_val username_val code_dir_val log_repo_val timezone_val default_mode_val

  if [ -f "$env_file" ]; then
    home_val=$(grep '^CCGM_HOME=' "$env_file" | cut -d= -f2-)
    username_val=$(grep '^CCGM_USERNAME=' "$env_file" | cut -d= -f2-)
    code_dir_val=$(grep '^CCGM_CODE_DIR=' "$env_file" | cut -d= -f2-)
    log_repo_val=$(grep '^CCGM_LOG_REPO=' "$env_file" | cut -d= -f2-)
    timezone_val=$(grep '^CCGM_TIMEZONE=' "$env_file" | cut -d= -f2-)
    default_mode_val=$(grep '^CCGM_DEFAULT_MODE=' "$env_file" | cut -d= -f2-)
  fi

  # Use sensible defaults for unset values
  home_val="${home_val:-$HOME}"
  code_dir_val="${code_dir_val:-$HOME/code}"
  default_mode_val="${default_mode_val:-ask}"

  # Perform replacements using sed
  # Use a different delimiter (|) in case paths contain /
  local sed_cmd="sed"
  # macOS sed requires -i '' while GNU sed uses -i
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed_cmd="sed -i ''"
  else
    sed_cmd="sed -i"
  fi

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

  # Apply sed in-place
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "$sed_expr" "$file"
  else
    sed -i "$sed_expr" "$file"
  fi
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
