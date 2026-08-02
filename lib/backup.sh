#!/usr/bin/env bash
# CCGM - Backup and restore

# --- Legacy hardcoded backup targets ---
# Pre-dynamic-derivation coverage. Kept as a fallback (modules dir missing)
# and unioned into the derived set so no prior coverage ever regresses.
_backup_legacy_paths() {
  printf '%s\n' \
    "settings.json" \
    "CLAUDE.md" \
    "rules" \
    "commands" \
    "hooks" \
    "multi-agent-system.md" \
    "github-repo-protocols.md"
}

# --- Resolve the CCGM modules directory ---
# Prefers CCGM_ROOT (set by start.sh/uninstall.sh) when it points at a real
# modules dir; falls back to deriving the repo root from this file's own
# location so backup.sh works correctly even when CCGM_ROOT is unset (e.g.
# sourced directly by a test). Prints nothing and returns 1 if neither
# resolves to an existing modules/ directory.
_backup_modules_dir() {
  if [ -n "${CCGM_ROOT:-}" ] && [ -d "${CCGM_ROOT}/modules" ]; then
    echo "${CCGM_ROOT}/modules"
    return 0
  fi

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -d "${script_dir}/../modules" ]; then
    (cd "${script_dir}/../modules" && pwd)
    return 0
  fi

  return 1
}

# --- Validate a derived top-level backup path segment ---
# Usage: _backup_safe_segment "segment"; returns 0 (safe) or 1 (reject).
# This is the guard against a manifest target that reduces to something
# dangerous once only its first path segment is kept. A target authored as
# "./skills/foo.md" reduces via "${t%%/*}" to the literal segment ".", and
# "../skills/foo.md" reduces to "..". Both would otherwise reach
# create_backup's copy loop as a real check_paths entry: "." resolves to
# target_dir itself, and since backup_dir lives *inside* target_dir, `cp -r`
# would copy the (in-progress) backup directory into itself; ".." resolves
# to target_dir's parent, a directory create_backup has no business ever
# touching. Rejects empty, ".", "..", anything containing "/" (defensive --
# %%/* should already prevent this), and anything outside a conservative
# [A-Za-z0-9._-] charset that does not start with a letter or digit (so a
# leading "." or "-" is also refused, even outside the "." / ".." cases).
#
# `local LC_ALL=C` forces byte-wise, ASCII-only matching for the charset
# check regardless of the caller's ambient locale. Without it, /bin/bash
# 3.2.57 (this repo's minimum-supported bash, and macOS's stock /bin/bash)
# combined with a UTF-8 locale (e.g. LC_ALL=en_US.UTF-8, a common ambient
# default) lets libc's fnmatch() collate accented Latin characters as
# "close enough" to the A-Z/a-z range, so a segment like "resume" is
# correctly rejected but "résumé" is not -- a discrepancy from bash 5.x,
# which rejects it under every locale. Scoping the assignment with `local`
# means the C locale applies only for the duration of this function; the
# caller's locale is restored the instant it returns.
_backup_safe_segment() {
  local LC_ALL=C
  local seg="$1"
  case "$seg" in
    ""|.|..) return 1 ;;
    */*) return 1 ;;
    [A-Za-z0-9]*) : ;;
    *) return 1 ;;
  esac
  case "$seg" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

# --- Extract (an over-approximation of) the "files" object's text (no jq) ---
# Usage: _backup_files_block "/path/to/module.json"
# Scans for the "files": { key and prints from its opening brace through the
# matching closing brace (tracking nesting depth across lines), so a later
# grep for "target" is scoped to (approximately) the files object instead of
# the whole manifest. This is a brace-depth counter, not a JSON parser, and
# it is NOT guaranteed to end exactly where the "files" object ends. Two
# known ways it can run past the true end (both verified against real
# input, neither fixed on purpose -- see below):
#   (a) a "target" key nested deeper inside a files-entry sub-object (e.g.
#       files.a.meta.target) is included, where jq's `.value.target` reads
#       only the direct child and would not see it;
#   (b) an unmatched "{" or "}" inside a JSON string value desyncs the
#       depth counter, so the scanned block can run past the real closing
#       brace and swallow a following key (e.g. a configPrompts entry).
# Both failure shapes only ADD a spurious "target" match; neither can ever
# drop a real one, because the scanner starts at the correct opening brace
# and only ever includes more text, never less. A spurious match is made
# harmless downstream by two independent layers: _backup_safe_segment
# rejects anything that is not a plausible bare path segment, and
# create_backup's `[ -e "${target_dir}/${p}" ]` check silently skips any
# segment that does not name something that actually exists on disk. So
# the practical blast radius of over-approximation is zero for any target
# dir that does not happen to contain a directory matching the spurious
# name.
#
# Writing a real string-aware JSON parser in awk to close (a) and (b)
# exactly was deliberately not done: this function exists only as the
# fallback for users without `jq` (the normal path, and the one verified
# byte-identical to jq's output across all 78 real module.json files in
# this repo), and a hand-rolled parser is disproportionate complexity --
# and a new source of bugs -- for code that decides what gets backed up.
# Bounding the failure to "may over-include a segment that is then
# filtered out or found to not exist" is the deliberate tradeoff.
_backup_files_block() {
  awk '
    BEGIN { in_files = 0; depth = 0; done = 0 }
    !in_files && !done {
      if (match($0, /"files"[ \t]*:[ \t]*\{/)) {
        in_files = 1
        rest = substr($0, RSTART + RLENGTH - 1)
        o = gsub(/\{/, "{", rest)
        c = gsub(/\}/, "}", rest)
        depth = o - c
        print rest
        if (depth <= 0) { in_files = 0; done = 1 }
        next
      }
      next
    }
    in_files {
      o = gsub(/\{/, "{", $0)
      c = gsub(/\}/, "}", $0)
      depth += (o - c)
      print $0
      if (depth <= 0) { in_files = 0; done = 1 }
    }
  ' "$1" 2>/dev/null
}

# --- Derive the set of CCGM-managed top-level backup paths ---
# Usage: managed_backup_paths
# Prints one deduped, sorted top-level path per line, derived from the first
# path segment of every module.json's files[].target (e.g.
# "skills/orrery/SKILL.md" -> "skills"), unioned with the legacy hardcoded
# list so no previously-covered path ever regresses. Falls back to the
# legacy list alone if the modules directory cannot be found -- failing
# closed to "back up less" would silently lose user data, so on any doubt
# we fail open to the known-safe legacy set instead. Every derived segment
# is additionally checked by _backup_safe_segment before it can reach the
# caller; a segment that fails the check is dropped (never included, never
# aborts the install) and reported to stderr so a malformed manifest target
# is visible without ever becoming a filesystem hazard.
managed_backup_paths() {
  local modules_dir
  if ! modules_dir="$(_backup_modules_dir)"; then
    _backup_legacy_paths
    return 0
  fi

  local have_jq=false
  if command -v jq &>/dev/null; then
    have_jq=true
  fi

  local manifest
  local -a targets=()
  local t

  for manifest in "${modules_dir}"/*/module.json; do
    [ -f "$manifest" ] || continue

    if [ "$have_jq" = true ]; then
      while IFS= read -r t; do
        [ -n "$t" ] && targets+=("$t")
      done < <(jq -r '.files // {} | to_entries[]? | .value.target // empty' "$manifest" 2>/dev/null)
    else
      # Minimal fallback: scope the extraction to the "files" object first
      # (see _backup_files_block) so a "target" key anywhere else in the
      # manifest can never be mistaken for a file-entry target.
      while IFS= read -r t; do
        [ -n "$t" ] && targets+=("$t")
      done < <(_backup_files_block "$manifest" | grep -o '"target"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/^"target"[[:space:]]*:[[:space:]]*"//; s/"$//')
    fi
  done

  # Union with the legacy list so removal/renaming of a module never
  # silently drops backup coverage for a path it used to own.
  while IFS= read -r t; do
    [ -n "$t" ] && targets+=("$t")
  done < <(_backup_legacy_paths)

  local -a tops=()
  local top
  for t in "${targets[@]}"; do
    top="${t%%/*}"
    if _backup_safe_segment "$top"; then
      tops+=("$top")
    else
      echo "WARNING: ignoring unsafe backup path segment '${top}' derived from manifest target '${t}'" >&2
    fi
  done

  printf '%s\n' "${tops[@]}" | sort -u
}

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

