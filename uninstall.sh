#!/usr/bin/env bash
set -euo pipefail

# CCGM - Uninstaller
# Cleanly removes installed modules using the manifest

# --- Determine script location ---
CCGM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
source "${CCGM_ROOT}/lib/ui.sh"
source "${CCGM_ROOT}/lib/backup.sh"

# ============================================================
# Main
# ============================================================
main() {
  local global_dir="$HOME/.claude"
  local manifest="${global_dir}/.ccgm-manifest.json"
  local has_jq=false
  command -v jq &>/dev/null && has_jq=true

  # Step 1: Welcome
  ui_header "CCGM Uninstaller"

  # Step 2: Find manifest
  if [ ! -f "$manifest" ]; then
    local project_manifest
    project_manifest="$(pwd)/.claude/.ccgm-manifest.json"
    if [ -f "$project_manifest" ]; then
      manifest="$project_manifest"
      ui_info "Found project-level manifest: $manifest"
    else
      ui_error "No CCGM manifest found."
      ui_info "Expected at: ${global_dir}/.ccgm-manifest.json"
      ui_info "CCGM may not be installed, or was installed without the manifest."
      exit 1
    fi
  fi

  # Step 3: Read manifest
  local installed_at preset scope module_count file_count
  if [ "$has_jq" = true ]; then
    installed_at=$(jq -r '.installedAt // "unknown"' "$manifest")
    preset=$(jq -r '.preset // "custom"' "$manifest")
    scope=$(jq -r '.scope // "global"' "$manifest")
    module_count=$(jq -r '.modules | length' "$manifest")
    file_count=$(jq -r 'if .files then (.files | length) else 0 end' "$manifest" 2>/dev/null || echo "0")

    ui_info "Installation details:"
    ui_info "  Installed: $installed_at"
    ui_info "  Preset: $preset"
    ui_info "  Scope: $scope"
    ui_info "  Modules: $module_count"
    ui_info "  Files: $file_count"
    echo ""

    ui_info "Installed modules:"
    while IFS= read -r mod; do
      echo "  - $mod"
    done < <(jq -r '.modules[]?' "$manifest")
    echo ""

    ui_info "Files to remove:"
    while IFS= read -r file; do
      if [ -e "$file" ]; then
        echo "  - $file"
      else
        echo "  - $file (already missing)"
      fi
    done < <(jq -r '.files[]?' "$manifest" 2>/dev/null)
  else
    ui_info "Found manifest at: $manifest"
    ui_warn "jq not available - will remove known CCGM paths"
  fi

  # Step 4: Confirm
  echo ""
  ui_warn "This will remove all CCGM-installed files listed above."
  ui_info "Your backups (if any) will NOT be removed."
  echo ""

  if ! ui_confirm "Proceed with uninstall?" "no"; then
    ui_info "Uninstall cancelled."
    exit 0
  fi

  # Step 5: Create a safety backup before removal
  ui_header "Safety Backup"

  local backup_path
  backup_path=$(create_backup "$global_dir")
  if [ -n "$backup_path" ]; then
    ui_success "Safety backup created: $backup_path"
  else
    ui_info "No files to back up"
  fi

  # Step 6: Remove files
  ui_header "Removing Files"

  local removed_count=0
  local skipped_count=0

  if [ "$has_jq" = true ]; then
    while IFS= read -r file; do
      [ -z "$file" ] && continue

      if [ -L "$file" ]; then
        rm -f "$file"
        ui_success "Removed (link): $file"
        removed_count=$((removed_count + 1))
      elif [ -f "$file" ]; then
        rm -f "$file"
        ui_success "Removed: $file"
        removed_count=$((removed_count + 1))
      else
        skipped_count=$((skipped_count + 1))
      fi
    done < <(jq -r '.files[]?' "$manifest" 2>/dev/null)
  else
    ui_warn "Cannot parse manifest without jq."
    ui_info "Install jq for precise file removal, or manually remove ~/.claude/ contents."
  fi

  # Remove CCGM metadata files
  local meta_file full_path
  for meta_file in ".ccgm-manifest.json" ".ccgm.env"; do
    full_path="${global_dir}/${meta_file}"
    if [ -f "$full_path" ]; then
      rm -f "$full_path"
      ui_success "Removed: $full_path"
      removed_count=$((removed_count + 1))
    fi
  done

  # Also check project-level
  if [ "$has_jq" = true ]; then
    scope=$(jq -r '.scope // ""' "$manifest" 2>/dev/null || true)
    if [ "$scope" = "project" ] || [ "$scope" = "both" ]; then
      local project_meta
      project_meta="$(pwd)/.claude/.ccgm-manifest.json"
      if [ -f "$project_meta" ]; then
        rm -f "$project_meta"
        ui_success "Removed: $project_meta"
      fi
    fi
  fi

  # Clean up empty directories
  local subdir base_dir target_path
  for subdir in rules commands hooks; do
    for base_dir in "$global_dir" "$(pwd)/.claude"; do
      target_path="${base_dir}/${subdir}"
      if [ -d "$target_path" ]; then
        if [ -z "$(ls -A "$target_path" 2>/dev/null)" ]; then
          rmdir "$target_path" 2>/dev/null && ui_info "Removed empty dir: $target_path"
        fi
      fi
    done
  done

  # Step 7: Summary and offer restore
  echo ""
  ui_info "Removed $removed_count file(s), skipped $skipped_count"
  echo ""

  if [ -n "$backup_path" ]; then
    if ui_confirm "Restore from the safety backup?" "no"; then
      restore_backup "$backup_path" "$global_dir"
      ui_success "Restored from backup: $backup_path"
    fi
  fi

  local latest_backup
  latest_backup=$(get_latest_backup 2>/dev/null || true)
  if [ -n "$latest_backup" ] && [ "$latest_backup" != "${backup_path:-}" ]; then
    echo ""
    ui_info "Previous backups available in ~/.claude/backups/"
    ui_info "To restore manually: cp -r <backup_dir>/* ~/.claude/"
  fi

  # Done
  echo ""
  ui_success "CCGM uninstalled."
  ui_info "To reinstall: ./install.sh"
  echo ""
}

main "$@"
