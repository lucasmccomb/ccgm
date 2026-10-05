#!/usr/bin/env python3
"""Recurrence metric: does an injected learning change what the agent does?
(#1098 Phase 4.1, redesign §3.5). Deterministic, no API calls.

Every dreamed learning carries a `trigger` (lib/triggers.py), copied onto its
store row at integration. Each night this step scans the transcript bytes
appended since its last run, records which triggers fired in which session,
joins that with the injection log (which sessions had which learning
injected), and compares each learning's hit rate in exposed sessions with
its hit rate in the 30 days before it was integrated.

What is scanned, per transcript line (`scan_texts()`):

  * assistant tool calls: the `command`, `file_path`, `notebook_path`,
    `path`, `pattern` and `url` inputs. Not file bodies or edit strings
    (`content`, `old_string`, `new_string`), which are code, not actions.
  * tool results with `is_error: true`: the error text.
  * typed human turns (the miner's human-origin gate), minus
    <system-reminder> blocks and harness wrappers.

Not scanned: assistant prose and thinking, successful tool output, system
reminders, and subagent prompts. Injected learnings reach the model through
reminders and the agent restates them in prose; scanning either would make
every exposed session "hit" its own learning. Subagent transcript lines
carry the parent's sessionId, so a subagent's tool calls count toward the
session that dispatched it (the one the injection log names).

Per learning, from the session table:

  exposed sessions   sessions whose injection-log record lists the learning,
                     started at or after it was integrated
  exposed hit rate   exposed sessions with at least one trigger hit / exposed
  baseline rate      sessions in the learning's scope (its slug, or every slug
                     for _global) started in the 30 days before integration
                     with a hit / those sessions. Computed once, by a one-time
                     scan when the learning is first seen.

Outcomes (decisions use exposed sessions since the last verify):

  avoided      >= 5 exposed and exposed rate <= half the baseline rate
               (baseline needs at least one hit)        -> auto `verify`
  ineffective  >= 5 exposed, >= 2 exposed hits, and exposed rate >= the
               baseline rate (>= 0.5 when no baseline sessions exist)
                                                        -> auto `deprecate`,
               with the engine's dwell and under its per-slug eviction cap
  dormant      integrated 45+ days ago and no hit in the last 45 days
                                                        -> no action; decay
                                                           retires it
  spike        a batch integrated in the last 7 days whose exposed sessions
               (>= 3) show >= 3 hits across all measured learnings and at
               least twice the hits their baselines predict -> a
               `recurrence_spike` content anomaly through
               apply_dream_proposal.record_anomaly(), which reverts the batch

Store writes happen only when optimistic integration is `active` and the
breaker is not suspended; otherwise the decision is recorded as held. A
`_global` learning is measured in every slug but never written: the store
refuses unattended verify/deprecate on `_global`, so it is held. Every
write is audited in state/apply-audit.jsonl in the engine's own shape
(`outcome: applied`, `method: auto_apply`, `posture: recurrence`), so the
health notice and the scorecard count it with no special case.

State (`state/recurrence.json`) is updated incrementally: its own per-file
byte cursors over the miner's discovery (`discover_with_offsets`), a session
table kept for 120 days, and the per-learning registry. History is never
rescanned, apart from the one-time baseline scan per new learning. When no
learning has a trigger, nothing is scanned.

`observed` rows written in-session carry no trigger and stay unmeasured;
`summary()` counts them so the scorecard can say so.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import breaker  # noqa: E402  (parse_iso / iso_from_epoch; stdlib only)
import triggers  # noqa: E402

STATE_FILENAME = "recurrence.json"
STATE_VERSION = 1
GLOBAL_SLUG = "_global"
DAY_S = 86400.0

MIN_EXPOSED_SESSIONS = 5
AVOIDED_MAX_RATIO = 0.5
MIN_INEFFECTIVE_HITS = 2
NO_BASELINE_INEFFECTIVE_RATE = 0.5
BASELINE_DAYS = 30
DORMANT_DAYS = 45
SPIKE_WINDOW_DAYS = 7
SPIKE_MIN_SESSIONS = 3
SPIKE_MIN_HITS = 3
SPIKE_FACTOR = 2.0
SESSION_KEEP_DAYS = 120

POSTURE = "recurrence"
ORIGINS = ("dreamed", "observed")
ACTIVE_STATUSES = ("measuring", "dormant")
SCANNED_INPUT_KEYS = ("command", "file_path", "notebook_path", "path", "pattern", "url")

_TM = None


def _tm():
    """transcript_miner, imported on first use: summary() callers (health,
    scorecard) never pay for it."""
    global _TM
    if _TM is None:
        import transcript_miner  # noqa: PLC0415
        _TM = transcript_miner
    return _TM


def _dreaming_dir() -> Path:
    return Path(os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))


def state_path() -> Path:
    return _dreaming_dir() / "state" / STATE_FILENAME


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION, "cursors": {}, "sessions": {}, "learnings": {},
        "unmeasured": {o: 0 for o in ORIGINS}, "spikes_reported": {}, "last_run": None,
    }


def read_state(path: "Path | str | None" = None) -> dict[str, Any]:
    """The state file, or an empty state when it is missing or unreadable.
    Losing the file costs one lookback-window rescan and fresh baselines."""
    state = _empty_state()
    try:
        data = json.loads(Path(path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        for key, default in state.items():
            if isinstance(data.get(key), type(default)) or (default is None and key in data):
                state[key] = data[key]
    return state


def _write_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=1), encoding="utf-8")
    tmp.replace(path)


def _epoch(value: Any) -> float | None:
    return breaker.parse_iso(value)


# ---------------------------------------------------------------------------
# What a transcript line contributes to the scan
# ---------------------------------------------------------------------------


def scan_texts(obj: Any) -> list[str]:
    """The texts in one transcript line that a trigger is matched against.
    See the module docstring for what is and is not scanned, and why."""
    if not isinstance(obj, dict):
        return []
    message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    content = message.get("content")
    out: list[str] = []
    if obj.get("type") == "assistant" and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                for key in SCANNED_INPUT_KEYS:
                    value = block["input"].get(key)
                    if isinstance(value, str) and value.strip():
                        out.append(value)
    elif obj.get("type") == "user":
        tm = _tm()
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    text = tm._text_from_content(block.get("content"))  # noqa: SLF001
                    if text.strip():
                        out.append(text)
        if not obj.get("isSidechain"):
            human = tm._clean_human_text({  # noqa: SLF001
                "role": "user", "human_origin": tm._is_human_origin_turn(obj),  # noqa: SLF001
                "is_meta": bool(obj.get("isMeta")), "text": tm._text_from_content(content),  # noqa: SLF001
            })
            if human:
                out.append(human)
    return out


def _in_scope(learning: dict[str, Any], slug: str | None) -> bool:
    return learning.get("slug") == GLOBAL_SLUG or (slug is not None and learning.get("slug") == slug)


# ---------------------------------------------------------------------------
# Registry: which learnings carry a trigger
# ---------------------------------------------------------------------------


def _sync_registry(state: dict[str, Any], ls: Any, slugs: list[str], batch_of: dict[str, str], now_iso: str) -> None:
    """Register every live store head with a valid trigger; mark registered
    heads that are no longer live `retired`; count live heads with no trigger
    by origin. Dreamed rows are written with source `inferred`."""
    learnings = state["learnings"]
    unmeasured = {o: 0 for o in ORIGINS}
    live_ids: set[str] = set()
    for slug in slugs:
        for head in ls.load_all(slug):
            if head.get("deprecated") or head.get("superseded_by"):
                continue
            hid = head.get("id")
            origin = "dreamed" if head.get("source") == "inferred" else "observed"
            trigger = head.get("trigger")
            if not hid or triggers.validate_trigger(trigger) is not None:
                unmeasured[origin] += 1
                continue
            live_ids.add(hid)
            if hid not in learnings:
                learnings[hid] = {
                    "slug": head.get("project") or slug, "origin": origin, "trigger": trigger,
                    "integrated_at": head.get("timestamp") or now_iso, "registered_at": now_iso,
                    "window_start": head.get("timestamp") or now_iso, "batch_id": batch_of.get(hid),
                    "content": (head.get("content") or "")[:300], "status": "measuring",
                    "baseline": None, "stats": None, "verified": 0, "last_decision": None,
                }
    for lid, entry in learnings.items():
        if entry.get("status") in ACTIVE_STATUSES and lid not in live_ids:
            entry["status"] = "retired"
    state["unmeasured"] = unmeasured


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _scan_file(path: Path, offset: int, slug: str | None, active: dict[str, dict[str, Any]],
               on_session: Any) -> int:
    """Feed every complete line after `offset` to on_session(sid, ts, hits).
    Returns the byte offset just past the last complete line."""
    tm = _tm()
    scoped = [(lid, entry["trigger"]) for lid, entry in active.items() if _in_scope(entry, slug)]
    end = offset
    for _lineno, obj, _start, line_end in tm._iter_jsonl(path, offset):  # noqa: SLF001
        end = line_end
        if obj is None or not isinstance(obj.get("sessionId"), str):
            continue
        texts = scan_texts(obj)
        hits = {lid for lid, trig in scoped if texts and triggers.matches_any(trig, texts)}
        on_session(obj["sessionId"], _epoch(obj.get("timestamp")), hits)
    return end


def _compute_baselines(state: dict[str, Any], active: dict[str, dict[str, Any]], projects_root: Path,
                       scan_slugs: list[str]) -> None:
    """One-time scan per new learning: hit rate in its scope over the 30
    days before it was integrated."""
    pending = {lid: e for lid, e in active.items() if e.get("baseline") is None}
    if not pending:
        return
    tm = _tm()
    windows = {lid: (_epoch(e["integrated_at"]) or 0.0) for lid, e in pending.items()}
    earliest = min(windows.values()) - BASELINE_DAYS * DAY_S
    wanted = set(scan_slugs) | {e["slug"] for e in pending.values() if e["slug"] != GLOBAL_SLUG}
    sessions: dict[str, dict[str, Any]] = {}

    for path, slug in tm._iter_slug_transcripts(sorted(wanted), projects_root):  # noqa: SLF001
        try:
            if path.stat().st_mtime < earliest:
                continue
        except OSError:
            continue

        def collect(sid: str, ts: float | None, hits: set[str], _slug: str = slug) -> None:
            rec = sessions.setdefault(sid, {"slug": _slug, "start": None, "hits": set()})
            if ts is not None and (rec["start"] is None or ts < rec["start"]):
                rec["start"] = ts
            rec["hits"] |= hits

        _scan_file(path, 0, slug, pending, collect)

    for lid, entry in pending.items():
        until = windows[lid]
        since = until - BASELINE_DAYS * DAY_S
        in_window = [s for s in sessions.values()
                     if s["start"] is not None and since <= s["start"] < until and _in_scope(entry, s["slug"])]
        entry["baseline"] = {
            "sessions": len(in_window), "hits": sum(1 for s in in_window if lid in s["hits"]),
            "since": breaker.iso_from_epoch(since), "until": breaker.iso_from_epoch(until),
        }


def _scan_new_bytes(state: dict[str, Any], active: dict[str, dict[str, Any]], projects_root: Path,
                    scan_slugs: list[str], lookback_days: int, now_iso: str) -> tuple[set[str], int]:
    """Scan what was appended since each file's cursor; update the session
    table and the cursors. Returns (touched session ids, files scanned)."""
    tm = _tm()
    cursors: dict[str, Any] = state["cursors"]
    sessions: dict[str, Any] = state["sessions"]
    due = tm.discover_with_offsets(scan_slugs, cursors=cursors, projects_root=projects_root,
                                   lookback_days=lookback_days)
    touched: set[str] = set()
    for key, offset in sorted(due.items()):
        path = Path(key)
        slug = tm._peek_slug(path)  # noqa: SLF001

        def record(sid: str, ts: float | None, hits: set[str], _slug: str | None = slug) -> None:
            rec = sessions.setdefault(sid, {"slug": _slug, "start": None, "first_scanned_at": now_iso,
                                             "hits": [], "exposed": []})
            if ts is not None and (_epoch(rec["start"]) is None or ts < _epoch(rec["start"])):
                rec["start"] = breaker.iso_from_epoch(ts)
            if hits - set(rec["hits"]):
                rec["hits"] = sorted(set(rec["hits"]) | hits)
            touched.add(sid)

        end = _scan_file(path, offset, slug, active, record)
        cursors[key] = {"slug": slug, "offset": end}
    for key in [k for k in cursors if not os.path.exists(k)]:
        del cursors[key]
    return touched, len(due)


def _read_injections(log_dir: Path, *, since: float) -> tuple[dict[str, set[str]], set[str]]:
    """({session_id: injected learning ids}, slugs seen) from the injection
    log files dated within the session window."""
    out: dict[str, set[str]] = {}
    slugs: set[str] = set()
    cutoff = datetime.fromtimestamp(since, tz=timezone.utc).date().isoformat()
    if not log_dir.is_dir():
        return out, slugs
    for path in sorted(log_dir.glob("*.jsonl")):
        if path.stem < cutoff:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not row.get("session_id"):
                continue
            ids = row.get("injected_ids") if isinstance(row.get("injected_ids"), list) else []
            out.setdefault(str(row["session_id"]), set()).update(str(i) for i in ids if i)
            if isinstance(row.get("project_slug"), str):
                slugs.add(row["project_slug"])
    return out, slugs


# ---------------------------------------------------------------------------
# Per-learning stats and decisions
# ---------------------------------------------------------------------------


def _stats(lid: str, entry: dict[str, Any], sessions: dict[str, Any], now: float) -> dict[str, Any]:
    integrated = _epoch(entry["integrated_at"]) or 0.0
    window_start = max(integrated, _epoch(entry.get("window_start")) or 0.0)
    exposed = [s for s in sessions.values()
               if lid in s.get("exposed", []) and (_epoch(s.get("start")) or -1.0) >= integrated]
    window = [s for s in exposed if (_epoch(s.get("start")) or -1.0) >= window_start]
    recent_cut = now - DORMANT_DAYS * DAY_S
    recent_hit = any(lid in s.get("hits", []) and (_epoch(s.get("start")) or -1.0) >= max(recent_cut, integrated)
                     for s in sessions.values() if _in_scope(entry, s.get("slug")))
    base = entry.get("baseline") or {}
    return {
        "exposed_sessions": len(exposed), "exposed_hits": sum(1 for s in exposed if lid in s.get("hits", [])),
        "window_sessions": len(window), "window_hits": sum(1 for s in window if lid in s.get("hits", [])),
        "baseline_sessions": int(base.get("sessions") or 0), "baseline_hits": int(base.get("hits") or 0),
        "hit_in_last_45_days": recent_hit,
    }


def decide(entry: dict[str, Any], stats: dict[str, Any], now: float) -> str | None:
    """"avoided", "ineffective", "dormant", or None (keep measuring)."""
    n, hits = stats["window_sessions"], stats["window_hits"]
    b_sessions, b_hits = stats["baseline_sessions"], stats["baseline_hits"]
    if n >= MIN_EXPOSED_SESSIONS:
        rate = hits / n
        b_rate = b_hits / b_sessions if b_sessions else None
        if b_rate and rate <= AVOIDED_MAX_RATIO * b_rate:
            return "avoided"
        floor = b_rate if b_rate is not None else NO_BASELINE_INEFFECTIVE_RATE
        if hits >= MIN_INEFFECTIVE_HITS and rate >= floor:
            return "ineffective"
    age = now - (_epoch(entry["integrated_at"]) or now)
    if age >= DORMANT_DAYS * DAY_S and not stats["hit_in_last_45_days"]:
        return "dormant"
    return None


def _evictions_today(audit: list[dict[str, Any]], slug: str, today: str) -> int:
    return sum(
        1 for a in audit
        if a.get("outcome") == "applied" and a.get("method") == "auto_apply" and a.get("project") == slug
        and a.get("kind") in ("learning_deprecate", "learning_contradict") and str(a.get("ts", "")).startswith(today)
    )


def _act(adp: Any, lid: str, entry: dict[str, Any], outcome: str, stats: dict[str, Any], *, ctx: dict[str, Any]) -> str:
    """Apply one decision, or say why it is held. Returns the action label."""
    kind = "learning_verify" if outcome == "avoided" else "learning_deprecate"
    if ctx["mode"] != "active":
        return f"held:{ctx['mode']}"
    if ctx["suspended"]:
        return "held:breaker_suspended"
    slug = entry["slug"]
    if slug == GLOBAL_SLUG:
        # The store refuses unattended verify/deprecate on _global (its admin
        # gate); attempting it would fail and audit every night.
        return "held:global_scope"
    opt_cfg = ctx["opt_cfg"]
    if kind == "learning_deprecate":
        live = ctx["live_counts"].setdefault(slug, adp._live_head_count(slug))  # noqa: SLF001
        cap = min(float(opt_cfg.get("max_eviction_absolute", 0)),
                  float(opt_cfg.get("max_eviction_fraction_per_run", 0)) * live)
        used = _evictions_today(ctx["audit"], slug, ctx["today"]) + ctx["evicted"].get(slug, 0)
        if used >= cap:
            return "held:over_cap"

    row = {"kind": kind, "project": slug, "target_id": lid}
    with adp._apply_lock():  # noqa: SLF001
        if kind == "learning_verify":
            result = adp._apply_learning_verify(row, reviewed_by=POSTURE, method="auto_apply")  # noqa: SLF001
        else:
            result = adp._apply_learning_deprecate(  # noqa: SLF001
                row, reviewed_by=POSTURE, method="auto_apply", dwell_hours=float(opt_cfg.get("dwell_hours", 24)))
    applied = result.get("outcome") == "applied"
    record = {
        "outcome": result.get("outcome"), "ok": applied, "method": "auto_apply", "posture": POSTURE,
        "kind": kind, "project": slug, "target_id": lid, "batch_id": ctx["run_id"], "reviewed_by": POSTURE,
        "recurrence": {"decision": outcome, **stats},
    }
    if result.get("detail"):
        record["detail"] = result["detail"]
    if applied:
        record["content"] = entry.get("content") or ""
        ctx["applied"] += 1
        if kind == "learning_deprecate":
            ctx["evicted"][slug] = ctx["evicted"].get(slug, 0) + 1
    adp._write_audit(record)  # noqa: SLF001
    return str(result.get("outcome"))


def _batches(audit: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{batch_id: {"ts", "ids"}} for optimistic-integrate batches that added
    or superseded learnings."""
    out: dict[str, dict[str, Any]] = {}
    for a in audit:
        bid = a.get("batch_id")
        if (a.get("outcome") != "applied" or a.get("method") != "auto_apply" or not isinstance(bid, str)
                or not bid.startswith("optbatch_") or a.get("kind") not in ("learning_add", "learning_supersede")
                or not a.get("new_entry_id")):
            continue
        ts = _epoch(a.get("ts"))
        b = out.setdefault(bid, {"ts": ts, "ids": []})
        if ts is not None and (b["ts"] is None or ts < b["ts"]):
            b["ts"] = ts
        b["ids"].append(a["new_entry_id"])
    return out


