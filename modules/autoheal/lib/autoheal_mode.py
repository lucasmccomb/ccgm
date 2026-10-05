#!/usr/bin/env python3
"""Off / shadow / active rollout modes for autoheal's opt-in behaviors.

Two flags take off | shadow | active:

  realtime_alerts_enabled   the realtime security scanner (read_mode)
  auto_apply_mode           nightly auto-apply of rule_insert fixes
                            (read_auto_apply_mode, #1099 Phase 4.2)

  off      the behavior does nothing.
  shadow   the decision is computed and appended to a JSONL under
           ~/.claude/autoheal/shadow/. Nothing else happens.
  active   the behavior runs.

Auto-apply has to earn `active`. Every shadow decision is compared with what
the user later decided in /autoheal-review (applied = accepted, rejected =
rejected). Switching to active is refused until there are at least
PROMOTION_MIN_DECIDED decided decisions at PROMOTION_MIN_AGREEMENT agreement or
better, and no would-apply decision whose fix was later measured harmful or
reverted. A successful switch records `auto_apply_promoted_at`; an `active`
value without it (a hand edit) runs as shadow. DEMOTION_REVERTS reverts within
DEMOTION_WINDOW_DAYS drop the mode back to shadow and record
`auto_apply_demoted_at`; only decisions logged after that count toward the next
promotion.

The legacy `auto_apply_enabled` flag is migrated on read: when
`auto_apply_mode` is absent, a legacy off/false reads as off and any other
legacy value (true, "shadow", "active") reads as shadow, never active, because
active must be earned. The toggle writes `auto_apply_mode` and deletes the
legacy key.

Pure standard library: the realtime hook, the daily scripts and the digest all
import it.

CLI (used by /autoheal, /autoheal-toggle and the shell scripts):
  autoheal_mode.py mode   <config.json> <key>
  autoheal_mode.py set    <config.json> <realtime|autoapply> <on|off|shadow|active>
                          exit 3 when the promotion bar refuses active
  autoheal_mode.py status <config.json> <realtime|autoapply>
  autoheal_mode.py stats  <config.json>        auto-apply mode, agreement, outcomes (JSON)
  autoheal_mode.py report                      digest section (markdown)
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
from typing import Any, Iterable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ACTIVE)

AUTO_APPLY_KEY = "auto_apply_mode"
LEGACY_AUTO_APPLY_KEY = "auto_apply_enabled"
PROMOTED_KEY = "auto_apply_promoted_at"
DEMOTED_KEY = "auto_apply_demoted_at"
DEMOTED_REASON_KEY = "auto_apply_demoted_reason"

# /autoheal-toggle subcommand -> config key.
FLAGS = {"realtime": "realtime_alerts_enabled", "autoapply": AUTO_APPLY_KEY}

# Promotion bar for auto-apply (#1099 Phase 4.2).
PROMOTION_MIN_DECIDED = 10
PROMOTION_MIN_AGREEMENT = 0.90
PROMOTION_MAX_HARMFUL = 0

# Demotion: this many reverts inside the window put active back to shadow.
DEMOTION_REVERTS = 3
DEMOTION_WINDOW_DAYS = 30

# Ledger states that mean "the user applied it" (later states keep that fact).
ACCEPTED_STATES = ("applied", "measured", "reverted")
OUTCOMES = ("effective", "ineffective", "harmful", "unmeasurable")


class PromotionRefused(Exception):
    """Switching auto-apply to active was refused; the message lists why."""


def resolve_mode(value: Any) -> str:
    """Map a persisted realtime flag value to "off", "shadow" or "active".

    A persisted boolean reads as active (true) or off (false). Anything
    unrecognised fails closed to "off".
    """
    if value is True:
        return MODE_ACTIVE
    if isinstance(value, str) and value.strip().lower() in MODES:
        return value.strip().lower()
    return MODE_OFF


def _load_config(config_path: str) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def read_mode(config_path: str, key: str) -> str:
    """Resolved mode of `key` in the config file. A missing, unreadable or
    malformed file, or a missing key, is "off". `auto_apply_mode` goes through
    the auto-apply resolver so the legacy flag is honoured."""
    cfg = _load_config(config_path)
    if key == AUTO_APPLY_KEY:
        return auto_apply_mode_of(cfg)
    return resolve_mode(cfg.get(key))


def auto_apply_mode_of(cfg: dict) -> str:
    """The configured auto-apply mode, with the legacy flag migrated (never to active)."""
    if AUTO_APPLY_KEY in cfg:
        value = cfg.get(AUTO_APPLY_KEY)
        if isinstance(value, str) and value.strip().lower() in MODES:
            return value.strip().lower()
        return MODE_OFF
    return MODE_SHADOW if resolve_mode(cfg.get(LEGACY_AUTO_APPLY_KEY)) != MODE_OFF else MODE_OFF


def read_auto_apply_mode(config_path: str) -> str:
    return auto_apply_mode_of(_load_config(config_path))


def effective_auto_apply_mode(cfg: dict) -> tuple[str, str]:
    """(mode the run uses, note). `active` without a promotion record runs as shadow."""
    mode = auto_apply_mode_of(cfg)
    if mode == MODE_ACTIVE and not cfg.get(PROMOTED_KEY):
        return MODE_SHADOW, ("auto_apply_mode is active but was not promoted through "
                             "/autoheal-toggle autoapply active; running as shadow")
    return mode, ""


# ---------------------------------------------------------------------------
# Paths (all overridable for tests)
# ---------------------------------------------------------------------------


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def config_path() -> str:
    return os.environ.get("CCGM_AUTOHEAL_CONFIG") or os.path.join(autoheal_dir(), "config.json")


def shadow_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_SHADOW_DIR") or os.path.join(autoheal_dir(), "shadow")


def shadow_log_path(kind: str) -> str:
    """`kind` is "auto-apply" or "realtime"."""
    return os.path.join(shadow_dir(), f"{kind}.jsonl")


def _ledger():
    spec = importlib.util.spec_from_file_location(
        "autoheal_ledger", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def now_utc() -> _dt.datetime:
    """Real time, or CCGM_AUTOHEAL_NOW / CCGM_AUTOHEAL_TODAY (noon UTC) in tests."""
    raw = os.environ.get("CCGM_AUTOHEAL_NOW")
    if not raw and os.environ.get("CCGM_AUTOHEAL_TODAY"):
        raw = os.environ["CCGM_AUTOHEAL_TODAY"] + "T12:00:00+00:00"
    when = _parse_ts(raw) if raw else None
    return when or _dt.datetime.now(_dt.timezone.utc)


def _parse_ts(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        when = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Shadow log
# ---------------------------------------------------------------------------


def log_shadow(kind: str, record: dict[str, Any]) -> None:
    """Append one record (with a `ts`) to the shadow log for `kind`."""
    record = {"ts": now_utc().isoformat(), **record}
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


def log_auto_apply_decision(row: dict[str, Any], would_apply: bool, reason: str, mode: str) -> None:
    """Record what auto-apply decided for one ready ledger row."""
    log_shadow("auto-apply", {
        "proposal_id": row.get("id"),
        "generated_at": row.get("generated_at"),
        "signature_id": row.get("signature_id"),
        "would_apply": bool(would_apply),
        "reason": reason,
        "mode": mode,
    })


# ---------------------------------------------------------------------------
# Agreement, promotion and demotion
# ---------------------------------------------------------------------------


def _key(rec: dict[str, Any]) -> tuple:
    return (rec.get("proposal_id", rec.get("id")), rec.get("generated_at"))


def human_outcomes(rows: Iterable[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """(id, generated_at) -> {"decision": accepted|rejected|None, "harmful": bool}.

    accepted: the user applied it in /autoheal-review (applied, measured or
    reverted, and not applied_by auto). rejected: the user rejected it.
    harmful: the fix was measured harmful or reverted, whoever applied it.
    """
    out: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        state = row.get("state", "ready")
        decision = None
        if state in ACCEPTED_STATES and row.get("applied_by") != "auto":
            decision = "accepted"
        elif state == "rejected":
            decision = "rejected"
        harmful = row.get("outcome") == "harmful" or state == "reverted"
        out[_key(row)] = {"decision": decision, "harmful": harmful}
    return out


def agreement(decisions: Iterable[dict[str, Any]], outcomes: dict[tuple, dict[str, Any]],
              since: _dt.datetime | None = None) -> dict[str, int]:
    """Compare shadow decisions with what the user later did.

    A proposal decided on several nights counts once, by its latest record.
    Records logged before `since` (the last demotion) are ignored.

    would-apply + accepted  -> agreed
    would-apply + rejected  -> false positive
    would-skip  + accepted  -> false negative
    would-skip  + rejected  -> agreed
    no decision yet         -> pending
    `harmful` counts would-apply decisions whose fix was later measured harmful
    or reverted.
    """
    latest: dict[tuple, dict[str, Any]] = {}
    for rec in decisions:
        if not rec.get("proposal_id"):
            continue
        if since is not None:
            ts = _parse_ts(rec.get("ts"))
            if ts is None or ts < since:
                continue
        latest[_key(rec)] = rec
    stats = {"decisions": len(latest), "decided": 0, "agreed": 0, "false_positives": 0,
             "false_negatives": 0, "pending": 0, "harmful": 0}
    for key, rec in latest.items():
        info = outcomes.get(key) or {}
        would = bool(rec.get("would_apply"))
        if would and info.get("harmful"):
            stats["harmful"] += 1
        decision = info.get("decision")
        if decision not in ("accepted", "rejected"):
            stats["pending"] += 1
            continue
        stats["decided"] += 1
        if would == (decision == "accepted"):
            stats["agreed"] += 1
        elif would:
            stats["false_positives"] += 1
        else:
            stats["false_negatives"] += 1
    return stats


def promotion_verdict(stats: dict[str, int]) -> dict[str, Any]:
    """Apply the promotion bar to `agreement()` output."""
    decided = stats["decided"]
    rate = stats["agreed"] / decided if decided else 0.0
    reasons: list[str] = []
    if decided < PROMOTION_MIN_DECIDED:
        reasons.append(f"{decided} of {PROMOTION_MIN_DECIDED} decided decisions")
    if decided and rate < PROMOTION_MIN_AGREEMENT:
        reasons.append(f"agreement {rate:.0%} is below {PROMOTION_MIN_AGREEMENT:.0%}")
    if stats["harmful"] > PROMOTION_MAX_HARMFUL:
        reasons.append(f"{stats['harmful']} would-apply decision(s) later measured harmful or reverted")
    return {"ready": not reasons, "decided": decided, "agreement": rate, "reasons": reasons}


def recent_reverts(rows: Iterable[dict[str, Any]], now: _dt.datetime,
                   days: int = DEMOTION_WINDOW_DAYS) -> int:
    cutoff = now - _dt.timedelta(days=days)
    n = 0
    for row in rows:
        when = _parse_ts(row.get("reverted_at"))
        if row.get("state") == "reverted" and when is not None and cutoff <= when <= now:
            n += 1
    return n


def outcome_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in OUTCOMES}
    for row in rows:
        if row.get("outcome") in counts:
            counts[row["outcome"]] += 1
    return counts


def auto_apply_stats(cfg_path: str | None = None, now: _dt.datetime | None = None) -> dict[str, Any]:
    """Everything /autoheal and the promotion check need, as one dict."""
    cfg_path = cfg_path or config_path()
    cfg = _load_config(cfg_path)
    now = now or now_utc()
    rows = _ledger().read_rows()
    decisions = read_jsonl(shadow_log_path("auto-apply"))
    since = _parse_ts(cfg.get(DEMOTED_KEY))
    stats = agreement(decisions, human_outcomes(rows), since)
    verdict = promotion_verdict(stats)
    targets = cfg.get("auto_apply_targets")
    return {
        "mode": auto_apply_mode_of(cfg),
        "promoted_at": cfg.get(PROMOTED_KEY),
        "demoted_at": cfg.get(DEMOTED_KEY),
        "demoted_reason": cfg.get(DEMOTED_REASON_KEY),
        **stats,
        "agreement": verdict["agreement"],
        "ready_for_active": verdict["ready"],
        "reasons": verdict["reasons"],
        "outcomes": outcome_counts(rows),
        "reverts_30d": recent_reverts(rows, now),
        "auto_applied": sum(1 for r in rows if r.get("applied_by") == "auto"),
        "targets": targets if isinstance(targets, list) else [],
    }


def maybe_demote(cfg_path: str | None = None, now: _dt.datetime | None = None) -> str:
    """Drop active to shadow after DEMOTION_REVERTS reverts in the window. Returns a
    message when it demoted, else ""."""
    cfg_path = cfg_path or config_path()
    cfg = _load_config(cfg_path)
    if auto_apply_mode_of(cfg) != MODE_ACTIVE:
        return ""
    now = now or now_utc()
    n = recent_reverts(_ledger().read_rows(), now)
    if n < DEMOTION_REVERTS:
        return ""
    reason = f"{n} reverts in {DEMOTION_WINDOW_DAYS} days"
    cfg[AUTO_APPLY_KEY] = MODE_SHADOW
    cfg[DEMOTED_KEY] = now.isoformat()
    cfg[DEMOTED_REASON_KEY] = reason
    cfg.pop(PROMOTED_KEY, None)
    cfg.pop(LEGACY_AUTO_APPLY_KEY, None)
    _write_config(cfg_path, cfg)
    return f"auto-apply demoted to shadow: {reason}"


def render_report() -> str:
    """Markdown section for the digest. Empty when no shadow log exists."""
    decisions = read_jsonl(shadow_log_path("auto-apply"))
    alerts = read_jsonl(shadow_log_path("realtime"))
    if not decisions and not alerts:
        return ""
    lines = ["## Shadow rollout", ""]
    if decisions:
        s = auto_apply_stats()
        lines += [
            f"- auto-apply mode: {s['mode']}",
            f"- shadow auto-apply decisions: {s['decisions']}",
            f"- agreed: {s['agreed']} of {s['decided']} decided",
            f"- disagreed: {s['false_positives'] + s['false_negatives']} "
            f"({s['false_positives']} false positive, {s['false_negatives']} false negative)",
            f"- pending (no review decision yet): {s['pending']}",
            f"- would-apply fixes later harmful or reverted: {s['harmful']}",
        ]
        if s["ready_for_active"]:
            lines.append(f"- promotion bar met ({s['decided']} decided, {s['agreement']:.0%} agreement): "
                         "`/autoheal-toggle autoapply active` is allowed")
        else:
            lines.append(f"- promotion bar not met: {'; '.join(s['reasons'])}")
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


def _write_config(cfg_path: str, cfg: dict) -> None:
    parent = os.path.dirname(os.path.abspath(cfg_path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, cfg_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_flag(cfg_path: str, flag: str, value: str) -> tuple[str, str]:
    """Set one flag to a mode and return (config key, stored mode). Preserves
    every other key and writes atomically. Raises ValueError on a bad flag or
    value and PromotionRefused when auto-apply has not earned active; either
    way the file is untouched."""
    if flag not in FLAGS:
        raise ValueError(f"unknown flag {flag!r} (expected one of {', '.join(FLAGS)})")
    mode = _SET_VALUES.get(value.strip().lower())
    if mode is None:
        raise ValueError(f"unknown mode {value!r} (expected on, off, shadow or active)")
    cfg = _load_config(cfg_path)
    key = FLAGS[flag]
    if flag == "autoapply":
        if mode == MODE_ACTIVE and auto_apply_mode_of(cfg) != MODE_ACTIVE:
            verdict = auto_apply_stats(cfg_path)
            if not verdict["ready_for_active"]:
                raise PromotionRefused("auto-apply stays " + auto_apply_mode_of(cfg) + ": "
                                       + "; ".join(verdict["reasons"])
                                       + f" (the bar is {PROMOTION_MIN_DECIDED} decided decisions at "
                                       f"{PROMOTION_MIN_AGREEMENT:.0%} agreement or better, none harmful)")
            cfg[PROMOTED_KEY] = now_utc().isoformat()
        elif mode != MODE_ACTIVE:
            cfg.pop(PROMOTED_KEY, None)
        cfg.pop(LEGACY_AUTO_APPLY_KEY, None)
    cfg[key] = mode
    _write_config(cfg_path, cfg)
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
        if cmd == "stats" and len(argv) == 3:
            print(json.dumps(auto_apply_stats(argv[2]), indent=2))
            return 0
        if cmd == "report" and len(argv) == 2:
            sys.stdout.write(render_report())
            return 0
    except PromotionRefused as exc:
        print(f"autoheal_mode: refused: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"autoheal_mode: {exc}", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
