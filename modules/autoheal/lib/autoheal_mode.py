#!/usr/bin/env python3
"""Off / shadow / active rollout modes for autoheal's opt-in behaviors.

`auto_apply_enabled` and `realtime_alerts_enabled` each take off | shadow |
active. Every reader goes through `resolve_mode` / `read_mode`; nothing else
compares the raw value.

  off      the behavior does nothing.
  shadow   the decision is computed and appended to a JSONL under
           ~/.claude/autoheal/shadow/. Nothing else happens: no branch, no
           applied record, no alert block.
  active   the behavior runs.

The module also holds the agreement arithmetic and the promotion bar the
digest reports, so "ready for active" is computed, not prose.

Pure standard library: the realtime hook, the daily scripts and the digest all
import it.

CLI (used by /autoheal-toggle and the shell scripts):
  autoheal_mode.py mode   <config.json> <key>
  autoheal_mode.py set    <config.json> <realtime|autoapply> <on|off|shadow|active>
  autoheal_mode.py status <config.json> <realtime|autoapply>
  autoheal_mode.py shadow-log auto-apply <proposals.jsonl> <proposal-id> <true|false> <reason>
  autoheal_mode.py report
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import sys
import tempfile
from typing import Any, Iterable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ACTIVE)

# /autoheal-toggle subcommand -> config key.
FLAGS = {"realtime": "realtime_alerts_enabled", "autoapply": "auto_apply_enabled"}

# Promotion bar: suggest `active` only when the shadow record shows at least
# this many decided (non-pending) decisions, at this agreement rate or better,
# with no more than this many false positives on guarded items. For auto-apply
# the guarded items are `check`-surface proposals (hooks, tests, lints), which
# change enforcement.
PROMOTION_MIN_DECIDED = 20
PROMOTION_MIN_AGREEMENT = 0.90
PROMOTION_MAX_GUARDED_FALSE_POSITIVES = 0

GUARDED_SURFACE = "check"


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


def read_mode(config_path: str, key: str) -> str:
    """Resolved mode of `key` in the config file. A missing, unreadable or
    malformed file, or a missing key, is "off"."""
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return MODE_OFF
    if not isinstance(cfg, dict):
        return MODE_OFF
    return resolve_mode(cfg.get(key))


# ---------------------------------------------------------------------------
# Paths (all overridable for tests)
# ---------------------------------------------------------------------------


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def shadow_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_SHADOW_DIR") or os.path.join(autoheal_dir(), "shadow")


def applied_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_APPLIED_DIR") or os.path.join(autoheal_dir(), "applied")


def snoozed_file() -> str:
    return os.environ.get("CCGM_AUTOHEAL_SNOOZED_FILE") or os.path.join(autoheal_dir(), "snoozed.json")


def shadow_log_path(kind: str) -> str:
    """`kind` is "auto-apply" or "realtime"."""
    return os.path.join(shadow_dir(), f"{kind}.jsonl")


# ---------------------------------------------------------------------------
# Shadow log
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def log_shadow(kind: str, record: dict[str, Any]) -> None:
    """Append one record (with a `ts`) to the shadow log for `kind`."""
    record = {"ts": _now_iso(), **record}
    path = shadow_log_path(kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError:
        pass
    return rows


def surface_of(proposal: dict[str, Any]) -> str:
    """Proposals written before fix_surface existed read as `rule`."""
    surface = proposal.get("fix_surface")
    return surface if isinstance(surface, str) and surface else "rule"


def log_auto_apply_decision(proposals_file: str, proposal_id: str, would_apply: bool, reason: str) -> None:
    """Record one auto-apply shadow decision, adding the proposal's
    fingerprint and fix surface so the digest can match snoozes and flag
    guarded false positives."""
    proposal: dict[str, Any] = {}
    for rec in read_jsonl(proposals_file):
        if rec.get("id") == proposal_id:
            proposal = rec
            break
    log_shadow("auto-apply", {
        "proposal_id": proposal_id,
        "would_apply": bool(would_apply),
        "reason": reason,
        "fingerprint": proposal.get("fingerprint"),
        "fix_surface": surface_of(proposal),
    })


# ---------------------------------------------------------------------------
# Agreement and the promotion bar
# ---------------------------------------------------------------------------


def applied_proposal_ids(directory: str) -> set[str]:
    """Proposal ids a human applied: a successful audit record (tests passed,
    not rolled back) in any applied/*.jsonl. In shadow mode auto-apply never
    runs, so such a record is a human /autoheal-apply or /permission-fix."""
    ids: set[str] = set()
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return ids
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        for rec in read_jsonl(os.path.join(directory, name)):
            pid = rec.get("proposal_id")
            if isinstance(pid, str) and rec.get("tests_passed") is True and not rec.get("rolled_back"):
                ids.add(pid)
    return ids


def snoozed_fingerprints(path: str) -> set[str]:
    """Fingerprints a human snoozed. Expired entries still count: the human
    already said no."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return set(data) if isinstance(data, dict) else set()


def human_outcomes(
    decisions: Iterable[dict[str, Any]], applied_ids: set[str], snoozed_fingerprints: set[str],
) -> dict[str, str]:
    """proposal_id -> "accepted" (a human applied it) or "rejected" (a human
    snoozed its fingerprint). Applying wins over snoozing. Ids with neither
    are absent, which `agreement` counts as pending."""
    outcomes: dict[str, str] = {}
    for rec in decisions:
        pid = rec.get("proposal_id")
        if not isinstance(pid, str):
            continue
        if pid in applied_ids:
            outcomes[pid] = "accepted"
        elif rec.get("fingerprint") in snoozed_fingerprints:
            outcomes[pid] = "rejected"
    return outcomes


def agreement(decisions: Iterable[dict[str, Any]], outcomes: dict[str, str]) -> dict[str, int]:
    """Compare shadow decisions with what the human later did.

    `decisions`: records with `proposal_id`, `would_apply` (bool) and
    `fix_surface`. A proposal decided more than once counts once, by its
    latest record. `outcomes` maps proposal_id to "accepted" or "rejected";
    any other or missing value leaves the decision pending.

    would-apply + accepted  -> agreed
    would-apply + rejected  -> false positive
    would-skip  + accepted  -> false negative
    would-skip  + rejected  -> agreed
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
        would = bool(rec.get("would_apply"))
        accepted = outcome == "accepted"
        if would == accepted:
            stats["agreed"] += 1
        elif would:
            stats["false_positives"] += 1
            if rec.get("fix_surface") == GUARDED_SURFACE:
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


def render_report() -> str:
    """Markdown section for the digest. Empty when no shadow log exists."""
    decisions = read_jsonl(shadow_log_path("auto-apply"))
    alerts = read_jsonl(shadow_log_path("realtime"))
    if not decisions and not alerts:
        return ""
    lines = ["## Shadow rollout", ""]
    if decisions:
        outcomes = human_outcomes(decisions, applied_proposal_ids(applied_dir()), snoozed_fingerprints(snoozed_file()))
        stats = agreement(decisions, outcomes)
        verdict = promotion_verdict(stats)
        lines += [
            f"- shadow auto-apply decisions: {stats['decisions']}",
            f"- agreed: {stats['agreed']}",
            f"- disagreed: {stats['false_positives'] + stats['false_negatives']} "
            f"({stats['false_positives']} false positive, {stats['false_negatives']} false negative)",
            f"- pending (no human outcome yet): {stats['pending']}",
            f"- guarded false positives (`{GUARDED_SURFACE}` surface): {stats['guarded_false_positives']}",
        ]
        if verdict["ready"]:
            lines.append(
                f"- promotion bar met ({verdict['decided']} decided, {verdict['agreement']:.0%} agreement): "
                "safe to suggest `active` for auto-apply"
            )
        else:
            lines.append(f"- promotion bar not met: {'; '.join(verdict['reasons'])}")
    if alerts:
        would = sum(1 for a in alerts if a.get("would_alert"))
        lines.append(
            f"- realtime shadow would-alert matches: {would} "
            "(alerts have no recorded human outcome, so they stay pending)"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

_SET_VALUES = {"on": MODE_ACTIVE, "off": MODE_OFF, "shadow": MODE_SHADOW, "active": MODE_ACTIVE}


def set_flag(config_path: str, flag: str, value: str) -> tuple[str, str]:
    """Set one flag to a mode and return (config key, stored mode). Preserves
    every other key and writes atomically. Raises ValueError on a bad flag or
    value, leaving the file untouched."""
    if flag not in FLAGS:
        raise ValueError(f"unknown flag {flag!r} (expected one of {', '.join(FLAGS)})")
    mode = _SET_VALUES.get(value.strip().lower())
    if mode is None:
        raise ValueError(f"unknown mode {value!r} (expected on, off, shadow or active)")
    cfg: dict[str, Any] = {}
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            cfg = loaded
    except (OSError, ValueError):
        pass
    key = FLAGS[flag]
    cfg[key] = mode
    parent = os.path.dirname(os.path.abspath(config_path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, config_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return key, mode


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "mode" and len(argv) == 4:
            print(read_mode(argv[2], argv[3]))
            return 0
        if cmd == "set" and len(argv) == 5:
            key, mode = set_flag(argv[2], argv[3], argv[4])
            print(f"set {key} = {mode}")
            return 0
        if cmd == "status" and len(argv) == 4:
            if argv[3] not in FLAGS:
                raise ValueError(f"unknown flag {argv[3]!r} (expected one of {', '.join(FLAGS)})")
            key = FLAGS[argv[3]]
            print(f"{key} = {read_mode(argv[2], key)}")
            return 0
        if cmd == "shadow-log" and len(argv) == 7 and argv[2] == "auto-apply":
            log_auto_apply_decision(argv[3], argv[4], argv[5] == "true", argv[6])
            return 0
        if cmd == "report" and len(argv) == 2:
            sys.stdout.write(render_report())
            return 0
    except ValueError as exc:
        print(f"autoheal_mode: {exc}", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
