#!/usr/bin/env python3
"""Deterministic weekly observability scorecard for the dreaming/read-path
memory system.

The honest answer to "how do I know the memory system is working": a
deterministic weekly aggregation over the read-path signals that are ALREADY
being recorded on disk. Every number here is a count of something that
happened -- captured / injected / reused / applied -- so this is a script,
not model work (latent-vs-deterministic: pure mechanical counting, no
judgment). It is testable to exact counts by feeding fixture JSONL to
`render()`.

READ-ONLY, by contract. This module never writes to the learnings store, the
proposals, the apply-audit, or any dreaming state. It only reads. The `.sh`
wrapper is the only thing that writes -- and only the rendered markdown, to
~/.claude/dreaming/scorecards/{date}.md.

NO `Date.now()` in this library. The window bounds AND the generated-at
timestamp are passed in by the caller (`render(..., generated_at=...)`), so a
test can pin a fixed clock and assert byte-stable output. The `.sh` wrapper
supplies the real wall clock.

Data sources (all read-only):
  - Captured / Reused: raw op-event JSONL under `learnings_dir`
    ({slug}/learnings.jsonl + {slug}/agents/*.jsonl). These sections are
    WINDOW-scoped and need each op-event's own `timestamp`, which the store's
    projected head view does not expose (a head records `uses`/`last_verified`
    only, not each individual verify's time) -- so they are read from the raw
    lines directly, exactly as the issue's §1/§3 specify ("from the store
    JSONL timestamp", "verify op-events in the window").
  - Store health: the SAME raw lines, projected through `store_api`'s existing
    projection engine (`_project_lines`) and scored with its existing
    `effective_confidence`. `store_api` is used purely as a pair of pure
    functions here -- it never touches its own global LEARNINGS_ROOT, so the
    scorecard has a single data source (`learnings_dir`) and stays trivially
    testable.
  - Injected: ~/.claude/dreaming/injection-log/*.jsonl (#782 telemetry).
  - Applied: the apply-audit (~/.claude/dreaming/state/apply-audit.jsonl,
    which carries the authoritative applied-at `ts`) cross-referenced with the
    proposals dir (~/.claude/dreaming/proposals/*.jsonl) for the
    generated->applied funnel.
  - Optimistic integration (optimistic-memory plan.md Epic 7): auto-integrated
    counts and circuit-breaker trips are read from the SAME apply-audit rows
    Applied already loads (`method == "auto_apply"` and `outcome ==
    "circuit_breaker_tripped"` respectively -- both already written today by
    Epic 3's run_optimistic_integrate()/record_anomaly()). Mid-dwell is read
    from the SAME projected heads Store health already computes
    (`store_api.is_dwelling(head, now=...)`). "Currently suspended" is read
    from ~/.claude/dreaming/state/optimistic.json -- a SIBLING of
    apply-audit.jsonl under the same `state/` dir in every real deployment, so
    its path is derived from `apply_audit_path` rather than threaded through
    as a new `render()` parameter (keeps the `.sh` wrapper's call site
    unchanged). "reverted-after-review" reads an `outcome == "reverted"`
    apply-audit record -- a convention this Epic establishes for Epic 6
    (`/dream-review` veto/revert, #804, not yet built as of this Epic) to
    write, mirroring every other state-changing action in
    apply_dream_proposal.py (exactly one `_write_audit()` call per action)
    rather than inferring a revert after the fact from op-event archaeology.
    Until Epic 6 ships that write, this legitimately reads 0 -- an accurate
    "nothing reverted yet" answer, not a broken counter.

Every section degrades gracefully: a missing/empty source prints
"_no data this window._" and never raises. The optimistic-integration
section is the one exception to the "_no data_" fallback (matching Store
health's own convention): it always renders concrete counts, including 0,
since a missing apply-audit/state file is a fully-determined "zero activity"
answer here, not an "unknown" one.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Effective-confidence bands for the store-health section. Documented here so
# the thresholds are one obvious place, not scattered magic numbers. The
# store's own read path skips entries below its deprecate_threshold (default
# 2.0) -- low-band entries at the bottom of this range are effectively dormant
# even though they are structurally still "active".
_BAND_HIGH = 7.0   # >= 7.0  -> "high"
_BAND_MEDIUM = 4.0  # >= 4.0 and < 7.0 -> "medium"; < 4.0 -> "low"

# A learning-store op-event is "captured" (a new learning) when it is a v2
# `add` event OR a legacy v1 row (which carries no `op` field and seeds a head
# verbatim -- see learnings_store._fold).
_CAPTURE_OPS = (None, "add")

_NO_DATA = "_no data this window._"


# ---------------------------------------------------------------------------
# Time helpers (no wall-clock reads -- everything is passed in)
# ---------------------------------------------------------------------------

def _to_epoch(value: "datetime | date | str | float | int") -> float:
    """Normalize a window bound / generated-at value to epoch seconds.

    Accepts an aware or naive datetime (naive is assumed UTC), a date
    (midnight UTC), an ISO-8601 string, or a raw epoch number. Deterministic:
    no `now()` fallback -- an unparseable value yields 0.0.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
    if isinstance(value, str):
        return _parse_ts(value)
    return 0.0