# --- Ensure a project-scope backups dir is gitignored ---
# Project-scope backups live inside a project's .claude/backups, which may sit
# in a git repo. Without this, `git add .` would stage backup snapshots. We drop
# a self-contained `.gitignore` (containing `*`) inside the backups dir so the
# whole dir is ignored, scoped exactly to backups and touching nothing else.
# Global-scope backups (~/.claude/backups) are irrelevant here and skipped.
# Idempotent: only writes when the marker is absent.
# Usage: ensure_backups_gitignored "/target/dir"
ensure_backups_gitignored() {
  local target_dir="$1"

  # No target means global scope (~/.claude/backups) -> nothing to do.
  if [ -z "$target_dir" ]; then
    return 0
  fi

  local backup_base
  backup_base=$(backup_base_for "$target_dir")

  # Global scope: backup base equals the home ~/.claude/backups -> skip.
  if [ "$backup_base" = "${HOME}/.claude/backups" ]; then
    return 0
  fi

  local ignore_file="${backup_base}/.gitignore"
  if [ ! -f "$ignore_file" ]; then
    mkdir -p "$backup_base"
    printf '*\n' > "$ignore_file"
  fi
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

  # Check for existing CCGM-managed files. The set of paths is derived from
  # every installed module's manifest (see managed_backup_paths), so newer
  # module targets like skills/, lib/, agents/, bin/ are covered without
  # needing a hardcoded list update per module.
  local has_files=false
  local -a check_paths=()
  local p
  while IFS= read -r p; do
    [ -n "$p" ] && check_paths+=("$p")
  done < <(managed_backup_paths)

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

  # For project-scope installs, the backups dir may live inside a git repo.
  # Drop a .gitignore so snapshots never get accidentally committed (no-op for
  # global scope). Idempotent across repeated backups.
  ensure_backups_gitignored "$target_dir"

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
