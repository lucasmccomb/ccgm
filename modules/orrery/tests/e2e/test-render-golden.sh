#!/usr/bin/env bash
set -euo pipefail

# Golden render E2E (plan Epic 1 / section 3.7).
#
# Renders the golden model through render_map.sh and asserts:
#   - exit 0; exactly one .html in dist/, named {slug}.html
#   - contains acme-shop, a blob/ href, and >=2 house-palette hex values
#   - self-contained: no external script src
#   - the DIFFERENTIAL implicit-views detector: build the model a second time
#     from a copy with likec4.config.json deleted; the L4 file element title
#     (a unique marker) occurs >=3x in the as-shipped artifact and exactly 1x
#     in the config-less one (measured 16x vs 1x). A size threshold cannot
#     serve here: at fixture scale on/off differ by ~2 percent.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$MODULE_DIR/skills/orrery/scripts"
GOLDEN="$MODULE_DIR/tests/fixtures/golden"
SLUG="acme-shop"
L4_TITLE="ProductGridFixtureL4"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-golden.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

count_in() {
  # occurrences (not lines) of a fixed string in a file
  { grep -o "$2" "$1" || true; } | wc -l | tr -d ' '
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

mkdir -p "$WORK/asrun/model" "$WORK/noconfig/model"
cp "$GOLDEN/spec.c4" "$GOLDEN/model.c4" "$GOLDEN/views.c4" "$GOLDEN/likec4.config.json" "$WORK/asrun/model/"
cp "$GOLDEN/spec.c4" "$GOLDEN/model.c4" "$GOLDEN/views.c4" "$WORK/noconfig/model/"

# --- as-shipped build --------------------------------------------------------
bash "$SCRIPTS/render_map.sh" "$WORK/asrun" "$SLUG" >/dev/null
ARTIFACT="$WORK/asrun/dist/$SLUG.html"

HTML_COUNT="$(find "$WORK/asrun/dist" -maxdepth 1 -name '*.html' | wc -l | tr -d ' ')"
[ "$HTML_COUNT" = "1" ] || fail "expected exactly one .html in dist, found $HTML_COUNT"
[ -f "$ARTIFACT" ] || fail "artifact not named $SLUG.html"
echo "ok: exactly one artifact, named $SLUG.html"

[ "$(count_in "$ARTIFACT" 'acme-shop')" -ge 1 ] || fail "artifact does not contain acme-shop"
[ "$(count_in "$ARTIFACT" 'blob/')" -ge 1 ] || fail "artifact does not contain a blob/ href"
echo "ok: contains acme-shop and a blob/ href"

# >=2 distinct house-palette hex values (section 3.4a), case-insensitive
PALETTE_HITS=0
for hex in 4C6EF5 845EF7 3B5BDB 5C7CFA 0CA678 0B7285 495057 868E96 ADB5BD CED4DA 748FFC; do
  n="$({ grep -io "$hex" "$ARTIFACT" || true; } | wc -l | tr -d ' ')"
  if [ "$n" -ge 1 ]; then
    PALETTE_HITS=$((PALETTE_HITS + 1))
  fi
done
[ "$PALETTE_HITS" -ge 2 ] || fail "expected >=2 palette hex values in the artifact, found $PALETTE_HITS"
echo "ok: $PALETTE_HITS palette hex values present"

[ "$(count_in "$ARTIFACT" '<script src="http')" = "0" ] || fail "artifact references an external script (not self-contained)"
echo "ok: self-contained (no external script src)"

# --- differential implicit-views detector ------------------------------------
bash "$SCRIPTS/render_map.sh" "$WORK/noconfig" "$SLUG" >/dev/null
NOCONFIG_ARTIFACT="$WORK/noconfig/dist/$SLUG.html"

AS_SHIPPED_N="$(count_in "$ARTIFACT" "$L4_TITLE")"
NOCONFIG_N="$(count_in "$NOCONFIG_ARTIFACT" "$L4_TITLE")"
echo "implicit-views detector: as-shipped=${AS_SHIPPED_N}x, config-less=${NOCONFIG_N}x"
[ "$AS_SHIPPED_N" -ge 3 ] || fail "L4 title occurs ${AS_SHIPPED_N}x in the as-shipped artifact (expected >=3: implicitViews not honored - is likec4.config.json inside the model dir?)"
[ "$NOCONFIG_N" = "1" ] || fail "L4 title occurs ${NOCONFIG_N}x in the config-less artifact (expected exactly 1: the differential baseline drifted)"
echo "ok: implicit views proven by content (>=3x vs exactly 1x)"

echo "test-render-golden.sh: PASS"
