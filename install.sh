#!/usr/bin/env bash
set -euo pipefail

# CCGM - Claude Code God Mode Installer
# Usage: ./install.sh [--link] [--preset <name>] [--scope <global|project|both>]

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
        echo "CCGM Installer"
        echo ""
        echo "Usage: ./install.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --link              Create symlinks instead of copies"
        echo "  --preset <name>     Use preset (minimal, standard, full, team)"
        echo "  --scope <scope>     Installation scope (global, project, both)"
        echo "  -h, --help          Show this help"
        echo ""
        echo "Examples:"
        echo "  ./install.sh                        Interactive installation"
        echo "  ./install.sh --preset standard       Quick install with standard preset"
        echo "  ./install.sh --link --preset full    Symlink full preset"
        exit 0
        ;;
      *)
        echo "Unknown option: $1"
        echo "Run ./install.sh --help for usage"
        exit 1
        ;;
    esac
  done

  # ===========================================================
  # Step 1: Welcome
  # ===========================================================
  ui_banner

  # ===========================================================
  # Step 2: Detect environment
  # ===========================================================
  ui_header "Environment Detection"

  local os_type="unknown"
  case "$OSTYPE" in
    darwin*)  os_type="macOS" ;;
    linux*)   os_type="Linux" ;;
    msys*|cygwin*|win*) os_type="Windows" ;;
  esac

  local shell_type
  shell_type="$(basename "${SHELL:-/bin/bash}")"
  local has_gum=false
  local has_jq=false

  command -v gum &>/dev/null && has_gum=true
  command -v jq &>/dev/null && has_jq=true

  ui_info "OS: $os_type"
  ui_info "Shell: $shell_type"
  if [ "$has_gum" = true ]; then
    ui_success "gum: installed (enhanced TUI)"
  else
    ui_info "gum: not found (using basic prompts)"
    ui_info "  Install for better experience: brew install gum"
  fi
  if [ "$has_jq" = true ]; then
    ui_success "jq: installed"
  else
    ui_warn "jq: not found - settings.json merging will be skipped"
    ui_info "  Install: brew install jq (macOS) or apt install jq (Linux)"
  fi

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
  declare -A MODULE_CONFIGS

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

          MODULE_CONFIGS["${mod}__${key}"]="$value"
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
  local log_repo="${MODULE_CONFIGS[session-logging____LOG_REPO__]:-${github_username}-agent-logs}"
  local env_entries=(
    "CCGM_HOME=${HOME}"
    "CCGM_USERNAME=${github_username}"
    "CCGM_CODE_DIR=${code_dir}"
    "CCGM_LOG_REPO=${log_repo}"
    "CCGM_TIMEZONE=${timezone}"
    "CCGM_DEFAULT_MODE=${default_mode}"
  )

  # Add module-specific configs
  local cfg_key
  for cfg_key in "${!MODULE_CONFIGS[@]}"; do
    case "$cfg_key" in
      *__LOG_REPO__*|*__defaultMode__*) continue ;;
    esac
    env_entries+=("CCGM_MODULE_${cfg_key}=${MODULE_CONFIGS[$cfg_key]}")
  done

  if [ "$install_global" = true ]; then
    write_env_file "$env_file" "${env_entries[@]}"
    ui_success "Wrote $env_file"
  fi

  # Process install plan
  INSTALLED_FILES=()

  local entry action src target template mod_name
  for entry in "${install_plan[@]}"; do
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
  for file in "${INSTALLED_FILES[@]}"; do
    if [ ! -e "$file" ]; then
      ui_error "Missing: $file"
      verify_errors=$((verify_errors + 1))
    fi
  done

  # Check for unexpanded templates
  local remaining
  for file in "${INSTALLED_FILES[@]}"; do
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
    echo "  3. Re-run './install.sh' to apply future CCGM updates"
  fi
  echo ""
  ui_info "Useful commands:"
  echo "  ./update.sh      Check for upstream updates"
  echo "  ./uninstall.sh   Remove installed modules"
  echo ""
}

main "$@"
