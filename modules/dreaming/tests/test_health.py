#!/usr/bin/env python3
"""
Failure surfacing (epic #1098, items 1.1-1.3).

* lib/health.py recomputes state/health.json from scratch from the files the
  pipeline already writes.
* bin/dream-daily.sh writes it from an EXIT trap, so a crash still writes it.
* hooks/dreaming-health.py injects a red status into the next session, reads
  files only, and stays silent on green.
* The weekly scorecard runs from the chain on Sundays; the reconciliation
  appendix goes to digests/<date>.reconcile.md so the digest stays small.

No network. Dream-daily runs against a temp CCGM_DREAMING_DIR with stub steps.

Run with: python3 -m pytest modules/dreaming/tests/test_health.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
sys.path.insert(0, str(MODULE / "lib"))

import health  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)  # a Sunday
TODAY = NOW.date()
HOOK = MODULE / "hooks" / "dreaming-health.py"
DAILY = MODULE / "bin" / "dream-daily.sh"
NOW_ENV = "2026-10-04T12:00:00Z"


def day(n: int) -> str:
    """ISO date n days before TODAY."""
    return (TODAY - timedelta(days=n)).isoformat()


def ts(n_days: float) -> str:
    return (NOW - timedelta(days=n_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def audit_rows(offsets) -> str:
    return "\n".join(
        json.dumps({"outcome": "anomaly_recorded", "reason": "red_eval_gate", "ts": ts(n)}) for n in offsets
    ) + "\n"


def build_green(root: Path, *, integration=True) -> None:
    """A healthy install: ran an hour ago, integrated yesterday, nothing pending."""
    write_json(root / "config.json", {"enabled": True, "optimistic_integration": {"enabled": integration}})
    write_json(root / "state" / "runs" / f"{TODAY.isoformat()}.json",
               {"date": TODAY.isoformat(), "generated_at": ts(1 / 24), "proposals_written": 2})
    (root / "state" / "apply-audit.jsonl").write_text(
        json.dumps({"outcome": "applied", "ok": True, "ts": ts(1)}) + "\n", encoding="utf-8")
    (root / "cost.log").write_text(f"{day(1)}\t1\t1\t0.50\tmap\n", encoding="utf-8")


def build_red(root: Path) -> None:
    """The 87-day failure: breaker suspended 87 nights, gate closed 30, 228 pending."""
    build_green(root)
    write_json(root / "state" / "optimistic.json", {"suspended": True, "suspended_at": ts(87), "anomaly_log": []})
    (root / "state" / "apply-audit.jsonl").write_text(audit_rows(range(30)), encoding="utf-8")
    d = root / "proposals"
    d.mkdir(parents=True, exist_ok=True)
    for n in range(87):
        rows = [{"id": f"p{n}-{i}", "status": "pending", "generated_at": ts(n)} for i in range(3 if n < 54 else 2)]
        (d / f"{day(n)}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def no_gate(**_kw):
    return {"state": "open", "code": "ok", "reason": "ok", "since": None}


def closed_gate(**_kw):
    return {"state": "closed", "code": "regression", "reason": "canary-01 on m regressed", "since": None}


def paused_gate(code: str, reason: str = "paused for a test"):
    def _gate(**_kw):
        return {"state": "paused", "code": code, "reason": reason, "since": None}
    return _gate


def compute(root: Path, **kw):
    kw.setdefault("gate_fn", no_gate)
    return health.compute(root, NOW, **kw)


def codes(h) -> list:
    return [r["code"] for r in h["reasons"]]


class HealthComputeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_green_fixture_is_green_with_no_reasons(self):
        build_green(self.root)
        h = compute(self.root)
        self.assertEqual(h["status"], "green")
        self.assertEqual(h["reasons"], [])
        self.assertEqual(h["pending_count"], 0)
        self.assertEqual(h["nights_since_last_integration"], 1)

    def test_shared_top_level_shape(self):
        build_green(self.root)
        h = compute(self.root)
        for key in ("status", "generated_at", "last_success_at", "reasons"):
            self.assertIn(key, h)
        self.assertEqual(h["generated_at"], NOW_ENV)

    def test_red_fixture_reports_breaker_gate_and_pending(self):
        build_red(self.root)
        h = compute(self.root, gate_fn=closed_gate)
        self.assertEqual(h["status"], "red")
        self.assertEqual(h["breaker"]["suspended"], True)
        self.assertEqual(h["breaker"]["nights_suspended"], 87)
        self.assertEqual(h["gate"]["state"], "closed")
        self.assertEqual(h["gate"]["consecutive_closed_nights"], 30)
        self.assertEqual(h["pending_count"], 228)
        self.assertEqual(h["oldest_pending"], day(86))
        for code in ("breaker_suspended", "gate_closed", "no_terminal_outcomes"):
            self.assertIn(code, codes(h))
        for reason in h["reasons"]:
            self.assertTrue(reason["message"] and reason["fix"])
            self.assertNotIn("\n", reason["message"])

    def test_reasons_put_most_actionable_first(self):
        build_red(self.root)
        h = compute(self.root, gate_fn=closed_gate)
        self.assertEqual(codes(h)[0], "breaker_suspended")

    def test_no_success_in_36h_is_red(self):
        build_green(self.root)
        (self.root / "state" / "runs" / f"{TODAY.isoformat()}.json").unlink()
        write_json(self.root / "state" / "runs" / f"{day(3)}.json", {"date": day(3), "generated_at": ts(3)})
        h = compute(self.root)
        self.assertEqual(h["status"], "red")
        self.assertIn("no_recent_success", codes(h))
        self.assertEqual(h["last_success_at"], ts(3))

    def test_never_succeeded_is_red(self):
        build_green(self.root)
        (self.root / "state" / "runs" / f"{TODAY.isoformat()}.json").unlink()
        h = compute(self.root)
        self.assertEqual(h["status"], "red")
        self.assertIsNone(h["last_success_at"])

    def test_failed_reduce_is_not_a_success(self):
        build_green(self.root)
        write_json(self.root / "state" / "runs" / f"{TODAY.isoformat()}.json",
                   {"date": TODAY.isoformat(), "generated_at": ts(0.01), "reduce_failed": True})
        h = compute(self.root)
        self.assertIsNone(h["last_success_at"])

    def test_success_age_between_26_and_36h_is_yellow(self):
        build_green(self.root)
        write_json(self.root / "state" / "runs" / f"{TODAY.isoformat()}.json", {"generated_at": ts(30 / 24)})
        h = compute(self.root)
        self.assertEqual(h["status"], "yellow")
        self.assertIn("success_aging", codes(h))

    def test_analyze_failed_is_red(self):
        build_green(self.root)
        h = compute(self.root, analyze_rc=1)
        self.assertEqual(h["status"], "red")
        self.assertEqual(h["analyze_rc"], 1)
        self.assertIn("analyze_failed", codes(h))

    def test_gate_closed_two_nights_is_yellow_three_is_red(self):
        build_green(self.root)
        audit = self.root / "state" / "apply-audit.jsonl"
        audit.write_text(audit_rows(range(2)), encoding="utf-8")
        h = compute(self.root, gate_fn=closed_gate)
        self.assertEqual((h["status"], h["gate"]["consecutive_closed_nights"]), ("yellow", 2))
        audit.write_text(audit_rows(range(3)), encoding="utf-8")
        h = compute(self.root, gate_fn=closed_gate)
        self.assertEqual((h["status"], h["gate"]["consecutive_closed_nights"]), ("red", 3))

    def test_gate_streak_counts_back_from_yesterday_when_today_has_no_row(self):
        build_green(self.root)
        (self.root / "state" / "apply-audit.jsonl").write_text(audit_rows(range(1, 5)), encoding="utf-8")
        self.assertEqual(compute(self.root, gate_fn=closed_gate)["gate"]["consecutive_closed_nights"], 4)

    def test_gate_streak_breaks_on_a_missing_night(self):
        build_green(self.root)
        (self.root / "state" / "apply-audit.jsonl").write_text(audit_rows((0, 1, 3, 4, 5)), encoding="utf-8")
        self.assertEqual(compute(self.root, gate_fn=closed_gate)["gate"]["consecutive_closed_nights"], 2)

    def test_breaker_suspended_one_night_is_yellow(self):
        build_green(self.root)
        write_json(self.root / "state" / "optimistic.json", {"suspended": True, "suspended_at": ts(1.5)})
        h = compute(self.root)
        self.assertEqual(h["status"], "yellow")
        self.assertIn("breaker_suspended", codes(h))

    def _reason(self, h, code):
        return next(r for r in h["reasons"] if r["code"] == code)

    def test_paused_gate_is_yellow_and_names_disabled_eval_refresh(self):
        build_green(self.root)
        h = compute(self.root, gate_fn=paused_gate("no_results", "no results"))
        self.assertEqual((h["status"], h["gate"]["state"]), ("yellow", "paused"))
        self.assertEqual(h["gate"]["code"], "no_results")
        fix = self._reason(h, "gate_paused")["fix"]
        self.assertIn("no fresh eval: eval-refresh is disabled until the Phase 4 smoke test lands", fix)

    def test_paused_gate_with_eval_refresh_enabled_points_at_the_next_refresh(self):
        build_green(self.root)
        write_json(self.root / "config.json",
                   {"enabled": True, "optimistic_integration": {"enabled": True, "eval_refresh_enabled": True}})
        h = compute(self.root, gate_fn=paused_gate("results_stale", "stale"))
        fix = self._reason(h, "gate_paused")["fix"]
        self.assertNotIn("disabled", fix)
        self.assertIn("eval-refresh", fix)

    def test_paused_gate_fix_names_each_infra_cause(self):
        build_green(self.root)
        expected = {
            "stale_own_writes": "max_unevaluated_writes",
            "harness_broken": "harness-broken",
            "budget_abort": "cost cap",
            "unmeasured_rows": "failed launches or judge errors",
            "results_empty": "results file is empty",
        }
        for code, needle in expected.items():
            with self.subTest(code=code):
                fix = self._reason(compute(self.root, gate_fn=paused_gate(code)), "gate_paused")["fix"]
                self.assertIn(needle, fix)

    def test_paused_gate_stays_yellow_however_long_it_lasts(self):
        build_green(self.root)
        audit = self.root / "state" / "apply-audit.jsonl"
        audit.write_text("".join(
            json.dumps({"outcome": "anomaly_recorded", "reason": "eval_gate_paused", "class": "infra", "ts": ts(n)}) + "\n"
            for n in range(10)), encoding="utf-8")
        h = compute(self.root, gate_fn=paused_gate("no_results"))
        self.assertEqual(h["status"], "yellow")
        self.assertEqual(h["gate"]["consecutive_closed_nights"], 10)
        self.assertIn("10 night(s)", self._reason(h, "gate_paused")["message"])

    def test_breaker_fix_says_resume_is_due_when_quiet_long_enough(self):
        build_red(self.root)
        fix = self._reason(compute(self.root, gate_fn=closed_gate), "breaker_suspended")["fix"]
        self.assertIn("no content anomaly", fix)
        self.assertIn("the next nightly run resumes it", fix)
        self.assertNotIn("optimistic-resume", fix)

    def test_breaker_fix_gives_the_resume_date_after_a_recent_content_anomaly(self):
        build_green(self.root)
        write_json(self.root / "state" / "optimistic.json", {
            "suspended": True, "suspended_at": ts(10),
            "anomaly_log": [{"ts": ts(2), "reason": "eval_regression", "class": "content", "batch_ids": []}],
        })
        h = compute(self.root)
        fix = self._reason(h, "breaker_suspended")["fix"]
        self.assertIn(day(-5), fix)
        self.assertEqual(h["breaker"]["resume_due"], day(-5))
        self.assertNotIn("optimistic-resume", fix)

    def test_integration_off_ignores_gate_breaker_and_pending(self):
        build_red(self.root)
        write_json(self.root / "config.json", {"enabled": True, "optimistic_integration": {"enabled": False}})
        h = compute(self.root, gate_fn=closed_gate)
        self.assertEqual(h["status"], "green")
        self.assertEqual(h["gate"]["state"], "off")

    def test_spend_over_80_percent_of_budget_is_red_over_60_yellow(self):
        build_green(self.root)
        write_json(self.root / "config.json",
                   {"enabled": True, "module_budget_usd_30d": 10.0, "optimistic_integration": {"enabled": True}})
        env = os.environ.get("CCGM_DREAMING_CONFIG")
        os.environ["CCGM_DREAMING_CONFIG"] = str(self.root / "config.json")
        try:
            (self.root / "cost.log").write_text(f"{day(2)}\t1\t1\t6.50\tmap\n", encoding="utf-8")
            h = compute(self.root)
            self.assertEqual(h["status"], "yellow")
            self.assertEqual((h["spend_30d"], h["budget_30d"]), (6.5, 10.0))
            (self.root / "cost.log").write_text(
                f"{day(2)}\t1\t1\t8.50\tmap\n{day(40)}\t1\t1\t99\told\n", encoding="utf-8")
            h = compute(self.root)
            self.assertEqual(h["status"], "red")
            self.assertIn("spend_near_budget", codes(h))
            self.assertEqual((h["spend_30d"], h["spend_7d"]), (8.5, 8.5))
        finally:
            if env is None:
                del os.environ["CCGM_DREAMING_CONFIG"]
            else:
                os.environ["CCGM_DREAMING_CONFIG"] = env

    def over_budget(self):
        """$80 spent against the default $25, no recent success, as on the operator's machine."""
        build_green(self.root)
        (self.root / "state" / "runs" / f"{TODAY.isoformat()}.json").unlink()
        write_json(self.root / "state" / "runs" / f"{day(5)}.json", {"generated_at": ts(5)})
        (self.root / "cost.log").write_text(
            f"{day(1)}\t1\t1\t40\tmap\n{day(10)}\t1\t1\t30\tmap\n{day(25)}\t1\t1\t10\tmap\n", encoding="utf-8")

    def last_run(self, outcome, rc=2, run_date=None):
        write_json(self.root / "state" / "last-run.json", {
            "date": run_date or TODAY.isoformat(), "rc": rc, "outcome": outcome, "spent_30d": None, "budget": None})

    def test_budget_refused_is_one_yellow_pause_not_a_failure(self):
        self.over_budget()
        self.last_run("budget_refused")
        h = compute(self.root, analyze_rc=2)
        self.assertEqual(h["status"], "yellow")
        self.assertEqual(codes(h), ["budget_paused"])
        # Oct 3's $40 row leaves the 30-day window on Nov 2; before that the sum stays >= $25.
        self.assertIn("resumes about 2026-11-02", h["reasons"][0]["message"])
        self.assertIn("$80.00 \u2265 $25.00", h["reasons"][0]["message"])
        self.assertIn("2026-11-02", h["reasons"][0]["fix"])
        self.assertIn("module_budget_usd_30d", h["reasons"][0]["fix"])

    def test_real_failure_with_rc2_during_budget_pause_is_red(self):
        self.over_budget()
        self.last_run("failed", rc=2)
        h = compute(self.root, analyze_rc=2)
        self.assertEqual(h["status"], "red")
        self.assertIn("analyze_failed", codes(h))
        self.assertIn("budget_paused", codes(h))

    def test_rc2_without_last_run_file_stays_red_during_budget_pause(self):
        self.over_budget()
        h = compute(self.root, analyze_rc=2)
        self.assertEqual(h["status"], "red")
        self.assertIn("analyze_failed", codes(h))

    def test_budget_refused_from_another_date_suppresses_nothing(self):
        self.over_budget()
        self.last_run("budget_refused", run_date=day(1))
        h = compute(self.root, analyze_rc=2)
        self.assertIn("analyze_failed", codes(h))
        self.assertEqual(h["status"], "red")

    def test_budget_paused_alone_is_yellow_and_hides_nothing_else(self):
        self.over_budget()
        h = compute(self.root, analyze_rc=0)
        self.assertIn("no_recent_success", codes(h))
        self.assertIn("budget_paused", codes(h))

    def test_failed_outcome_with_rc1_is_analyze_failed(self):
        self.over_budget()
        self.last_run("failed", rc=1)
        h = compute(self.root, analyze_rc=1)
        self.assertIn("analyze_failed", codes(h))

    def test_daily_cap_refused_is_yellow_daily_cap_reached(self):
        build_green(self.root)
        self.last_run("daily_cap_refused")
        h = compute(self.root, analyze_rc=2)
        self.assertEqual(h["status"], "yellow")
        self.assertEqual(codes(h), ["daily_cap_reached"])

    def test_analyze_rc_falls_back_to_last_run_file(self):
        build_green(self.root)
        self.last_run("failed", rc=1)
        h = compute(self.root)
        self.assertEqual(h["analyze_rc"], 1)
        self.assertIn("analyze_failed", codes(h))

    def test_spend_at_90_percent_is_red_spend_near_budget(self):
        build_green(self.root)
        (self.root / "cost.log").write_text(f"{day(2)}\t1\t1\t22.50\tmap\n", encoding="utf-8")
        h = compute(self.root)
        self.assertEqual(h["status"], "red")
        self.assertEqual(codes(h), ["spend_near_budget"])

    def test_spend_exactly_at_budget_is_paused_not_near_budget(self):
        build_green(self.root)
        (self.root / "cost.log").write_text(f"{day(2)}\t1\t1\t25\tmap\n", encoding="utf-8")
        self.assertEqual(codes(compute(self.root)), ["budget_paused"])

    def test_eval_budget_abort_marker_is_red_and_reported(self):
        build_green(self.root)
        (self.root / "evals").mkdir()
        (self.root / "evals" / f"{day(2)}.budget-abort").write_text("{}", encoding="utf-8")
        (self.root / "cost.log").write_text(
            f"{day(2)}\t1\t1\t1.25\teval:arm:x\n{day(2)}\t1\t1\t0.25\teval:judge:x\n", encoding="utf-8")
        h = compute(self.root)
        self.assertEqual(h["status"], "red")
        self.assertEqual(h["eval_budget_abort"], day(2))
        self.assertEqual(h["eval_last_cost"], 1.5)
        self.assertIn("eval_budget_abort", codes(h))

    def test_old_budget_abort_marker_does_not_stick(self):
        build_green(self.root)
        (self.root / "evals").mkdir()
        (self.root / "evals" / f"{day(20)}.budget-abort").write_text("{}", encoding="utf-8")
        self.assertEqual(compute(self.root)["status"], "green")

    def test_eval_last_run_is_newest_results_file_date(self):
        build_green(self.root)
        (self.root / "evals").mkdir()
        (self.root / "evals" / f"{day(9)}.jsonl").write_text("{}\n", encoding="utf-8")
        (self.root / "evals" / f"{day(4)}.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertEqual(compute(self.root)["eval_last_run"], day(4))

    def test_old_unprocessed_pending_alone_is_yellow(self):
        build_green(self.root)
        d = self.root / "proposals"
        d.mkdir()
        (d / f"{day(4)}.jsonl").write_text(json.dumps({"id": "a", "status": "pending"}) + "\n", encoding="utf-8")
        h = compute(self.root)
        self.assertEqual(h["status"], "yellow")
        self.assertIn("pending_backlog", codes(h))

    def test_terminal_outcome_in_window_clears_no_terminal_red(self):
        build_red(self.root)
        p = self.root / "proposals" / f"{day(2)}.jsonl"
        p.write_text(json.dumps({"id": "z", "status": "accepted"}) + "\n", encoding="utf-8")
        self.assertNotIn("no_terminal_outcomes", codes(compute(self.root)))

    def test_remine_ratio_is_omitted(self):
        build_green(self.root)
        self.assertNotIn("remine_ratio", compute(self.root))

    def test_recompute_is_not_sticky(self):
        build_red(self.root)
        self.assertEqual(compute(self.root, gate_fn=closed_gate)["status"], "red")
        for p in (self.root / "proposals").glob("*.jsonl"):
            p.unlink()
        write_json(self.root / "state" / "optimistic.json", {"suspended": False})
        (self.root / "state" / "apply-audit.jsonl").write_text(
            json.dumps({"outcome": "applied", "ok": True, "ts": ts(1)}) + "\n", encoding="utf-8")
        self.assertEqual(compute(self.root)["status"], "green")

    def test_corrupt_inputs_never_raise(self):
        build_green(self.root)
        (self.root / "state" / "optimistic.json").write_text("{nope", encoding="utf-8")
        (self.root / "state" / "apply-audit.jsonl").write_text("garbage\n[1]\n", encoding="utf-8")
        (self.root / "cost.log").write_text("junk\n", encoding="utf-8")
        self.assertIn(compute(self.root)["status"], ("green", "yellow", "red"))

    def test_gate_failure_degrades_to_unknown(self):
        build_green(self.root)

        def boom(**_kw):
            raise RuntimeError("x")
        self.assertEqual(compute(self.root, gate_fn=boom)["gate"]["state"], "unknown")

    def test_write_is_atomic_json_and_history_counts_red_nights(self):
        build_red(self.root)
        for n in (2, 1, 0):
            health.write(self.root, datetime(2026, 10, 4 - n, 12, 0, tzinfo=timezone.utc), gate_fn=closed_gate)
        data = json.loads((self.root / "state" / "health.json").read_text())
        self.assertEqual(data["status"], "red")
        self.assertEqual(data["consecutive_red_nights"], 3)
        self.assertFalse(list((self.root / "state").glob("health.json.tmp*")))

    def test_green_night_resets_consecutive_red(self):
        build_red(self.root)
        health.write(self.root, datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc), gate_fn=closed_gate)
        for p in (self.root / "proposals").glob("*.jsonl"):
            p.unlink()
        write_json(self.root / "state" / "optimistic.json", {"suspended": False})
        (self.root / "state" / "apply-audit.jsonl").write_text("", encoding="utf-8")
        health.write(self.root, NOW, gate_fn=no_gate)
        data = json.loads((self.root / "state" / "health.json").read_text())
        self.assertEqual((data["status"], data["consecutive_red_nights"]), ("green", 0))


