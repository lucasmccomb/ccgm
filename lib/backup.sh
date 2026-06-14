#!/usr/bin/env bash
# CCGM - Backup and restore

# --- Resolve the backup base for a given install target ---
# Backups are scoped to the install target so a project-scope (.claude/) install
# never writes to or restores from the global ~/.claude/backups (and vice-versa).
# The backups dir sits alongside the target (<target>/backups), so a project
# target's backups live under that project's .claude/backups.
# Usage: backup_base_for "/target/dir"
backup_base_for() {
  local target_dir="$1"
  if [ -z "$target_dir" ]; then
    echo "${HOME}/.claude/backups"
    return 0
  fi
  echo "${target_dir%/}/backups"
}

# --- Create timestamped backup ---
# Usage: create_backup "/target/dir"
# Backs up existing config files to <target>/backups/ccgm-YYYYMMDD-HHMMSS/
# Returns the backup directory path on stdout
create_backup() {
  local target_dir="$1"
  local backup_base
  backup_base=$(backup_base_for "$target_dir")
  local timestamp
  timestamp=$(date '+%Y%m%d-%H%M%S')
  local backup_dir="${backup_base}/ccgm-${timestamp}"

  # Check if there's anything to back up
  if [ ! -d "$target_dir" ]; then
    return 0
  fi

  # Check for existing CCGM-managed files
  local has_files=false
  local check_paths=(
    "settings.json"
    "CLAUDE.md"
    "rules"
    "commands"
    "hooks"
    "multi-agent-system.md"
    "github-repo-protocols.md"
  )

  for p in "${check_paths[@]}"; do
    if [ -e "${target_dir}/${p}" ]; then
      has_files=true
      break
    fi
  done

  if [ "$has_files" = false ]; then
    return 0
  fi

  # Create backup directory
  mkdir -p "$backup_dir"

  # Copy existing files
  for p in "${check_paths[@]}"; do
    local src="${target_dir}/${p}"
    if [ -e "$src" ]; then
      local dest="${backup_dir}/${p}"
      local dest_dir
      dest_dir=$(dirname "$dest")
      mkdir -p "$dest_dir"
      if [ -d "$src" ]; then
        cp -r "$src" "$dest"
      else
        cp "$src" "$dest"
      fi
    fi
  done

  # Also back up .ccgm files
  for f in "${target_dir}"/.ccgm*; do
    if [ -f "$f" ]; then
      cp "$f" "$backup_dir/"
    fi
  done

  echo "$backup_dir"
}

# --- Restore from backup ---
# Usage: restore_backup "/path/to/backup" "/target/dir"
restore_backup() {
  local backup_dir="$1"
  local target_dir="$2"

  if [ ! -d "$backup_dir" ]; then
    echo "ERROR: Backup directory not found: $backup_dir" >&2
    return 1
  fi

  if [ ! -d "$target_dir" ]; then
    mkdir -p "$target_dir"
  fi

  # Copy everything from backup to target. The globs may not match (empty
  # backup, or no hidden files); tolerate that without aborting under `set -e`.
  cp -r "${backup_dir}/"* "$target_dir/" 2>/dev/null || true
  # Also restore hidden files
  cp -r "${backup_dir}/".[!.]* "$target_dir/" 2>/dev/null || true

  return 0
}

# --- List available backups ---
# Usage: list_backups ["/target/dir"]
# Prints each backup dir for the target's scope, newest first.
list_backups() {
  local backup_base
  backup_base=$(backup_base_for "${1:-}")
  if [ ! -d "$backup_base" ]; then
    return 0
  fi

  local backup
  for backup in $(ls -1d "${backup_base}"/ccgm-* 2>/dev/null | sort -r); do
    if [ -d "$backup" ]; then
      local name
      name=$(basename "$backup")
      local file_count
      file_count=$(find "$backup" -type f | wc -l | tr -d ' ')
      echo "$name ($file_count files)"
    fi
  done
}

# --- Get most recent backup ---
# Usage: get_latest_backup ["/target/dir"]
get_latest_backup() {
  local backup_base
  backup_base=$(backup_base_for "${1:-}")
  if [ ! -d "$backup_base" ]; then
    return 1
  fi

  ls -1d "${backup_base}"/ccgm-* 2>/dev/null | sort -r | head -1
}

# --- Clean old backups (keep N most recent) ---
# Usage: clean_backups [keep] ["/target/dir"]
clean_backups() {
  local keep="${1:-5}"
  local backup_base
  backup_base=$(backup_base_for "${2:-}")

  if [ ! -d "$backup_base" ]; then
    return 0
  fi

  local count=0
  for backup in $(ls -1d "${backup_base}"/ccgm-* 2>/dev/null | sort -r); do
    count=$((count + 1))
    if [ $count -gt "$keep" ]; then
      rm -rf "$backup"
    fi
  done
}
