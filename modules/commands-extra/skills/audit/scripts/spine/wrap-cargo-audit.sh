#!/usr/bin/env bash
# CCGM audit spine -- cargo-audit wrapper
# Scans Rust projects for known dependency vulnerabilities.
#
# Usage: wrap-cargo-audit.sh <repo_root>
#
# Detects Rust projects by presence of Cargo.toml.
# Runs: cargo audit --json
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-cargo-audit.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip cargo-audit \
    "deps/vulnerable-dependency:no repo_root argument supplied"
  exit 0
fi

# Only run if this looks like a Rust project
if [[ ! -f "$REPO_ROOT/Cargo.toml" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip cargo-audit \
    "deps/vulnerable-dependency:no Cargo.toml found -- cargo-audit skipped"
  exit 0
fi

if ! command -v cargo-audit > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip cargo-audit \
    "deps/vulnerable-dependency:cargo-audit not installed -- Rust vulnerability scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-cargo-audit-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run cargo audit -- repo path is passed via cd into subshell;
# never interpolated into the audit command string itself.
# cargo audit exits non-zero when vulnerabilities are found; that is expected.
set +e
(
  cd "$REPO_ROOT"
  cargo audit --json 2>/dev/null > "$TMPFILE" || true
)
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE"
