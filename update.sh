#!/usr/bin/env bash
set -euo pipefail

# CCGM - Update checker
# Checks for upstream changes and optionally re-runs installer

# --- Determine script location ---
CCGM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
source "${CCGM_ROOT}/lib/ui.sh"
source "${CCGM_ROOT}/lib/modules.sh"

# ============================================================
# Helper: Check installed file drift
# ============================================================
_check_installed_drift() {
  local manifest="${HOME}/.claude/.ccgm-manifest.json"
  if [ ! -f "$manifest" ] || ! command -v jq &>/dev/null; then
    return 0
  fi

  ui_header "Drift Check"

  local modules
  modules=$(jq -r '.modules[]?' "$manifest" 2>/dev/null)
  local link_mode
  link_mode=$(jq -r '.linkMode // false' "$manifest" 2>/dev/null)
  local drift_count=0

  if [ "$link_mode" = "true" ]; then
    ui_info "Link mode: files auto-update with repo changes"
    return 0
  fi

  while IFS= read -r mod; do
    [ -z "$mod" ] && continue
    while IFS='|' read -r src target type template merge; do
      local full_src="${CCGM_ROOT}/modules/${mod}/${src}"
      local full_target="${HOME}/.claude/${target}"

      if [ -f "$full_target" ] && [ -f "$full_src" ]; then
        # For non-template, non-merge files, compare directly
        if [ "$template" = "false" ] && [ "$merge" = "false" ]; then
          if ! diff -q "$full_src" "$full_target" &>/dev/null; then
            ui_warn "Drift detected: $target"
            drift_count=$((drift_count + 1))
          fi
        fi
      fi
    done < <(get_module_files "$mod" 2>/dev/null)
  done <<< "$modules"

  if [ $drift_count -eq 0 ]; then
    ui_success "No drift detected - installed files match source"
  else
    ui_warn "$drift_count file(s) differ from source"
    ui_info "Run ./install.sh to re-apply from source"
  fi
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
      exec "${CCGM_ROOT}/install.sh" "${args[@]}"
    else
      ui_info "Run ./install.sh to configure a new installation."
    fi
  else
    if ui_confirm "Run the installer to apply updates?"; then
      exec "${CCGM_ROOT}/install.sh"
    else
      ui_info "Run ./install.sh when ready to apply updates."
    fi
  fi
}

# ============================================================
# Main
# ============================================================
main() {
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
        install.sh|update.sh|uninstall.sh|lib/*) installer_changes+=("$file") ;;
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
