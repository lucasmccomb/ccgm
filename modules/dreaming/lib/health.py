#!/usr/bin/env python3
"""Dreaming health: one file that says whether the pipeline works.

`state/health.json` is recomputed from scratch on every run from files the
pipeline already writes. Nothing in it is sticky: fix the cause and the next
run reads green. dream-daily.sh calls this from an EXIT trap, so a crash
mid-chain still writes it. hooks/dreaming-health.py reads it at session start.

Shared shape (autoheal's health.json uses the same top level, so the two
modules agree on it without importing each other):

    status         "green" | "yellow" | "red"
    generated_at   UTC ISO time this file was computed
    last_success_at  UTC ISO time of the last good run, or null
    reasons        [{code, message, fix}], red first, most actionable first

Dreaming adds: analyze_rc, gate, breaker, nights_since_last_integration,
pending_count, oldest_pending, spend_7d, spend_30d, budget_30d, eval_last_run,
eval_last_cost, eval_budget_abort, consecutive_red_nights.

Two small ledgers sit beside it and are inputs, not status: `last-success.json`
(the time the analyze step last exited 0, so a quiet night with nothing to mine
still counts) and `health-history.jsonl` (one status per date, for
`consecutive_red_nights`).

`remine_ratio` (share of map input identical to the previous night) is not
written. The mining cursors store byte offsets only and cost.log stores token
totals, so neither records which input repeated. A later change that logs it
can add the field and a red rule at > 0.2.

Rules (R = red, Y = yellow; integration rules apply only when
optimistic_integration is shadow or active):

  no_recent_success   R  no good run in 36h (or ever)
  success_aging       Y  last good run 26-36h ago
  analyze_failed      R  the analyze step exited non-zero this run
  breaker_suspended   R  suspended 3+ nights   Y  suspended 0-2 nights. The fix
                          says what clears it: N nights with no content anomaly
                          (lib/breaker.py), and the date that falls on.
  gate_closed         R  closed 3+ nights      Y  closed 1-2 nights (a supported
                          regression)
  gate_paused         Y  the gate is paused (no usable eval: missing, stale,
                          broken, budget-aborted). Never red by itself; the fix
                          names the cause.
  no_terminal_outcomes R oldest pending is 7+ nights old and no proposal in the
                          last 7 nights was integrated, accepted or rejected
  pending_backlog     Y  oldest pending is 3+ nights old (and not red above)
  spend_near_budget   R  30-day spend over 80% of budget   Y  over 60%
                          (below 100%; at or above it budget_paused replaces it)
  budget_paused       Y  30-day spend >= budget (derived from cost.log). The message
                          gives the date the 30-day window drops under budget.
  daily_cap_reached   Y  state/last-run.json says daily_cap_refused for today

state/last-run.json (written by dream_analyze.py) says how tonight's analyze run
ended: ok, budget_refused, daily_cap_refused or failed. Only budget_refused
(for today's date) suppresses no_recent_success, success_aging and
analyze_failed; only a refusal recorded by the analyzer suppresses
analyze_failed. A non-zero exit with no last-run.json, or with outcome failed,
stays analyze_failed red even during a budget pause.
  eval_budget_abort   R  an eval budget-abort marker from the last 7 days that
                          no later results file follows

Python 3 standard library only, plus dream_analyze, rollout_mode and breaker
from this directory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

STALE_RED_HOURS = 36
STALE_YELLOW_HOURS = 26
GATE_RED_NIGHTS = 3
BREAKER_RED_NIGHTS = 3
TERMINAL_WINDOW_NIGHTS = 7
STUCK_RED_NIGHTS = 7
BACKLOG_YELLOW_NIGHTS = 3
SPEND_RED_FRACTION = 0.8
SPEND_YELLOW_FRACTION = 0.6
EVAL_ABORT_WINDOW_DAYS = 7
HISTORY_KEEP = 60
SUCCESS_MARKER = "last-success.json"

PRIORITY = [
    "no_recent_success", "analyze_failed", "breaker_suspended", "gate_closed",
    "no_terminal_outcomes", "spend_near_budget", "eval_budget_abort",
    "gate_paused", "success_aging", "pending_backlog", "budget_paused", "daily_cap_reached",
]

# Audit `anomaly_recorded` reasons dream-daily.sh writes on a night the gate
# did not open. `red_eval_gate` is the pre-#1098 name.
GATE_NIGHT_REASONS = frozenset({
    "red_eval_gate", "eval_gate_paused", "harness_failure", "eval_regression", "eval_regression_unattributed",
})

# Returns {"state": "open"|"closed"|"paused", "code", "reason", ...}; see
# memory_eval.gate_check().
GateFn = Callable[..., "dict[str, Any]"]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: Any) -> "datetime | None":
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> "list[dict[str, Any]]":
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _file_date(path: Path) -> "date | None":
    try:
        return date.fromisoformat(path.name.split(".")[0])
    except ValueError:
        return None


def _nights(today: date, then: "date | None") -> int:
    return max(0, (today - then).days) if then else 0


def _cost_rows(path: Path) -> "list[tuple[str, float, str]]":
    out: list[tuple[str, float, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 4:
            try:
                out.append((parts[0], float(parts[3]), parts[4] if len(parts) > 4 else ""))
            except ValueError:
                continue
    return out


def _resume_date(costs: "list[tuple[str, float, str]]", budget: float, today: date) -> str:
    """First date after `today` on which the 30-day window ending then sums
    below the budget (same window rule as read_cost_spent_30d: a row exactly
    30 days back is outside)."""
    for offset in range(1, 32):
        d = today + timedelta(days=offset)
        cutoff = (d - timedelta(days=30)).isoformat()
        total = sum(c for rd, c, _ in costs if cutoff < rd <= d.isoformat())
        if total < budget:
            return d.isoformat()
    return (today + timedelta(days=31)).isoformat()


def _default_gate(**_kw: Any) -> "dict[str, Any]":
    sys.path.insert(0, str(_HERE.parent / "eval"))
    import memory_eval  # noqa: PLC0415 -- heavy; only the nightly chain needs it

    return memory_eval.gate_check()


def _config(dreaming: Path) -> "dict[str, Any]":
    path = Path(os.environ.get("CCGM_DREAMING_CONFIG", str(dreaming / "config.json")))
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def _reason(code: str, severity: str, message: str, fix: str) -> "dict[str, str]":
    return {"code": code, "severity": severity, "message": message, "fix": fix}


def _paused_fix(code: str, eval_refresh_enabled: bool) -> str:
    """The fix line for a paused gate, naming the actual cause."""
    if eval_refresh_enabled:
        no_fresh = ("the next weekly eval-refresh writes fresh results; check it with "
                    "grep eval-refresh ~/.claude/logs/dreaming-daily-$(date -u +%F).log")
    else:
        no_fresh = ("no fresh eval: eval-refresh is disabled until the Phase 4 smoke test lands "
                    "(optimistic_integration.eval_refresh_enabled is false), so integration stays paused")
    fixes = {
        "no_results": no_fresh,
        "results_stale": no_fresh,
        "stale_own_writes": ("dreaming made more auto writes since the last eval than max_unevaluated_writes "
                             f"allows (default 15); {no_fresh}"),
        "harness_broken": "the eval harness launched no agent run; read the first failure in ~/.claude/dreaming/evals/*.harness-broken",
        "budget_abort": "the last eval stopped on its cost cap; see grep eval_ ~/.claude/dreaming/config.json and tail ~/.claude/dreaming/cost.log",
        "unmeasured_rows": "the last eval had failed launches or judge errors on a checked task, so it cannot rule out a regression; re-run bash ~/.claude/bin/dream-eval.sh",
        "results_empty": "the newest results file is empty; re-run bash ~/.claude/bin/dream-eval.sh",
    }
    return fixes.get(code, "bash ~/.claude/bin/dream-eval.sh --gate")


def compute(
    dreaming: Path,
    now: datetime,
    *,
    analyze_rc: "int | None" = None,
    gate_fn: "GateFn | None" = None,
) -> "dict[str, Any]":
    """Build the health dict from the files under `dreaming`. Never raises on
    bad input files; each unreadable source reads as absent."""
    import breaker  # noqa: PLC0415
    import dream_analyze as da  # noqa: PLC0415
    import rollout_mode  # noqa: PLC0415

    dreaming = Path(dreaming)
    state = dreaming / "state"
    today = now.date()
    cfg = _config(dreaming)
    opt_cfg = cfg.get("optimistic_integration")
    mode = rollout_mode.resolve_mode(opt_cfg.get("enabled") if isinstance(opt_cfg, dict) else None)
    integration_on = mode != rollout_mode.MODE_OFF
    reasons: list[dict[str, str]] = []

    # --- how tonight's analyze run ended --------------------------------------
    # dream_analyze.py writes state/last-run.json. Only an outcome recorded by
    # the refusing code suppresses a failure reason; exit code 2 alone never
    # does (it is shared by both refusals and by real failures). A missing or
    # stale (other date) file suppresses nothing.
    last_run = _read_json(state / "last-run.json")
    last_run = last_run if isinstance(last_run, dict) and last_run.get("date") == today.isoformat() else {}
    if analyze_rc is None and isinstance(last_run.get("rc"), int):
        analyze_rc = last_run["rc"]
    budget_refused = last_run.get("outcome") == "budget_refused"
    daily_cap_refused = last_run.get("outcome") == "daily_cap_refused"

    # --- spend and budget pause --------------------------------------------
    # When the 30-day spend has reached the budget, the analyzer refuses to
    # start on purpose. budget_paused is a yellow notice derived from cost.log
    # that says when it resumes; it never hides a failure by itself.
    cost_path = dreaming / "cost.log"
    costs = _cost_rows(cost_path)
    spend_30d = round(da.read_cost_spent_30d(cost_path, today.isoformat()), 4)
    week_cut = (today - timedelta(days=7)).isoformat()
    spend_7d = round(sum(c for d, c, _ in costs if d > week_cut), 4)
    try:
        budget = float(cfg.get("module_budget_usd_30d", da.DEFAULT_MODULE_BUDGET_USD_30D))
    except (TypeError, ValueError):
        budget = float(da.DEFAULT_MODULE_BUDGET_USD_30D)
    paused = budget > 0 and spend_30d >= budget
    if paused:
        resume = _resume_date(costs, budget, today)
        reasons.append(_reason(
            "budget_paused", "yellow",
            f"dreaming paused: 30-day spend ${spend_30d:.2f} ≥ ${budget:.2f} budget; resumes about {resume}",
            f"wait until {resume}, or raise module_budget_usd_30d in ~/.claude/dreaming/config.json"))

    # --- last success -----------------------------------------------------
    last_success: "str | None" = None
    last_success_dt: "datetime | None" = None
    # Two sources: run summaries (written only on nights that mined something)
    # and last-success.json (written when the analyze step exits 0, so a quiet
    # night with nothing to mine still counts).
    runs = state / "runs"
    sources = [_read_json(p) for p in (sorted(runs.glob("*.json")) if runs.is_dir() else [])]
    marker = _read_json(state / SUCCESS_MARKER)
    if isinstance(marker, dict):
        sources.append({"generated_at": marker.get("at")})
    for run in sources:
        if not isinstance(run, dict) or run.get("reduce_failed"):
            continue
        stamp = _parse(run.get("generated_at"))
        if stamp and (last_success_dt is None or stamp > last_success_dt):
            last_success_dt, last_success = stamp, run["generated_at"]
    if budget_refused:
        pass  # the analyzer recorded a budget refusal tonight: no success is expected
    elif last_success_dt is None:
        reasons.append(_reason(
            "no_recent_success", "red", "dreaming has never completed a successful run",
            "bash ~/.claude/bin/dream-daily.sh"))
    else:
        age_h = (now - last_success_dt).total_seconds() / 3600
        if age_h > STALE_RED_HOURS:
            reasons.append(_reason(
                "no_recent_success", "red", f"no successful dreaming run in {int(age_h)}h (last {last_success})",
                "tail -n 40 ~/.claude/logs/dreaming-daily-$(date -u +%F).log"))
        elif age_h > STALE_YELLOW_HOURS:
            reasons.append(_reason(
                "success_aging", "yellow", f"last successful dreaming run was {int(age_h)}h ago",
                "tail -n 40 ~/.claude/logs/dreaming-daily-$(date -u +%F).log"))

    if daily_cap_refused:
        reasons.append(_reason(
            "daily_cap_reached", "yellow", "the analyzer stopped at its daily cost cap; it clears tomorrow",
            "grep daily_cost_cap_usd ~/.claude/dreaming/config.json"))
    if analyze_rc not in (None, 0) and not (budget_refused or daily_cap_refused):
        reasons.append(_reason(
            "analyze_failed", "red", f"the analyze step exited {analyze_rc}",
            "tail -n 40 ~/.claude/logs/dreaming-daily-$(date -u +%F).log"))

    # --- audit: integrations and red-gate nights ---------------------------
    audit = _read_jsonl(state / "apply-audit.jsonl")
    last_applied: "date | None" = None
    applied_in_window = False
    gate_days: set[date] = set()
    window_start = today - timedelta(days=TERMINAL_WINDOW_NIGHTS - 1)
    for row in audit:
        stamp = _parse(row.get("ts"))
        if stamp is None:
            continue
        d = stamp.date()
        if row.get("outcome") == "applied":
            if last_applied is None or d > last_applied:
                last_applied = d
            if d >= window_start:
                applied_in_window = True
        elif row.get("outcome") == "anomaly_recorded" and row.get("reason") in GATE_NIGHT_REASONS:
            gate_days.add(d)
    nights_since_integration = _nights(today, last_applied) if last_applied else None

    # --- breaker -----------------------------------------------------------
    opt_state = _read_json(state / "optimistic.json")
    opt_state = opt_state if isinstance(opt_state, dict) else {}
    suspended = bool(opt_state.get("suspended"))
    since = opt_state.get("suspended_at") if suspended else None
    since_dt = _parse(since)
    breaker_nights = _nights(today, since_dt.date() if since_dt else None) if suspended else 0
    # Resume rule (#1098 item 2.2): N nights with no CONTENT anomaly, checked
    # at the top of every chain. Infra anomalies (a paused gate) never hold it.
    try:
        resume_nights = int((opt_cfg if isinstance(opt_cfg, dict) else {}).get(
            "circuit_breaker_auto_resume_nights", breaker.DEFAULT_RESUME_NIGHTS))
    except (TypeError, ValueError):
        resume_nights = breaker.DEFAULT_RESUME_NIGHTS
    entries = breaker.normalize_anomaly_log(opt_state.get("anomaly_log"), audit)
    due = breaker.resume_due_epoch(opt_state, entries, resume_nights=resume_nights) if suspended else None
    resume_due = datetime.fromtimestamp(due, tz=timezone.utc).date() if due is not None else None
    breaker_info = {
        "suspended": suspended, "since": since if suspended else None, "nights_suspended": breaker_nights,
        "resume_due": resume_due.isoformat() if resume_due else None,
    }
    if suspended and integration_on:
        red = breaker_nights >= BREAKER_RED_NIGHTS
        rule = f"it resumes after {resume_nights} night(s) with no content anomaly"
        if resume_due is None:
            fix = (f"{rule}, but its suspension time is unreadable, so it will not resume on its own; "
                   "check ~/.claude/dreaming/state/optimistic.json")
        elif resume_due <= today:
            fix = f"{rule}; that has passed, so the next nightly run resumes it (bash ~/.claude/bin/dream-daily.sh)"
        else:
            fix = (f"{rule}; with none before then, the nightly run on {resume_due.isoformat()} resumes it. "
                   "Content anomalies: grep '\"class\": \"content\"' ~/.claude/dreaming/state/apply-audit.jsonl")
        reasons.append(_reason(
            "breaker_suspended", "red" if red else "yellow",
            f"integration circuit breaker suspended {breaker_nights} night(s) since {since}; nothing integrates",
            fix))

    # --- gate --------------------------------------------------------------
    if not integration_on:
        gate: dict[str, Any] = {"state": "off", "reason": "optimistic integration is off", "consecutive_closed_nights": 0}
    else:
        gate_code = None
        try:
            result = (gate_fn or _default_gate)()
            gate_state, gate_code, gate_reason = str(result["state"]), result.get("code"), str(result.get("reason"))
        except Exception as exc:  # noqa: BLE001 -- health must never crash the chain
            gate_state, gate_reason = "unknown", f"gate check failed: {exc}"
        streak = 0
        if gate_state != "open":
            cursor = today if today in gate_days else today - timedelta(days=1)
            while cursor in gate_days:
                streak += 1
                cursor -= timedelta(days=1)
        gate = {"state": gate_state, "code": gate_code, "reason": gate_reason, "consecutive_closed_nights": streak}
        if gate_state == "paused":
            # Infra, not content: yellow however long it lasts. The fix names
            # the cause, which is usually that no eval has run.
            refresh_on = bool((opt_cfg if isinstance(opt_cfg, dict) else {}).get("eval_refresh_enabled", False))
            nights = f" {streak} night(s)" if streak else ""
            reasons.append(_reason(
                "gate_paused", "yellow", f"eval gate paused{nights}, nothing integrates: {gate_reason}",
                _paused_fix(str(gate_code), refresh_on)))
        elif streak:
            reasons.append(_reason(
                "gate_closed", "red" if streak >= GATE_RED_NIGHTS else "yellow",
                f"eval gate closed {streak} night(s): {gate_reason}",
                "bash ~/.claude/bin/dream-eval.sh --gate"))

    # --- proposals ---------------------------------------------------------
    pending = 0
    oldest_pending: "date | None" = None
    terminal_in_window = False
    pdir = dreaming / "proposals"
    for path in sorted(pdir.glob("*.jsonl")) if pdir.is_dir() else []:
        fdate = _file_date(path)
        for row in _read_jsonl(path):
            status = row.get("status")
            if status == "pending":
                pending += 1
                if fdate and (oldest_pending is None or fdate < oldest_pending):
                    oldest_pending = fdate
            elif status and fdate and fdate >= window_start:
                terminal_in_window = True
    if integration_on and pending:
        age = _nights(today, oldest_pending)
        if age >= STUCK_RED_NIGHTS and not terminal_in_window and not applied_in_window:
            reasons.append(_reason(
                "no_terminal_outcomes", "red",
                f"{pending} proposals pending, oldest {oldest_pending}; none integrated or discarded in {TERMINAL_WINDOW_NIGHTS} nights",
                "python3 ~/.claude/lib/apply_dream_proposal.py list"))
        elif age >= BACKLOG_YELLOW_NIGHTS:
            reasons.append(_reason(
                "pending_backlog", "yellow", f"{pending} proposals pending, oldest {oldest_pending}",
                "python3 ~/.claude/lib/apply_dream_proposal.py list"))

    # --- spend (computed above; budget_paused handled there) ----------------
    if budget > 0 and SPEND_YELLOW_FRACTION * budget < spend_30d < budget:
        red = spend_30d > SPEND_RED_FRACTION * budget
        reasons.append(_reason(
            "spend_near_budget", "red" if red else "yellow",
            f"30-day spend ${spend_30d:.2f} is {spend_30d / budget:.0%} of the ${budget:.2f} budget",
            "tail -n 20 ~/.claude/dreaming/cost.log"))

    # --- eval --------------------------------------------------------------
    edir = dreaming / "evals"
    result_dates = sorted(d for d in (_file_date(p) for p in edir.glob("*.jsonl")) if d) if edir.is_dir() else []
    abort_dates = sorted(d for d in (_file_date(p) for p in edir.glob("*.budget-abort")) if d) if edir.is_dir() else []
    eval_last_run = result_dates[-1] if result_dates else None
    abort = abort_dates[-1] if abort_dates else None
    abort_live = bool(
        abort and (today - abort).days <= EVAL_ABORT_WINDOW_DAYS and (eval_last_run is None or abort >= eval_last_run))
    last_eval_day = max([d for d in (eval_last_run, abort) if d], default=None)
    eval_last_cost = None
    if last_eval_day:
        eval_last_cost = round(sum(
            c for d, c, m in costs if d == last_eval_day.isoformat() and m.startswith(da.EVAL_COST_LABEL_PREFIX)), 4)
    if abort_live:
        reasons.append(_reason(
            "eval_budget_abort", "red", f"an eval run stopped on its cost cap on {abort}",
            "grep eval_ ~/.claude/dreaming/config.json"))

    reasons.sort(key=lambda r: (r["severity"] != "red", PRIORITY.index(r["code"])))
    status = "red" if any(r["severity"] == "red" for r in reasons) else ("yellow" if reasons else "green")

    return {
        "status": status,
        "generated_at": _iso(now),
        "last_success_at": last_success,
        "nights_since_last_integration": nights_since_integration,
        "gate": gate,
        "breaker": breaker_info,
        "pending_count": pending,
        "oldest_pending": oldest_pending.isoformat() if oldest_pending else None,
        "spend_7d": spend_7d,
        "spend_30d": spend_30d,
        "budget_30d": budget,
        "eval_last_run": eval_last_run.isoformat() if eval_last_run else None,
        "eval_last_cost": eval_last_cost,
        "eval_budget_abort": abort.isoformat() if abort_live and abort else None,
        "analyze_rc": analyze_rc,
        "reasons": [{k: r[k] for k in ("code", "message", "fix")} for r in reasons],
    }


def _consecutive_red(history: "list[dict[str, Any]]") -> int:
    count = 0
    for row in sorted(history, key=lambda r: r["date"], reverse=True):
        if row.get("status") != "red":
            break
        count += 1
    return count


def write(
    dreaming: Path,
    now: datetime,
    *,
    analyze_rc: "int | None" = None,
    gate_fn: "GateFn | None" = None,
) -> "dict[str, Any]":
    """Compute, record the night's status in the history ledger, and write
    state/health.json atomically. The ledger holds one status per date so
    `consecutive_red_nights` can be counted; the current status never reads it."""
    dreaming = Path(dreaming)
    state = dreaming / "state"
    state.mkdir(parents=True, exist_ok=True)
    if analyze_rc == 0:
        _atomic_write(state / SUCCESS_MARKER, json.dumps({"at": _iso(now)}) + "\n")
    data = compute(dreaming, now, analyze_rc=analyze_rc, gate_fn=gate_fn)

    ledger = state / "health-history.jsonl"
    today = now.date().isoformat()
    history = [r for r in _read_jsonl(ledger) if isinstance(r.get("date"), str) and r["date"] != today]
    history.append({"date": today, "status": data["status"]})
    history = sorted(history, key=lambda r: r["date"])[-HISTORY_KEEP:]
    _atomic_write(ledger, "".join(json.dumps(r) + "\n" for r in history))

    data["consecutive_red_nights"] = _consecutive_red(history)
    _atomic_write(state / "health.json", json.dumps(data, indent=2) + "\n")
    return data


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Write dreaming state/health.json")
    ap.add_argument("--dreaming-dir", default=os.environ.get("CCGM_DREAMING_DIR", os.path.expanduser("~/.claude/dreaming")))
    ap.add_argument("--analyze-rc", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        data = write(Path(args.dreaming_dir), datetime.now(timezone.utc), analyze_rc=args.analyze_rc)
    except Exception as exc:  # noqa: BLE001 -- an EXIT trap must not turn into a second failure
        print(f"health: could not write health.json: {exc}", file=sys.stderr)
        return 0
    print(f"health: {data['status']} ({len(data['reasons'])} reason(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
