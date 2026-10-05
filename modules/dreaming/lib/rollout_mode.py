#!/usr/bin/env python3
"""Off / shadow / active rollout mode for dreaming's optimistic integration.

One resolver (`resolve_mode`) maps the persisted `optimistic_integration.enabled`
value to a mode. Every reader of that flag goes through it; nothing else
compares the raw value.

  off      the engine does nothing.
  shadow   the engine runs its decision pass (posture, floors, caps, anomaly,
           breaker) and logs what it would integrate. It writes nothing to the
           learnings store.
  active   the engine integrates.

The module also holds the shadow-decision tally the scorecard reports.

Pure and dependency-free: scorecard.py, dream_analyze.py and dream-daily.sh
all import it.
"""
from __future__ import annotations

import sys
from typing import Any, Iterable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ACTIVE)

def resolve_mode(value: Any) -> str:
    """Map a persisted flag value to "off", "shadow" or "active".

    Configs written before shadow mode hold a boolean, and users' files on
    disk are never rewritten, so `true` reads as "active" and `false` as
    "off". Anything unrecognised fails closed to "off".
    """
    if value is True:
        return MODE_ACTIVE
    if isinstance(value, str) and value.strip().lower() in MODES:
        return value.strip().lower()
    return MODE_OFF


def shadow_tally(decisions: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count shadow decisions for the scorecard.

    `decisions`: records with `proposal_id` and `would_integrate` (bool). A
    proposal decided more than once counts once, by its latest record. There is
    no human outcome to compare against: proposals are never queued for review
    (#1098 2.3), so shadow mode reports what the engine would do and nothing more.
    """
    latest: dict[str, dict[str, Any]] = {}
    for rec in decisions:
        pid = rec.get("proposal_id")
        if isinstance(pid, str) and pid:
            latest[pid] = rec
    would = sum(1 for rec in latest.values() if rec.get("would_integrate"))
    return {"decisions": len(latest), "would_integrate": would, "would_skip": len(latest) - would}


def render_lines(stats: dict[str, int]) -> list[str]:
    """Markdown lines for the scorecard's shadow section."""
    return [
        f"- shadow decisions: {stats['decisions']}",
        f"- would integrate: {stats['would_integrate']}",
        f"- would skip: {stats['would_skip']}",
    ]


if __name__ == "__main__":
    # Shell entry: `rollout_mode.py <config.json>` prints the mode.
    import json

    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            cfg = json.load(fh)
        opt = cfg.get("optimistic_integration") if isinstance(cfg, dict) else None
        print(resolve_mode(opt.get("enabled") if isinstance(opt, dict) else None))
    except Exception:
        print(MODE_OFF)
