#!/usr/bin/env python3
"""Circuit-breaker rules shared by apply_dream_proposal.py and health.py.

Pure functions over `state/optimistic.json`'s `anomaly_log` and the
apply-audit rows; no I/O and no imports beyond the standard library, so
health.py can use them without loading the apply engine.

Two anomaly classes (#1098 item 2.2):

* infra   -- the pipeline could not measure or run tonight: the eval gate
             paused (missing, stale, broken or budget-aborted results), the
             gate script itself failed, the analyzer failed, a batch timed
             out or found a dirty tree, or a regression no integrated batch
             can explain. Pauses that night's integration; never counts
             toward a trip.
* content -- something dreaming wrote may be bad: a batch-anomaly fire, an
             eval regression attributable to a batch integrated since the
             last green run, or a recurrence spike (the seam for the Phase 4
             recurrence metric). Counts toward a trip; a trip reverts the
             implicated batches.

`anomaly_log` entries are `{ts, reason, class, batch_ids}`. Entries written
before #1098 are bare ISO timestamps with no reason. `normalize_anomaly_log`
re-classifies them on read: a bare timestamp that the apply-audit pairs with
an `anomaly_recorded` row for an infra reason (the 89 nightly `red_eval_gate`
rows) is infra; any other bare timestamp may have been a batch anomaly and is
kept as content. Nothing is migrated on disk until the next state write.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

INFRA = "infra"
CONTENT = "content"

INFRA_REASONS = frozenset({
    "eval_gate_paused",
    "harness_failure",
    "analyze_failed",
    "timeout",
    "dirty_learnings_tree",
    "eval_regression_unattributed",
    "red_eval_gate",  # pre-#1098 name for every not-open gate night
})
CONTENT_REASONS = frozenset({
    "eval_regression",
    "batch_eviction_concentration",
    "session_citation_concentration",
    "rolling_add_rate_exceeded",
    "recurrence_spike",  # Phase 4 recurrence metric; recorded via record-anomaly
})

# Reason given to a pre-#1098 bare timestamp the audit cannot explain.
LEGACY_REASON = "legacy_unclassified"

# A pre-#1098 record_anomaly() appended the timestamp, then wrote the audit
# row a few milliseconds later. Two seconds is generous for that gap and far
# below the one-night spacing between real anomalies.
LEGACY_AUDIT_MATCH_S = 2.0

DEFAULT_RESUME_NIGHTS = 7


def anomaly_class(reason: str) -> str:
    """The class of a known anomaly reason. Raises ValueError otherwise, so
    a typo at a call site never silently lands in either class."""
    if reason in INFRA_REASONS:
        return INFRA
    if reason in CONTENT_REASONS:
        return CONTENT
    raise ValueError(f"unknown anomaly reason: {reason!r}")


def parse_iso(value: Any) -> float | None:
    """Epoch seconds for an ISO-8601 UTC string, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso_from_epoch(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_entry(ts: str, reason: str, batch_ids: Iterable[str] = ()) -> dict[str, Any]:
    return {"ts": ts, "reason": reason, "class": anomaly_class(reason), "batch_ids": list(batch_ids)}


def _infra_audit_epochs(audit_rows: Iterable[dict[str, Any]]) -> list[float]:
    out = []
    for row in audit_rows:
        if row.get("outcome") != "anomaly_recorded" or row.get("reason") not in INFRA_REASONS:
            continue
        epoch = parse_iso(row.get("ts"))
        if epoch is not None:
            out.append(epoch)
    return out


def needs_audit(entries: Iterable[Any]) -> bool:
    """True when the log holds a pre-#1098 bare timestamp, the only case
    whose class depends on the apply-audit."""
    return any(isinstance(e, str) for e in entries)


def normalize_anomaly_log(entries: Any, audit_rows: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Every entry as `{ts, reason, class, batch_ids}`. Drops entries with no
    parseable timestamp. See the module docstring for legacy entries."""
    if not isinstance(entries, list):
        return []
    infra_epochs = _infra_audit_epochs(audit_rows) if needs_audit(entries) else []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            epoch = parse_iso(entry)
            if epoch is None:
                continue
            paired = any(0 <= audit - epoch <= LEGACY_AUDIT_MATCH_S for audit in infra_epochs)
            out.append({
                "ts": entry, "reason": "red_eval_gate" if paired else LEGACY_REASON,
                "class": INFRA if paired else CONTENT, "batch_ids": [],
            })
        elif isinstance(entry, dict) and parse_iso(entry.get("ts")) is not None:
            cls = entry.get("class")
            ids = entry.get("batch_ids")
            out.append({
                "ts": entry["ts"], "reason": str(entry.get("reason") or LEGACY_REASON),
                # Anything not explicitly infra counts: an unreadable class
                # must never stop the breaker from seeing a content anomaly.
                "class": INFRA if cls == INFRA else CONTENT,
                "batch_ids": [str(i) for i in ids] if isinstance(ids, list) else [],
            })
    return out


def content_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("class") == CONTENT]


def content_in_window(entries: list[dict[str, Any]], *, now: float, window_nights: int) -> list[dict[str, Any]]:
    start = now - window_nights * 86400.0
    return [e for e in content_entries(entries) if (parse_iso(e["ts"]) or 0.0) >= start]


def prune(entries: list[dict[str, Any]], *, now: float, window_nights: int) -> list[dict[str, Any]]:
    """Drop entries older than twice the trip window. Never removes an entry
    a trip decision would still count (that window is half this one)."""
    cutoff = now - 2 * window_nights * 86400.0
    return [e for e in entries if (parse_iso(e["ts"]) or 0.0) >= cutoff]


def resume_due_epoch(state: dict[str, Any], entries: list[dict[str, Any]], *, resume_nights: int) -> float | None:
    """When a suspended breaker may resume: `resume_nights` after the later
    of the suspension and the newest content anomaly. None when the
    suspension time is unreadable, which never auto-resumes."""
    suspended_at = parse_iso(state.get("suspended_at"))
    if suspended_at is None:
        return None
    last_content = max((parse_iso(e["ts"]) or 0.0 for e in content_entries(entries)), default=0.0)
    return max(suspended_at, last_content) + resume_nights * 86400.0
