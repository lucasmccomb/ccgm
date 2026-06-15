#!/usr/bin/env bash
# CCGM audit spine -- semgrep wrapper
# Runs semgrep with explicit --config (never --config auto) for config isolation.
#
# Usage: wrap-semgrep.sh <repo_root> [semgrep_config]
#   repo_root:      absolute path to the repository root
#   semgrep_config: semgrep ruleset (default: p/default)
#
# Config isolation: --config is always explicit. Never passes --config auto
# against the audited repo (which would execute repo-local semgrep rules).
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SEMGREP_CONFIG="${2:-p/default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-semgrep.py"

# shellcheck source=exclude.sh
. "$SCRIPT_DIR/exclude.sh"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip semgrep \
    "sast/code-injection:no repo_root argument supplied"
  exit 0
fi

if ! command -v semgrep > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip semgrep \
    "sast/code-injection:semgrep not installed -- SAST scan skipped" \
    "sast/insecure-deserialization:semgrep not installed -- SAST scan skipped" \
    "sast/sql-injection:semgrep not installed -- SAST scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-semgrep-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Config isolation: explicit --config, never --config auto
# --no-autofix: read-only scan
# --metrics off: no telemetry
# --quiet: suppress progress output
# --exclude: vendored/generated dirs and stale worktrees (#1).  semgrep already
#   honors .gitignore + a default .semgrepignore, but an un-gitignored stale
#   .claude/worktrees tree would still be scanned; this makes exclusion explicit.
# repo_root passed as positional arg
ccgm_semgrep_exclude_args
set +e
semgrep scan \
  --config "$SEMGREP_CONFIG" \
  --json \
  --output "$TMPFILE" \
  --no-autofix \
  --metrics off \
  --quiet \
  "${CCGM_FLAGS[@]}" \
  "$REPO_ROOT" \
  > /dev/null 2>&1
SEMGREP_EXIT=$?
set -e

if [[ $SEMGREP_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip semgrep \
    "sast/code-injection:semgrep exited non-zero with no output"
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