def run_hook(root: Path, now_env=None):
    env = {**os.environ, "CCGM_DREAMING_DIR": str(root)}
    if now_env:
        env["CCGM_DREAMING_NOW"] = now_env
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, str(HOOK)], input='{"hook_event_name":"SessionStart"}',
                          capture_output=True, text=True, env=env, timeout=10)
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, elapsed


def context_of(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def load_hook():
    spec = importlib.util.spec_from_file_location("dreaming_health_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HealthHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def red_health(self, **extra):
        build_red(self.root)
        health.write(self.root, NOW, gate_fn=closed_gate)
        if extra:
            p = self.root / "state" / "health.json"
            d = json.loads(p.read_text())
            d.update(extra)
            p.write_text(json.dumps(d))

    def test_red_fixture_injects_status_reasons_and_fix(self):
        self.red_health()
        out, _ = run_hook(self.root, NOW_ENV)
        payload = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "SessionStart")
        text = payload["additionalContext"]
        self.assertIn('<dreaming-health status="red">', text)
        self.assertIn("no content anomaly", text)  # the breaker fix says what clears it
        self.assertNotIn("optimistic-resume", text)
        self.assertEqual(text.count("fix:"), 2)  # top 2 reasons only

    def test_green_fixture_injects_nothing(self):
        build_green(self.root)
        health.write(self.root, NOW, gate_fn=no_gate)
        out, _ = run_hook(self.root, NOW_ENV)
        self.assertEqual(out.strip(), "")

    def test_yellow_injects_nothing(self):
        build_green(self.root)
        write_json(self.root / "state" / "optimistic.json", {"suspended": True, "suspended_at": ts(1.5)})
        health.write(self.root, NOW, gate_fn=no_gate)
        self.assertEqual(json.loads((self.root / "state" / "health.json").read_text())["status"], "yellow")
        out, _ = run_hook(self.root, NOW_ENV)
        self.assertEqual(out.strip(), "")

    def test_green_file_with_stale_last_success_injects_red(self):
        build_green(self.root)
        health.write(self.root, NOW, gate_fn=no_gate)
        out, _ = run_hook(self.root, "2026-10-07T12:00:00Z")
        text = context_of(out)
        self.assertIn('<dreaming-health status="red">', text)
        self.assertIn("dream-install", text)

    def test_three_red_nights_adds_mention_once_instruction(self):
        self.red_health(consecutive_red_nights=3)
        text = context_of(run_hook(self.root, NOW_ENV)[0])
        self.assertIn("mention", text.lower())
        self.assertIn("once", text.lower())

    def test_fewer_than_three_red_nights_has_no_mention_instruction(self):
        self.red_health(consecutive_red_nights=2)
        text = context_of(run_hook(self.root, NOW_ENV)[0])
        self.assertNotIn("mention", text.lower())

    def test_not_installed_injects_nothing(self):
        out, _ = run_hook(self.root)
        self.assertEqual(out.strip(), "")

    def test_enabled_without_health_file_says_it_never_ran(self):
        write_json(self.root / "config.json", {"enabled": True})
        out, _ = run_hook(self.root)
        self.assertIn("never run", context_of(out))

    def test_disabled_config_without_health_injects_nothing(self):
        write_json(self.root / "config.json", {"enabled": False})
        out, _ = run_hook(self.root)
        self.assertEqual(out.strip(), "")

    def test_corrupt_health_file_never_blocks(self):
        (self.root / "state").mkdir()
        (self.root / "state" / "health.json").write_text("{nope", encoding="utf-8")
        write_json(self.root / "config.json", {"enabled": True})
        out, _ = run_hook(self.root)
        self.assertNotIn("Traceback", out)

    def test_runtime_bound_in_process(self):
        self.red_health()
        hook = load_hook()
        os.environ["CCGM_DREAMING_DIR"] = str(self.root)
        try:
            hook.build_context(NOW)  # warm
            t0 = time.perf_counter()
            for _ in range(20):
                hook.build_context(NOW)
            per_call = (time.perf_counter() - t0) / 20
        finally:
            del os.environ["CCGM_DREAMING_DIR"]
        self.assertLess(per_call, 0.020)

    def test_process_wall_clock_bound(self):
        self.red_health()
        _, elapsed = run_hook(self.root, NOW_ENV)
        self.assertLess(elapsed, 0.5)


def run_daily(root: Path, bin_dir: Path, *args: str, today="2026-10-04"):
    env = {**os.environ, "CCGM_DREAMING_DIR": str(root), "CCGM_DREAMING_BIN_DIR": str(bin_dir),
           "CCGM_DREAMING_LOGS_DIR": str(root.parent / "logs"), "CCGM_DREAMING_TODAY": today,
           "CCGM_LEARNINGS_DIR": str(root.parent / "learnings")}
    return subprocess.run(["bash", str(DAILY), *args], capture_output=True, text=True, env=env, timeout=120)


def stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")


class DailyChainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "dreaming"
        self.bins = Path(self._tmp.name) / "bin"
        self.root.mkdir()
        write_json(self.root / "config.json", {"enabled": True})

    def tearDown(self):
        self._tmp.cleanup()

    def health(self):
        return json.loads((self.root / "state" / "health.json").read_text())

    def test_failing_analyze_still_writes_health_with_rc(self):
        stub(self.bins, "dream-analyze.sh", "exit 7")
        run_daily(self.root, self.bins)
        h = self.health()
        self.assertEqual(h["analyze_rc"], 7)
        self.assertEqual(h["status"], "red")
        self.assertIn("analyze_failed", codes(h))

    def test_chain_killed_mid_run_still_writes_health(self):
        stub(self.bins, "dream-analyze.sh", "kill -TERM $PPID; sleep 1")
        run_daily(self.root, self.bins)
        self.assertTrue((self.root / "state" / "health.json").is_file())
        self.assertEqual(self.health()["status"], "red")

    def test_successful_chain_writes_health_with_rc_zero(self):
        stub(self.bins, "dream-analyze.sh", "exit 0")
        run_daily(self.root, self.bins)
        h = self.health()
        self.assertEqual(h["analyze_rc"], 0)
        # A quiet night writes no run summary; exit 0 from analyze still counts.
        self.assertIsNotNone(h["last_success_at"])
        self.assertEqual(h["status"], "green")

    def test_sunday_run_writes_scorecard_weekday_does_not(self):
        stub(self.bins, "dream-analyze.sh", "exit 0")
        stub(self.bins, "dream-scorecard.sh", 'mkdir -p "$CCGM_DREAMING_DIR/scorecards"; echo "# card" > "$CCGM_DREAMING_DIR/scorecards/$1.md"')
        run_daily(self.root, self.bins, today="2026-10-05")  # Monday
        self.assertFalse((self.root / "scorecards" / "2026-10-05.md").exists())
        proc = run_daily(self.root, self.bins, today="2026-10-04")  # Sunday
        self.assertTrue((self.root / "scorecards" / "2026-10-04.md").is_file(), proc.stderr)

    def test_real_offline_chain_on_a_sunday_writes_everything_and_a_small_digest(self):
        env = {**os.environ, "CCGM_DREAMING_DIR": str(self.root), "CCGM_DREAMING_LOGS_DIR": str(self.root.parent / "logs"),
               "CCGM_LEARNINGS_DIR": str(self.root.parent / "learnings"),
               "CCGM_DREAMING_PROJECTS_ROOT": str(self.root.parent / "projects")}
        (self.root.parent / "projects").mkdir()
        proc = subprocess.run(
            ["bash", str(DAILY), "--offline", str(HERE / "fixtures" / "offline-responses"), "--force-day", "2026-10-04"],
            capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / "scorecards" / "2026-10-04.md").is_file())
        self.assertTrue((self.root / "digests" / "2026-10-04.reconcile.md").is_file())
        self.assertLess((self.root / "digests" / "2026-10-04.md").stat().st_size, 20 * 1024)
        self.assertIn(self.health()["status"], ("green", "yellow", "red"))


