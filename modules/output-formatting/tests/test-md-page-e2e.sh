#!/usr/bin/env bash
set -euo pipefail

# Browser test for ccgm-md-page (headless Chromium, no focus, no windows).
# Driver: orrery's lockfile-pinned playwright, reached through likec4.sh.
#
# Toolchain or browser missing:
#   CCGM_E2E_REQUIRED=1 -> exit 1 with a message
#   otherwise           -> print a skip note and exit 0

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "$TESTS_DIR/.." && pwd)"
LIKEC4="$MODULE_DIR/../orrery/skills/orrery/scripts/likec4.sh"
REQUIRED="${CCGM_E2E_REQUIRED:-0}"

absent() {
  if [ "$REQUIRED" = "1" ]; then
    echo "FAIL: $1 (CCGM_E2E_REQUIRED=1 treats this as a failure)" >&2
    exit 1
  fi
  echo "skip: $1 - browser test not run (set CCGM_E2E_REQUIRED=1 to fail instead)"
  exit 0
}

[ -f "$LIKEC4" ] || absent "orrery toolchain script not found at $LIKEC4"

if ! TOOLCHAIN_DIR="$(bash "$LIKEC4" --print-toolchain-dir 2>/dev/null)" || [ -z "$TOOLCHAIN_DIR" ] \
  || [ ! -d "$TOOLCHAIN_DIR/node_modules/playwright" ]; then
  absent "orrery playwright toolchain is not installed"
fi

set +e
NODE_PATH="$TOOLCHAIN_DIR/node_modules" node -e '
const fs = require("fs");
const pw = require("playwright");
process.exit(fs.existsSync(pw.chromium.executablePath()) ? 0 : 3);
'
PROBE=$?
set -e
[ "$PROBE" = "0" ] || absent "playwright chromium is not installed (bash $LIKEC4 playwright install chromium)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/md-page-e2e.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

for name in basic xss mermaid; do
  cp "$TESTS_DIR/fixtures/$name.md" "$WORK/$name.md"
  python3 "$MODULE_DIR/bin/ccgm-md-page" "$WORK/$name.md" -o "$WORK/$name.html" >/dev/null
done

NODE_PATH="$TOOLCHAIN_DIR/node_modules" node "$TESTS_DIR/md_page_e2e.js" \
  "$WORK/basic.html" "$WORK/xss.html" "$WORK/mermaid.html"

echo "test-md-page-e2e.sh: PASS"
