#!/usr/bin/env bash
# CCGM - Repair stale symlinks left behind by module renames/removals.
#
# When modules are renamed (e.g. session-logging -> startup-dashboard) or files
# are moved within a module, any existing symlinks under ~/.claude/ that point
# at the old source path become dangling. The installer would normally recreate
# the new link at a new target, but the stale link at the old target remains
# and breaks commands like /startup ("Unknown command").
#
# Strategy: dangling symlink pruning.
#   - Walk a fixed set of CCGM-managed subdirectories under the target dir.
#   - For every symlink whose target does not exist (`! -e`), remove it.
#   - Never remove regular files or directories.
#
# Rationale: this is independent of manifest format, strictly idempotent, and
# only touches links the installer itself created (the scanned subdirectories
# are CCGM-owned).

# Requires: lib/ui.sh sourced (ui_info, ui_success)

# --- Directories CCGM installs symlinks into ---
# Keep this list in sync with module.json `target` prefixes.
_CCGM_LINK_DIRS=(
  "commands"
  "rules"
  "hooks"
  "lib"
  "scripts"
  "agents"
  "skills"
)

# --- Remove dangling symlinks under a target directory ---
# Usage: repair_dangling_symlinks "/Users/foo/.claude"
# Prints removed links via ui_info; prints a summary via ui_success.
# Returns 0 always (no dangling links is a success, not a failure).
repair_dangling_symlinks() {
  local target_dir="$1"
  local removed_count=0

  if [ -z "$target_dir" ] || [ ! -d "$target_dir" ]; then
    return 0
  fi

  local subdir full_subdir link
  for subdir in "${_CCGM_LINK_DIRS[@]}"; do
    full_subdir="${target_dir}/${subdir}"
    [ -d "$full_subdir" ] || continue

    # `find -type l` matches symlinks regardless of target state.
    # We filter to ones whose target does not exist (-e follows the link).
    while IFS= read -r link; do
      [ -z "$link" ] && continue
      # Symlink exists (-L) but its target doesn't (! -e) -> dangling.
      if [ -L "$link" ] && [ ! -e "$link" ]; then
        if rm -f "$link"; then
          ui_info "  Removed stale symlink: ${link#$HOME/}"
          removed_count=$((removed_count + 1))
        fi
      fi
    done < <(find "$full_subdir" -type l 2>/dev/null)
  done

  if [ $removed_count -gt 0 ]; then
    ui_success "Repaired $removed_count stale symlink(s) in ${target_dir#$HOME/}"
  fi

  return 0
}
