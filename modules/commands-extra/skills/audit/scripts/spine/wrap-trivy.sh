#!/usr/bin/env bash
# CCGM audit spine -- trivy wrapper
# Scans filesystem for vulnerabilities (OS packages, language deps, IaC misconfig).
#
# Usage: wrap-trivy.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-trivy.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip trivy \
    "deps/container-vulnerability:no repo_root argument supplied"
  exit 0
fi

if ! command -v trivy > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip trivy \
    "deps/container-vulnerability:trivy not installed -- container/IaC scan skipped" \
    "iac/misconfig:trivy not installed -- IaC misconfiguration scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-trivy-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# trivy fs: scan the filesystem
# --format json: machine-readable output
# --exit-code 0: always exit 0 (we handle findings ourselves)
# --quiet: suppress progress bars
# repo_root passed as positional arg (never interpolated into string)
set +e
trivy fs \
  --format json \
  --output "$TMPFILE" \
  --exit-code 0 \
  --quiet \
  --scanners vuln,misconfig,secret \
  "$REPO_ROOT" \
  > /dev/null 2>&1
TRIVY_EXIT=$?
set -e

if [[ $TRIVY_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip trivy \
    "deps/container-vulnerability:trivy exited non-zero with no output"
  exit 0
fi

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
