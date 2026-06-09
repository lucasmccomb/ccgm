#!/usr/bin/env bash
# CCGM audit spine -- actionlint + zizmor wrapper
# Lints GitHub Actions workflow files.
# Runs actionlint first; runs zizmor if present for deeper security analysis.
#
# Usage: wrap-actionlint.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-actionlint.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip actionlint \
    "ci/workflow-issue:no repo_root argument supplied"
  exit 0
fi

# Only run if workflow files exist
WORKFLOWS_DIR="$REPO_ROOT/.github/workflows"
if [[ ! -d "$WORKFLOWS_DIR" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip actionlint \
    "ci/workflow-issue:no .github/workflows directory -- actionlint skipped"
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
  python3 "$NORMALIZE_PY" --emit-skip actionlint \
    "ci/workflow-issue:no workflow YAML files found -- actionlint skipped"
  exit 0
fi

if ! command -v actionlint > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip actionlint \
    "ci/workflow-issue:actionlint not installed -- GitHub Actions lint skipped" \
    "ci/workflow-injection:actionlint not installed -- expression injection check skipped"
  exit 0
fi

TMPFILE_AL="$(mktemp /tmp/ccgm-actionlint-XXXXXX.json)"
TMPFILE_ZI="$(mktemp /tmp/ccgm-zizmor-XXXXXX.json)"
trap 'rm -f "$TMPFILE_AL" "$TMPFILE_ZI"' EXIT

# actionlint: -format json, workflow files as argv array
set +e
actionlint -format '{{json .}}' "${WORKFLOW_FILES[@]}" > "$TMPFILE_AL" 2>/dev/null || true
set -e

# zizmor (optional): deeper security analysis
if command -v zizmor > /dev/null 2>&1; then
  set +e
  zizmor --format json "${WORKFLOW_FILES[@]}" > "$TMPFILE_ZI" 2>/dev/null || true
  set -e
fi

python3 "$PARSE_PY" "$TMPFILE_AL" "$TMPFILE_ZI" "$REPO_ROOT"
