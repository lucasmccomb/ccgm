#!/usr/bin/env bash
# CCGM audit spine -- zizmor wrapper
# Audits GitHub Actions workflow files for security issues:
#   - pull_request_target misuse (dangerous triggers)
#   - excessive GITHUB_TOKEN permissions
#   - expression injection via ${{ github.event.* }}
#
# Usage: wrap-zizmor.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-zizmor.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip zizmor \
    "cicd/dangerous-trigger:no repo_root argument supplied" \
    "cicd/excessive-permissions:no repo_root argument supplied" \
    "cicd/script-injection:no repo_root argument supplied"
  exit 0
fi

# Only run if workflow files exist
WORKFLOWS_DIR="$REPO_ROOT/.github/workflows"
if [[ ! -d "$WORKFLOWS_DIR" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip zizmor \
    "cicd/dangerous-trigger:no .github/workflows directory -- zizmor skipped" \
    "cicd/excessive-permissions:no .github/workflows directory -- zizmor skipped" \
    "cicd/script-injection:no .github/workflows directory -- zizmor skipped"
  exit 0
fi

# Collect workflow files safely using a NUL-delimited read loop.
# Bash-3.2-portable: mapfile -d '' requires bash 4+; use while-read instead.
WORKFLOW_FILES=()
while IFS= read -r -d '' f; do
  WORKFLOW_FILES+=("$f")
done < <(
  find "$WORKFLOWS_DIR" \
    -maxdepth 1 \
    -type f \
    \( -name "*.yml" -o -name "*.yaml" \) \
    -print0
)

if [[ ${#WORKFLOW_FILES[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip zizmor \
    "cicd/dangerous-trigger:no workflow YAML files found -- zizmor skipped" \
    "cicd/excessive-permissions:no workflow YAML files found -- zizmor skipped" \
    "cicd/script-injection:no workflow YAML files found -- zizmor skipped"
  exit 0
fi

if ! command -v zizmor > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip zizmor \
    "cicd/dangerous-trigger:zizmor not installed -- dangerous trigger check skipped" \
    "cicd/excessive-permissions:zizmor not installed -- permissions check skipped" \
    "cicd/script-injection:zizmor not installed -- script injection check skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-zizmor-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# zizmor --format sarif: emits SARIF JSON
# Pass workflow files as argv (never interpolated into a shell string).
# zizmor exits non-zero when findings exist; always exit 0 in the wrapper.
set +e
zizmor --format sarif "${WORKFLOW_FILES[@]}" > "$TMPFILE" 2>/dev/null
set -e

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
