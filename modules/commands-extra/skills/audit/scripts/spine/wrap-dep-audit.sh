#!/usr/bin/env bash
# CCGM audit spine -- dependency audit wrapper (npm/pnpm/yarn/bun)
# Detects vulnerable dependencies.
#
# Usage: wrap-dep-audit.sh <repo_root>
#
# Detects which package manager is in use from lockfile presence:
#   pnpm-lock.yaml -> pnpm
#   yarn.lock      -> yarn
#   bun.lockb      -> bun
#   package-lock.json -> npm
#   package.json (no lockfile) -> npm (best effort)
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-dep-audit.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip dep-audit \
    "deps/vulnerable-dependency:no repo_root argument supplied"
  exit 0
fi

# Detect package manager from lockfile
PM=""
if [[ -f "$REPO_ROOT/pnpm-lock.yaml" ]]; then
  PM="pnpm"
elif [[ -f "$REPO_ROOT/yarn.lock" ]]; then
  PM="yarn"
elif [[ -f "$REPO_ROOT/bun.lockb" ]]; then
  PM="bun"
elif [[ -f "$REPO_ROOT/package-lock.json" || -f "$REPO_ROOT/package.json" ]]; then
  PM="npm"
fi

if [[ -z "$PM" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip dep-audit \
    "deps/vulnerable-dependency:no package.json found -- dependency audit skipped"
  exit 0
fi

if ! command -v "$PM" > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip dep-audit \
    "deps/vulnerable-dependency:${PM} not installed -- dependency audit skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-dep-audit-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run audit -- all args are static; repo_root is passed as the working directory
# via a subshell so we never interpolate it into the audit command string itself.
set +e
(
  cd "$REPO_ROOT"
  case "$PM" in
    npm)
      npm audit --json 2>/dev/null > "$TMPFILE"
      ;;
    pnpm)
      pnpm audit --json 2>/dev/null > "$TMPFILE"
      ;;
    yarn)
      # yarn audit exits non-zero when vulns found; that is expected
      yarn audit --json 2>/dev/null > "$TMPFILE" || true
      ;;
    bun)
      bun audit 2>/dev/null > "$TMPFILE" || true
      ;;
  esac
)
AUDIT_EXIT=$?
set -e

if [[ $AUDIT_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip dep-audit \
    "deps/vulnerable-dependency:${PM} audit exited non-zero with no output"
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$PM"
