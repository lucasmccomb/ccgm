#!/usr/bin/env bash
set -euo pipefail

# CCGM - Claude Code God Mode
# Usage: ./start.sh [--link] [--preset <name>] [--scope <global|project|both>]

# --- Determine script location ---
CCGM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
# shellcheck source=lib/ui.sh
source "${CCGM_ROOT}/lib/ui.sh"
# shellcheck source=lib/modules.sh
source "${CCGM_ROOT}/lib/modules.sh"
# shellcheck source=lib/template.sh
source "${CCGM_ROOT}/lib/template.sh"
# shellcheck source=lib/merge.sh
source "${CCGM_ROOT}/lib/merge.sh"
# shellcheck source=lib/backup.sh
source "${CCGM_ROOT}/lib/backup.sh"

# --- Write manifest helper ---
write_manifest() {
  local manifest_dir="$1"
  local manifest_file="${manifest_dir}/.ccgm-manifest.json"
  local timestamp
  timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

  if command -v jq &>/dev/null; then
    # Build proper JSON with jq
    local modules_json files_json backups_json
    modules_json=$(printf '%s\n' "${RESOLVED_MODULES[@]}" | jq -R . | jq -s .)
    if [ ${#INSTALLED_FILES[@]} -gt 0 ]; then
      files_json=$(printf '%s\n' "${INSTALLED_FILES[@]}" | jq -R . | jq -s .)
    else
      files_json="[]"
    fi
    if [ ${#BACKUP_DIRS[@]} -gt 0 ]; then
      backups_json=$(printf '%s\n' "${BACKUP_DIRS[@]}" | jq -R . | jq -s .)
    else
      backups_json="[]"
    fi

    jq -n \
      --arg version "1.0.0" \
      --arg timestamp "$timestamp" \
      --arg preset "${PRESET_NAME:-custom}" \
      --arg scope "$SCOPE" \
      --argjson link "$LINK_MODE" \
      --argjson modules "$modules_json" \
      --argjson files "$files_json" \
      --argjson backups "$backups_json" \
      --arg ccgm_root "$CCGM_ROOT" \
      '{
        version: $version,
        installedAt: $timestamp,
        preset: $preset,
        scope: $scope,
        linkMode: $link,
        ccgmRoot: $ccgm_root,
        modules: $modules,
        files: $files,
        backups: $backups
      }' > "$manifest_file"
  else
    # Simple JSON without jq
    {
      echo "{"
      echo "  \"version\": \"1.0.0\","
      echo "  \"installedAt\": \"$timestamp\","
      echo "  \"preset\": \"${PRESET_NAME:-custom}\","
      echo "  \"scope\": \"$SCOPE\","
      echo "  \"linkMode\": $LINK_MODE,"
      echo "  \"ccgmRoot\": \"$CCGM_ROOT\","
      echo "  \"modules\": ["
      local first=true
      local mod
      for mod in "${RESOLVED_MODULES[@]}"; do
        if [ "$first" = true ]; then first=false; else echo ","; fi
        echo -n "    \"$mod\""
      done
      echo ""
      echo "  ]"
      echo "}"
    } > "$manifest_file"
  fi

  ui_success "Wrote manifest: $manifest_file"
}

# --- Main ---
main() {
  # Parse arguments
  LINK_MODE=false
  PRESET_NAME=""
  SCOPE=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --link)
        LINK_MODE=true
        shift
        ;;
      --preset)
        PRESET_NAME="$2"
        shift 2
        ;;
      --scope)
        SCOPE="$2"
        shift 2
        ;;
      --help|-h)
        echo "CCGM - Claude Code God Mode"
        echo ""
        echo "Usage: ./start.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --link              Create symlinks instead of copies"
        echo "  --preset <name>     Use preset (minimal, standard, full, team)"
        echo "  --scope <scope>     Installation scope (global, project, both)"
        echo "  -h, --help          Show this help"
        echo ""
        echo "Examples:"
        echo "  ./start.sh                        Interactive installation"
        echo "  ./start.sh --preset standard       Quick install with standard preset"
        echo "  ./start.sh --link --preset full    Symlink full preset"
        exit 0
        ;;
      *)
        echo "Unknown option: $1"
        echo "Run ./start.sh --help for usage"
        exit 1
        ;;
    esac
  done

  # ===========================================================
  # Step 1: Welcome
  # ===========================================================
  ui_banner

  # ===========================================================
  # Step 2: Check prerequisites
  # ===========================================================
  ui_header "Checking Prerequisites"

  local os_type="unknown"
  case "$OSTYPE" in
    darwin*)  os_type="macOS" ;;
    linux*)   os_type="Linux" ;;
    msys*|cygwin*|win*) os_type="Windows" ;;
  esac

  local shell_type
  shell_type="$(basename "${SHELL:-/bin/bash}")"

  ui_info "OS: $os_type | Shell: $shell_type"
  echo ""

  # Detect package manager
  local pkg_manager=""
  local pkg_install=""
  if command -v brew &>/dev/null; then
    pkg_manager="brew"
    pkg_install="brew install"
  elif command -v apt-get &>/dev/null; then
    pkg_manager="apt"
    pkg_install="sudo apt-get install -y"
  elif command -v dnf &>/dev/null; then
    pkg_manager="dnf"
    pkg_install="sudo dnf install -y"
  elif command -v pacman &>/dev/null; then
    pkg_manager="pacman"
    pkg_install="sudo pacman -S --noconfirm"
  fi

  # Define prerequisites: name|required|check_cmd|pkg_name_brew|pkg_name_apt|description
  local -a missing_required=()
  local -a missing_optional=()
  local has_gum=false
  local has_jq=false

  # Check each prerequisite
  _check_prereq() {
    local name="$1"
    local required="$2"
    local description="$3"

    if command -v "$name" &>/dev/null; then
      ui_success "$name: installed"
      return 0
    else
      if [ "$required" = "true" ]; then
        ui_error "$name: missing (required) - $description"
        missing_required+=("$name")
      else
        ui_warn "$name: missing (optional) - $description"
        missing_optional+=("$name")
      fi
      return 1
    fi
  }

  # Required prerequisites
  _check_prereq "git" "true" "version control" || true
  _check_prereq "python3" "true" "needed for hooks module" || true
  _check_prereq "jq" "true" "needed for settings.json merging" || true
  if command -v jq &>/dev/null; then has_jq=true; fi

  # Optional but recommended
  _check_prereq "gh" "false" "GitHub CLI for issue/PR commands" || true
  _check_prereq "gum" "false" "enhanced terminal UI" || true
  if command -v gum &>/dev/null; then has_gum=true; fi

  echo ""

  # Handle missing required prerequisites
  if [ ${#missing_required[@]} -gt 0 ]; then
    ui_header "Missing Required Prerequisites"
    ui_warn "The following required tools are not installed:"
    for tool in "${missing_required[@]}"; do
      echo "  - $tool"
    done
    echo ""

    if [ -n "$pkg_manager" ]; then
      local install_cmd="$pkg_install ${missing_required[*]}"
      if ui_confirm "Install missing required tools with $pkg_manager? ($install_cmd)"; then
        ui_info "Installing: ${missing_required[*]}"
        if $pkg_install "${missing_required[@]}"; then
          ui_success "Required tools installed successfully"
          # Re-check jq
          command -v jq &>/dev/null && has_jq=true
        else
          ui_error "Installation failed. Please install manually and re-run ./start.sh"
          exit 1
        fi
      else
        ui_info "No problem. Install them when you're ready:"
        ui_info "  $pkg_install ${missing_required[*]}"
        ui_info ""
        ui_info "Then re-run ./start.sh"
        exit 1
      fi
    elif [ "$os_type" = "macOS" ]; then
      # macOS without Homebrew - offer to install it
      ui_info "No package manager found. On macOS, Homebrew is the standard way to install developer tools."
      echo ""
      if ui_confirm "Install Homebrew? (https://brew.sh)"; then
        ui_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for this session (Apple Silicon vs Intel)
        if [ -f /opt/homebrew/bin/brew ]; then
          eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -f /usr/local/bin/brew ]; then
          eval "$(/usr/local/bin/brew shellenv)"
        fi
        if command -v brew &>/dev/null; then
          ui_success "Homebrew installed"
          pkg_manager="brew"
          pkg_install="brew install"
          ui_info "Installing required tools: ${missing_required[*]}"
          if brew install "${missing_required[@]}"; then
            ui_success "Required tools installed successfully"
            command -v jq &>/dev/null && has_jq=true
          else
            ui_error "Installation failed. Please run 'brew install ${missing_required[*]}' manually and re-run ./start.sh"
            exit 1
          fi
        else
          ui_error "Homebrew installation didn't complete successfully."
          ui_info "Try installing manually: https://brew.sh"
          ui_info "Then re-run ./start.sh"
          exit 1
        fi
      else
        ui_info "No problem. You can install Homebrew later from https://brew.sh"
        ui_info "Then install the required tools:"
        ui_info "  brew install ${missing_required[*]}"
        ui_info ""
        ui_info "Re-run ./start.sh when ready."
        exit 1
      fi
    else
      # Linux without apt/dnf/pacman - genuinely unusual
      ui_error "No supported package manager found (brew, apt, dnf, pacman)."
      ui_info ""
      ui_info "Please install the following tools using your system's package manager:"
      for tool in "${missing_required[@]}"; do
        case "$tool" in
          git)     ui_info "  git     - https://git-scm.com/downloads" ;;
          python3) ui_info "  python3 - https://www.python.org/downloads/" ;;
          jq)      ui_info "  jq      - https://jqlang.github.io/jq/download/" ;;
        esac
      done
      ui_info ""
      ui_info "Re-run ./start.sh when ready."
      exit 1
    fi
  fi

  # Handle missing optional prerequisites
  if [ ${#missing_optional[@]} -gt 0 ] && [ -n "$pkg_manager" ]; then
    if ui_confirm "Install optional tools for a better experience? (${missing_optional[*]})"; then
      ui_info "Installing: ${missing_optional[*]}"
      if $pkg_install "${missing_optional[@]}"; then
        ui_success "Optional tools installed"
        command -v gum &>/dev/null && has_gum=true
      else
        ui_info "Optional install failed - continuing without them"
      fi
    else
      ui_info "Skipping optional tools - continuing with basic setup"
    fi
  fi

  echo ""
  ui_success "All prerequisites satisfied"

  # ===========================================================
  # Step 3: Collect user info
  # ===========================================================
  ui_header "Configuration"

  # Auto-detect defaults
  local default_code_dir="$HOME/code"
  local default_timezone=""
  if command -v timedatectl &>/dev/null; then
    default_timezone=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  elif [ -f /etc/timezone ]; then
    default_timezone=$(cat /etc/timezone 2>/dev/null || true)
  elif command -v readlink &>/dev/null && [ -L /etc/localtime ]; then
    default_timezone=$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)
  fi
  default_timezone="${default_timezone:-UTC}"

  # GitHub username
  local github_username="${CCGM_USERNAME:-}"
  if [ -z "$github_username" ] && command -v gh &>/dev/null; then
    github_username=$(gh api user --jq '.login' 2>/dev/null || true)
  fi
  github_username=$(ui_input "GitHub username" "$github_username")

  if [ -z "$github_username" ]; then
    ui_error "GitHub username is required"
    exit 1
  fi

  # Code workspace directory
  local code_dir
  code_dir=$(ui_input "Code workspace directory" "${CCGM_CODE_DIR:-$default_code_dir}")

  # Timezone
  local timezone
  timezone=$(ui_input "Timezone" "${CCGM_TIMEZONE:-$default_timezone}")

  # Default permission mode
  local default_mode
  default_mode=$(ui_choose "Default permission mode" "ask" "dontAsk")

  # ===========================================================
  # Step 4: Choose scope
  # ===========================================================
  ui_header "Installation Scope"

  if [ -z "$SCOPE" ]; then
    ui_info "Global: ~/.claude/ (applies to all projects)"
    ui_info "Project: .claude/ in current directory (project-specific)"
    ui_info "Both: Install to both locations"
    echo ""
    SCOPE=$(ui_choose "Where to install?" "global" "project" "both")
  fi

  local install_global=false
  local install_project=false

  case "$SCOPE" in
    global) install_global=true ;;
    project) install_project=true ;;
    both) install_global=true; install_project=true ;;
    *)
      ui_error "Invalid scope: $SCOPE"
      exit 1
      ;;
  esac

  local global_dir="$HOME/.claude"
  local project_dir
  project_dir="$(pwd)/.claude"

  # ===========================================================
  # Step 5: Choose modules
  # ===========================================================
  ui_header "Module Selection"

  SELECTED_MODULES=()

  if [ -n "$PRESET_NAME" ]; then
    # Preset mode (from CLI arg)
    ui_info "Using preset: $PRESET_NAME"
    while IFS= read -r mod; do
      [ -n "$mod" ] && SELECTED_MODULES+=("$mod")
    done < <(load_preset "$PRESET_NAME")
  else
    # Interactive selection
    local selection_mode
    selection_mode=$(ui_choose "Installation mode" "Choose a preset" "Custom module selection")

    if [ "$selection_mode" = "Choose a preset" ]; then
      ui_info "Available presets:"
      echo ""

      # Show preset details
      local pf pname pcount pmods
      for pf in "${CCGM_ROOT}"/presets/*.json; do
        pname=$(basename "$pf" .json)
        if [ "$has_jq" = true ]; then
          pcount=$(jq -r 'length' "$pf")
          pmods=$(jq -r 'join(", ")' "$pf")
        else
          pcount=$(tr -d '[]" \n' < "$pf" | tr ',' '\n' | wc -l | tr -d ' ')
          pmods=$(tr -d '[]"' < "$pf" | tr ',' ' ')
        fi
        ui_list_item "$pname" "($pcount modules) $pmods"
      done
      echo ""

      PRESET_NAME=$(ui_choose "Select preset" "minimal" "standard" "full" "team")
      while IFS= read -r mod; do
        [ -n "$mod" ] && SELECTED_MODULES+=("$mod")
      done < <(load_preset "$PRESET_NAME")
    else
      # Custom module selection
      local all_modules=()
      local module_labels=()
      local desc
      while IFS= read -r mod; do
        all_modules+=("$mod")
        desc=""
        if [ "$has_jq" = true ]; then
          desc=$(jq -r '.description' "${CCGM_ROOT}/modules/${mod}/module.json" 2>/dev/null | head -c 80)
        fi
        if [ -n "$desc" ]; then
          module_labels+=("$mod - $desc")
        else
          module_labels+=("$mod")
        fi
      done < <(discover_modules)

      local selected_labels
      selected_labels=$(ui_multichoose "Select modules to install" "${module_labels[@]}")
      local mod_name
      while IFS= read -r label; do
        mod_name=$(echo "$label" | cut -d' ' -f1)
        [ -n "$mod_name" ] && SELECTED_MODULES+=("$mod_name")
      done <<< "$selected_labels"
    fi
  fi

  if [ ${#SELECTED_MODULES[@]} -eq 0 ]; then
    ui_error "No modules selected. Exiting."
    exit 1
  fi

  # ===========================================================
  # Step 6: Resolve dependencies
  # ===========================================================
  ui_header "Dependency Resolution"

  RESOLVED_MODULES=()
  while IFS= read -r mod; do
    [ -n "$mod" ] && RESOLVED_MODULES+=("$mod")
  done < <(resolve_dependencies "${SELECTED_MODULES[@]}")

  # Show what was added
  local added_deps=()
  local found
  for mod in "${RESOLVED_MODULES[@]}"; do
    found=false
    for sel in "${SELECTED_MODULES[@]}"; do
      if [ "$mod" = "$sel" ]; then
        found=true
        break
      fi
    done
    if [ "$found" = false ]; then
      added_deps+=("$mod")
    fi
  done

  if [ ${#added_deps[@]} -gt 0 ]; then
    ui_info "Auto-added dependencies:"
    local dep_display
    for dep in "${added_deps[@]}"; do
      dep_display=$(get_module_display_name "$dep")
      echo "  + $dep ($dep_display)"
    done
  else
    ui_success "No additional dependencies needed"
  fi

  echo ""
  ui_info "Modules to install (${#RESOLVED_MODULES[@]}):"
  local disp
  for mod in "${RESOLVED_MODULES[@]}"; do
    disp=$(get_module_display_name "$mod")
    echo "  - $mod ($disp)"
  done

  # ===========================================================
  # Step 7: Collect module-specific config
  # ===========================================================
  # Store module configs as indexed array of "key=value" pairs
  # (bash 3.x compatible - no associative arrays)
  MODULE_CONFIG_KEYS=()
  MODULE_CONFIG_VALS=()

  _set_module_config() {
    MODULE_CONFIG_KEYS+=("$1")
    MODULE_CONFIG_VALS+=("$2")
  }

  _get_module_config() {
    local lookup="$1"
    local default="${2:-}"
    local i=0
    while [ $i -lt ${#MODULE_CONFIG_KEYS[@]} ]; do
      if [ "${MODULE_CONFIG_KEYS[$i]}" = "$lookup" ]; then
        echo "${MODULE_CONFIG_VALS[$i]}"
        return 0
      fi
      i=$((i + 1))
    done
    echo "$default"
  }

  for mod in "${RESOLVED_MODULES[@]}"; do
    if [ "$has_jq" = true ]; then
      local prompt_count
      prompt_count=$(jq -r '.configPrompts | length' "${CCGM_ROOT}/modules/${mod}/module.json" 2>/dev/null || echo "0")
      if [ "$prompt_count" -gt 0 ] 2>/dev/null; then
        local key prompt default options value
        while IFS='|' read -r key prompt default options; do
          [ -z "$key" ] && continue

          if [ -n "$options" ]; then
            local opt_arr
            IFS=',' read -ra opt_arr <<< "$options"
            value=$(ui_choose "$prompt" "${opt_arr[@]}")
          else
            case "$key" in
              __LOG_REPO__)
                default="${default:-${github_username}-agent-logs}"
                ;;
            esac
            value=$(ui_input "$prompt" "$default")
          fi

          _set_module_config "${mod}__${key}" "$value"
        done < <(get_module_config_prompts "$mod")
      fi
    fi
  done

  # ===========================================================
  # Step 8: Preview files
  # ===========================================================
  ui_header "Installation Preview"

  local install_plan=()

  for mod in "${RESOLVED_MODULES[@]}"; do
    if [ "$has_jq" != true ]; then
      ui_warn "Skipping file preview for $mod (requires jq)"
      continue
    fi

    local src target type template merge
    while IFS='|' read -r src target type template merge; do
      local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
      local scope_list
      scope_list=$(get_module_scope "$mod")

      local mod_scope
      while IFS= read -r mod_scope; do
        local target_dir=""
        case "$mod_scope" in
          global)
            [ "$install_global" = true ] && target_dir="$global_dir"
            ;;
          project)
            [ "$install_project" = true ] && target_dir="$project_dir"
            ;;
        esac

        [ -z "$target_dir" ] && continue

        local full_target="${target_dir}/${target}"
        local action="copy"
        [ "$LINK_MODE" = true ] && [ "$merge" != "true" ] && action="link"
        [ "$merge" = "true" ] && action="merge"

        install_plan+=("${action}|${full_src}|${full_target}|${template}|${mod}")

        if [ -f "$full_target" ]; then
          ui_warn "  overwrite: $full_target"
        else
          ui_preview_file "$full_target" "  create: ${target_dir##*/}/$target"
        fi
      done <<< "$scope_list"
    done < <(get_module_files "$mod")
  done

  echo ""
  if [ "$LINK_MODE" = true ]; then
    ui_info "Mode: symlink (files linked back to CCGM repo)"
  else
    ui_info "Mode: copy (standalone files)"
  fi

  # ===========================================================
  # Step 9: Confirm
  # ===========================================================
  echo ""
  if ! ui_confirm "Proceed with installation?"; then
    ui_warn "Installation cancelled."
    exit 0
  fi

  # ===========================================================
  # Step 10: Backup existing configs
  # ===========================================================
  ui_header "Backup"

  BACKUP_DIRS=()
  local backup_path
  if [ "$install_global" = true ] && [ -d "$global_dir" ]; then
    backup_path=$(create_backup "$global_dir")
    if [ -n "$backup_path" ]; then
      BACKUP_DIRS+=("$backup_path")
      ui_success "Global config backed up to: $backup_path"
    else
      ui_info "No existing global config to back up"
    fi
  fi

  if [ "$install_project" = true ] && [ -d "$project_dir" ]; then
    backup_path=$(create_backup "$project_dir")
    if [ -n "$backup_path" ]; then
      BACKUP_DIRS+=("$backup_path")
      ui_success "Project config backed up to: $backup_path"
    else
      ui_info "No existing project config to back up"
    fi
  fi

  # ===========================================================
  # Step 11: Install
  # ===========================================================
  ui_header "Installing"

  # Create target directories
  [ "$install_global" = true ] && mkdir -p "$global_dir"
  [ "$install_project" = true ] && mkdir -p "$project_dir"

  # Write .ccgm.env
  local env_file="${global_dir}/.ccgm.env"
  local log_repo
  log_repo=$(_get_module_config "session-logging____LOG_REPO__" "${github_username}-agent-logs")
  local env_entries=(
    "CCGM_HOME=${HOME}"
    "CCGM_USERNAME=${github_username}"
    "CCGM_CODE_DIR=${code_dir}"
    "CCGM_LOG_REPO=${log_repo}"
    "CCGM_TIMEZONE=${timezone}"
    "CCGM_DEFAULT_MODE=${default_mode}"
  )

  # Add module-specific configs
  local cfg_idx=0
  while [ $cfg_idx -lt ${#MODULE_CONFIG_KEYS[@]} ]; do
    local cfg_key="${MODULE_CONFIG_KEYS[$cfg_idx]}"
    case "$cfg_key" in
      *__LOG_REPO__*|*__defaultMode__*) cfg_idx=$((cfg_idx + 1)); continue ;;
    esac
    env_entries+=("CCGM_MODULE_${cfg_key}=${MODULE_CONFIG_VALS[$cfg_idx]}")
    cfg_idx=$((cfg_idx + 1))
  done

  if [ "$install_global" = true ]; then
    write_env_file "$env_file" "${env_entries[@]}"
    ui_success "Wrote $env_file"
  fi

  # Process install plan
  INSTALLED_FILES=()

  local entry action src target template mod_name
  for entry in ${install_plan[@]+"${install_plan[@]}"}; do
    IFS='|' read -r action src target template mod_name <<< "$entry"

    # Create target parent directory
    mkdir -p "$(dirname "$target")"

    case "$action" in
      merge)
        if [ "$has_jq" = true ]; then
          init_settings "$target"

          if [ "$template" = "true" ]; then
            local tmp_merge
            tmp_merge=$(mktemp)
            cp "$src" "$tmp_merge"
            expand_templates "$tmp_merge" "$env_file"
            merge_settings "$target" "$tmp_merge"
            rm -f "$tmp_merge"
          else
            merge_settings "$target" "$src"
          fi
          ui_success "Merged: $target"
        else
          ui_warn "Skipped merge (no jq): $target"
        fi
        ;;
      link)
        [ -e "$target" ] && rm -f "$target"

        if [ "$template" = "true" ]; then
          # Templates cannot be symlinked - must copy and expand
          cp "$src" "$target"
          expand_templates "$target" "$env_file"
          ui_success "Copied+expanded (template): $target"
        else
          ln -s "$src" "$target"
          ui_success "Linked: $target"
        fi
        ;;
      copy)
        cp "$src" "$target"
        if [ "$template" = "true" ]; then
          expand_templates "$target" "$env_file"
          ui_success "Copied+expanded: $target"
        else
          ui_success "Copied: $target"
        fi
        ;;
    esac

    INSTALLED_FILES+=("$target")
  done

  # ===========================================================
  # Step 12: Write manifest
  # ===========================================================
  ui_header "Manifest"

  [ "$install_global" = true ] && write_manifest "$global_dir"
  [ "$install_project" = true ] && write_manifest "$project_dir"

  # ===========================================================
  # Step 13: Verify installation
  # ===========================================================
  ui_header "Verification"

  local verify_errors=0

  local file
  for file in ${INSTALLED_FILES[@]+"${INSTALLED_FILES[@]}"}; do
    if [ ! -e "$file" ]; then
      ui_error "Missing: $file"
      verify_errors=$((verify_errors + 1))
    fi
  done

  # Check for unexpanded templates
  local remaining
  for file in ${INSTALLED_FILES[@]+"${INSTALLED_FILES[@]}"}; do
    if [ -f "$file" ] && has_unexpanded_templates "$file"; then
      remaining=$(list_unexpanded_templates "$file")
      ui_warn "Unexpanded templates in $file: $remaining"
    fi
  done

  # Verify settings.json is valid JSON
  local settings_path
  for target_dir in "$global_dir" "$project_dir"; do
    settings_path="${target_dir}/settings.json"
    if [ -f "$settings_path" ] && [ "$has_jq" = true ]; then
      if ! jq empty "$settings_path" 2>/dev/null; then
        ui_error "Invalid JSON: $settings_path"
        verify_errors=$((verify_errors + 1))
      else
        ui_success "settings.json is valid"
      fi
    fi
  done

  if [ $verify_errors -eq 0 ]; then
    ui_success "All files verified!"
  else
    ui_error "$verify_errors verification error(s) found"
  fi

  # ===========================================================
  # Step 14: Next steps
  # ===========================================================
  ui_header "Installation Complete!"

  echo ""
  ui_success "CCGM installed successfully with ${#RESOLVED_MODULES[@]} modules."
  echo ""

  if [ ${#BACKUP_DIRS[@]} -gt 0 ]; then
    ui_info "Backups saved to:"
    local bdir
    for bdir in "${BACKUP_DIRS[@]}"; do
      echo "  $bdir"
    done
    echo ""
  fi

  ui_info "Next steps:"
  echo "  1. Open a new Claude Code session to pick up the new config"
  if [ "$install_global" = true ]; then
    echo "  2. Review ~/.claude/settings.json and adjust permissions"
  fi
  if [ "$LINK_MODE" = true ]; then
    echo "  3. Run './update.sh' to check for CCGM updates"
  else
    echo "  3. Re-run './start.sh' to apply future CCGM updates"
  fi
  echo ""
  ui_info "Useful commands:"
  echo "  ./update.sh      Check for upstream updates"
  echo "  ./uninstall.sh   Remove installed modules"
  echo ""
}

main "$@"
