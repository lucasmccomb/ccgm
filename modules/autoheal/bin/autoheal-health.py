#!/usr/bin/env python3
"""autoheal-health.py - write ~/.claude/autoheal/health.json (the heartbeat).

autoheal-daily.sh calls this from an EXIT trap, so a crash mid-chain still
leaves a record. Top-level shape matches dreaming's health.json
(modules/dreaming/lib/health.py): status, generated_at, last_success_at,
reasons[{code, message, fix}].

    status           ok | partial | failed | paused
    outcome          ok | paused | daily_cap_refused | analyze_failed | crashed
    started_at, finished_at, generated_at, last_success_at   UTC ISO times
    steps            {step: exit code} for each step that ran
    calls, cost_usd  today's rows in cost.log
    signatures       signature count from runs/{today}.json, or null
    proposals        lines in proposals/{today}.jsonl
    analyzer_sha     short git SHA of the module checkout, or null

Rules:
  paused     the wrapper's preflight skipped every step. Counts as a success
             for staleness: the user asked for silence.
  failed     the wrapper died before finishing, or the analyze step exited
             non-zero with no recorded refusal.
  partial    analyze succeeded (or stopped on purpose) and a later step failed.
  ok         everything exited 0, or the analyzer stopped on the daily cost cap.

A daily-cap stop is deliberate, never inferred from exit code 2 alone (the
analyzer also exits 2 for an unsupported model). It counts only when the
analyzer recorded it in last-run.json for today's date: {date, outcome}.

Python 3 standard library only. Never raises: a trap must not become a second
failure.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAP_OUTCOME = "daily_cap_refused"
ANALYZE_FIX = "tail -n 40 ~/.claude/logs/autoheal-daily-$(date -u +%F).log"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_steps(text: str) -> "dict[str, int]":
    steps: dict[str, int] = {}
    for token in text.split():
        name, _, rc = token.partition("=")
        if name and rc.lstrip("-").isdigit():
            steps[name] = int(rc)
    return steps


def today_cost(cost_log: Path, today: str) -> "tuple[int, float]":
    calls, total = 0, 0.0
    try:
        lines = cost_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0.0
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 4 and parts[0] == today:
            try:
                total += float(parts[3])
            except ValueError:
                continue
            calls += 1
    return calls, round(total, 6)


def _sha(module_root: Path) -> "str | None":
    try:
        out = subprocess.run(
            ["git", "-C", str(module_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def classify(
    steps: "dict[str, int]", *, paused: bool, complete: bool, cap_refused: bool,
) -> "tuple[str, str, list[dict[str, str]]]":
    """Return (status, outcome, reasons)."""
    if paused:
        return "paused", "paused", []
    reasons: list[dict[str, str]] = []
    if not complete:
        reasons.append({
            "code": "wrapper_crashed",
            "message": "autoheal-daily.sh exited before finishing its steps",
            "fix": ANALYZE_FIX})
        return "failed", "crashed", reasons
    analyze_rc = steps.get("analyze")
    if analyze_rc is None:
        analyze_rc = 127
    outcome = "ok"
    if analyze_rc != 0 and cap_refused and analyze_rc == 2:
        outcome = CAP_OUTCOME
        reasons.append({
            "code": "daily_cap_reached",
            "message": "the analyzer stopped at its daily cost cap; it clears tomorrow",
            "fix": "grep daily_cost_cap_usd ~/.claude/autoheal/config.json"})
    elif analyze_rc != 0:
        hint = " (command not found or not executable)" if analyze_rc == 127 else ""
        reasons.append({
            "code": "analyze_failed",
            "message": f"the analyze step exited {analyze_rc}{hint}",
            "fix": ANALYZE_FIX})
        return "failed", "analyze_failed", reasons
    others = sorted(n for n, rc in steps.items() if n != "analyze" and rc != 0)
    for name in others:
        reasons.append({
            "code": "step_failed",
            "message": f"the {name} step exited {steps[name]}",
            "fix": ANALYZE_FIX})
    return ("partial" if others else "ok"), outcome, reasons


def build(args: argparse.Namespace, now: datetime) -> "dict[str, Any]":
    adir = Path(args.dir)
    steps = parse_steps(args.steps)
    last_run = _read_json(adir / "last-run.json")
    cap_refused = (
        isinstance(last_run, dict)
        and last_run.get("date") == args.today
        and last_run.get("outcome") == CAP_OUTCOME)
    status, outcome, reasons = classify(
        steps, paused=args.paused, complete=args.complete, cap_refused=cap_refused)

    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    previous = _read_json(adir / "health.json")
    last_success = previous.get("last_success_at") if isinstance(previous, dict) else None
    if status in ("ok", "partial", "paused"):
        last_success = stamp

    calls, cost = today_cost(adir / "cost.log", args.today)
    run = _read_json(adir / "runs" / f"{args.today}.json")
    signatures = run.get("signatures") if isinstance(run, dict) and isinstance(run.get("signatures"), int) else None
    try:
        proposals = sum(1 for ln in (adir / "proposals" / f"{args.today}.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip())
    except OSError:
        proposals = 0

    return {
        "status": status,
        "outcome": outcome,
        "generated_at": stamp,
        "last_success_at": last_success,
        "started_at": args.started,
        "finished_at": stamp,
        "steps": steps,
        "calls": calls,
        "cost_usd": cost,
        "signatures": signatures,
        "proposals": proposals,
        "analyzer_sha": _sha(Path(__file__).resolve().parent.parent),
        "reasons": reasons,
    }


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Write autoheal health.json")
    ap.add_argument("--dir", default=os.environ.get("CCGM_AUTOHEAL_DIR", os.path.expanduser("~/.claude/autoheal")))
    ap.add_argument("--today", required=True)
    ap.add_argument("--started", required=True)
    ap.add_argument("--steps", default="", help='"analyze=0 digest=1"')
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--complete", action="store_true", help="every step was attempted")
    args = ap.parse_args(argv)
    try:
        data = build(args, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 -- an EXIT trap must not fail the run
        print(f"autoheal-health: could not build health.json: {exc}", file=sys.stderr)
        return 0
    try:
        adir = Path(args.dir)
        adir.mkdir(parents=True, exist_ok=True)
        tmp = adir / f"health.json.tmp{os.getpid()}"
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(adir / "health.json")
    except OSError as exc:
        print(f"autoheal-health: could not write health.json: {exc}", file=sys.stderr)
    print(data["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
