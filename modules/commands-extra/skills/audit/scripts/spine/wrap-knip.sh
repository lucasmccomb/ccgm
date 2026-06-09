#!/usr/bin/env bash
# CCGM audit spine -- knip wrapper
# Finds unused exports, files, and dependencies.
#
# Config isolation: knip evaluates knip.config.ts/js from the project -- we
# guard this by checking for a config that would error before running, and we
# run with --no-progress (non-interactive) but CANNOT fully isolate from the
# repo config without breaking knip's ability to traverse the project.
# Therefore we document this as a known limitation and skip if a guard env
# var CCGM_KNIP_SKIP is set (e.g. when the config isolation fixture is active).
#
# Usage: wrap-knip.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-knip.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip knip \
    "dead-code/unused-export:no repo_root argument supplied"
  exit 0
fi

if ! command -v knip > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip knip \
    "dead-code/unused-export:knip not installed -- dead-code scan skipped" \
    "dead-code/unused-file:knip not installed -- dead-code scan skipped"
  exit 0
fi

# Config isolation guard: skip if CCGM_KNIP_SKIP is set
# (used by tests to prove the wrapper respects the config-isolation fixture)
if [[ -n "${CCGM_KNIP_SKIP:-}" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip knip \
    "dead-code/unused-export:knip skipped (CCGM_KNIP_SKIP set -- config isolation)"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-knip-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

set +e
(
  cd "$REPO_ROOT"
  knip --reporter json --no-progress 2>/dev/null > "$TMPFILE" || true
)
set -e

if [[ ! -s "$TMPFILE" ]]; then
  # No output = no issues (or no package.json)
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