def _spike_numbers(batch: dict[str, Any], state: dict[str, Any],
                   active: dict[str, dict[str, Any]]) -> tuple[int, int, float]:
    """(exposed sessions, observed hits, expected hits) across every measured
    learning, in sessions exposed to the batch. A learning counts in a
    session only when it was already registered when that session was first
    scanned, and only when its baseline is known."""
    ids = set(batch["ids"])
    exposed = [s for s in state["sessions"].values()
               if set(s.get("exposed", [])) & ids and (_epoch(s.get("start")) or -1.0) >= batch["ts"]]
    observed, expected = 0, 0.0
    for s in exposed:
        first = _epoch(s.get("first_scanned_at")) or 0.0
        for lid, entry in active.items():
            base = entry.get("baseline") or {}
            if not base.get("sessions") or not _in_scope(entry, s.get("slug")):
                continue
            if (_epoch(entry.get("registered_at")) or 0.0) > first:
                continue
            expected += base["hits"] / base["sessions"]
            observed += 1 if lid in s.get("hits", []) else 0
    return len(exposed), observed, expected


def _check_spikes(adp: Any, state: dict[str, Any], active: dict[str, dict[str, Any]], audit: list[dict[str, Any]],
                  now: float, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    reported = state["spikes_reported"]
    reverted = set(adp._read_optimistic_state().get("reverted_batches") or [])  # noqa: SLF001
    out = []
    for bid, batch in sorted(_batches(audit).items()):
        if bid in reported or bid in reverted or batch["ts"] is None or now - batch["ts"] > SPIKE_WINDOW_DAYS * DAY_S:
            continue
        n, observed, expected = _spike_numbers(batch, state, active)
        if n < SPIKE_MIN_SESSIONS or observed < SPIKE_MIN_HITS or observed < SPIKE_FACTOR * expected:
            continue
        spike = {"batch_id": bid, "exposed_sessions": n, "observed_hits": observed,
                 "expected_hits": round(expected, 4), "at": ctx["now_iso"]}
        if ctx["mode"] == "active":
            result = adp.record_anomaly("recurrence_spike", batch_ids=[bid])
            spike.update(action="anomaly_recorded", reverted=result.get("reverted") or [],
                         circuit_breaker=result.get("circuit_breaker"))
        else:
            spike["action"] = f"held:{ctx['mode']}"
        reported[bid] = spike
        out.append(spike)
    return out


# ---------------------------------------------------------------------------
# The nightly step
# ---------------------------------------------------------------------------


def run(*, now: float | None = None, projects_root: "Path | str | None" = None, day: str | None = None) -> dict[str, Any]:
    """Scan, measure, decide, act. Never calls a model."""
    import apply_dream_proposal as adp  # noqa: PLC0415  (heavy; only the nightly step needs it)
    import rollout_mode  # noqa: PLC0415

    now = time.time() if now is None else float(now)
    now_iso = breaker.iso_from_epoch(now)
    ls, da = adp.learnings_store, adp.da
    root = Path(projects_root) if projects_root else Path(ls.CLAUDE_PROJECTS_ROOT)
    cfg = da.load_config()
    opt_cfg = cfg.get("optimistic_integration") or {}
    state = read_state()
    audit = adp._read_jsonl(adp.apply_audit_path())  # noqa: SLF001
    batch_of = {i: bid for bid, b in _batches(audit).items() for i in b["ids"]}

    store_slugs = ls.list_project_slugs()
    _sync_registry(state, ls, store_slugs, batch_of, now_iso)
    active = {lid: e for lid, e in state["learnings"].items() if e.get("status") in ACTIVE_STATUSES}
    run_id = f"recurrence_{uuid.uuid4().hex[:12]}"
    report: dict[str, Any] = {
        "day": day or datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat(), "at": now_iso,
        "run_id": run_id, "files_scanned": 0, "sessions_touched": 0, "learnings_measured": len(active),
        "decisions": [], "spikes": [],
    }
    if active:
        injections, inj_slugs = _read_injections(_dreaming_dir() / "injection-log",
                                                 since=now - SESSION_KEEP_DAYS * DAY_S)
        scan_slugs = sorted((set(store_slugs) | inj_slugs) - {GLOBAL_SLUG})
        _compute_baselines(state, active, root, scan_slugs)
        touched, files = _scan_new_bytes(state, active, root, scan_slugs, int(cfg.get("lookback_days", 7)), now_iso)
        report.update(files_scanned=files, sessions_touched=len(touched))
        known = set(state["learnings"])
        for sid in touched:
            rec = state["sessions"][sid]
            rec["exposed"] = sorted((set(rec.get("exposed", [])) | injections.get(sid, set())) & known)
        cut = now - SESSION_KEEP_DAYS * DAY_S
        state["sessions"] = {sid: s for sid, s in state["sessions"].items()
                             if (_epoch(s.get("start")) or _epoch(s.get("first_scanned_at")) or 0.0) >= cut}

        ctx = {
            "mode": rollout_mode.resolve_mode(opt_cfg.get("enabled")),
            "suspended": bool(adp._read_optimistic_state().get("suspended")),  # noqa: SLF001
            "opt_cfg": opt_cfg, "audit": audit, "run_id": run_id, "now_iso": now_iso,
            # Wall-clock date, not `now`: it is matched against apply-audit
            # `ts` values, which _write_audit stamps with the wall clock.
            "today": datetime.fromtimestamp(time.time(), tz=timezone.utc).date().isoformat(),
            "live_counts": {}, "evicted": {}, "applied": 0,
        }
        with adp._suppressed_autocommit():  # noqa: SLF001
            for lid, entry in sorted(active.items()):
                stats = _stats(lid, entry, state["sessions"], now)
                entry["stats"] = stats
                outcome = decide(entry, stats, now)
                if outcome == "dormant":
                    entry["status"] = "dormant"
                    continue
                entry["status"] = "measuring"
                if outcome is None:
                    continue
                action = _act(adp, lid, entry, outcome, stats, ctx=ctx)
                decision = {"learning_id": lid, "slug": entry["slug"], "outcome": outcome, "action": action, **stats}
                entry["last_decision"] = {"at": now_iso, "outcome": outcome, "action": action}
                if action == "applied" and outcome == "avoided":
                    entry["verified"] = int(entry.get("verified") or 0) + 1
                    entry["window_start"] = now_iso
                elif action == "applied":
                    entry["status"] = "deprecated"
                report["decisions"].append(decision)
        if ctx["applied"]:
            report["commit"] = adp._run_sync_commit(message=f"dreaming: recurrence {run_id}")  # noqa: SLF001
        report["spikes"] = _check_spikes(adp, state, active, adp._read_jsonl(adp.apply_audit_path()), now, ctx)  # noqa: SLF001

    state["last_run"] = {k: report[k] for k in ("day", "at", "run_id", "files_scanned", "sessions_touched",
                                                "learnings_measured")}
    state["last_run"].update(decisions=len(report["decisions"]), spikes=len(report["spikes"]))
    _write_state(state)
    return report


# ---------------------------------------------------------------------------
# Read-only summary (health.json, scorecard)
# ---------------------------------------------------------------------------


def summary(state: dict[str, Any]) -> dict[str, Any]:
    """Recurrence reduction across measured learnings, split by origin.

    reduction = 1 - observed / expected, where observed is the exposed
    sessions with a hit and expected is each learning's baseline rate times
    its exposed sessions, summed over learnings with a known baseline. None
    when nothing is expected yet. Negative means the mistakes got more
    frequent. `tracked` counts learnings with a trigger; `measured` the ones
    with at least one exposed session."""
    learnings = state.get("learnings") if isinstance(state.get("learnings"), dict) else {}
    unmeasured = state.get("unmeasured") if isinstance(state.get("unmeasured"), dict) else {}
    out: dict[str, Any] = {}
    for origin in ORIGINS:
        tracked = [e for e in learnings.values() if e.get("origin") == origin and isinstance(e.get("stats"), dict)]
        rows = [e for e in tracked if e["stats"].get("exposed_sessions")]
        observed, expected = 0, 0.0
        for e in rows:
            st = e["stats"]
            if st.get("baseline_sessions"):
                expected += st["baseline_hits"] / st["baseline_sessions"] * st.get("exposed_sessions", 0)
                observed += st.get("exposed_hits", 0)
        out[origin] = {
            "tracked": len(tracked),
            "measured": len(rows),
            "exposed_sessions": sum(e["stats"].get("exposed_sessions", 0) for e in rows),
            "observed_hits": observed, "expected_hits": round(expected, 4),
            "reduction": round(1 - observed / expected, 4) if expected > 0 else None,
            "unmeasured": int(unmeasured.get(origin) or 0),
        }
    statuses = [e.get("status") for e in learnings.values()]
    out["verified_total"] = sum(int(e.get("verified") or 0) for e in learnings.values())
    out["deprecated_total"] = statuses.count("deprecated")
    out["dormant"] = statuses.count("dormant")
    out["spikes_reported"] = len(state.get("spikes_reported") or {})
    last = state.get("last_run")
    out["last_run"] = last.get("day") if isinstance(last, dict) else None
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dreaming recurrence metric (#1098 Phase 4.1). No API calls.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="scan new transcript bytes, measure, and act")
    run_p.add_argument("--day")
    run_p.add_argument("--projects-root")
    sub.add_parser("summary", help="print the recurrence summary as JSON")
    args = ap.parse_args(argv)
    if args.cmd == "summary":
        print(json.dumps(summary(read_state()), sort_keys=True))
        return 0
    report = run(projects_root=args.projects_root, day=args.day)
    print(json.dumps({k: report[k] for k in ("day", "files_scanned", "sessions_touched", "learnings_measured")}
                     | {"decisions": [(d["learning_id"], d["outcome"], d["action"]) for d in report["decisions"]],
                        "spikes": [(s["batch_id"], s["action"]) for s in report["spikes"]]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
