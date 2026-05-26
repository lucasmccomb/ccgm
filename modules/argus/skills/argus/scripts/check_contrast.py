#!/usr/bin/env python3
"""Deterministic WCAG 2.x contrast gate for Argus.

Reads a generated tokens.json (the design-system mirror) and a contrast-pairs.json
(declared fg/bg pairs + minimum ratios), composites any alpha over the background,
computes the relative-luminance contrast ratio per pair per appearance, and exits
non-zero if any non-whitelisted pair falls below its minimum.

This is the platform-agnostic floor: the math is identical for web, iOS, macOS, or
anything else, so it lives in the module, not in a per-project adapter. No third-party
dependencies — Python stdlib only.

Usage:
  check_contrast.py --tokens tokens.json --pairs contrast-pairs.json [--appearances light,dark] [--json]
Exit code: 0 if all checked pairs pass, 1 if any fails, 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import sys


def _err(msg: str) -> "None":
    print(f"check_contrast: {msg}", file=sys.stderr)


def parse_color(value):
    """Return (r, g, b, a) with r,g,b in 0-255 and a in 0-1, or raise ValueError."""
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) == 6:
            r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
            return (r, g, b, 1.0)
        if len(s) == 8:
            r, g, b, a = (int(s[i : i + 2], 16) for i in (0, 2, 4, 6))
            return (r, g, b, a / 255.0)
        raise ValueError(f"bad hex color '{value}'")
    if isinstance(value, dict) and all(k in value for k in ("r", "g", "b")):
        a = value.get("a", 1.0)
        return (float(value["r"]), float(value["g"]), float(value["b"]), float(a))
    raise ValueError(f"unrecognized color {value!r}")


def resolve(tokens_colors, name, appearance):
    """Resolve a color name+appearance to (r,g,b,a). Supports appearance-split or flat."""
    if name not in tokens_colors:
        raise ValueError(f"token color '{name}' not found in tokens.json")
    entry = tokens_colors[name]
    # Direct color object (has r/g/b) or hex string => flat, applies to all appearances.
    if isinstance(entry, str) or (isinstance(entry, dict) and all(k in entry for k in ("r", "g", "b"))):
        return parse_color(entry)
    if isinstance(entry, dict):
        if appearance in entry:
            return parse_color(entry[appearance])
        # Fall back to a lone value if there is exactly one appearance defined.
        if len(entry) == 1:
            return parse_color(next(iter(entry.values())))
        raise ValueError(f"token '{name}' has no '{appearance}' appearance")
    raise ValueError(f"token '{name}' is not a color")


def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    r, g, b = (_srgb_to_linear(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def composite_over(fg, bg):
    """Alpha-composite fg over opaque bg in sRGB space; returns opaque (r,g,b)."""
    fr, fg_, fb, fa = fg
    br, bg_, bb, _ = bg
    return (
        fr * fa + br * (1 - fa),
        fg_ * fa + bg_ * (1 - fa),
        fb * fa + bb * (1 - fa),
    )


def contrast_ratio(fg, bg):
    composited = composite_over(fg, bg)
    l1 = luminance(composited)
    l2 = luminance(bg[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def discover_appearances(colors) -> list:
    found = []
    for entry in colors.values():
        if isinstance(entry, dict) and not all(k in entry for k in ("r", "g", "b")):
            for k in entry:
                if k not in found:
                    found.append(k)
    return found or ["default"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WCAG contrast gate over declared token pairs.")
    ap.add_argument("--tokens", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--appearances", default="", help="Comma list to restrict (default: all in tokens).")
    ap.add_argument("--json", action="store_true", help="Emit a JSON report on stdout.")
    args = ap.parse_args(argv)

    try:
        with open(args.tokens) as f:
            tokens = json.load(f)
        with open(args.pairs) as f:
            pairs_doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _err(f"cannot read input: {e}")
        return 2

    colors = tokens.get("colors", {})
    if not colors:
        _err("tokens.json has no 'colors' map")
        return 2

    appearances = (
        [a.strip() for a in args.appearances.split(",") if a.strip()]
        if args.appearances
        else discover_appearances(colors)
    )

    results, failures = [], []
    for pair in pairs_doc.get("pairs", []):
        fg_name, bg_name = pair.get("fg"), pair.get("bg")
        minimum = float(pair.get("min", 4.5))
        whitelist = pair.get("whitelist", [])
        if whitelist is True:
            whitelist = list(appearances)
        for appearance in appearances:
            entry = {"fg": fg_name, "bg": bg_name, "appearance": appearance, "min": minimum}
            if appearance in whitelist:
                entry["status"] = "whitelisted"
                results.append(entry)
                continue
            try:
                fg = resolve(colors, fg_name, appearance)
                bg = resolve(colors, bg_name, appearance)
            except ValueError as e:
                _err(str(e))
                return 2
            ratio = round(contrast_ratio(fg, bg), 2)
            entry["ratio"] = ratio
            entry["status"] = "pass" if ratio >= minimum else "fail"
            results.append(entry)
            if entry["status"] == "fail":
                failures.append(entry)

    passed = not failures
    if args.json:
        print(json.dumps({"pairs": results, "failures": failures, "pass": passed}, indent=2))
    else:
        for r in results:
            ratio = r.get("ratio", "—")
            print(f"  [{r['status']:>11}] {r['fg']}/{r['bg']} ({r['appearance']}): {ratio} (min {r['min']})")
        print(f"contrast: {'PASS' if passed else 'FAIL'} ({len(failures)} failing pair(s))")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
