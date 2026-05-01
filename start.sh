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
# shellcheck source=lib/repair.sh
source "${CCGM_ROOT}/lib/repair.sh"

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
      echo "  ],"
      echo "  \"files\": ["
      first=true
      local file
      if [ ${#INSTALLED_FILES[@]} -gt 0 ]; then
        for file in "${INSTALLED_FILES[@]}"; do
          if [ "$first" = true ]; then first=false; else echo ","; fi
          echo -n "    \"$file\""
        done
      fi
      echo ""
      echo "  ],"
      echo "  \"backups\": ["
      first=true
      local backup
      if [ ${#BACKUP_DIRS[@]} -gt 0 ]; then
        for backup in "${BACKUP_DIRS[@]}"; do
          if [ "$first" = true ]; then first=false; else echo ","; fi
          echo -n "    \"$backup\""
        done
      fi
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
  local sudo_cmd="sudo"
  # Skip sudo if already running as root (e.g., Docker containers)
  if [ "$(id -u)" -eq 0 ]; then
    sudo_cmd=""
  fi
  if command -v brew &>/dev/null; then
    pkg_manager="brew"
    pkg_install="brew install"
  elif command -v apt-get &>/dev/null; then
    pkg_manager="apt"
    pkg_install="${sudo_cmd:+$sudo_cmd }apt-get install -y"
  elif command -v dnf &>/dev/null; then
    pkg_manager="dnf"
    pkg_install="${sudo_cmd:+$sudo_cmd }dnf install -y"
  elif command -v pacman &>/dev/null; then
    pkg_manager="pacman"
    pkg_install="${sudo_cmd:+$sudo_cmd }pacman -S --noconfirm"
  fi

  # Define prerequisites: name|required|check_cmd|pkg_name_brew|pkg_name_apt|description
  local -a missing_required=()
  local -a missing_optional=()
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

  # Check for Claude Code first
  if command -v claude &>/dev/null; then
    ui_success "claude: installed"
  else
    echo ""
    ui_warn "Claude Code is not installed."
    ui_info "CCGM configures Claude Code, so you'll need it installed to use these configs."
    ui_info "Install: npm install -g @anthropic-ai/claude-code"
    ui_info "  Docs: https://docs.anthropic.com/en/docs/claude-code"
    echo ""
    if ! ui_confirm "Continue installing CCGM configs anyway?"; then
      ui_info "Install Claude Code first, then re-run ./start.sh"
      exit 0
    fi
    echo ""
  fi

  # Required prerequisites
  _check_prereq "git" "true" "version control" || true
  _check_prereq "python3" "true" "needed for hooks module" || true
  _check_prereq "jq" "true" "needed for settings.json merging" || true
  if command -v jq &>/dev/null; then has_jq=true; fi

  # Optional but recommended
  _check_prereq "gh" "false" "GitHub CLI for issue/PR commands" || true

  # Version checks for key tools (warnings only, not blockers)
  if command -v jq &>/dev/null; then
    jq_version=$(jq --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if [ -n "$jq_version" ] && [ "$(printf '%s\n' "1.6" "$jq_version" | sort -V | head -1)" != "1.6" ]; then
      ui_warn "jq version $jq_version found, 1.6+ recommended"
    fi
  fi
  if command -v python3 &>/dev/null; then
    py_version=$(python3 -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))" 2>/dev/null)
    if [ -n "$py_version" ] && [ "$(printf '%s\n' "3.6" "$py_version" | sort -V | head -1)" != "3.6" ]; then
      ui_warn "Python $py_version found, 3.6+ recommended"
    fi
  fi

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
  ui_success "Username: $github_username"
  echo ""

  # Code workspace directory
  local code_dir
  code_dir=$(ui_input "Code workspace directory (the parent directory for your code repositories)" "${CCGM_CODE_DIR:-$default_code_dir}")
  ui_success "Code directory: $code_dir"
  echo ""

  # Timezone
  local timezone
  timezone=$(ui_input "Timezone" "${CCGM_TIMEZONE:-$default_timezone}")
  ui_success "Timezone: $timezone"

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
      # Custom module selection - stable modules first, beta modules last.
      local all_modules=()
      local stable_labels=()
      local beta_labels=()
      local desc
      while IFS= read -r mod; do
        all_modules+=("$mod")
        desc=""
        if [ "$has_jq" = true ]; then
          desc=$(jq -r '.description' "${CCGM_ROOT}/modules/${mod}/module.json" 2>/dev/null | head -c 80)
        fi
        if is_beta "$mod"; then
          if [ -n "$desc" ]; then
            beta_labels+=("$mod [BETA] - $desc")
          else
            beta_labels+=("$mod [BETA]")
          fi
        else
          if [ -n "$desc" ]; then
            stable_labels+=("$mod - $desc")
          else
            stable_labels+=("$mod")
          fi
        fi
      done < <(discover_modules)

      local module_labels=("${stable_labels[@]}" "${beta_labels[@]}")

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

  local has_module_config=false
  for mod in "${RESOLVED_MODULES[@]}"; do
    if [ "$has_jq" = true ]; then
      local prompt_count
      prompt_count=$(jq -r '.configPrompts | length' "${CCGM_ROOT}/modules/${mod}/module.json" 2>/dev/null || echo "0")
      if [ "$prompt_count" -gt 0 ] 2>/dev/null; then
        if [ "$has_module_config" = false ]; then
          ui_header "Module Configuration"
          has_module_config=true
        fi
        local mod_display
        mod_display=$(get_module_display_name "$mod")
        ui_info "$mod_display"

        # Read all prompts into an array first to avoid stdin conflicts
        # (ui_input uses read, which conflicts with process substitution)
        local config_lines=()
        while IFS= read -r line; do
          [ -n "$line" ] && config_lines+=("$line")
        done < <(get_module_config_prompts "$mod")

        local key prompt default options value
        for config_line in "${config_lines[@]}"; do
          IFS='|' read -r key prompt default options <<< "$config_line"
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
              protectedBranches)
                ui_info "Default protected branches (direct commits blocked, PRs required):"
                echo "  develop, dev, main, master, prod, production, release, staging, stag, trunk"
                echo ""
                ;;
            esac
            value=$(ui_input "$prompt" "$default")
          fi

          if [ -n "$value" ]; then
            ui_success "Set: $value"
          else
            case "$key" in
              protectedBranches) ui_success "Using defaults only" ;;
              *) ui_success "Set: (empty)" ;;
            esac
          fi
          _set_module_config "${mod}__${key}" "$value"
        done
        echo ""
      fi
    fi
  done

  # --- Identity module: follow-up personalization prompts ---
  local personalize_identity
  personalize_identity=$(_get_module_config "identity__personalizeIdentity" "no")
  if [ "$personalize_identity" = "yes" ]; then
    ui_info "Answer as much or as little as you like. Press Enter to skip any question."
    echo ""

    local id_role id_expertise id_communication id_building id_values

    id_role=$(ui_input "Professional role (e.g., Senior full-stack engineer, Data scientist)" "")
    [ -n "$id_role" ] && ui_success "Set: $id_role" || ui_success "Skipped"

    id_expertise=$(ui_input "Technical expertise (e.g., TypeScript, React, Python, AWS)" "")
    [ -n "$id_expertise" ] && ui_success "Set: $id_expertise" || ui_success "Skipped"

    id_communication=$(ui_choose "Communication preference" "Concise and direct" "Detailed explanations" "Balanced")
    ui_success "Set: $id_communication"

    id_building=$(ui_input "What are you building? (e.g., A SaaS product for project management)" "")
    [ -n "$id_building" ] && ui_success "Set: $id_building" || ui_success "Skipped"

    id_values=$(ui_choose "What do you value most in code?" "Simplicity and readability" "Performance and optimization" "Comprehensive test coverage" "All of the above")
    ui_success "Set: $id_values"

    _set_module_config "identity__role" "$id_role"
    _set_module_config "identity__expertise" "$id_expertise"
    _set_module_config "identity__communication" "$id_communication"
    _set_module_config "identity__building" "$id_building"
    _set_module_config "identity__values" "$id_values"
    echo ""
  fi

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

  # Remove stale symlinks from prior installs (e.g. modules renamed upstream).
  # Must run before `ln -s` below, because `ln -s` fails if a dangling symlink
  # already occupies the target path (`[ -e ... ]` doesn't detect it).
  [ "$install_global" = true ] && repair_dangling_symlinks "$global_dir"
  [ "$install_project" = true ] && repair_dangling_symlinks "$project_dir"

  # Write .ccgm.env
  local env_file="${global_dir}/.ccgm.env"
  local default_mode
  default_mode=$(_get_module_config "settings__defaultMode" "ask")
  local auto_update_raw
  auto_update_raw=$(_get_module_config "hooks__autoUpdateCheck" "yes")
  local auto_update_check="false"
  case "$auto_update_raw" in
    yes|true|1) auto_update_check="true" ;;
  esac
  local env_entries=(
    "CCGM_HOME=${HOME}"
    "CCGM_USERNAME=${github_username}"
    "CCGM_CODE_DIR=${code_dir}"
    "CCGM_TIMEZONE=${timezone}"
    "CCGM_DEFAULT_MODE=${default_mode}"
    "CCGM_AUTO_UPDATE_CHECK=${auto_update_check}"
  )

  # Add module-specific configs
  local cfg_idx=0
  while [ $cfg_idx -lt ${#MODULE_CONFIG_KEYS[@]} ]; do
    local cfg_key="${MODULE_CONFIG_KEYS[$cfg_idx]}"
    case "$cfg_key" in
      *__defaultMode__*|*__autoUpdateCheck__*) cfg_idx=$((cfg_idx + 1)); continue ;;
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

  # --- Identity module: generate personalized files or print reminder ---
  local _identity_installed=false
  for mod in "${RESOLVED_MODULES[@]}"; do
    [ "$mod" = "identity" ] && _identity_installed=true
  done

  if [ "$_identity_installed" = true ]; then
    if [ "$personalize_identity" = "yes" ]; then
      local id_role id_expertise id_communication id_building id_values
      id_role=$(_get_module_config "identity__role" "")
      id_expertise=$(_get_module_config "identity__expertise" "")
      id_communication=$(_get_module_config "identity__communication" "Balanced")
      id_building=$(_get_module_config "identity__building" "")
      id_values=$(_get_module_config "identity__values" "All of the above")

      # Determine target directory
      local id_target_dir=""
      [ "$install_global" = true ] && id_target_dir="$global_dir"
      [ -z "$id_target_dir" ] && [ "$install_project" = true ] && id_target_dir="$project_dir"

      if [ -n "$id_target_dir" ]; then
        # --- Generate soul.md ---
        local soul_file="${id_target_dir}/rules/soul.md"
        {
          echo "# Soul"
          echo ""

          # Identity section
          echo "## Identity"
          echo ""
          if [ -n "$id_role" ]; then
            echo "You are a senior engineering partner, not an assistant. We work together as equals with complementary strengths."
          else
            cat <<'TMPL'
<!-- Who is this AI collaborator? What is the relationship model?
     Example: "You are a senior engineering partner, not an assistant." -->
TMPL
          fi
          echo ""

          # Communication Style section
          echo "## Communication Style"
          echo ""
          case "$id_communication" in
            "Concise and direct")
              echo "Lead with the answer or action, not the reasoning. Skip filler, preamble, and unnecessary transitions. One sentence beats three. Show the diff, not the explanation."
              ;;
            "Detailed explanations")
              echo "Explain your reasoning and trade-offs. Include context for decisions so I can learn and verify your approach. Be thorough but organized."
              ;;
            "Balanced")
              echo "Be direct but include enough context for me to follow your reasoning. Skip filler, but explain non-obvious decisions."
              ;;
          esac
          echo ""

          # Reasoning Principles section
          echo "## Reasoning Principles"
          echo ""
          echo "Understand before acting. Read the error, check assumptions, try a focused fix. Don't retry identical actions or abandon viable approaches after a single failure."
          echo ""
          echo "Evidence before claims. Never assert that something works, passes, or is fixed without fresh proof."
          echo ""
          echo "Simplest viable approach first. Don't over-engineer or design for hypothetical future requirements."
          echo ""

          # Core Values section
          echo "## Core Values"
          echo ""
          case "$id_values" in
            "Simplicity and readability")
              echo "Simplicity over cleverness. Readability over brevity. Code should be obvious to the next person who reads it."
              ;;
            "Performance and optimization")
              echo "Performance matters. Profile before optimizing, but don't leave known bottlenecks on the table. Ship fast code that stays fast."
              ;;
            "Comprehensive test coverage")
              echo "Every piece of code has tests. Every bug fix starts with a failing test. Every claim has evidence. No exceptions."
              ;;
            "All of the above")
              echo "Correctness over speed. Simplicity over cleverness. Shipping over perfecting. Every piece of code has tests."
              ;;
          esac
          echo ""

          # Boundaries section
          echo "## Boundaries"
          echo ""
          echo "Defer on ambiguous product decisions where multiple valid directions exist and my preference matters. Make decisions yourself for routine technical choices."
          echo ""
          echo "Never guess at credentials or API keys. Ask once, then proceed."
          echo ""
          echo "Confirm before destructive actions on shared systems."
        } > "$soul_file"
        ui_success "Generated personalized: $soul_file"

        # --- Generate human-context.md ---
        local hc_file="${id_target_dir}/rules/human-context.md"
        {
          echo "# Human Context"
          echo ""

          # Who I Am section
          echo "## Who I Am"
          echo ""
          if [ -n "$id_role" ] || [ -n "$id_expertise" ]; then
            [ -n "$id_role" ] && echo "$id_role."
            [ -n "$id_expertise" ] && echo "Technical expertise: $id_expertise."
          else
            cat <<'TMPL'
<!-- Your professional identity and technical background.
     Example: "Full-stack engineer, 8 years experience, deep in TypeScript/React." -->
TMPL
          fi
          echo ""

          # What I'm Building section
          echo "## What I'm Building"
          echo ""
          if [ -n "$id_building" ]; then
            echo "$id_building"
          else
            cat <<'TMPL'
<!-- Your current projects, their purpose, and how they connect.
     Example: "Building a SaaS product for X. Also maintaining an open-source tool for Y." -->
TMPL
          fi
          echo ""

          # How I Work section
          echo "## How I Work"
          echo ""
          case "$id_communication" in
            "Concise and direct")
              echo "I prefer terse communication. Show me the diff, not the explanation. Don't summarize what you just did - I can read the output."
              ;;
            "Detailed explanations")
              echo "I appreciate thorough explanations of trade-offs and reasoning. Walk me through your approach so I can verify and learn."
              ;;
            "Balanced")
              echo "Be direct but explain non-obvious decisions. I read diffs but appreciate context for architectural choices."
              ;;
          esac
          echo ""

          # What I Value section
          echo "## What I Value"
          echo ""
          case "$id_values" in
            "Simplicity and readability")
              echo "Clean, readable code that communicates intent. Fewer abstractions, obvious naming, minimal dependencies."
              ;;
            "Performance and optimization")
              echo "Fast, efficient code. Measure before optimizing, but don't accept slow as the default."
              ;;
            "Comprehensive test coverage")
              echo "Test coverage is non-negotiable. Every feature has tests, every bug fix starts with a failing test."
              ;;
            "All of the above")
              echo "Quality that compounds. Every PR should make the codebase more intentional, not more accidental. Tests are non-negotiable."
              ;;
          esac
          echo ""

          # Where I'm Going section
          echo "## Where I'm Going"
          echo ""
          cat <<'TMPL'
