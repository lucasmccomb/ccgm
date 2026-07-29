#!/usr/bin/env bash
set -euo pipefail

# Embed E2E (plan Epic 1 spike (e) / section 3.6).
#
# Three assertions, split by what each instrument can decide:
#   (iii) snippet-string check - runs ALWAYS, no browser needed: every
#         published copy of the section-3.6 embed snippet (module README,
#         SKILL.md if present) must contain allow-popups AND
#         allow-popups-to-escape-sandbox and must NOT contain
#         allow-same-origin. This is the regression adrev-005 caught by hand.
#   (i)   direct-load mount + escaping assertions (browser)
#   (ii)  frame-scoped mount inside the verbatim snippet host page (browser)
#
# Driver: the toolchain's own pinned playwright (direct likec4 dependency).
# Browser binary absent: ORRERY_STRICT=1 -> FAILURE; unset -> (i)/(ii) skip
# with a message and (iii) still runs.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$MODULE_DIR/skills/orrery/scripts"
GOLDEN="$MODULE_DIR/tests/fixtures/golden"
SLUG="acme-shop"
STRICT="${ORRERY_STRICT:-0}"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# --- (iii) snippet-string assertion (no browser; cannot skip) ----------------
echo "--- (iii) embed-snippet string assertion ---"
# Build the scanned-file list as positional parameters so every path stays a
# single argument even under an install path containing spaces (bash 3.2 safe).
set -- "$MODULE_DIR/README.md"
if [ -f "$MODULE_DIR/skills/orrery/SKILL.md" ]; then
  set -- "$@" "$MODULE_DIR/skills/orrery/SKILL.md"
fi
python3 - "$@" <<'PYEOF'
import re
import sys

found = 0
problems = []
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for tag in re.findall(r"<iframe[^>]*>", text, re.S):
        if "sandbox=" not in tag:
            continue
        found += 1
        if "allow-popups" not in tag:
            problems.append("%s: sandbox snippet missing allow-popups" % path)
        if "allow-popups-to-escape-sandbox" not in tag:
            problems.append("%s: sandbox snippet missing allow-popups-to-escape-sandbox" % path)
        if "allow-same-origin" in tag:
            problems.append("%s: sandbox snippet must NOT contain allow-same-origin" % path)
if found == 0:
    problems.append("no sandboxed iframe snippet found in any published copy (README) - the check would be vacuous")
if problems:
    for p in problems:
        print("FAIL: " + p)
    sys.exit(1)
print("ok: %d published sandbox snippet(s) carry allow-popups + allow-popups-to-escape-sandbox, no allow-same-origin" % found)
PYEOF

# --- browser availability -----------------------------------------------------
# Stderr deliberately NOT suppressed: on a cold cache this call runs npm ci,
# and its failure must stay loud (diagnostics visible, nonzero exit).
TOOLCHAIN_DIR="$(bash "$SCRIPTS/likec4.sh" --print-toolchain-dir)"
[ -n "$TOOLCHAIN_DIR" ] || fail "could not resolve the toolchain dir"

set +e
NODE_PATH="$TOOLCHAIN_DIR/node_modules" node -e '
const fs = require("fs");
const pw = require("playwright");
process.exit(fs.existsSync(pw.chromium.executablePath()) ? 0 : 3);
'
BROWSER_PROBE=$?
set -e

if [ "$BROWSER_PROBE" != "0" ]; then
  if [ "$STRICT" = "1" ]; then
    fail "playwright chromium is not installed and ORRERY_STRICT=1 treats a missing browser as a failure, not a skip (install: bash $SCRIPTS/likec4.sh playwright install chromium)"
  fi
  echo "skip: playwright chromium not installed - (i)/(ii) skipped (install: likec4.sh playwright install chromium; ORRERY_STRICT=1 makes this a failure)"
  echo "test-embed-browser.sh: PASS (snippet-string assertion only)"
  exit 0
fi

# --- build the artifact -------------------------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-embed.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/model"
cp "$GOLDEN/spec.c4" "$GOLDEN/model.c4" "$GOLDEN/views.c4" "$GOLDEN/likec4.config.json" "$WORK/model/"
bash "$SCRIPTS/render_map.sh" "$WORK" "$SLUG" >/dev/null

# --- (i) + (ii) browser assertions -------------------------------------------
NODE_PATH="$TOOLCHAIN_DIR/node_modules" node "$E2E_DIR/embed_check.js" "$WORK/dist/$SLUG.html" \
  || fail "browser assertions failed (embed_check.js)"

echo "test-embed-browser.sh: PASS"
