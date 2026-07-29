#!/usr/bin/env bash
set -euo pipefail

# orrery render step (plan sections 3.7 / Epic 1).
#
# Usage: render_map.sh <out-dir> <slug>
#
# Runs the pinned toolchain's production build against <out-dir>/model and
# produces exactly one artifact: <out-dir>/dist/<slug>.html.
#
# The slug is an explicit argument: it is the input to the frozen artifact-name
# contract and must not be re-derived here.
#
# likec4 build --output-single-file writes index.html + an identical 404.html
# (+ sometimes a favicon svg) into -o <dir>, never {slug}.html. Its exit code is
# meaningless (always 0) and is NEVER used as a gate - validate is the gate,
# run before this script. This script renames index.html -> {slug}.html,
# removes the leftovers IF PRESENT (a bare rm of the favicon under set -e would
# fail on the builds that do not leave it on disk), then asserts exactly one
# .html remains and it is the named artifact.

if [ "$#" -ne 2 ]; then
  echo "usage: render_map.sh <out-dir> <slug>" >&2
  exit 2
fi

OUT_DIR="$1"
SLUG="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$OUT_DIR/model" ]; then
  echo "render_map.sh: model dir not found: $OUT_DIR/model" >&2
  exit 2
fi

# dist/ is owned by this script and fully generated - nothing user-authored
# lives there. Wipe it before the build: a likec4 build into a non-empty out
# dir skips its own cleanup and leaves intermediates (favicon.ico,
# likec4-views.js, robots.txt, a stale prior artifact) beside the renamed
# artifact, silently violating the single-artifact contract on reruns.
rm -rf "$OUT_DIR/dist"
mkdir -p "$OUT_DIR/dist"

bash "$SCRIPT_DIR/likec4.sh" build --output-single-file --base ./ -o "$OUT_DIR/dist" "$OUT_DIR/model"

if [ ! -f "$OUT_DIR/dist/index.html" ]; then
  echo "render_map.sh: build did not produce $OUT_DIR/dist/index.html" >&2
  exit 1
fi

mv "$OUT_DIR/dist/index.html" "$OUT_DIR/dist/$SLUG.html"

# Leftovers: 404.html is always written; the favicon svg is logged but not
# always left on disk - both removals must tolerate absence.
rm -f "$OUT_DIR/dist/404.html"
find "$OUT_DIR/dist" -maxdepth 1 -name 'favicon*.svg' -exec rm -f {} +

# Exactly ONE entry (of any kind) may remain, and it must be the named
# artifact - counting only *.html would let stray build outputs ride along.
ENTRY_COUNT="$(find "$OUT_DIR/dist" -mindepth 1 | wc -l | tr -d ' ')"
if [ "$ENTRY_COUNT" != "1" ]; then
  echo "render_map.sh: expected exactly one file in $OUT_DIR/dist, found $ENTRY_COUNT:" >&2
  find "$OUT_DIR/dist" -mindepth 1 >&2
  exit 1
fi
if [ ! -f "$OUT_DIR/dist/$SLUG.html" ]; then
  echo "render_map.sh: the single remaining file is not the named artifact $SLUG.html" >&2
  exit 1
fi

echo "render_map.sh: artifact $OUT_DIR/dist/$SLUG.html"
