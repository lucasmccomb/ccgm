#!/usr/bin/env python3
"""
Phase 0 cost safety (epic #1098, items 0.2 and 0.3).

* memory_eval keeps a running total over every billed call, aborts before the
  call that would cross the cap, writes a `budget-abort` marker, and leaves
  the gate state alone.
* A rolling 30-day module budget, summed from cost.log, stops both the
  analyzer and the eval.
* Every billed call (arm sessions, judge calls, in-eval mining, manual runs)
  lands in cost.log.

No test here touches the network: `claude` is a shell-script fake and the
judge transport is patched.

Run with: python3 -m pytest modules/dreaming/tests/test_cost_safety.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent

# learnings_store freezes LEARNINGS_ROOT at import time, and the other test
# files in this directory each import these modules under their own tempdir.
# So import a private copy under this file's tempdir, then put sys.modules and
# the env back as found, leaving the other files' imports undisturbed.
_PRIVATE = ("learnings_store", "dream_analyze", "transcript_miner", "memory_eval", "eligibility")
_modules_before = dict(sys.modules)
_env_before = os.environ.get("CCGM_LEARNINGS_DIR")
for _name in _PRIVATE:
    sys.modules.pop(_name, None)
os.environ["CCGM_LEARNINGS_DIR"] = tempfile.mkdtemp(prefix="ccgm-cost-safety-learnings-")

sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent / "lib"))

import dream_analyze as da  # noqa: E402
import memory_eval as me  # noqa: E402

for _name in list(sys.modules):
    if _name in _modules_before:
        sys.modules[_name] = _modules_before[_name]
    elif _name in _PRIVATE:
        del sys.modules[_name]
for _name in _PRIVATE:
    if _name in _modules_before:
        sys.modules[_name] = _modules_before[_name]
if _env_before is None:
    os.environ.pop("CCGM_LEARNINGS_DIR", None)
else:
    os.environ["CCGM_LEARNINGS_DIR"] = _env_before

DAY = "2026-09-02"


def _isolate_env(test: unittest.TestCase) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ccgm-cost-safety-"))
    keys = (
        "CCGM_DREAMING_DIR", "CCGM_LEARNINGS_DIR", "CCGM_DREAMING_ENV_FILE",
        "CCGM_DREAMING_AUTOHEAL_ENV_FILE", "CCGM_DREAMING_TODAY", "ANTHROPIC_API_KEY",
    )
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["CCGM_DREAMING_DIR"] = str(tmp / "dreaming")
    os.environ["CCGM_LEARNINGS_DIR"] = str(tmp / "learnings")
    os.environ["CCGM_DREAMING_ENV_FILE"] = str(tmp / "nonexistent.env")
    os.environ["CCGM_DREAMING_AUTOHEAL_ENV_FILE"] = str(tmp / "nonexistent-autoheal.env")
    os.environ["CCGM_DREAMING_TODAY"] = DAY
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-fixture"

    def _restore():
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        me.set_cost_tracker(None)

    test.addCleanup(_restore)
    return tmp


def _ledger_rows() -> list[list[str]]:
    path = da.cost_log_path()
    if not path.is_file():
        return []
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _seed_ledger(date: str, cost: float, model: str = "seed") -> None:
    da._append_cost(da.cost_log_path(), date, 0, 0, cost, model)  # noqa: SLF001


class ModuleBudgetWindowTests(unittest.TestCase):
    def setUp(self):
        _isolate_env(self)

    def test_window_sums_only_the_last_30_days(self):
        _seed_ledger("2026-09-02", 2.0)
        _seed_ledger("2026-08-04", 3.0)  # 29 days back: inside
        _seed_ledger("2026-08-03", 5.0)  # 30 days back: outside
        spent = da.read_cost_spent_30d(da.cost_log_path(), "2026-09-02")
        self.assertAlmostEqual(spent, 5.0, places=6)

    def test_default_budget_is_25(self):
        self.assertEqual(da.load_config()["module_budget_usd_30d"], 25.0)

    def test_analyzer_refuses_at_or_above_budget(self):
        _seed_ledger("2026-08-20", 25.0)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = da.main(["--force-day", DAY])
        self.assertEqual(rc, 2)
        self.assertIn("30-day module budget", stderr.getvalue())

    def test_analyzer_does_not_refuse_below_budget(self):
        _seed_ledger("2026-08-20", 24.99)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            da.main(["--force-day", DAY])
        self.assertNotIn("30-day module budget", stderr.getvalue())

    def test_run_budget_is_what_is_left_of_the_module_budget(self):
        _seed_ledger("2026-08-20", 24.0)  # $1 left of $25; daily cap is $10
        cfg = da.load_config()
        self.assertAlmostEqual(da.remaining_run_budget_usd(cfg, DAY), 1.0, places=6)

    def test_run_budget_is_daily_headroom_when_that_is_smaller(self):
        _seed_ledger(DAY, 9.0)  # $1 left today; plenty of module budget
        cfg = da.load_config()
        self.assertAlmostEqual(da.remaining_run_budget_usd(cfg, DAY), 1.0, places=6)

    def test_offline_run_budget_is_the_full_daily_cap(self):
        _seed_ledger("2026-08-20", 24.9)
        cfg = da.load_config()
        self.assertAlmostEqual(da.remaining_run_budget_usd(cfg, DAY, offline=True), 10.0, places=6)

    def test_analyzer_plans_against_the_module_budget_left(self):
        _seed_ledger("2026-08-20", 24.0)
        seen = {}
        real_plan = da.plan_run

        def spy(bundles, **kw):
            seen["remaining"] = kw["remaining_budget_usd"]
            return real_plan(bundles, **kw)

        with mock.patch.object(da, "plan_run", side_effect=spy), \
                mock.patch.object(da, "mine_due_slugs", return_value=([{"slug": "s"}], {})), \
                mock.patch.object(da, "resolve_candidate_slugs", return_value=["s"]), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                da.main(["--force-day", DAY, "--dry-run"])
            except Exception:
                pass  # the fake bundle may not survive planning; only the budget handed in matters
        self.assertAlmostEqual(seen["remaining"], 1.0, places=6)

    def test_offline_analyzer_ignores_budget(self):
        _seed_ledger("2026-08-20", 99.0)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            da.main(["--force-day", DAY, "--offline", str(HERE / "fixtures" / "offline-responses")])
        self.assertNotIn("30-day module budget", stderr.getvalue())


class LastRunRecordTests(unittest.TestCase):
    """state/last-run.json says how each analyzer run ended, so health.py never
    infers a refusal from the exit code (rc 2 is shared)."""

    def setUp(self):
        _isolate_env(self)

    def run_main(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return da.main(["--force-day", DAY, *argv])

    def record(self):
        return json.loads(da.last_run_path().read_text(encoding="utf-8"))

    def test_budget_refusal_is_recorded_with_spend_and_budget(self):
        _seed_ledger("2026-08-20", 80.0)
        self.assertEqual(self.run_main(), 2)
        self.assertEqual(self.record(), {
            "date": DAY, "rc": 2, "outcome": "budget_refused", "spent_30d": 80.0, "budget": 25.0})

    def test_daily_cap_refusal_is_recorded_distinctly(self):
        with mock.patch.object(da, "resolve_candidate_slugs", return_value=["s"]), \
                mock.patch.object(da, "mine_due_slugs", return_value=({"s": {}}, {})), \
                mock.patch.object(da, "plan_run", return_value=([], {})):
            self.assertEqual(self.run_main(), 2)
        rec = self.record()
        self.assertEqual((rec["rc"], rec["outcome"]), (2, "daily_cap_refused"))

    def test_other_exit_2_is_failed_not_a_refusal(self):
        with mock.patch.object(da, "_main", return_value=2):
            self.assertEqual(self.run_main(), 2)
        self.assertEqual(self.record()["outcome"], "failed")

    def test_exception_is_recorded_as_failed_and_reraised(self):
        with mock.patch.object(da, "resolve_candidate_slugs", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_main()
        rec = self.record()
        self.assertEqual((rec["rc"], rec["outcome"]), (1, "failed"))

    def test_argparse_error_is_recorded_as_failed(self):
        with self.assertRaises(SystemExit):
            self.run_main("--no-such-flag")
        rec = self.record()
        self.assertEqual((rec["rc"], rec["outcome"]), (2, "failed"))

    def test_successful_run_is_recorded_ok(self):
        self.assertEqual(self.run_main("--offline", str(HERE / "fixtures" / "offline-responses")), 0)
        rec = self.record()
        self.assertEqual((rec["rc"], rec["outcome"]), (0, "ok"))

    def test_dry_run_writes_no_record(self):
        self.run_main("--dry-run")
        self.assertFalse(da.last_run_path().exists())

    def test_record_write_is_atomic(self):
        _seed_ledger("2026-08-20", 80.0)
        self.run_main()
        self.assertEqual(list(da.last_run_path().parent.glob("last-run.json.tmp*")), [])


class FakeClaudeEvalTests(unittest.TestCase):
    """Drives me.main() against a shell-script `claude` that reports $1.00
    per session."""

    def setUp(self):
        self.tmp = _isolate_env(self)
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        task = {
            "id": "canary-a", "kind": "canary", "prompt": "do the thing",
            "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"],
        }
        (self.tasks_dir / "01-a.json").write_text(json.dumps(task), encoding="utf-8")
        self.counter = self.tmp / "sessions.count"
        self.fake_claude = self.tmp / "fake-claude"
        self.fake_claude.write_text(
            "#!/bin/sh\n"
            f"echo x >> '{self.counter}'\n"
            "cat <<'JSON'\n"
            '{"is_error": false, "result": "done", "num_turns": 1, "total_cost_usd": 1.0,'
            ' "usage": {"input_tokens": 100, "output_tokens": 20}}\n'
            "JSON\n",
            encoding="utf-8",
        )
        self.fake_claude.chmod(self.fake_claude.stat().st_mode | stat.S_IXUSR)

        # A prior open gate. An abort leaves the results files exactly as
        # they are, and its marker pauses the gate (#1098 item 2.1).
        arm = {"runs": 5, "format_error_rate": 0.0, "judge_error_rate": 0.0, "mean_score": 9.0}
        green = {
            "date": "2026-08-30", "task_id": "dreamed-01", "kind": "dreamed", "offline": False,
            "backbone": "m", "runs": 5, "baseline": arm, "treatment": arm, "full_context": arm,
            "delta": 2.0, "delta_sat": 1.0, "bucket": "high_value", "cost_usd": 0.5,
            "mining": {"noise_high_value": False},
        }
        me.evals_dir().mkdir(parents=True, exist_ok=True)
        (me.evals_dir() / "2026-08-30.jsonl").write_text(json.dumps(green) + "\n", encoding="utf-8")
        self.addCleanup(lambda: None)

    def _sessions_run(self) -> int:
        if not self.counter.is_file():
            return 0
        return len(self.counter.read_text(encoding="utf-8").splitlines())

    def _run_main(self, *extra: str, judge_usage=None) -> tuple[int, str]:
        usage = judge_usage or {"input_tokens": 0, "output_tokens": 0}
        stderr = io.StringIO()
        with mock.patch.object(me, "_call_judge_api", return_value=({"pass": True, "score": 7.0}, usage)), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            rc = me.main([
                "--full",
                "--tasks", str(self.tasks_dir / "*.json"),
                "--backbone", "fixture-model",
                "--claude-bin", str(self.fake_claude),
                "--date", DAY,
                *extra,
            ])
        return rc, stderr.getvalue()

    def _evals_snapshot(self) -> dict[str, str]:
        return {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(me.evals_dir().iterdir()) if p.suffix == ".jsonl"
        }

    def test_three_dollar_cap_runs_exactly_three_sessions(self):
        snapshot_before = self._evals_snapshot()
        self.assertEqual(me.gate_check()["state"], "open")

        rc, stderr = self._run_main("--runs", "3", "--max-total-usd", "3")

        self.assertEqual(rc, 1, stderr)
        self.assertEqual(self._sessions_run(), 3)
        marker = me.evals_dir() / f"{DAY}.budget-abort"
        self.assertTrue(marker.is_file(), "budget-abort marker missing")
        body = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(body["cap_usd"], 3.0)
        self.assertAlmostEqual(body["spent_usd"], 3.0, places=6)
        self.assertEqual(body["phase"], "run")
        # Results untouched; the marker pauses the gate (infra, not content).
        self.assertEqual(self._evals_snapshot(), snapshot_before)
        gate = me.gate_check()
        self.assertEqual((gate["state"], gate["code"]), ("paused", "budget_abort"))
        self.assertFalse(list(me.evals_dir().glob("*.harness-broken")))
        # All spend is in the ledger.
        rows = _ledger_rows()
        arm_rows = [r for r in rows if r[4].startswith("eval:arm:")]
        self.assertEqual(len(arm_rows), 3)
        self.assertAlmostEqual(sum(float(r[3]) for r in rows), 3.0, places=6)

    def test_preflight_refuses_when_estimate_exceeds_cap(self):
        rc, stderr = self._run_main("--runs", "3", "--max-total-usd", "0.5")
        self.assertEqual(rc, 1, stderr)
        self.assertEqual(self._sessions_run(), 0)
        body = json.loads((me.evals_dir() / f"{DAY}.budget-abort").read_text(encoding="utf-8"))
        self.assertEqual(body["phase"], "preflight")
        self.assertEqual(_ledger_rows(), [])
        self.assertEqual(me.gate_check()["code"], "budget_abort")

    def test_eval_refuses_when_module_budget_is_spent(self):
        _seed_ledger("2026-08-20", 25.0)
        rc, stderr = self._run_main("--runs", "1", "--max-total-usd", "3")
        self.assertEqual(rc, 1, stderr)
        self.assertEqual(self._sessions_run(), 0)
        self.assertIn("30-day module budget", stderr)
        self.assertTrue((me.evals_dir() / f"{DAY}.budget-abort").is_file())

    def test_remaining_module_budget_lowers_the_run_cap(self):
        _seed_ledger("2026-08-20", 24.5)  # $0.50 left of the $25 budget
        rc, _stderr = self._run_main("--runs", "3", "--max-total-usd", "3")
        self.assertEqual(rc, 1)
        self.assertEqual(self._sessions_run(), 0, "preflight must use the $0.50 left, not the $3 flag")
        body = json.loads((me.evals_dir() / f"{DAY}.budget-abort").read_text(encoding="utf-8"))
        self.assertEqual(body["phase"], "preflight")
        self.assertAlmostEqual(body["cap_usd"], 0.5, places=6)

    def test_run_that_fits_writes_results_and_ledger_without_marker(self):
        rc, stderr = self._run_main("--runs", "1", "--max-total-usd", "10")
        self.assertEqual(rc, 0, stderr)
        self.assertEqual(self._sessions_run(), 3)
        self.assertTrue(me.results_path_for_date(DAY).is_file())
        self.assertFalse((me.evals_dir() / f"{DAY}.budget-abort").exists())
        self.assertAlmostEqual(sum(float(r[3]) for r in _ledger_rows()), 3.0, places=6)

    def test_judge_calls_in_a_live_run_reach_the_ledger(self):
        rc, stderr = self._run_main(
            "--runs", "1", "--max-total-usd", "10",
            judge_usage={"input_tokens": 1000, "output_tokens": 100},
        )
        self.assertEqual(rc, 0, stderr)
        judge_rows = [r for r in _ledger_rows() if r[4].startswith("eval:judge:")]
        self.assertEqual(len(judge_rows), 3)
        self.assertEqual(judge_rows[0][1:3], ["1000", "100"])
        self.assertGreater(float(judge_rows[0][3]), 0.0)

    def test_budget_abort_marker_does_not_leak_into_results_glob(self):
        self._run_main("--runs", "3", "--max-total-usd", "3")
        latest = me._find_latest_results_file()  # noqa: SLF001
        self.assertEqual(latest.name, "2026-08-30.jsonl")


class JudgeAndMiningLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def _tracker(self, cap: float = 10.0) -> "me.CostTracker":
        tracker = me.CostTracker(
            cap_usd=cap, ledger_path=da.cost_log_path(), date=DAY, cfg=da.load_config(),
            session_estimate_usd=0.25,
        )
        me.set_cost_tracker(tracker)
        return tracker

    def test_offline_run_with_canned_judge_usage_writes_a_judge_row(self):
        self._tracker()
        out = me.judge_output(
            {"prompt": "p"}, judge_model="claude-opus-4-8", judge_system_prompt="s",
            api_key=None, api_url="http://unused",
            offline_score={"score": 8.0, "judge_usage": {"input_tokens": 2000, "output_tokens": 50}},
        )
        self.assertEqual(out["score"], 8.0)
        rows = _ledger_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "eval:judge:claude-opus-4-8")
        self.assertEqual(rows[0][1:3], ["2000", "50"])
        self.assertAlmostEqual(float(rows[0][3]), 2000 * 5e-6 + 50 * 25e-6, places=6)

    def test_offline_run_without_judge_usage_writes_no_row(self):
        self._tracker()
        me.judge_output(
            {"prompt": "p"}, judge_model="claude-opus-4-8", judge_system_prompt="s",
            api_key=None, api_url="http://unused", offline_score={"score": 8.0},
        )
        self.assertEqual(_ledger_rows(), [])

    def test_judge_call_that_would_cross_the_cap_aborts_before_calling(self):
        tracker = self._tracker(cap=0.001)
        with mock.patch.object(me, "_call_judge_api") as judge:
            with self.assertRaises(me.BudgetAbortError):
                me.judge_output(
                    {"prompt": "p"}, judge_model="claude-opus-4-8", judge_system_prompt="s",
                    api_key="k", api_url="http://unused", offline_score=None,
                )
            judge.assert_not_called()
        self.assertEqual(tracker.spent_usd, 0.0)

    def test_in_eval_mining_spend_is_forwarded_to_the_ledger(self):
        tracker = self._tracker()
        sandbox_state = self.tmp / "sandbox-state"
        sandbox_state.mkdir()
        (sandbox_state / "cost.log").write_text(
            "2026-09-02\t1000\t200\t0.004000\tclaude-sonnet-5\n"
            "2026-09-02\t3000\t500\t0.018500\tclaude-opus-4-8\n",
            encoding="utf-8",
        )
        me.forward_mining_cost(sandbox_state)
        rows = _ledger_rows()
        self.assertEqual([r[4] for r in rows], ["eval:mine:claude-sonnet-5", "eval:mine:claude-opus-4-8"])
        self.assertAlmostEqual(tracker.spent_usd, 0.0225, places=6)

    def test_mining_is_capped_by_what_is_left_of_the_run_cap(self):
        tracker = self._tracker(cap=3.0)
        tracker.record(in_tok=0, out_tok=0, cost_usd=2.5, label="eval:arm:m")
        sandbox_state = self.tmp / "sandbox-state"
        me.write_mining_budget(sandbox_state)
        cfg = json.loads((sandbox_state / "config.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(cfg["daily_cost_cap_usd"], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
