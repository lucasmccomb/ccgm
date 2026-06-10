#!/usr/bin/env bash
# CCGM audit spine -- bundler-audit wrapper
# Scans Ruby projects for known dependency vulnerabilities.
#
# Usage: wrap-bundler-audit.sh <repo_root>
#
# Detects Ruby projects by presence of Gemfile.lock.
# Runs: bundle-audit check --format json (falls back to text on older versions)
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-bundler-audit.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip bundler-audit \
    "deps/vulnerable-dependency:no repo_root argument supplied"
  exit 0
fi

# Only run if this looks like a Ruby project with a lockfile
if [[ ! -f "$REPO_ROOT/Gemfile.lock" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip bundler-audit \
    "deps/vulnerable-dependency:no Gemfile.lock found -- bundler-audit skipped"
  exit 0
fi

if ! command -v bundle-audit > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip bundler-audit \
    "deps/vulnerable-dependency:bundle-audit not installed -- Ruby vulnerability scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-bundler-audit-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Try JSON format first (bundler-audit >= 0.9 supports --format json).
# bundle-audit exits non-zero when vulnerabilities are found; that is expected.
set +e
(
  cd "$REPO_ROOT"
  bundle-audit check --format json 2>/dev/null > "$TMPFILE" || true
)
set -e

# If JSON output is empty or not valid JSON, fall back to text format
if [[ ! -s "$TMPFILE" ]] || ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$TMPFILE" 2>/dev/null; then
  rm -f "$TMPFILE"
  TMPFILE="$(mktemp /tmp/ccgm-bundler-audit-text-XXXXXX.txt)"
  trap 'rm -f "$TMPFILE"' EXIT
  set +e
  (
    cd "$REPO_ROOT"
    bundle-audit check 2>/dev/null > "$TMPFILE" || true
  )
  set -e
fi

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE"
