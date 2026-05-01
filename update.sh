#!/usr/bin/env bash
set -euo pipefail

# CCGM - Update checker
# Checks for upstream changes and optionally re-runs installer

# --- Determine script location ---
CCGM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
source "${CCGM_ROOT}/lib/ui.sh"
source "${CCGM_ROOT}/lib/modules.sh"
source "${CCGM_ROOT}/lib/repair.sh"

# ============================================================
# Helper: Check installed file drift
# ============================================================
_check_installed_drift() {
  local manifest="${HOME}/.claude/.ccgm-manifest.json"
  if [ ! -f "$manifest" ] || ! command -v jq &>/dev/null; then
    return 0
  fi

  ui_header "Drift Check"

  # Prune symlinks whose source file no longer exists in the CCGM repo
  # (e.g. after a module rename). Missing files surface as drift below
  # and can be reinstalled via the existing "Install missing?" prompt.
  repair_dangling_symlinks "${HOME}/.claude"

  local link_mode
  link_mode=$(jq -r '.linkMode // false' "$manifest" 2>/dev/null)
  local preset
  preset=$(jq -r '.preset // "custom"' "$manifest" 2>/dev/null)
  local drift_count=0

  # --- Check 1: Missing modules (in preset but not installed) ---
  local missing_modules=()
  if [ "$preset" != "custom" ] && [ -f "${CCGM_ROOT}/presets/${preset}.json" ]; then
    local preset_modules installed_modules
    preset_modules=$(jq -r '.[]' "${CCGM_ROOT}/presets/${preset}.json" 2>/dev/null | sort)
    installed_modules=$(jq -r '.modules[]?' "$manifest" 2>/dev/null | sort)

    while IFS= read -r mod; do
      [ -z "$mod" ] && continue
      missing_modules+=("$mod")
    done < <(comm -23 <(echo "$preset_modules") <(echo "$installed_modules"))

    if [ ${#missing_modules[@]} -gt 0 ]; then
      ui_warn "${#missing_modules[@]} module(s) in '${preset}' preset but not installed:"
      for mod in "${missing_modules[@]}"; do
        local display
        display=$(get_module_display_name "$mod" 2>/dev/null)
        echo "    $mod${display:+ ($display)}"
      done
      drift_count=$((drift_count + ${#missing_modules[@]}))
    fi
  fi

  # --- Check 2: Missing files in installed modules ---
  local installed_modules
  installed_modules=$(jq -r '.modules[]?' "$manifest" 2>/dev/null)
  local missing_files=()

  while IFS= read -r mod; do
    [ -z "$mod" ] && continue
    while IFS='|' read -r src target type template merge; do
      local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
      local full_target="${HOME}/.claude/${target}"

      # Skip merge files (settings.json etc) - they're managed differently
      [ "$merge" = "true" ] && continue

      if [ ! -e "$full_target" ]; then
        missing_files+=("${mod}:${target}")
        ui_warn "Missing: $target (from $mod)"
        drift_count=$((drift_count + 1))
      elif [ "$link_mode" = "true" ] && [ ! -L "$full_target" ] && [ "$template" = "false" ]; then
        # In link mode, non-template files should be symlinks
        missing_files+=("${mod}:${target}")
        ui_warn "Not symlinked: $target (from $mod)"
        drift_count=$((drift_count + 1))
      fi
    done < <(get_module_files "$mod" 2>/dev/null)
  done <<< "$installed_modules"

  # --- Check 3: Content drift (copy mode only) ---
  if [ "$link_mode" != "true" ]; then
    while IFS= read -r mod; do
      [ -z "$mod" ] && continue
      while IFS='|' read -r src target type template merge; do
        local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
        local full_target="${HOME}/.claude/${target}"

        if [ -f "$full_target" ] && [ -f "$full_src" ]; then
          if [ "$template" = "false" ] && [ "$merge" = "false" ]; then
            if ! diff -q "$full_src" "$full_target" &>/dev/null; then
              ui_warn "Content drift: $target"
              drift_count=$((drift_count + 1))
            fi
          fi
        fi
      done < <(get_module_files "$mod" 2>/dev/null)
    done <<< "$installed_modules"
  else
    ui_info "Link mode: existing symlinks auto-update with repo changes"
  fi

  # --- Report ---
  if [ $drift_count -eq 0 ]; then
    ui_success "No drift detected - installation is complete and current"
  else
    ui_warn "$drift_count issue(s) found"
  fi

  # --- Offer to fix ---
  if [ ${#missing_modules[@]} -gt 0 ] || [ ${#missing_files[@]} -gt 0 ]; then
    echo ""
    if ui_confirm "Install missing modules/files now?"; then
      _install_missing "$link_mode" missing_modules missing_files
    else
      ui_info "Run ./start.sh to do a full reinstall"
    fi
  fi
}

# ============================================================
# Helper: Install missing modules and files
# ============================================================
_install_missing() {
  local link_mode="$1"
  local -n _missing_mods=$2
  local -n _missing_files=$3
  local installed_count=0

  # Install files from missing modules
  for mod in ${_missing_mods[@]+"${_missing_mods[@]}"}; do
    ui_info "Installing module: $mod"
    while IFS='|' read -r src target type template merge; do
      local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
      local full_target="${HOME}/.claude/${target}"

      mkdir -p "$(dirname "$full_target")"

      if [ "$merge" = "true" ]; then
        # Skip merge files (settings.json) - too complex for incremental install
        ui_info "  Skipped (merge): $target"
        continue
      fi

      [ -e "$full_target" ] && rm -f "$full_target"

      if [ "$link_mode" = "true" ] && [ "$template" = "false" ]; then
        ln -s "$full_src" "$full_target"
        ui_success "  Linked: $target"
      else
        cp "$full_src" "$full_target"
        ui_success "  Copied: $target"
      fi
      installed_count=$((installed_count + 1))
    done < <(get_module_files "$mod" 2>/dev/null)
  done

  # Fix missing/unsymlinked files in already-installed modules
  for entry in ${_missing_files[@]+"${_missing_files[@]}"}; do
    local mod="${entry%%:*}"
    local target="${entry#*:}"

    # Skip if this module was just fully installed above
    local already_done=false
    for m in ${_missing_mods[@]+"${_missing_mods[@]}"}; do
      [ "$m" = "$mod" ] && already_done=true
    done
    [ "$already_done" = true ] && continue

    # Find the source for this target
    while IFS='|' read -r src file_target type template merge; do
      [ "$file_target" != "$target" ] && continue
      local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
      local full_target="${HOME}/.claude/${target}"

      mkdir -p "$(dirname "$full_target")"
      [ -e "$full_target" ] && rm -f "$full_target"

      if [ "$link_mode" = "true" ] && [ "$template" = "false" ]; then
        ln -s "$full_src" "$full_target"
        ui_success "  Linked: $target"
      else
        cp "$full_src" "$full_target"
        ui_success "  Copied: $target"
      fi
      installed_count=$((installed_count + 1))
    done < <(get_module_files "$mod" 2>/dev/null)
  done

  # Update manifest with newly installed modules
  if [ ${#_missing_mods[@]} -gt 0 ]; then
    local manifest="${HOME}/.claude/.ccgm-manifest.json"
    local tmp_manifest
    tmp_manifest=$(mktemp)

    # Add missing modules to the modules array
    local new_modules_json
    new_modules_json=$(printf '%s\n' "${_missing_mods[@]}" | jq -R . | jq -s .)
    jq --argjson new "$new_modules_json" '.modules = (.modules + $new | unique)' "$manifest" > "$tmp_manifest"

    # Add new file paths to the files array
    for mod in "${_missing_mods[@]}"; do
      while IFS='|' read -r src target type template merge; do
        [ "$merge" = "true" ] && continue
        local full_target="${HOME}/.claude/${target}"
        new_modules_json=$(jq --arg f "$full_target" '.files += [$f] | .files = (.files | unique)' "$tmp_manifest")
        echo "$new_modules_json" > "$tmp_manifest"
      done < <(get_module_files "$mod" 2>/dev/null)
    done

    mv "$tmp_manifest" "$manifest"
    ui_success "Updated manifest with ${#_missing_mods[@]} new module(s)"
  fi

  echo ""
  ui_success "Installed $installed_count file(s)"
}

# ============================================================
# Helper: Offer to re-run installer
# ============================================================
_offer_reinstall() {
  echo ""
  ui_header "Re-install"

  # Check if a manifest exists
  local manifest="${HOME}/.claude/.ccgm-manifest.json"
  if [ -f "$manifest" ] && command -v jq &>/dev/null; then
    local prev_preset prev_scope prev_link
    prev_preset=$(jq -r '.preset // "custom"' "$manifest")
    prev_scope=$(jq -r '.scope // "global"' "$manifest")
    prev_link=$(jq -r '.linkMode // false' "$manifest")

    ui_info "Previous installation:"
    ui_info "  Preset: $prev_preset"
    ui_info "  Scope: $prev_scope"
    ui_info "  Link mode: $prev_link"
    echo ""

    if ui_confirm "Re-run installer with same settings?"; then
      local args=("--preset" "$prev_preset" "--scope" "$prev_scope")
      if [ "$prev_link" = "true" ]; then
        args+=("--link")
      fi
      exec "${CCGM_ROOT}/start.sh" "${args[@]}"
    else
      ui_info "Run ./start.sh to configure a new installation."
    fi
  else
    if ui_confirm "Run the installer to apply updates?"; then
      exec "${CCGM_ROOT}/start.sh"
    else
      ui_info "Run ./start.sh when ready to apply updates."
    fi
  fi
}

# ============================================================
# Helper: Migrate legacy ~/.claude/mcp.json (issue #427)
# Current Claude Code reads MCP config from ~/.claude.json (managed by the
# `claude mcp` CLI), not ~/.claude/mcp.json. Pre-#427 CCGM docs told users
# to hand-edit the legacy file; entries there are silently ignored.
# This re-registers each entry via `claude mcp add-json --scope user`.
# ============================================================
_migrate_legacy_mcp_json() {
  local legacy="${HOME}/.claude/mcp.json"
  [ ! -f "$legacy" ] && return 0

  local migrate_script="${CCGM_ROOT}/lib/mcp-migrate.sh"
  if [ ! -x "$migrate_script" ]; then
    return 0
  fi

  ui_header "Legacy MCP Migration"
  ui_info "Found ${legacy} - current Claude Code reads ~/.claude.json instead."
  ui_info "Re-registering entries via 'claude mcp add-json --scope user'."
  echo ""
  bash "$migrate_script" "$legacy" || ui_warn "Some entries failed; see output above."
  echo ""
}

# ============================================================
# Main
# ============================================================
main() {
  # Step 0: Migrate legacy MCP config if present (idempotent; skips on empty)
  _migrate_legacy_mcp_json

  # Step 1: Check for CCGM repo updates
  ui_header "CCGM Update Check"

  # Verify we're in a git repo
  if ! git -C "$CCGM_ROOT" rev-parse --is-inside-work-tree &>/dev/null; then
    ui_error "CCGM directory is not a git repository: $CCGM_ROOT"
    ui_info "Cannot check for updates without git history."
    exit 1
  fi

  # Fetch latest
  ui_info "Fetching latest changes..."
  if ! git -C "$CCGM_ROOT" fetch origin 2>/dev/null; then
    ui_error "Failed to fetch from remote. Check your network connection."
    exit 1
  fi

  # Compare local vs remote
  local local_head remote_head
  local_head=$(git -C "$CCGM_ROOT" rev-parse HEAD 2>/dev/null)
  remote_head=$(git -C "$CCGM_ROOT" rev-parse origin/main 2>/dev/null || echo "")

  if [ -z "$remote_head" ]; then
    ui_warn "Could not determine remote HEAD. Skipping update check."
    exit 0
  fi

  if [ "$local_head" = "$remote_head" ]; then
    ui_success "CCGM is up to date!"
    echo ""
    _check_installed_drift
    exit 0
  fi

  # Show what changed
  ui_info "Updates available!"
  echo ""
  local behind_count
  behind_count=$(git -C "$CCGM_ROOT" rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
  ui_info "$behind_count new commit(s) on origin/main"
  echo ""

  # Show commit log
  git -C "$CCGM_ROOT" log --oneline HEAD..origin/main 2>/dev/null | while IFS= read -r line; do
    echo "  $line"
  done
  echo ""

  # Step 2: Show changed files
  ui_header "Changed Files"

  local changed_files
  changed_files=$(git -C "$CCGM_ROOT" diff --name-only HEAD..origin/main 2>/dev/null)

  if [ -n "$changed_files" ]; then
    local module_changes=()
    local preset_changes=()
    local installer_changes=()
    local other_changes=()

    while IFS= read -r file; do
      case "$file" in
        modules/*) module_changes+=("$file") ;;
        presets/*) preset_changes+=("$file") ;;
        start.sh|update.sh|uninstall.sh|lib/*) installer_changes+=("$file") ;;
        *) other_changes+=("$file") ;;
      esac
    done <<< "$changed_files"

    if [ ${#module_changes[@]} -gt 0 ]; then
      ui_info "Module changes (${#module_changes[@]} files):"
      for f in "${module_changes[@]}"; do echo "  $f"; done
    fi

    if [ ${#preset_changes[@]} -gt 0 ]; then
      ui_info "Preset changes (${#preset_changes[@]} files):"
      for f in "${preset_changes[@]}"; do echo "  $f"; done
    fi

    if [ ${#installer_changes[@]} -gt 0 ]; then
      ui_info "Installer changes (${#installer_changes[@]} files):"
      for f in "${installer_changes[@]}"; do echo "  $f"; done
    fi

    if [ ${#other_changes[@]} -gt 0 ]; then
      ui_info "Other changes (${#other_changes[@]} files):"
      for f in "${other_changes[@]}"; do echo "  $f"; done
    fi
  fi

  # Step 3: Offer to update
  echo ""

  if ui_confirm "Pull latest changes?"; then
    ui_info "Pulling changes..."
    if git -C "$CCGM_ROOT" pull --ff-only origin main 2>/dev/null; then
      ui_success "Updated to latest version!"
    else
      ui_warn "Fast-forward pull failed. You may need to resolve conflicts manually."
      ui_info "  cd $CCGM_ROOT && git pull origin main"
      exit 1
    fi
  else
    ui_info "Skipped pull. Run 'git -C $CCGM_ROOT pull origin main' to update manually."
    exit 0
  fi

  # Step 4: Re-run installer
  _offer_reinstall
}

main "$@"
