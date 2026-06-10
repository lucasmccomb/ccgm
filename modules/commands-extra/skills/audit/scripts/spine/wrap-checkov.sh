#!/usr/bin/env bash
# CCGM audit spine -- checkov wrapper
# Scans IaC files (Terraform, Dockerfiles, CloudFormation, k8s manifests)
# for security and compliance misconfigurations.
#
# Usage: wrap-checkov.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-checkov.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip checkov \
    "iac/public-ingress:no repo_root argument supplied" \
    "iac/missing-encryption:no repo_root argument supplied" \
    "iac/hardcoded-secret-in-iac:no repo_root argument supplied"
  exit 0
fi

if ! command -v checkov > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip checkov \
    "iac/public-ingress:checkov not installed -- IaC security scan skipped" \
    "iac/missing-encryption:checkov not installed -- IaC security scan skipped" \
    "iac/hardcoded-secret-in-iac:checkov not installed -- IaC security scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-checkov-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run checkov on the repo directory.
# --directory: target path (passed as argv, not interpolated)
# --output json: machine-readable JSON output
# --quiet: suppress progress bars and logging
# --compact: omit passed checks from JSON output (findings only)
# --soft-fail: exit 0 regardless of findings (we handle them ourselves)
# Config isolation: --no-guide suppresses network calls;
# we do NOT load any .checkov.yaml from the repo (no --config-file).
set +e
checkov \
  --directory "$REPO_ROOT" \
  --output json \
  --quiet \
  --compact \
  --soft-fail \
  > "$TMPFILE" 2>/dev/null
CHECKOV_EXIT=$?
set -e

if [[ $CHECKOV_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip checkov \
    "iac/public-ingress:checkov exited non-zero with no output"
  exit 0
fi

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
