#!/usr/bin/env bash
# CCGM - Backup and restore

# --- Create timestamped backup ---
# Usage: create_backup "/target/dir"
# Backs up existing config files to ~/.claude/backups/ccgm-YYYYMMDD-HHMMSS/
# Returns the backup directory path on stdout
create_backup() {
  local target_dir="$1"
  local backup_base="${HOME}/.claude/backups"
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

  # Copy everything from backup to target
  cp -r "${backup_dir}/"* "$target_dir/" 2>/dev/null
  # Also restore hidden files
  cp -r "${backup_dir}/".[!.]* "$target_dir/" 2>/dev/null

  return 0
}

# --- List available backups ---
# Prints each backup dir, newest first
list_backups() {
  local backup_base="${HOME}/.claude/backups"
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
get_latest_backup() {
  local backup_base="${HOME}/.claude/backups"
  if [ ! -d "$backup_base" ]; then
    return 1
  fi

  ls -1d "${backup_base}"/ccgm-* 2>/dev/null | sort -r | head -1
}

# --- Clean old backups (keep N most recent) ---
clean_backups() {
  local keep="${1:-5}"
  local backup_base="${HOME}/.claude/backups"

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
