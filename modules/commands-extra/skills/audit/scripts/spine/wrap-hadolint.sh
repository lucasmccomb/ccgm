#!/usr/bin/env bash
# CCGM audit spine -- hadolint wrapper
# Lints Dockerfiles for best practices and security issues.
#
# Usage: wrap-hadolint.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-hadolint.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip hadolint \
    "iac/dockerfile-issue:no repo_root argument supplied"
  exit 0
fi

if ! command -v hadolint > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip hadolint \
    "iac/dockerfile-issue:hadolint not installed -- Dockerfile lint skipped"
  exit 0
fi

# Find all Dockerfiles -- use find with -print0 for injection safety
TMPFILES_LIST="$(mktemp /tmp/ccgm-hadolint-files-XXXXXX.txt)"
TMPFILE="$(mktemp /tmp/ccgm-hadolint-XXXXXX.json)"
trap 'rm -f "$TMPFILES_LIST" "$TMPFILE"' EXIT

# Collect Dockerfiles via find -- NUL-delimited read loop.
# Bash-3.2-portable: mapfile -d '' requires bash 4+; use while-read instead.
DOCKERFILES=()
while IFS= read -r -d '' f; do
  DOCKERFILES+=("$f")
done < <(
  find "$REPO_ROOT" \
    -type f \
    \( -name "Dockerfile" -o -name "Dockerfile.*" \) \
    -not -path "*/.git/*" \
    -print0
)

if [[ ${#DOCKERFILES[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip hadolint \
    "iac/dockerfile-issue:no Dockerfiles found -- hadolint skipped"
  exit 0
fi

# Run hadolint on each Dockerfile -- each path is a separate array element
# (never interpolated into a shell string)
set +e
hadolint --format json "${DOCKERFILES[@]}" > "$TMPFILE" 2>/dev/null || true
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
