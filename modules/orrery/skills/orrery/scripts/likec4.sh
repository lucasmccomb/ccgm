#!/usr/bin/env bash
set -euo pipefail

# orrery toolchain entry point (plan section 3.7).
#
# Resolves the lockfile-pinned LikeC4 toolchain into a cache directory keyed by
# the sha256 of the checked-in package-lock.json, installs it with `npm ci`
# (never npx - npx pins only the entry point, not transitives), prunes every
# stale toolchain-* cache dir so exactly one remains, then execs the LOCAL bin.
#
# Usage:
#   likec4.sh <likec4 args...>              # e.g. validate --json <dir>, build ...
#   likec4.sh playwright <playwright args>  # passthrough to the pinned playwright CLI
#   likec4.sh --print-toolchain-dir         # resolve (installing if needed), print dir
#
# Node floor: likec4@1.59.2 declares engines node >=22.22.3. A below-floor node
# WARNS and never blocks (measured working on 22.17.0 - plan section 4).
#
# Portable: macOS bash 3.2 + BSD tools. Hash helper: shasum -a 256, falling
# back to sha256sum (absent on macOS), falling back to python3 hashlib.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLCHAIN_SRC="$SCRIPT_DIR/toolchain"
LOCKFILE="$TOOLCHAIN_SRC/package-lock.json"
CACHE_ROOT="${ORRERY_CACHE_ROOT:-$HOME/.cache/orrery}"
NODE_FLOOR="22.22.3"

if [ ! -f "$LOCKFILE" ]; then
  echo "likec4.sh: missing $LOCKFILE" >&2
  exit 1
fi

hash_file() {
  # Portable sha256 of a file. sha256sum does not exist on macOS.
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

warn_node_floor() {
  # WARN (never block) when node is below the likec4 engines floor.
  local ver major minor patch fmajor fminor fpatch
  ver="$(node --version 2>/dev/null | sed 's/^v//')" || return 0
  [ -n "$ver" ] || return 0
  major="$(printf '%s' "$ver" | cut -d. -f1)"
  minor="$(printf '%s' "$ver" | cut -d. -f2)"
  patch="$(printf '%s' "$ver" | cut -d. -f3 | sed 's/[^0-9].*$//')"
  fmajor="$(printf '%s' "$NODE_FLOOR" | cut -d. -f1)"
  fminor="$(printf '%s' "$NODE_FLOOR" | cut -d. -f2)"
  fpatch="$(printf '%s' "$NODE_FLOOR" | cut -d. -f3)"
  case "$major$minor$patch" in *[!0-9]*) return 0 ;; esac
  below=0
  if [ "$major" -lt "$fmajor" ]; then below=1
  elif [ "$major" -eq "$fmajor" ]; then
    if [ "$minor" -lt "$fminor" ]; then below=1
    elif [ "$minor" -eq "$fminor" ] && [ "$patch" -lt "$fpatch" ]; then below=1
    fi
  fi
  if [ "$below" -eq 1 ]; then
    echo "likec4.sh: WARNING: node v$ver is below likec4@1.59.2's declared engines floor ($NODE_FLOOR)." >&2
    echo "likec4.sh: WARNING: proceeding anyway (validate/build measured working on 22.17.0)." >&2
    echo "likec4.sh: WARNING: remediation: nvm install 22 && nvm use 22   (or: brew install node@22)" >&2
  fi
}

if ! command -v node >/dev/null 2>&1; then
  echo "likec4.sh: node is required but not on PATH (install Node >= $NODE_FLOOR)" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "likec4.sh: npm is required but not on PATH" >&2
  exit 1
fi
warn_node_floor

LOCK_HASH="$(hash_file "$LOCKFILE")"
TOOLCHAIN_DIR="$CACHE_ROOT/toolchain-$LOCK_HASH"

if [ ! -x "$TOOLCHAIN_DIR/node_modules/.bin/likec4" ]; then
  mkdir -p "$TOOLCHAIN_DIR"
  cp "$TOOLCHAIN_SRC/package.json" "$TOOLCHAIN_SRC/package-lock.json" "$TOOLCHAIN_DIR/"
  echo "likec4.sh: installing pinned toolchain into $TOOLCHAIN_DIR (npm ci)" >&2
  if ! (cd "$TOOLCHAIN_DIR" && npm ci --no-audit --no-fund >&2); then
    # Retry once: npm ci cold-start flakiness (plan section 11).
    echo "likec4.sh: npm ci failed; retrying once" >&2
    rm -rf "$TOOLCHAIN_DIR/node_modules"
    (cd "$TOOLCHAIN_DIR" && npm ci --no-audit --no-fund >&2)
  fi
fi

# Prune every stale toolchain-* cache dir, keeping exactly the current one.
# Unpruned, each toolchain bump orphans ~111 MB permanently (plan section 3.7).
for stale in "$CACHE_ROOT"/toolchain-*; do
  [ -d "$stale" ] || continue
  [ "$stale" = "$TOOLCHAIN_DIR" ] && continue
  rm -rf "$stale"
done

if [ "${1:-}" = "--print-toolchain-dir" ]; then
  printf '%s\n' "$TOOLCHAIN_DIR"
  exit 0
fi

if [ "${1:-}" = "playwright" ]; then
  shift
  exec "$TOOLCHAIN_DIR/node_modules/.bin/playwright" "$@"
fi

exec "$TOOLCHAIN_DIR/node_modules/.bin/likec4" "$@"
