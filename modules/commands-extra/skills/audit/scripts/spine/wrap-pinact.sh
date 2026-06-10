#!/usr/bin/env bash
# CCGM audit spine -- pinact wrapper
# Checks GitHub Actions workflows for unpinned third-party actions
# (actions referenced by mutable tag or branch instead of a full commit SHA).
#
# Usage: wrap-pinact.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-pinact.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip pinact \
    "cicd/unpinned-action:no repo_root argument supplied"
  exit 0
fi

# Only run if workflow files exist
WORKFLOWS_DIR="$REPO_ROOT/.github/workflows"
if [[ ! -d "$WORKFLOWS_DIR" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip pinact \
    "cicd/unpinned-action:no .github/workflows directory -- pinact skipped"
  exit 0
fi

# Collect workflow files safely
mapfile -d '' WORKFLOW_FILES < <(
  find "$WORKFLOWS_DIR" \
    -maxdepth 1 \
    -type f \
    \( -name "*.yml" -o -name "*.yaml" \) \
    -print0
)

if [[ ${#WORKFLOW_FILES[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip pinact \
    "cicd/unpinned-action:no workflow YAML files found -- pinact skipped"
  exit 0
fi

if ! command -v pinact > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip pinact \
    "cicd/unpinned-action:pinact not installed -- action-pinning check skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-pinact-XXXXXX.txt)"
trap 'rm -f "$TMPFILE"' EXIT

# pinact run --check: exits non-zero if unpinned actions are found.
# Output is a diff-like text showing which actions need pinning.
# Pass workflow files as argv (never interpolated into a shell string).
set +e
pinact run --check "${WORKFLOW_FILES[@]}" > "$TMPFILE" 2>&1
set -e

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
