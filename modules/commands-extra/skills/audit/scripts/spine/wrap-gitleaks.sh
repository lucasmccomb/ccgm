#!/usr/bin/env bash
# CCGM audit spine -- gitleaks wrapper
# Detects hard-coded secrets in the working tree.
#
# Usage: wrap-gitleaks.sh <repo_root>
#   repo_root: absolute path to the repository root
#
# Output (stdout): JSONL -- one JSON object per line.
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-gitleaks.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:no repo_root argument supplied"
  exit 0
fi

if ! command -v gitleaks > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:gitleaks not installed -- secret scanning skipped" \
    "secrets/high-entropy-string:gitleaks not installed -- entropy scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-gitleaks-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run gitleaks -- repo root passed as positional arg (never shell-interpolated)
# --no-git: scan working tree (works in worktrees / detached heads)
# --exit-code 0: we handle non-zero ourselves
set +e
gitleaks detect \
  --source "$REPO_ROOT" \
  --report-format json \
  --report-path "$TMPFILE" \
  --no-git \
  --exit-code 0 \
  > /dev/null 2>&1
GL_EXIT=$?
set -e

if [[ $GL_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:gitleaks exited non-zero with no output"
  exit 0
fi

# Normalize output -> finding.schema.json
python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
