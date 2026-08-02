#!/usr/bin/env bash
set -euo pipefail

# CCGM - Uninstaller
# Cleanly removes installed modules using the manifest

# --- Determine script location ---
CCGM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
source "${CCGM_ROOT}/lib/ui.sh"
source "${CCGM_ROOT}/lib/backup.sh"
source "${CCGM_ROOT}/lib/merge.sh"
source "${CCGM_ROOT}/lib/template.sh"

# --- Remove CCGM shell aliases + comment header from a single rc file ---
# Usage: remove_ccgm_alias_lines "/path/to/rc_file"
# Returns 1 (no-op) when the file is missing or has no CCGM aliases.
# Only the alias step in start.sh ever writes a "# CCGM - " line to an rc
# file, so matching the whole prefix (rather than specific trailing words)
# is safe and also cleans up comment text left by older CCGM versions.
remove_ccgm_alias_lines() {
  local rc="$1"
  if [ ! -f "$rc" ] || ! grep -qE 'alias ccgm(s)?=' "$rc" 2>/dev/null; then
    return 1
  fi
  sed_inplace '/^# CCGM - /d' "$rc"
  sed_inplace '/^alias ccgm=/d' "$rc"
  sed_inplace '/^alias ccgms=/d' "$rc"
  return 0
}

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
    # Read all scalar values in a single jq call instead of 5 separate invocations
    eval "$(jq -r '
      "installed_at=\(.installedAt // "unknown")",
      "preset=\(.preset // "custom")",
      "scope=\(.scope // "global")",
      "module_count=\(.modules | length)",
      "file_count=\(if .files then (.files | length) else 0 end)"
    ' "$manifest")"

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

    # Merge targets (e.g. settings.json) are NOT deleted - only CCGM-contributed
    # keys are un-merged out, preserving the user's own settings.
    if jq -e '.mergedFiles | length > 0' "$manifest" >/dev/null 2>&1; then
      echo ""
      ui_info "Settings to un-merge (file preserved, only CCGM keys removed):"
      while IFS= read -r mtarget; do
        [ -z "$mtarget" ] && continue
        if [ -e "$mtarget" ]; then
          echo "  - $mtarget"
        else
          echo "  - $mtarget (already missing)"
        fi
      done < <(jq -r '.mergedFiles[]?.target' "$manifest" 2>/dev/null | sort -u)
    fi
  else
    ui_info "Found manifest at: $manifest"
    ui_warn "jq not available - will remove known CCGM paths"
  fi

  # Step 4: Confirm
  echo ""
  ui_warn "This will remove all CCGM-installed files listed above."
  ui_info "Your backups (if any) will NOT be removed."
  echo ""

  # Interactive default is "no" for safety. An explicit non-interactive run
  # (CCGM_NON_INTERACTIVE=1) opts in to proceeding, matching the installer's
  # non-interactive contract.
  local proceed_default="no"
  [ "${CCGM_NON_INTERACTIVE:-}" = "1" ] && proceed_default="yes"
  if ! ui_confirm "Proceed with uninstall?" "$proceed_default"; then
    ui_info "Uninstall cancelled."
    exit 0
  fi

  # Step 5: Create a safety backup before removal
  ui_header "Safety Backup"

  local backup_path
  backup_path=$(create_backup "$global_dir")
  if [ -n "$backup_path" ]; then
    ui_success "Safety backup created: $backup_path"
    # Bound backup growth: keep the 5 most recent global-scope backups.
    clean_backups 5 "$global_dir"
  else
    ui_info "No files to back up"
  fi

  # Step 6: Remove files
  ui_header "Removing Files"

  local removed_count=0
  local skipped_count=0
  local unmerged_count=0

  if [ "$has_jq" = true ]; then
    # Collect merge-target paths so we never rm -f a file that is a merge target.
    # This also protects legacy manifests where a merge target (settings.json)
    # was incorrectly recorded in files[] - those entries are skipped here and
    # handled by the un-merge pass below instead of being deleted wholesale.
    local merge_targets=()
    local mt
    while IFS= read -r mt; do
      [ -n "$mt" ] && merge_targets+=("$mt")
    done < <(jq -r '.mergedFiles[]?.target' "$manifest" 2>/dev/null | sort -u)

    _is_merge_target() {
      local candidate="$1" t
      for t in ${merge_targets[@]+"${merge_targets[@]}"}; do
        [ "$t" = "$candidate" ] && return 0
      done
      return 1
    }

    while IFS= read -r file; do
      [ -z "$file" ] && continue

      # Never delete a merge target - it holds the user's own settings too.
      if _is_merge_target "$file"; then
        ui_info "Preserving merge target (will un-merge): $file"
        skipped_count=$((skipped_count + 1))
        continue
      fi

      # Defense-in-depth for legacy manifests written before mergedFiles[]
      # existed: settings.json is ALWAYS a merge target. If it leaked into
      # files[] with no recorded partial, we cannot un-merge precisely, so we
      # refuse to delete it - skipping preserves the user's data over a clean
      # uninstall. The empty-dir cleanup below will still tidy CCGM-only dirs.
      if [ "$(basename "$file")" = "settings.json" ]; then
        ui_warn "Preserving settings.json (no merge record; refusing to delete): $file"
        skipped_count=$((skipped_count + 1))
        continue
      fi

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

    # Un-merge CCGM-contributed keys from each merge target. The file is left in
    # place with the user's keys intact; it is removed only if nothing remains.
    while IFS=$'\t' read -r mtarget mpartial; do
      [ -z "$mtarget" ] && continue
      if unmerge_settings "$mtarget" "$mpartial"; then
        if [ -f "$mtarget" ]; then
          ui_success "Un-merged CCGM keys from: $mtarget (user settings preserved)"
        else
          ui_success "Removed (empty after un-merge): $mtarget"
        fi
        unmerged_count=$((unmerged_count + 1))
      else
        ui_warn "Could not un-merge $mtarget - left untouched"
      fi
      # Clean up the recorded sidecar partial.
      [ -f "$mpartial" ] && rm -f "$mpartial"
    done < <(jq -r '.mergedFiles[]? | [.target, .partial] | @tsv' "$manifest" 2>/dev/null)

    # Remove the now-empty sidecar store if nothing else lives there.
    local merged_dir="${global_dir}/.ccgm-merged"
    if [ -d "$merged_dir" ] && [ -z "$(ls -A "$merged_dir" 2>/dev/null)" ]; then
      rmdir "$merged_dir" 2>/dev/null && ui_info "Removed empty dir: $merged_dir"
    fi
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

  # Also check project-level (scope already read from manifest in Step 3)
  if [ "$has_jq" = true ]; then
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
  ui_info "Removed $removed_count file(s), un-merged $unmerged_count settings file(s), skipped $skipped_count"
  echo ""

  if [ -n "$backup_path" ]; then
    if ui_confirm "Restore from the safety backup?" "no"; then
      restore_backup "$backup_path" "$global_dir"
      ui_success "Restored from backup: $backup_path"
    fi
  fi

  local latest_backup
  latest_backup=$(get_latest_backup "$global_dir" 2>/dev/null || true)
  if [ -n "$latest_backup" ] && [ "$latest_backup" != "${backup_path:-}" ]; then
    echo ""
    ui_info "Previous backups available in ~/.claude/backups/"
    ui_info "To restore manually: cp -r <backup_dir>/* ~/.claude/"
  fi

  # Step 8: Remove shell aliases
  ui_header "Shell Aliases"

  local rc_files=("$HOME/.zshrc" "$HOME/.bashrc")
  local rc alias_removed=false
  for rc in "${rc_files[@]}"; do
    if remove_ccgm_alias_lines "$rc"; then
      ui_success "Removed CCGM aliases from $rc"
      alias_removed=true
    fi
  done

  if [ "$alias_removed" = false ]; then
    ui_info "No CCGM aliases found in shell configs"
  else
    ui_info "Run 'source ~/.zshrc' or open a new terminal to apply changes"
  fi

  # Done
  echo ""
  ui_success "CCGM uninstalled."
  ui_info "To reinstall: ./start.sh"
  echo ""
}

# Guard so this file can be sourced (e.g. by tests, to call
# remove_ccgm_alias_lines directly) without triggering a live uninstall run.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
