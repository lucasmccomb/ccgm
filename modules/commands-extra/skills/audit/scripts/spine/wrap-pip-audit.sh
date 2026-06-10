#!/usr/bin/env bash
# CCGM audit spine -- pip-audit wrapper
# Scans Python projects for known dependency vulnerabilities.
#
# Usage: wrap-pip-audit.sh <repo_root>
#
# Detects Python projects by presence of requirements.txt or pyproject.toml.
# Runs: pip-audit --format json
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-pip-audit.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip pip-audit \
    "deps/vulnerable-dependency:no repo_root argument supplied"
  exit 0
fi

# Only run if this looks like a Python project
if [[ ! -f "$REPO_ROOT/requirements.txt" && \
      ! -f "$REPO_ROOT/pyproject.toml" && \
      ! -f "$REPO_ROOT/setup.py" && \
      ! -f "$REPO_ROOT/Pipfile" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip pip-audit \
    "deps/vulnerable-dependency:no Python manifest found -- pip-audit skipped"
  exit 0
fi

if ! command -v pip-audit > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip pip-audit \
    "deps/vulnerable-dependency:pip-audit not installed -- Python vulnerability scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-pip-audit-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run pip-audit -- repo path is passed as argv via cd into subshell;
# never interpolated into the audit command string itself.
set +e
(
  cd "$REPO_ROOT"
  pip-audit --format json 2>/dev/null > "$TMPFILE" || true
)
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE"
