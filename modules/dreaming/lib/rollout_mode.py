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

The module also holds the agreement arithmetic and the promotion bar the
scorecard reports, so "ready for active" is computed, not prose.

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

# Promotion bar: suggest `active` only when the shadow record shows at least
# this many decided (non-pending) decisions, at this agreement rate or better,
# with no more than this many false positives on guarded items. For dreaming
# the guarded items are evictions (contradict / deprecate), which remove
# knowledge from the store.
PROMOTION_MIN_DECIDED = 20
PROMOTION_MIN_AGREEMENT = 0.90
PROMOTION_MAX_GUARDED_FALSE_POSITIVES = 0

GUARDED_KINDS = ("learning_contradict", "learning_deprecate")


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


def agreement(
    decisions: Iterable[dict[str, Any]], outcomes: dict[str, str],
) -> dict[str, int]:
    """Compare shadow decisions with what the human later did.

    `decisions`: records with `proposal_id`, `would_integrate` (bool) and
    `kind`. A proposal decided more than once counts once, by its latest
    record. `outcomes` maps proposal_id to "accepted" or "rejected"; any other
    or missing value leaves the decision pending.

    would-integrate + accepted  -> agreed
    would-integrate + rejected  -> false positive
    would-skip      + accepted  -> false negative
    would-skip      + rejected  -> agreed
    """
    latest: dict[str, dict[str, Any]] = {}
    for rec in decisions:
        pid = rec.get("proposal_id")
        if isinstance(pid, str) and pid:
            latest[pid] = rec
    stats = {
        "decisions": len(latest), "agreed": 0, "false_positives": 0,
        "false_negatives": 0, "pending": 0, "guarded_false_positives": 0,
    }
    for pid, rec in latest.items():
        outcome = outcomes.get(pid)
        if outcome not in ("accepted", "rejected"):
            stats["pending"] += 1
            continue
        would = bool(rec.get("would_integrate"))
        accepted = outcome == "accepted"
        if would == accepted:
            stats["agreed"] += 1
        elif would:
            stats["false_positives"] += 1
            if rec.get("kind") in GUARDED_KINDS:
                stats["guarded_false_positives"] += 1
        else:
            stats["false_negatives"] += 1
    return stats


def promotion_verdict(stats: dict[str, int]) -> dict[str, Any]:
    """Apply the promotion bar to `agreement()` output."""
    decided = stats["agreed"] + stats["false_positives"] + stats["false_negatives"]
    rate = stats["agreed"] / decided if decided else 0.0
    reasons: list[str] = []
    if decided < PROMOTION_MIN_DECIDED:
        reasons.append(f"{decided} of {PROMOTION_MIN_DECIDED} decided decisions")
    if decided and rate < PROMOTION_MIN_AGREEMENT:
        reasons.append(f"agreement {rate:.0%} is below {PROMOTION_MIN_AGREEMENT:.0%}")
    if stats["guarded_false_positives"] > PROMOTION_MAX_GUARDED_FALSE_POSITIVES:
        reasons.append(f"{stats['guarded_false_positives']} false positive(s) on guarded items")
    return {"ready": not reasons, "decided": decided, "agreement": rate, "reasons": reasons}


def render_lines(stats: dict[str, int]) -> list[str]:
    """Markdown lines for the scorecard's shadow section."""
    verdict = promotion_verdict(stats)
    lines = [
        f"- shadow decisions: {stats['decisions']}",
        f"- agreed: {stats['agreed']}",
        f"- disagreed: {stats['false_positives'] + stats['false_negatives']} "
        f"({stats['false_positives']} false positive, {stats['false_negatives']} false negative)",
        f"- pending (no human outcome yet): {stats['pending']}",
        f"- guarded false positives (evictions): {stats['guarded_false_positives']}",
    ]
    if verdict["ready"]:
        lines.append(
            f"- promotion bar met ({verdict['decided']} decided, {verdict['agreement']:.0%} agreement): "
            "safe to suggest `active`"
        )
    else:
        lines.append(f"- promotion bar not met: {'; '.join(verdict['reasons'])}")
    return lines


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
