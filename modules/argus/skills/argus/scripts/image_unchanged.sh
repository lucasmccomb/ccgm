#!/usr/bin/env bash
# image_unchanged.sh PREV.png CURR.png
#
# Hash-suppression for the Argus loop: decides whether a freshly captured render is
# perceptually unchanged from the previous one, so the loop can skip a judge dispatch.
# Prints {"unchanged": bool, "method": "..."} on stdout. Exit 0 on success, 2 on bad input.
#
# Method:
#   - If ImageMagick is present, compares with `compare -metric AE -fuzz 5%` and calls the
#     render unchanged when fewer than 0.5% of pixels differ (perceptual, tolerant of noise).
#   - Otherwise falls back to sha256 byte-equality. The fallback is STRICTER (it only
#     suppresses byte-identical renders), so it never false-suppresses a real change — the
#     cost is at most an extra judge pass.
set -euo pipefail

PREV="${1:-}"
CURR="${2:-}"
if [[ -z "$PREV" || -z "$CURR" ]]; then
  echo "usage: image_unchanged.sh PREV.png CURR.png" >&2
  exit 2
fi
if [[ ! -f "$CURR" ]]; then
  echo "image_unchanged: current image not found: $CURR" >&2
  exit 2
fi
# No previous render => treat as changed (first iteration always judges).
if [[ ! -f "$PREV" ]]; then
  printf '{"unchanged": false, "method": "no-baseline"}\n'
  exit 0
fi

# Resolve ImageMagick v7 (magick) or v6 (compare/identify) if available.
COMPARE=""
IDENTIFY=""
if command -v magick >/dev/null 2>&1; then
  COMPARE="magick compare"
  IDENTIFY="magick identify"
elif command -v compare >/dev/null 2>&1 && command -v identify >/dev/null 2>&1; then
  COMPARE="compare"
  IDENTIFY="identify"
fi

if [[ -n "$COMPARE" ]]; then
  total="$($IDENTIFY -format '%[fx:w*h]' "$CURR" 2>/dev/null || echo 0)"
  # `compare` writes the absolute-error pixel count to stderr and exits non-zero when images differ.
  ae="$($COMPARE -metric AE -fuzz 5% "$PREV" "$CURR" null: 2>&1 || true)"
  ae="$(printf '%s' "$ae" | grep -oE '^[0-9]+' | head -1 || true)"
  ae="${ae:-0}"
  if [[ "$total" -gt 0 ]]; then
    unchanged="$(awk -v ae="$ae" -v total="$total" 'BEGIN { print (ae / total < 0.005) ? "true" : "false" }')"
  else
    unchanged="false"
  fi
  printf '{"unchanged": %s, "method": "imagemagick", "diff_pixels": %s, "total_pixels": %s}\n' \
    "$unchanged" "$ae" "$total"
  exit 0
fi

# Fallback: exact byte equality.
prev_sum="$(shasum -a 256 "$PREV" | awk '{print $1}')"
curr_sum="$(shasum -a 256 "$CURR" | awk '{print $1}')"
if [[ "$prev_sum" == "$curr_sum" ]]; then
  printf '{"unchanged": true, "method": "sha256"}\n'
else
  printf '{"unchanged": false, "method": "sha256"}\n'
fi
