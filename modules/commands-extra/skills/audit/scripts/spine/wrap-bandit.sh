#!/usr/bin/env bash
# CCGM audit spine -- bandit wrapper
# Scans Python source for common security issues.
#
# Usage: wrap-bandit.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-bandit.py"

# shellcheck source=exclude.sh
. "$SCRIPT_DIR/exclude.sh"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip bandit \
    "sast/python-security:no repo_root argument supplied"
  exit 0
fi

# Only run if this looks like a Python project
if [[ ! -f "$REPO_ROOT/requirements.txt" && ! -f "$REPO_ROOT/pyproject.toml" && ! -f "$REPO_ROOT/setup.py" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip bandit \
    "sast/python-security:no Python project files found -- bandit skipped"
  exit 0
fi

if ! command -v bandit > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip bandit \
    "sast/python-security:bandit not installed -- Python SAST scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-bandit-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# -r: recursive  -f json: JSON output
# -q: quiet (suppress progress)
# -x: exclude vendored/generated dirs so a recursive scan does not descend into
#     node_modules, .venv, stale worktrees, etc. (field report #1).
# repo_root passed as positional arg
ccgm_bandit_exclude_csv
set +e
bandit -r "$REPO_ROOT" -x "$CCGM_BANDIT_EXCLUDE" -f json -q -o "$TMPFILE" > /dev/null 2>&1 || true
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
