#!/usr/bin/env bash
# CCGM audit spine -- eslint wrapper
# Config isolation: --no-config-lookup prevents loading repo .eslintrc/.eslintrc.js
# and uses only the flags we pass explicitly. This is the safety-critical flag.
#
# Usage: wrap-eslint.sh <repo_root> [glob_pattern]
#   glob_pattern: optional, defaults to "**/*.{js,jsx,ts,tsx,mjs,cjs}"
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
GLOB_PATTERN="${2:-**/*.{js,jsx,ts,tsx,mjs,cjs}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-eslint.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip eslint \
    "lint/eslint-error:no repo_root argument supplied"
  exit 0
fi

if ! command -v eslint > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip eslint \
    "lint/eslint-error:eslint not installed -- lint scan skipped" \
    "lint/eslint-warning:eslint not installed -- lint scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-eslint-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Config isolation: --no-config-lookup is the critical flag.
# We pass --rule '{}' so no rules run by default -- this is intentional:
# the audit spine is for security/quality rules from known packs, not
# running the repo's own lint config against itself.
# repo_root is passed via cd in subshell, glob is a static pattern.
set +e
(
  cd "$REPO_ROOT"
  eslint \
    --no-config-lookup \
    --rule '{"no-eval":["error"],"no-implied-eval":["error"],"no-new-func":["error"]}' \
    --format json \
    --output-file "$TMPFILE" \
    "$GLOB_PATTERN" \
    > /dev/null 2>&1
)
ESLINT_EXIT=$?
set -e

# eslint exits 1 when errors/warnings found (expected), 2 on config error
if [[ $ESLINT_EXIT -eq 2 || (! -s "$TMPFILE") ]]; then
  python3 "$NORMALIZE_PY" --emit-skip eslint \
    "lint/eslint-error:eslint configuration error or no output"
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