def _parse_ts(s: str) -> float:
    """Parse an on-disk ISO-8601 UTC timestamp to epoch seconds; 0.0 on
    failure. Handles the store/injection-log forms (second- or
    millisecond-precision, trailing `Z`) plus a general `fromisoformat`
    fallback for anything else that lands on disk."""
    if not s or not isinstance(s, str):
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def _in_window(ts: float, start: float, end: float) -> bool:
    """Half-open window [start, end): a record stamped exactly at `end` belongs
    to the NEXT window, so consecutive weekly windows partition time without
    double-counting a boundary event."""
    return start <= ts < end


def _fmt_dt(value: "datetime | date | str | float") -> str:
    """Human-readable UTC stamp for the header (deterministic from input)."""
    epoch = _to_epoch(value)
    if epoch <= 0:
        return str(value)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_date(value: "datetime | date | str | float") -> str:
    epoch = _to_epoch(value)
    if epoch <= 0:
        return str(value)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# JSONL reading (defensive -- never raises on a bad/missing file)
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse every line of one JSONL file, skipping malformed/blank lines.
    Missing file -> []."""
    rows: list[dict[str, Any]] = []
    try:
        if not path.is_file():
            return rows
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return rows
    return rows


def _load_jsonl_dir(directory: Path) -> list[dict[str, Any]]:
    """Concatenate every `*.jsonl` file in a directory (sorted for
    determinism). Missing dir -> []."""
    rows: list[dict[str, Any]] = []
    try:
        if not directory.is_dir():
            return rows
        for path in sorted(directory.glob("*.jsonl")):
            rows.extend(_load_jsonl(path))
    except OSError:
        return rows
    return rows


def _load_json_object(path: Path) -> dict[str, Any]:
    """Parse one JSON-object file (e.g. state/optimistic.json -- a single
    object, NOT one-per-line JSONL). Missing file, unreadable file, or
    non-object JSON -> {} (never raises), mirroring the JSONL loaders'
    defensive philosophy above. Read-only: never creates or touches the
    file when it is missing."""
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dedupe_by_id(lines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate op-events by event `id` (first occurrence wins),
    mirroring learnings_store._dedupe_lines_by_id so a physically duplicated
    line (e.g. from a future git union-merge) can never double-count a capture
    or a reuse. Lines without an `id` are kept as-is."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ln in lines:
        _id = ln.get("id")
        if _id is not None:
            if _id in seen:
                continue
            seen.add(_id)
        out.append(ln)
    return out


def _slug_sources(learnings_dir: Path) -> list[tuple[str, list[Path]]]:
    """Enumerate (slug, [jsonl paths]) for every project dir under the store
    root, mirroring learnings_store.list_project_slugs' detection (a legacy
    learnings.jsonl and/or an agents/ shard dir). Single source of truth: the
    scorecard reads ONLY from `learnings_dir`."""
    out: list[tuple[str, list[Path]]] = []
    try:
        if not learnings_dir.is_dir():
            return out
        for d in sorted(learnings_dir.iterdir()):
            if not d.is_dir():
                continue
            paths: list[Path] = []
            legacy = d / "learnings.jsonl"
            if legacy.is_file():
                paths.append(legacy)
            agents = d / "agents"
            if agents.is_dir():
                paths.extend(sorted(agents.glob("*.jsonl")))
            if paths:
                out.append((d.name, paths))
    except OSError:
        return out
    return out


def _read_slug_lines(paths: list[Path]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for p in paths:
        lines.extend(_load_jsonl(p))
    return _dedupe_by_id(lines)


# ---------------------------------------------------------------------------
# Section aggregators (each pure over already-read rows; individually testable)
# ---------------------------------------------------------------------------

def _aggregate_captured_reused(
    slug_lines: dict[str, list[dict[str, Any]]],
    start: float,
    end: float,
) -> dict[str, Any]:
    """Walk every slug's raw op-events once and bucket the window-scoped
    captures (add / legacy rows) and reuses (verify events)."""
    captured_by_type_project: dict[tuple[str, str], int] = defaultdict(int)
    captured_total = 0
    refined_total = 0
    reused_events = 0
    reused_by_target: dict[str, int] = defaultdict(int)

    for slug, lines in slug_lines.items():
        for ln in lines:
            ts = _parse_ts(ln.get("timestamp", ""))
            if not _in_window(ts, start, end):
                continue
            op = ln.get("op")
            if op in _CAPTURE_OPS:
                type_ = ln.get("type") or "unknown"
                captured_by_type_project[(type_, slug)] += 1
                captured_total += 1
            elif op == "supersede":
                # A supersede is a REFINEMENT of an existing learning, not a
                # new capture -- counted separately so a week of refinements
                # is not invisible (it would read as 0 "new") while keeping
                # "Captured" strictly add-only.
                refined_total += 1
            elif op == "verify":
                target = ln.get("target_id")
                if target:
                    reused_by_target[target] += 1
                    reused_events += 1

    return {
        "captured_total": captured_total,
        "captured_by_type_project": dict(captured_by_type_project),
        "refined_total": refined_total,
        "reused_events": reused_events,
        "reused_learnings": len(reused_by_target),
        "reused_by_target": dict(reused_by_target),
    }


def _aggregate_injected(rows: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    sessions: set[str] = set()
    total_injected = 0
    id_freq: Counter[str] = Counter()
    records = 0
    for r in rows:
        if not _in_window(_parse_ts(r.get("timestamp", "")), start, end):
            continue
        records += 1
        sid = str(r.get("session_id") or "")
        if sid:
            sessions.add(sid)
        try:
            total_injected += int(r.get("injected_count") or 0)
        except (TypeError, ValueError):
            pass
        for lid in r.get("injected_ids") or []:
            if lid:
                id_freq[str(lid)] += 1
    return {
        "records": records,
        "sessions": len(sessions),
        "total_injected": total_injected,
        "top_injected": id_freq.most_common(10),
    }


def _aggregate_applied(
    audit_rows: list[dict[str, Any]],
    proposal_rows: list[dict[str, Any]],
    start: float,
    end: float,
) -> dict[str, Any]:
    """Applied = apply-audit records whose outcome is a successful apply and
    whose `ts` is in-window (the audit carries the authoritative applied-at
    time). Cross-referenced with proposals generated in-window for the
    generated->applied funnel."""
    applied_by_kind: Counter[str] = Counter()
    applied_total = 0
    for r in audit_rows:
        if not (r.get("ok") is True or r.get("outcome") == "applied"):
            continue
        if not _in_window(_parse_ts(r.get("ts", "")), start, end):
            continue
        applied_total += 1
        applied_by_kind[str(r.get("kind") or "unknown")] += 1

    generated = 0
    still_pending = 0
    for p in proposal_rows:
        if not _in_window(_parse_ts(p.get("generated_at", "")), start, end):
            continue
        generated += 1
        if p.get("status", "pending") == "pending":
            still_pending += 1

    return {
        "applied_total": applied_total,
        "applied_by_kind": dict(applied_by_kind),
        "generated": generated,
        "still_pending": still_pending,
    }


def _aggregate_optimistic(
    audit_rows: list[dict[str, Any]],
    start: float,
    end: float,
) -> dict[str, Any]:
    """Window-scoped optimistic-integration signals (optimistic-memory
    plan.md Epic 7) -- read from the SAME apply-audit rows
    `_aggregate_applied` already loads; no new data source.

    auto-integrated: records the optimistic engine itself wrote
    (`method == "auto_apply"`, `outcome == "applied"` --
    `run_optimistic_integrate()`/`_process_one_proposal()` in
    apply_dream_proposal.py), grouped by the `posture` string already
    recorded on the same record (`resolve_posture()`'s
    optimistic-immediate/optimistic-dwell/dwell-quarantine/gated).

    reverted-after-review ("rows vetoed / reverts in the window"): see the
    module docstring's "Optimistic integration" paragraph for why this counts
    `outcome == "reverted"` -- a convention this Epic establishes for Epic 6
    (#804, not yet built) to write, rather than inferring a revert from
    op-event archaeology. Reads 0 until Epic 6 ships that write.

    circuit-breaker trips: `outcome == "circuit_breaker_tripped"` records
    already written today by `_evaluate_breaker_trip()`, from BOTH the
    end-of-batch check in `run_optimistic_integrate()` and the standalone
    `record_anomaly()` path (a red eval-gate night that never reaches
    `run_optimistic_integrate()` at all) -- counting this outcome value
    catches both sources of a trip.
    """
    auto_integrated_total = 0
    auto_integrated_by_posture: Counter[str] = Counter()
    reverted_total = 0
    breaker_trips = 0

    for r in audit_rows:
        if not _in_window(_parse_ts(r.get("ts", "")), start, end):
            continue
        outcome = r.get("outcome")
        if outcome == "applied" and r.get("method") == "auto_apply":
            auto_integrated_total += 1
            auto_integrated_by_posture[str(r.get("posture") or "unknown")] += 1
        elif outcome == "reverted":
            reverted_total += 1
        elif outcome == "circuit_breaker_tripped":
            breaker_trips += 1

    return {
        "auto_integrated_total": auto_integrated_total,
        "auto_integrated_by_posture": dict(auto_integrated_by_posture),
        "reverted_total": reverted_total,
        "breaker_trips": breaker_trips,
    }


def _aggregate_health(
    slug_lines: dict[str, list[dict[str, Any]]],
    store_api: Any,
    now_epoch: float,
) -> dict[str, Any]:
    """Project every slug's raw lines through the store's own projection
    engine and band the ACTIVE heads (not deprecated, not superseded) by
    effective confidence. Uses `store_api` as two pure functions only
    (_project_lines + effective_confidence) -- no disk writes, no snapshot
    cache, no global-path coupling."""
    high = medium = low = 0
    active = deprecated = superseded = dwelling = 0
    for lines in slug_lines.values():
        try:
            heads = store_api._project_lines(lines).get("heads", [])
        except Exception:
            # A pathological shard must never sink the whole scorecard.
            continue
        for head in heads:
            if head.get("deprecated"):
                deprecated += 1
                continue
            if head.get("superseded_by"):
                superseded += 1
                continue
            active += 1
            try:
                eff = float(store_api.effective_confidence(head, now=now_epoch))
            except Exception:
                eff = 0.0
            if eff >= _BAND_HIGH:
                high += 1
            elif eff >= _BAND_MEDIUM:
                medium += 1
            else:
                low += 1
            # optimistic-memory plan.md Epic 7: a still-dwelling row is real,
            # active store content (only deprecated/superseded rows are
            # excluded from "active" above) -- it is additionally flagged
            # here as not-yet-read-eligible so the scorecard can surface it.
            try:
                if store_api.is_dwelling(head, now=now_epoch):
                    dwelling += 1
            except Exception:
                pass
    return {
        "active": active,
        "high": high,
        "medium": medium,
        "low": low,
        "deprecated": deprecated,
        "superseded": superseded,
        "dwelling": dwelling,
    }


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _sanitize(store_api: Any, text: str) -> str:
    """Render-time defense-in-depth for any store CONTENT surfaced in the
    scorecard (the reused-learnings section). Reuses the store's own
    sanitizer if available, matching dream-digest.sh's render-time
    neutralization; falls back to the raw text if the hook is unavailable."""
    fn = getattr(store_api, "sanitize_content", None)
    if callable(fn):
        try:
            return fn(text)
        except Exception:
            return text
    return text


def _excerpt(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(
    window_start: "datetime | date | str",
    window_end: "datetime | date | str",
    *,
    learnings_dir: "Path | str",
    injection_log_dir: "Path | str",
    proposals_dir: "Path | str",
    apply_audit_path: "Path | str",
    store_api: Any,
    generated_at: "datetime | date | str",
    now: "datetime | date | str | None" = None,
) -> str:
    """Render the weekly observability scorecard as a markdown string.

    Args:
        window_start / window_end: half-open window [start, end). Accept a
            datetime, date, or ISO string.
        learnings_dir: learnings-store root (contains {slug}/learnings.jsonl
            and/or {slug}/agents/*.jsonl).
        injection_log_dir: ~/.claude/dreaming/injection-log.
        proposals_dir: ~/.claude/dreaming/proposals.
        apply_audit_path: ~/.claude/dreaming/state/apply-audit.jsonl.
        store_api: the learnings_store module (used only for the pure
            functions _project_lines + effective_confidence + is_dwelling +
            optional sanitize_content).
        generated_at: report generation time, PASSED IN (no Date.now here).
        now: decay anchor for effective_confidence; defaults to window_end.

    All aggregation is deterministic; feed fixtures and assert exact counts.
    """
    learnings_dir = Path(learnings_dir)
    injection_log_dir = Path(injection_log_dir)
    proposals_dir = Path(proposals_dir)
    apply_audit_path = Path(apply_audit_path)
    # state/optimistic.json is a SIBLING of apply-audit.jsonl under state/ in
    # every real deployment (both dream_analyze.state_dir()-rooted) -- derived
    # here rather than threaded as a new render() parameter so the .sh
    # wrapper's call site needs no change (plan.md Epic 7).
    optimistic_state_path = apply_audit_path.parent / "optimistic.json"

    start = _to_epoch(window_start)
    end = _to_epoch(window_end)
    now_epoch = _to_epoch(now) if now is not None else end

    # --- Read every data source ONCE (read-only) ---------------------------
    slug_lines: dict[str, list[dict[str, Any]]] = {
        slug: _read_slug_lines(paths) for slug, paths in _slug_sources(learnings_dir)
    }
    injection_rows = _load_jsonl_dir(injection_log_dir)
    proposal_rows = _load_jsonl_dir(proposals_dir)
    audit_rows = _load_jsonl(apply_audit_path)
    optimistic_state = _load_json_object(optimistic_state_path)

    # --- Aggregate ---------------------------------------------------------
    cap = _aggregate_captured_reused(slug_lines, start, end)
    inj = _aggregate_injected(injection_rows, start, end)
    app = _aggregate_applied(audit_rows, proposal_rows, start, end)
    opt = _aggregate_optimistic(audit_rows, start, end)
    health = _aggregate_health(slug_lines, store_api, now_epoch)

    # Build an id -> content map only from the reused targets, so the reused
    # section can name what got reinforced. Projected across all slugs.
    reused_targets = set(cap["reused_by_target"])
    id_content: dict[str, str] = {}
    if reused_targets:
        for lines in slug_lines.values():
            try:
                heads = store_api._project_lines(lines).get("heads", [])
            except Exception:
                continue
            for head in heads:
                hid = head.get("id")
                if hid in reused_targets and hid not in id_content:
                    id_content[hid] = head.get("content") or ""

    out: list[str] = []

    # --- Header + one-line run summary (§6) --------------------------------
    # The window is half-open [start, end); the "week ending" date a human
    # cares about (and the filename the wrapper uses) is the LAST day actually
    # included -- one second before the exclusive end -- not the end bound
    # itself (which is next week's first instant).
    week_ending = _fmt_date(end - 1) if end > 0 else _fmt_date(window_end)
    out.append(f"# Dreaming scorecard — week ending {week_ending}")
    out.append("")
    out.append(
        f"_Window: {_fmt_dt(window_start)} → {_fmt_dt(window_end)} "
        f"· generated {_fmt_dt(generated_at)}_"
    )
    out.append("")
    out.append(
        f"**{cap['captured_total']} captured · {inj['sessions']} sessions injected "
        f"· {cap['reused_learnings']} learnings reused ({cap['reused_events']} events) "
        f"· {app['applied_total']} applied**"
    )
    out.append("")

    # --- 1. Captured -------------------------------------------------------
    out.append(f"## Captured — {cap['captured_total']} new learnings this window")
    out.append("")
    if cap["refined_total"]:
        # Refinements are real activity but not "new"; surface them so a week
        # of supersede-only work does not read as an empty capture section.
        out.append(f"_(+ {cap['refined_total']} refined via supersede)_")
        out.append("")
    if not cap["captured_total"]:
        # Only "no data" when there is neither a new capture NOR a refinement.
        if not cap["refined_total"]:
            out.append(_NO_DATA)
    else:
        out.append("| type | project | new |")
        out.append("|------|---------|-----|")
        for (type_, slug), n in sorted(
            cap["captured_by_type_project"].items(), key=lambda kv: (-kv[1], kv[0])
        ):
            out.append(f"| {type_} | {slug} | {n} |")
    out.append("")

    # --- 2. Injected -------------------------------------------------------
    out.append("## Injected")
    out.append("")
    if not inj["records"]:
        out.append(_NO_DATA)
    else:
        out.append(
            f"- {inj['sessions']} session(s) received injected memory "
            f"({inj['records']} injection event(s))"
        )
        out.append(f"- {inj['total_injected']} total learnings injected")
        if inj["top_injected"]:
            out.append("- top injected learnings:")
            for lid, freq in inj["top_injected"]:
                out.append(f"  - `{lid}` — {freq}×")
    out.append("")

    # --- 3. Reused (the key value signal) ----------------------------------
    out.append(
        f"## Reused — {cap['reused_learnings']} learnings reinforced "
        f"({cap['reused_events']} reuse events)"
    )
    out.append("")
    out.append(
        "_Recurrence is the signal that memory is paying off across sessions: "
        "a `verify` op-event means a stored learning got reused._"
    )
    out.append("")
    if not cap["reused_events"]:
        out.append(_NO_DATA)
    else:
        ranked = sorted(cap["reused_by_target"].items(), key=lambda kv: (-kv[1], kv[0]))
        for target, n in ranked:
            content = _excerpt(_sanitize(store_api, id_content.get(target, "")))
            suffix = f" — {content}" if content else ""
            out.append(f"- `{target}` — {n}× reused{suffix}")
    out.append("")

    # --- 4. Applied --------------------------------------------------------
    out.append(f"## Applied — {app['applied_total']} proposals applied this window")
    out.append("")
    if not app["applied_total"] and not app["generated"]:
        out.append(_NO_DATA)
    else:
        out.append(
            f"- generated this window: {app['generated']} "
            f"({app['still_pending']} still pending review)"
        )
        out.append(f"- applied this window: {app['applied_total']}")
        if app["applied_by_kind"]:
            for kind, n in sorted(app["applied_by_kind"].items(), key=lambda kv: (-kv[1], kv[0])):
                out.append(f"  - {kind}: {n}")
    out.append("")

    # --- 4b. Optimistic integration (plan.md Epic 7) ------------------------
    # Unlike every section above, this one never falls back to _NO_DATA: a
    # missing apply-audit/state file is a fully-determined "zero activity"
    # answer here (matching Store health's own always-numeric convention),
    # not an "unknown" one.
    out.append(
        f"## Optimistic integration — {opt['auto_integrated_total']} auto-integrated · "
        f"{health['dwelling']} mid-dwell · {opt['reverted_total']} reverted · "
        f"{opt['breaker_trips']} breaker trips"
    )
    out.append("")
    out.append(f"- auto-integrated this window: {opt['auto_integrated_total']}")
    if opt["auto_integrated_by_posture"]:
        for posture, n in sorted(
            opt["auto_integrated_by_posture"].items(), key=lambda kv: (-kv[1], kv[0])
        ):
            out.append(f"  - {posture}: {n}")
    out.append(f"- mid-dwell (currently, all projects): {health['dwelling']}")
    out.append(f"- reverted after review (veto/batch-revert) this window: {opt['reverted_total']}")
    out.append(f"- circuit-breaker trips this window: {opt['breaker_trips']}")
    if optimistic_state.get("suspended"):
        since = optimistic_state.get("suspended_at") or "unknown time"
        out.append(f"- currently suspended: yes (since {since})")
    else:
        out.append("- currently suspended: no")
    out.append("")

    # --- 5. Store health ---------------------------------------------------
    out.append(f"## Store health — {health['active']} active learnings")
    out.append("")
    out.append("- effective-confidence bands (active heads):")
    out.append(f"  - high (≥{_BAND_HIGH:.0f}): {health['high']}")
    out.append(f"  - medium (≥{_BAND_MEDIUM:.0f}): {health['medium']}")
    out.append(f"  - low (<{_BAND_MEDIUM:.0f}): {health['low']}")
    out.append(f"- deprecated: {health['deprecated']}")
    out.append(f"- superseded: {health['superseded']}")
    out.append("")

    out.append("---")
    out.append("")
    out.append("- `/dream` — status")
    out.append("- `/dream-digest` — today's proposal digest")
    out.append("")

    return "\n".join(out)