class StatuslineSegmentTest(unittest.TestCase):
    STATUSLINE = MODULE.parents[1] / "lib" / "statusline.sh"

    def render(self, status):
        with tempfile.TemporaryDirectory() as home:
            if status:
                write_json(Path(home) / ".claude" / "dreaming" / "state" / "health.json", {"status": status})
            proc = subprocess.run(
                ["bash", str(self.STATUSLINE)], input='{"model":{"display_name":"x"},"cwd":"/tmp"}',
                capture_output=True, text=True, env={**os.environ, "HOME": home}, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_red_shows_segment(self):
        self.assertIn("dream:red", self.render("red"))

    def test_yellow_shows_segment(self):
        self.assertIn("dream:yellow", self.render("yellow"))

    def test_green_and_missing_show_nothing(self):
        self.assertNotIn("dream:", self.render("green"))
        self.assertNotIn("dream:", self.render(None))


class ReconcileSplitTest(unittest.TestCase):
    def test_reconcile_writes_sidecar_and_leaves_digest_body_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dreaming"
            (root / "digests").mkdir(parents=True)
            digest = root / "digests" / "2026-10-04.md"
            digest.write_text("# Dreaming digest -- 2026-10-04\n\nbody\n\n## Reconciliation\n\nold inline\n", encoding="utf-8")
            proj = Path(tmp) / "projects"
            proj.mkdir()
            env = {**os.environ, "CCGM_DREAMING_DIR": str(root), "CCGM_DREAMING_PROJECTS_ROOT": str(proj),
                   "CCGM_LEARNINGS_DIR": str(Path(tmp) / "learnings")}
            proc = subprocess.run(["bash", str(MODULE / "bin" / "dream-reconcile.sh"), "2026-10-04"],
                                  capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            side = root / "digests" / "2026-10-04.reconcile.md"
            self.assertTrue(side.is_file())
            self.assertIn("## Reconciliation", side.read_text())
            body = digest.read_text()
            self.assertNotIn("## Reconciliation", body)
            self.assertNotIn("old inline", body)
            self.assertIn("2026-10-04.reconcile.md", body)

    def test_digest_stays_under_20kb_on_a_typical_fixture(self):
        # The pipeline smoke renders a digest from the offline fixtures and
        # the reconcile step; the combined digest must stay small.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dreaming"
            (root / "digests").mkdir(parents=True)
            proj = Path(tmp) / "projects"
            proj.mkdir()
            env = {**os.environ, "CCGM_DREAMING_DIR": str(root), "CCGM_DREAMING_PROJECTS_ROOT": str(proj),
                   "CCGM_LEARNINGS_DIR": str(Path(tmp) / "learnings")}
            # reconcile against a store with many auto-memory files would have
            # inflated the digest; the sidecar means the digest never grows.
            memdir = proj / "p1" / "memory"
            memdir.mkdir(parents=True)
            for i in range(300):
                (memdir / f"m{i}.md").write_text(f"---\nname: m{i}\n---\n" + "fact " * 60, encoding="utf-8")
            (root / "digests" / "2026-10-04.md").write_text("# Dreaming digest\n", encoding="utf-8")
            subprocess.run(["bash", str(MODULE / "bin" / "dream-reconcile.sh"), "2026-10-04"],
                           capture_output=True, text=True, env=env, timeout=120, check=True)
            size = (root / "digests" / "2026-10-04.md").stat().st_size
            self.assertLess(size, 20 * 1024)


if __name__ == "__main__":
    unittest.main()