<!-- Your longer-horizon goals and how current work serves them.
     Example: "Building toward independent consulting. Current projects are portfolio pieces." -->
TMPL
        } > "$hc_file"
        ui_success "Generated personalized: $hc_file"
      fi
    else
      # Remind user to edit the template files later
      local id_target_dir=""
      [ "$install_global" = true ] && id_target_dir="$global_dir"
      [ -z "$id_target_dir" ] && [ "$install_project" = true ] && id_target_dir="$project_dir"
      if [ -n "$id_target_dir" ]; then
        echo ""
        ui_info "Identity files installed as templates. Edit them to personalize:"
        echo "  ${id_target_dir}/rules/soul.md"
        echo "  ${id_target_dir}/rules/human-context.md"
      fi
    fi
  fi

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
  # Step 14: Shell aliases
  # ===========================================================
  ui_header "Shell Aliases"

  # Resolve rc file - prompt user if shell is unrecognized
  local rc_file=""
  case "$shell_type" in
    zsh)  rc_file="$HOME/.zshrc" ;;
    bash) rc_file="$HOME/.bashrc" ;;
    *)
      ui_info "Unrecognized shell: $shell_type"
      echo ""
      echo "Which shell config file should aliases be added to?"
      echo "  1) ~/.zshrc"
      echo "  2) ~/.bashrc"
      echo "  3) Skip alias setup"
      local shell_choice
      read -rp "Choice [1-3]: " shell_choice
      case "$shell_choice" in
        1) rc_file="$HOME/.zshrc" ;;
        2) rc_file="$HOME/.bashrc" ;;
        *) rc_file="" ;;
      esac
      ;;
  esac

  # Explain the alias before prompting
  echo ""
  ui_info "CCGM provides a shell alias for launching Claude Code:"
  echo ""
  echo "  ccgm   Session startup   claude /startup --dangerously-skip-permissions"
  echo "         Prints the startup dashboard: git state, open PRs, tracking,"
  echo "         live sessions, recent activity, orphans, release check."
  echo ""

  local alias_ccgm_installed=false

  if [ -n "$rc_file" ]; then
    local ccgm_cmd='claude /startup --dangerously-skip-permissions'
    if [ -f "$rc_file" ] && grep -qF 'alias ccgm=' "$rc_file" 2>/dev/null; then
      ui_info "Alias 'ccgm' already exists in ${rc_file} - skipping"
    elif ui_confirm "Add 'ccgm' alias to ${rc_file}?"; then
      echo "" >> "$rc_file"
      echo "# CCGM - startup dashboard" >> "$rc_file"
      echo "alias ccgm=\"${ccgm_cmd}\"" >> "$rc_file"
      ui_success "ccgm alias added"
      alias_ccgm_installed=true
    else
      ui_info "Skipped. Add manually: alias ccgm=\"${ccgm_cmd}\""
    fi

    if [ "$alias_ccgm_installed" = true ]; then
      echo ""
      ui_info "Run 'source ${rc_file}' or open a new terminal to use the alias"
    fi
  else
    ui_info "Skipping alias setup."
    echo ""
    echo "Add manually to your shell config:"
    echo "  alias ccgm=\"claude /startup --dangerously-skip-permissions\""
  fi

  # ===========================================================
  # Step 14b: Migrate legacy ~/.claude/mcp.json (issue #427)
  # Pre-#427 docs told users to hand-edit ~/.claude/mcp.json. Current
  # Claude Code reads ~/.claude.json (managed by `claude mcp` CLI).
  # Re-register each entry; idempotent (skips on no legacy file or
  # already-registered names).
  # ===========================================================
  if [ -f "${HOME}/.claude/mcp.json" ] && [ -x "${CCGM_ROOT}/lib/mcp-migrate.sh" ]; then
    ui_header "Legacy MCP Migration"
    ui_info "Re-registering entries via 'claude mcp add-json --scope user'."
    echo ""
    bash "${CCGM_ROOT}/lib/mcp-migrate.sh" "${HOME}/.claude/mcp.json" || ui_warn "Some entries failed; see output above."
    echo ""
  fi

  # ===========================================================
  # Step 15: Next steps
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
  local step=1
  if [ "$alias_ccgm_installed" = true ]; then
    echo "  ${step}. Run 'source ${rc_file}' to activate the new alias"
    step=$((step + 1))
  else
    echo "  ${step}. Open a new Claude Code session to pick up the new config"
    step=$((step + 1))
  fi
  if [ "$install_global" = true ]; then
    echo "  ${step}. Review ~/.claude/settings.json and adjust permissions"
    step=$((step + 1))
  fi
  if [ "$LINK_MODE" = true ]; then
    echo "  ${step}. Run './update.sh' to check for CCGM updates"
  else
    echo "  ${step}. Re-run './start.sh' to apply future CCGM updates"
  fi
  echo ""
  ui_info "Useful commands:"
  if [ "$alias_ccgm_installed" = true ]; then
    echo "  ccgm             Session startup (git status, tracking, live sessions, recent activity)"
  fi
  echo "  ./update.sh      Check for upstream updates"
  echo "  ./uninstall.sh   Remove installed modules"
  echo ""
}

main "$@"
