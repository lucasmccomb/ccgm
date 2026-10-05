#!/usr/bin/env python3
"""autoheal_metrics.py - the success metrics of the autoheal redesign (RCA section 3.8).

    python3 autoheal_metrics.py [--now ISO]

Prints one JSON object: {"generated_at", "metrics": [...]}. Each metric has
`id`, `name`, `target`, `status` ("met", "missed" or "not_computable"), `value`
(null when not computable) and `detail`, one plain sentence with the numbers.
/autoheal renders it.

Computable today:
  run_health_30d        days with status ok / days, last 30, from health-history.jsonl
                        (one row per daily run, appended by autoheal-health.py). Days
                        before the first recorded run and paused days are left out.
  acceptance_rate       fixes you accepted / fixes you accepted or rejected, whole ledger.
                        Rows applied by auto-apply are not your decision and are left out.
  applied_effective     effective / (effective + ineffective + harmful) among measured fixes.
                        Unmeasurable rows are left out.
  monthly_spend_usd     cost.log, last 30 days. Target under $3.

Not computable yet, each with its reason: time to detect a dead job (no notice
log), friction rate (needs 60 days of counts after the first applied fix), cost
per accepted fix (no per-fix cost record).

Env (tests): CCGM_AUTOHEAL_DIR, CCGM_AUTOHEAL_NOW or CCGM_AUTOHEAL_TODAY.
Python 3 standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys

WINDOW_DAYS = 30
RUN_HEALTH_TARGET = 0.95
ACCEPTANCE_TARGET = 0.40
EFFECTIVE_TARGET = 0.60
SPEND_TARGET_USD = 3.00
ACCEPTED_STATES = ("applied", "measured", "reverted")
RATED_OUTCOMES = ("effective", "ineffective", "harmful")


def autoheal_dir() -> str:
    return os.environ.get("CCGM_AUTOHEAL_DIR") or os.path.expanduser("~/.claude/autoheal")


def _now() -> dt.datetime:
    raw = os.environ.get("CCGM_AUTOHEAL_NOW")
    if not raw and os.environ.get("CCGM_AUTOHEAL_TODAY"):
        raw = os.environ["CCGM_AUTOHEAL_TODAY"] + "T12:00:00+00:00"
    if raw:
        try:
            when = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc)


def _ledger_rows(adir: str) -> list:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.py")
    spec = importlib.util.spec_from_file_location("autoheal_ledger", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.read_rows(os.environ.get("CCGM_AUTOHEAL_LEDGER") or os.path.join(adir, "proposals.jsonl"))


def _jsonl(path: str) -> list:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _metric(mid: str, name: str, target: str, value, met, detail: str) -> dict:
    status = "not_computable" if value is None else ("met" if met else "missed")
    return {"id": mid, "name": name, "target": target, "status": status, "value": value, "detail": detail}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def run_health(adir: str, today: dt.date) -> dict:
    name, target = "Run health, last 30 days", ">= 95% of days with status ok"
    last_status: dict = {}
    for row in _jsonl(os.path.join(adir, "health-history.jsonl")):  # file order: the last run of a day wins
        day, status = row.get("date"), row.get("status")
        if isinstance(day, str) and isinstance(status, str):
            last_status[day] = status
    window_start = today - dt.timedelta(days=WINDOW_DAYS - 1)
    days = {}
    for day, status in last_status.items():
        try:
            d = dt.date.fromisoformat(day)
        except ValueError:
            continue
        if window_start <= d <= today:
            days[d] = status
    if not days:
        return _metric("run_health_30d", name, target, None, False,
                       "not computable yet: health-history.jsonl has no runs in the window; it fills in as the daily job runs")
    start = min(days)
    span = (today - start).days + 1
    paused = sum(1 for s in days.values() if s == "paused")
    counted = span - paused
    ok = sum(1 for s in days.values() if s == "ok")
    if counted <= 0:
        return _metric("run_health_30d", name, target, None, False,
                       f"not computable yet: every recorded day ({span}) was paused")
    rate = ok / counted
    note = f", {paused} paused day(s) left out" if paused else ""
    return _metric("run_health_30d", name, target, round(rate, 3), rate >= RUN_HEALTH_TARGET,
                   f"{ok} ok of {counted} days since the first recorded run{note} ({_pct(rate)})")


def acceptance(rows: list) -> dict:
    name, target = "Acceptance rate in /autoheal-review", ">= 40%"
    accepted = sum(1 for r in rows if r.get("state") in ACCEPTED_STATES and r.get("applied_by") != "auto")
    rejected = sum(1 for r in rows if r.get("state") == "rejected")
    if accepted + rejected == 0:
        return _metric("acceptance_rate", name, target, None, False,
                       "not computable yet: no fix has been accepted or rejected")
    rate = accepted / (accepted + rejected)
    return _metric("acceptance_rate", name, target, round(rate, 3), rate >= ACCEPTANCE_TARGET,
                   f"{accepted} accepted, {rejected} rejected ({_pct(rate)})")


def applied_effective(rows: list) -> dict:
    name, target = "Applied fixes effective at +14 days", ">= 60%"
    counts = {o: sum(1 for r in rows if r.get("outcome") == o) for o in RATED_OUTCOMES}
    total = sum(counts.values())
    if total == 0:
        return _metric("applied_effective", name, target, None, False,
                       "not computable yet: no applied fix has been measured at +14 days")
    rate = counts["effective"] / total
    return _metric("applied_effective", name, target, round(rate, 3), rate >= EFFECTIVE_TARGET,
                   f"{counts['effective']} effective, {counts['ineffective']} ineffective, "
                   f"{counts['harmful']} harmful ({_pct(rate)})")


def monthly_spend(adir: str, today: dt.date) -> dict:
    name, target = "API spend, last 30 days", "under $3"
    start = today - dt.timedelta(days=WINDOW_DAYS - 1)
    total, calls, seen = 0.0, 0, False
    try:
        with open(os.path.join(adir, "cost.log"), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            day = dt.date.fromisoformat(parts[0])
            cost = float(parts[3])
        except ValueError:
            continue
        seen = True
        if start <= day <= today:
            total += cost
            calls += 1
    if not seen:
        return _metric("monthly_spend_usd", name, target, None, False, "not computable yet: cost.log has no rows")
    return _metric("monthly_spend_usd", name, target, round(total, 2), total < SPEND_TARGET_USD,
                   f"${total:.2f} over {calls} call(s) in the last {WINDOW_DAYS} days")


def not_computable() -> list:
    return [
        _metric("time_to_detect", "Time to detect a dead job", "<= 1 SessionStart after the first missed run",
                None, False, "not computable yet: the session notice keeps no log of when it fired"),
        _metric("friction_rate", "Friction rate (failures per 100 tool calls)", "down 20% within 60 days",
                None, False, "not computable yet: needs 60 days of counts after the first applied fix"),
        _metric("cost_per_accepted", "Cost per accepted fix", "under $1",
                None, False, "not computable yet: cost.log records no per-fix cost"),
    ]


def collect(now: dt.datetime | None = None) -> dict:
    now = now or _now()
    today = now.astimezone(dt.timezone.utc).date()
    adir = autoheal_dir()
    rows = _ledger_rows(adir)
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": [run_health(adir, today), acceptance(rows), applied_effective(rows),
                    monthly_spend(adir, today)] + not_computable(),
    }


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="autoheal success metrics")
    ap.add_argument("--now", default="", help="ISO time to measure from (tests)")
    args = ap.parse_args(argv)
    now = None
    if args.now:
        now = dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
    print(json.dumps(collect(now), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
