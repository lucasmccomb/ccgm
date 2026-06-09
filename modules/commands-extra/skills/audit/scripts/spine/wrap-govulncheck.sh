#!/usr/bin/env bash
# CCGM audit spine -- govulncheck wrapper
# Scans Go modules for known vulnerabilities.
#
# Usage: wrap-govulncheck.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-govulncheck.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip govulncheck \
    "deps/go-vulnerability:no repo_root argument supplied"
  exit 0
fi

# Only run if this looks like a Go project
if [[ ! -f "$REPO_ROOT/go.mod" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip govulncheck \
    "deps/go-vulnerability:no go.mod found -- govulncheck skipped"
  exit 0
fi

if ! command -v govulncheck > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip govulncheck \
    "deps/go-vulnerability:govulncheck not installed -- Go vulnerability scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-govulncheck-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

set +e
(
  cd "$REPO_ROOT"
  govulncheck -json ./... 2>/dev/null > "$TMPFILE" || true
)
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE"
