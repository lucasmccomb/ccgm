#!/usr/bin/env python3
"""
Phase 4.2 of epic #1098: the regression smoke test that replaces the $21,
270-session eval.

The smoke is the default of memory_eval.py: 4 tasks (one uplift, one canary,
contradiction-01, dreamed-01) x 2 arms (baseline, treatment) x runs 3 on the
Sonnet backbone = 24 sessions, graded by deterministic checks instead of the
LLM judge, with per-run artifacts under evals/<date>/. `--full` keeps the old
suite.

Nothing here touches the network. `claude` is a Python fake that edits the
workdir the way an agent would; in-eval mining is replaced by a canned
proposals file; the judge transport is patched to fail the test if reached.

Run with: python3 -m pytest modules/dreaming/tests/test_smoke_eval.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-smoke-test-learnings-")
os.environ.setdefault("CCGM_LEARNINGS_DIR", _TMP_LEARNINGS)

sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent / "lib"))

import dream_analyze as da  # noqa: E402
import memory_eval as me  # noqa: E402

TASKS_DIR = HERE.parent / "eval" / "tasks"
OFFLINE_FIXTURES = HERE / "fixtures" / "offline-responses"
DAY = "2026-10-04"

SMOKE_IDS = [
    "uplift-01-migration-reserved-keywords",
    "canary-01-unrelated-rename",
    "contradiction-01-branch-update-workflow",
    "dreamed-01-pipeline-end-to-end",
]

_ENV_KEYS = (
    "CCGM_DREAMING_DIR", "CCGM_LEARNINGS_DIR", "CCGM_LEARNINGS_CACHE_DIR", "CCGM_CLAUDE_PROJECTS_DIR",
    "CCGM_DREAMING_ENV_FILE", "CCGM_DREAMING_AUTOHEAL_ENV_FILE", "CCGM_DREAMING_TODAY",
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CCGM_EVAL_OAUTH_TOKEN_FILE",
)


def _isolate_env(test: unittest.TestCase, *, api_key: str | None = "sk-test-fixture") -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ccgm-smoke-test-"))
    previous = {k: os.environ.get(k) for k in _ENV_KEYS}
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "CCGM_EVAL_OAUTH_TOKEN_FILE", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    os.environ["CCGM_DREAMING_DIR"] = str(tmp / "dreaming")
    os.environ["CCGM_LEARNINGS_DIR"] = str(tmp / "learnings")
    os.environ["CCGM_DREAMING_ENV_FILE"] = str(tmp / "nonexistent.env")
    os.environ["CCGM_DREAMING_AUTOHEAL_ENV_FILE"] = str(tmp / "nonexistent-autoheal.env")
    os.environ["CCGM_DREAMING_TODAY"] = DAY
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    def _restore():
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        me.set_cost_tracker(None)
        me.set_run_context(None)

    test.addCleanup(_restore)
    return tmp


def _load(task_id_prefix: str) -> dict:
    paths = sorted(TASKS_DIR.glob(f"{task_id_prefix}*.json"))
    assert len(paths) == 1, paths
    return me.load_task(paths[0])


def _ledger_rows() -> list[list[str]]:
    path = da.cost_log_path()
    if not path.is_file():
        return []
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The task set
# ---------------------------------------------------------------------------


class SmokeTaskSetTests(unittest.TestCase):
    def test_exactly_four_tasks_are_marked_smoke(self):
        tasks = [t for t in me.load_tasks(me.default_tasks_glob()) if t.get("smoke")]
        self.assertEqual(sorted(t["id"] for t in tasks), sorted(SMOKE_IDS))

    def test_one_uplift_one_canary_one_contradiction_one_dreamed(self):
        tasks = [t for t in me.load_tasks(me.default_tasks_glob()) if t.get("smoke")]
        self.assertEqual(sorted(t["kind"] for t in tasks), ["canary", "contradiction", "dreamed", "uplift"])

    def test_every_smoke_task_carries_a_grader(self):
        for task in me.load_tasks(me.default_tasks_glob()):
            if not task.get("smoke"):
                continue
            grader = me.task_grader(task)
            self.assertTrue(grader["checks"], task["id"])

    def test_the_full_suite_is_still_on_disk(self):
        self.assertEqual(len(me.load_tasks(me.default_tasks_glob())), 9)


# ---------------------------------------------------------------------------
# Deterministic graders
# ---------------------------------------------------------------------------


def _workdir(files: dict[str, str]) -> Path:
    return me.build_fixture_workdir(files, Path(tempfile.mkdtemp(prefix="ccgm-smoke-grader-")) / "w")


GOOD_MIGRATION = (
    'CREATE TABLE IF NOT EXISTS order_tracking (\n  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n'
    '  "order" integer NOT NULL,\n  "position" integer NOT NULL\n);\n'
)


class GraderTests(unittest.TestCase):
    def grade(self, task: dict, files: dict[str, str]) -> dict:
        return me.run_grader(me.task_grader(task), _workdir(files))

    def failed(self, result: dict) -> list[str]:
        return [c["id"] for c in result["checks"] if not c["pass"]]

    def test_check_kinds(self):
        wd = _workdir({"a.txt": "Hello World\n", "d/b.sql": "x"})
        grader = {"checks": [
            {"id": "exists", "kind": "file_exists", "path": "a.txt"},
            {"id": "missing", "kind": "file_exists", "path": "nope.txt"},
            {"id": "re", "kind": "regex", "path": "a.txt", "pattern": "hello\\s+world", "flags": "i"},
            {"id": "re-miss", "kind": "regex", "path": "a.txt", "pattern": "goodbye"},
            {"id": "absent", "kind": "not_regex", "path": "a.txt", "pattern": "goodbye"},
            {"id": "present", "kind": "not_regex", "path": "a.txt", "pattern": "Hello"},
            {"id": "no-sql", "kind": "glob_empty", "pattern": "**/*.sql"},
            {"id": "no-md", "kind": "glob_empty", "pattern": "**/*.md"},
            {"id": "on-missing-file", "kind": "not_regex", "path": "nope.txt", "pattern": "x"},
        ]}
        result = me.run_grader(grader, wd)
        by_name = {c["id"]: c["pass"] for c in result["checks"]}
        self.assertEqual(by_name, {
            "exists": True, "missing": False, "re": True, "re-miss": False,
            "absent": True, "present": False, "no-sql": False, "no-md": True,
            "on-missing-file": False,  # a check on a missing file fails closed
        })
        self.assertFalse(result["pass"])
        self.assertAlmostEqual(result["score"], 10 * 4 / 9, places=3)

    def test_all_checks_passing_scores_ten(self):
        result = me.run_grader(
            {"checks": [{"id": "e", "kind": "file_exists", "path": "a.txt"}]}, _workdir({"a.txt": "x"}),
        )
        self.assertEqual((result["pass"], result["score"]), (True, 10.0))

    def test_unknown_kind_and_escaping_path_raise(self):
        wd = _workdir({"a.txt": "x"})
        with self.assertRaises(ValueError):
            me.run_grader({"checks": [{"id": "n", "kind": "bogus", "path": "a.txt"}]}, wd)
        with self.assertRaises(ValueError):
            me.run_grader({"checks": [{"id": "n", "kind": "file_exists", "path": "../a.txt"}]}, wd)

    def test_uplift_passes_quoted_identifiers_and_fails_bare_ones(self):
        task = _load("01-")
        fixture = task["fixture"]["files"]
        path = "supabase/migrations/0002_add_order_tracking.sql"
        good = self.grade(task, {**fixture, path: GOOD_MIGRATION})
        self.assertTrue(good["pass"], self.failed(good))
        bare = GOOD_MIGRATION.replace('"order"', "order").replace('"position"', "position")
        failed = self.failed(self.grade(task, {**fixture, path: bare}))
        self.assertTrue(any("order" in n for n in failed) and any("position" in n for n in failed), failed)
        self.assertFalse(self.grade(task, fixture)["pass"], "an untouched fixture must not pass")
        no_guard = GOOD_MIGRATION.replace("IF NOT EXISTS ", "")
        self.assertFalse(self.grade(task, {**fixture, path: no_guard})["pass"])

    def test_canary_requires_the_rename_and_no_sql(self):
        task = _load("06-")
        done = {
            "src/utils/date.ts": "export function formatDateTime(iso) {\n  return new Date(iso).toLocaleString();\n}\n",
            "src/components/Timestamp.tsx": (
                'import { formatDateTime } from "../utils/date";\n\n'
                "export function Timestamp({ iso }) {\n  return <span>{formatDateTime(iso)}</span>;\n}\n"
            ),
        }
        self.assertTrue(self.grade(task, done)["pass"], self.failed(self.grade(task, done)))
        self.assertFalse(self.grade(task, task["fixture"]["files"])["pass"])
        half = {**done, "src/components/Timestamp.tsx": task["fixture"]["files"]["src/components/Timestamp.tsx"]}
        self.assertFalse(self.grade(task, half)["pass"])
        with_sql = {**done, "supabase/migrations/0001.sql": "select 1;"}
        self.assertFalse(self.grade(task, with_sql)["pass"])

    def test_contradiction_wants_rebase_and_not_a_merge_recommendation(self):
        task = _load("08-")
        path = "docs/CONTRIBUTING.md"
        rebase = "# Contributing\n\n## Branch Updates\n\nRun `git rebase origin/main`, then `git push --force-with-lease`.\n"
        self.assertTrue(self.grade(task, {path: rebase})["pass"])
        old = task["fixture"]["files"][path]
        self.assertFalse(self.grade(task, {path: old})["pass"])
        both = rebase + "Or merge main in with `git merge origin/main --no-ff`.\n"
        self.assertFalse(self.grade(task, {path: both})["pass"])
        superseded = rebase + "The old `git merge origin/main --no-ff` approach is no longer used.\n"
        self.assertTrue(self.grade(task, {path: superseded})["pass"])

    def test_dreamed_followup_needs_the_synced_at_column(self):
        task = _load("09-")
        fixture = task["follow_up"]["fixture"]["files"]
        path = "supabase/migrations/0002_add_items_review.sql"
        without = (
            "CREATE TABLE IF NOT EXISTS items_review (\n  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n"
            "  passed boolean NOT NULL DEFAULT false\n);\n"
        )
        with_col = without.replace("\n);", ",\n  _synced_at timestamptz\n);")
        failed = self.failed(self.grade(task, {**fixture, path: without}))
        self.assertEqual(len(failed), 1)
        self.assertIn("synced", failed[0])
        self.assertTrue(self.grade(task, {**fixture, path: with_col})["pass"])


# ---------------------------------------------------------------------------
# A fake `claude` that edits the workdir, and a canned mining step
# ---------------------------------------------------------------------------

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

cfg = json.loads(Path(__file__).with_name("fake-claude.json").read_text())
log = Path(cfg["log"])
cwd = Path.cwd()
inject = os.environ.get("CCGM_LEARNINGS_INJECT") == "true"
previous = [json.loads(l) for l in log.read_text().splitlines()] if log.is_file() else []


def put(rel, text):
    p = cwd / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


kind = "unknown"
if (cwd / "src/utils/date.ts").is_file():
    kind = "canary"
    sabotage = inject and sum(1 for r in previous if r["task"] == "canary" and r["inject"]) < cfg.get("canary_treatment_fail", 0)
    if not sabotage:
        put("src/utils/date.ts", "export function formatDateTime(iso) {\n  return new Date(iso).toLocaleString();\n}\n")
        put("src/components/Timestamp.tsx",
            'import { formatDateTime } from "../utils/date";\n\nexport function Timestamp({ iso }) {\n'
            "  return <span>{formatDateTime(iso)}</span>;\n}\n")
elif (cwd / "docs/CONTRIBUTING.md").is_file():
    kind = "contradiction"
    if inject:
        put("docs/CONTRIBUTING.md", "# Contributing\n\n## Branch Updates\n\nRun `git rebase origin/main`.\n")
elif (cwd / "supabase/migrations/0001_init.sql").is_file() and "shipments" in (cwd / "supabase/migrations/0001_init.sql").read_text():
    kind = "uplift"
    put("supabase/migrations/0002_add_order_tracking.sql",
        'CREATE TABLE IF NOT EXISTS order_tracking (\n  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n'
        '  "order" integer NOT NULL,\n  "position" integer NOT NULL\n);\n')
elif (cwd / "supabase/migrations/0001_init.sql").is_file():
    kind = "dreamed"
    synced = ",\n  _synced_at timestamptz" if inject and not cfg.get("dreamed_no_lift") else ""
    put("supabase/migrations/0002_add_items_review.sql",
        "CREATE TABLE IF NOT EXISTS items_review (\n  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "  passed boolean NOT NULL DEFAULT false" + synced + "\n);\n")

with log.open("a") as fh:
    fh.write(json.dumps({
        "task": kind, "inject": inject, "argv": sys.argv[1:],
        "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "api_key": os.environ.get("ANTHROPIC_API_KEY"),
        "oauth": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
    }) + "\n")
print(json.dumps({
    "is_error": False, "result": "edited " + kind, "num_turns": 2, "total_cost_usd": cfg.get("cost", 0.05),
    "usage": {"input_tokens": 100, "output_tokens": 20},
}))
'''


def _install_fake_claude(tmp: Path, **config) -> tuple[Path, Path]:
    log = tmp / "claude-calls.jsonl"
    script = tmp / "fake-claude"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    (tmp / "fake-claude.json").write_text(json.dumps({"log": str(log), **config}), encoding="utf-8")
    return script, log


def _calls(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


MINED_CONTENT = "Every new table must include a _synced_at timestamptz column for the replication pipeline."


def _fake_mining(dreaming_state_dir: Path, *, force_day: str, **_kwargs) -> Path:
    path = dreaming_state_dir / "proposals" / f"{force_day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{
        "id": "p-signal-1", "kind": "learning_add", "project": "dreamed-fixture-repo", "type": "pitfall",
        "content": MINED_CONTENT, "confidence": 8, "status": "pending",
    }]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _mine_stub(**kwargs):
    return _fake_mining(kwargs["dreaming_state_dir"], force_day=kwargs["force_day"])


class LiveFakeSmokeBase(unittest.TestCase):
    """Drives me.main() in its live (non --offline) path against the fake."""

    api_key: str | None = "sk-test-fixture"

    def setUp(self):
        self.tmp = _isolate_env(self, api_key=self.api_key)
        self.claude, self.log = _install_fake_claude(self.tmp)

    def run_main(self, *extra: str, config: dict | None = None):
        if config is not None:
            (self.tmp / "fake-claude.json").write_text(
                json.dumps({"log": str(self.log), **config}), encoding="utf-8")
        stderr = io.StringIO()
        with mock.patch.object(me, "_mine_and_analyze", side_effect=_mine_stub), \
                mock.patch.object(me, "_call_judge_api", side_effect=AssertionError("the smoke must not call the judge")), \
                mock.patch.object(me, "judge_output", side_effect=AssertionError("the smoke must not call the judge")), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            rc = me.main(["--claude-bin", str(self.claude), "--date", DAY, *extra])
        return rc, stderr.getvalue()

    def rows(self) -> list[dict]:
        return me._read_results_file(me.results_path_for_date(DAY))  # noqa: SLF001


class SmokeRunTests(LiveFakeSmokeBase):
    def test_default_run_is_four_tasks_two_arms_three_runs_on_the_map_model(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        calls = _calls(self.log)
        self.assertEqual(len(calls), 24)
        self.assertEqual(sum(1 for c in calls if c["inject"]), 12)
        rows = self.rows()
        self.assertEqual(sorted(r["task_id"] for r in rows), sorted(SMOKE_IDS))
        map_model = da.load_config()["map_model"]
        for row in rows:
            self.assertEqual(row["backbone"], map_model)
            self.assertEqual(row["runs"], 3)
            self.assertEqual(row["baseline"]["runs"], 3)
            self.assertEqual(row["treatment"]["runs"], 3)
            self.assertEqual(row["full_context"]["runs"], 0, "the smoke drops the full_context arm")
            self.assertEqual(row["suite"], "smoke")
            self.assertIn("seed_fingerprint", row)
            self.assertEqual(row["baseline"]["judge_error_rate"], 0.0)
        for call in calls:
            self.assertEqual(call["argv"][call["argv"].index("--model") + 1], map_model)
            self.assertEqual(call["argv"][call["argv"].index("--max-budget-usd") + 1], "0.25")

    def test_graders_decide_the_rows_and_their_results_are_in_the_row(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        by_task = {r["task_id"]: r for r in self.rows()}
        results = 0
        for row in by_task.values():
            for arm in ("baseline", "treatment"):
                detail = row[arm]["run_results"]
                self.assertEqual([d["run"] for d in detail], [0, 1, 2])
                results += len(detail)
        self.assertEqual(results, 24)
        canary = by_task["canary-01-unrelated-rename"]
        self.assertEqual((canary["baseline"]["pass_rate"], canary["treatment"]["pass_rate"]), (1.0, 1.0))
        contradiction = by_task["contradiction-01-branch-update-workflow"]
        self.assertEqual((contradiction["baseline"]["pass_rate"], contradiction["treatment"]["pass_rate"]), (0.0, 1.0))
        dreamed = by_task["dreamed-01-pipeline-end-to-end"]
        self.assertEqual((dreamed["baseline"]["pass_rate"], dreamed["treatment"]["pass_rate"]), (0.0, 1.0))
        self.assertEqual(dreamed["mining"]["signal_proposals_written"], 1)
        self.assertEqual(dreamed["seed_fingerprint"], me.seed_fingerprint([MINED_CONTENT]))

    def test_gate_opens_on_a_clean_smoke_result(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        gate = me.gate_check()
        self.assertEqual((gate["state"], gate["code"]), ("open", "ok"), gate)

    def test_gate_closes_on_a_canary_that_regresses_in_two_of_three_runs(self):
        rc, stderr = self.run_main(config={"canary_treatment_fail": 2})
        self.assertEqual(rc, 0, stderr)
        canary = {r["task_id"]: r for r in self.rows()}["canary-01-unrelated-rename"]
        self.assertEqual(canary["baseline"]["pass_rate"], 1.0)
        self.assertAlmostEqual(canary["treatment"]["pass_rate"], 1 / 3, places=4)
        self.assertEqual(canary["bucket"], "regression")
        gate = me.gate_check()
        self.assertEqual((gate["state"], gate["code"]), ("closed", "regression"), gate)
        self.assertIn("canary-01-unrelated-rename", gate["reason"])

    def test_one_failed_canary_run_in_three_does_not_close_the_gate(self):
        rc, stderr = self.run_main(config={"canary_treatment_fail": 1})
        self.assertEqual(rc, 0, stderr)
        self.assertEqual(me.gate_check()["state"], "open")

    def test_dreamed_no_lift_is_diagnosable_and_is_not_a_regression(self):
        rc, stderr = self.run_main(config={"dreamed_no_lift": True})
        self.assertEqual(rc, 0, stderr)
        dreamed = {r["task_id"]: r for r in self.rows()}["dreamed-01-pipeline-end-to-end"]
        self.assertEqual((dreamed["baseline"]["pass_rate"], dreamed["treatment"]["pass_rate"]), (0.0, 0.0))
        self.assertEqual(me.gate_check()["state"], "open")
        run_dir = next((me.evals_dir() / DAY / "dreamed-01-pipeline-end-to-end").glob("*/treatment-0"))
        grader = json.loads((run_dir / "grader.json").read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in grader["checks"] if not c["pass"]], ["adds _synced_at timestamptz"])

    def test_session_costs_reach_the_ledger_under_the_model_label(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        arm_rows = [r for r in _ledger_rows() if r[4].startswith("eval:arm:")]
        self.assertEqual(len(arm_rows), 24)
        self.assertEqual({r[4] for r in arm_rows}, {f"eval:arm:{da.load_config()['map_model']}"})
        self.assertAlmostEqual(sum(float(r[3]) for r in arm_rows), 24 * 0.05, places=6)
        self.assertEqual([r for r in _ledger_rows() if r[4].startswith("eval:judge:")], [])

    def test_hard_stop_still_applies(self):
        rc, stderr = self.run_main("--max-total-usd", "2.0", config={"cost": 0.20})
        self.assertEqual(rc, 1, stderr)  # 24 x $0.20 = $4.80 > cap; stops before the call that would cross it
        self.assertTrue((me.evals_dir() / f"{DAY}.budget-abort").is_file())
        self.assertLess(len(_calls(self.log)), 24)


class SmokeCostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def tracker(self, smoke=True, subscription=False):
        return me.CostTracker(
            cap_usd=2.0, ledger_path=da.cost_log_path(), date=DAY, cfg=da.load_config(),
            session_estimate_usd=me.smoke_session_estimate(subscription=subscription) if smoke else me.ESTIMATED_SESSION_COST_USD,
        )

    def smoke_tasks(self):
        return [t for t in me.load_tasks(me.default_tasks_glob()) if t.get("smoke")]

    def test_preflight_estimate_for_24_sessions_with_no_judge_is_under_two_dollars(self):
        estimate = me.estimate_run_cost(
            self.smoke_tasks(), backbones=["m"], runs=3, arms=2, judge=False,
            judge_model="j", judge_system_prompt="s", tracker=self.tracker(),
        )
        self.assertLessEqual(estimate, 1.60, "leave at least $0.40 of the $2.00 cap for real sessions above the mean")
        # 24 sessions plus the dreamed task's mining, nothing for a judge.
        self.assertAlmostEqual(estimate, 24 * me.SMOKE_SESSION_COST_USD + me.ESTIMATED_MINING_COST_USD, places=6)

    def test_full_suite_estimate_keeps_three_arms_and_the_judge(self):
        tasks = me.load_tasks(me.default_tasks_glob())
        estimate = me.estimate_run_cost(
            tasks, backbones=["a", "b"], runs=5, judge_model="claude-opus-4-8",
            judge_system_prompt="s", tracker=self.tracker(smoke=False),
        )
        self.assertGreater(estimate, 20.0)

    def test_subscription_sessions_estimate_at_zero(self):
        estimate = me.estimate_run_cost(
            self.smoke_tasks(), backbones=["m"], runs=3, arms=2, judge=False,
            judge_model="j", judge_system_prompt="s", tracker=self.tracker(subscription=True),
        )
        self.assertAlmostEqual(estimate, me.ESTIMATED_MINING_COST_USD, places=6)

    def test_in_eval_mining_runs_on_the_map_model_and_is_capped_by_the_run(self):
        tracker = self.tracker()
        me.set_cost_tracker(tracker)
        tracker.record(in_tok=0, out_tok=0, cost_usd=1.5, label="eval:arm:m")
        state = self.tmp / "mining-state"
        me.write_mining_budget(state)
        cfg = json.loads((state / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["reduce_model"], da.load_config()["map_model"])
        self.assertNotEqual(cfg["reduce_model"], da.load_config()["reduce_model"])
        self.assertAlmostEqual(cfg["daily_cost_cap_usd"], 0.5, places=6)

    def test_mining_estimate_prices_three_sonnet_calls(self):
        pricing = da.resolve_pricing(da.load_config(), da.load_config()["map_model"])
        per_call = da.estimate_call_cost_usd(6000, 3000, pricing)
        self.assertGreaterEqual(me.ESTIMATED_MINING_COST_USD, 3 * per_call)

    def test_per_session_budget_default_is_a_quarter_dollar(self):
        self.assertEqual(me.DEFAULT_MAX_BUDGET_USD_PER_RUN, 0.25)

    def test_the_refresh_cap_default_is_two_dollars(self):
        self.assertEqual(da.load_config()["optimistic_integration"]["eval_refresh_cost_cap_usd"], 2.0)
        self.assertFalse(da.load_config()["optimistic_integration"]["eval_refresh_enabled"])

    def test_main_prints_the_preflight_estimate(self):
        script, _log = _install_fake_claude(self.tmp)
        stderr = io.StringIO()
        with mock.patch.object(me, "_mine_and_analyze", side_effect=_mine_stub), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            me.main(["--claude-bin", str(script), "--date", DAY, "--max-total-usd", "2.0"])
        self.assertRegex(stderr.getvalue(), r"preflight estimate \$1\.59")


# ---------------------------------------------------------------------------
# Artifacts (R10)
# ---------------------------------------------------------------------------


class ArtifactTests(LiveFakeSmokeBase):
    def test_every_run_leaves_output_diff_and_grader_results(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        root = me.evals_dir() / DAY
        run_dirs = sorted(p for p in root.glob("*/*/*-[0-9]") if p.is_dir())
        self.assertEqual(len(run_dirs), 24, [str(p.relative_to(root)) for p in run_dirs])
        for run_dir in run_dirs:
            for name in ("output.txt", "workdir.diff", "grader.json", "result.json"):
                self.assertTrue((run_dir / name).is_file(), f"{run_dir.name}/{name}")
        canary = next(p for p in run_dirs if p.parts[-3] == "canary-01-unrelated-rename" and p.name == "treatment-0")
        self.assertIn("formatDateTime", (canary / "workdir.diff").read_text(encoding="utf-8"))
        self.assertEqual((canary / "output.txt").read_text(encoding="utf-8"), "edited canary")
        grader = json.loads((canary / "grader.json").read_text(encoding="utf-8"))
        self.assertTrue(grader["pass"])
        self.assertTrue(all(c["pass"] for c in grader["checks"]))

    def test_diff_shows_what_changed_against_the_fixture(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        root = me.evals_dir() / DAY
        baseline = next(root.glob("dreamed-01-pipeline-end-to-end/*/baseline-0"))
        treatment = next(root.glob("dreamed-01-pipeline-end-to-end/*/treatment-0"))
        self.assertNotIn("_synced_at", (baseline / "workdir.diff").read_text(encoding="utf-8"))
        diff = (treatment / "workdir.diff").read_text(encoding="utf-8")
        self.assertIn("+  _synced_at timestamptz", diff)
        self.assertIn("0002_add_items_review.sql", diff)

    def test_dreamed_task_keeps_the_mined_proposal_text(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        mining = me.evals_dir() / DAY / "dreamed-01-pipeline-end-to-end" / "mining"
        proposals = (mining / "proposals.jsonl").read_text(encoding="utf-8")
        self.assertIn(MINED_CONTENT, proposals)
        applied = json.loads((mining / "applied.json").read_text(encoding="utf-8"))
        self.assertEqual(applied["injected_facts"], [MINED_CONTENT])
        self.assertIn("applied", applied)

    def test_artifact_dir_is_not_mistaken_for_a_results_file(self):
        self.run_main()
        self.assertEqual(me._find_latest_results_file().name, f"{DAY}.jsonl")  # noqa: SLF001
        self.assertEqual(me.gate_check()["state"], "open")


# ---------------------------------------------------------------------------
# Offline smoke (CI step d): plumbing only, no judge, no claude
# ---------------------------------------------------------------------------


class OfflineSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self, api_key=None)

    def run_offline(self, *extra: str, judge_allowed: bool = False):
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(me, "run_claude_p", side_effect=AssertionError("claude called")))
            if not judge_allowed:
                stack.enter_context(mock.patch.object(me, "_call_judge_api", side_effect=AssertionError("judge called")))
                stack.enter_context(mock.patch.object(me, "judge_output", side_effect=AssertionError("judge called")))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            rc = me.main(["--offline", str(OFFLINE_FIXTURES), "--date", DAY, *extra])
        return rc, stderr.getvalue()

    def test_offline_smoke_writes_24_graded_runs_and_no_judge_calls(self):
        rc, stderr = self.run_offline()
        self.assertEqual(rc, 0, stderr)
        rows = me._read_results_file(me.results_path_for_date(DAY))  # noqa: SLF001
        self.assertEqual(sorted(r["task_id"] for r in rows), sorted(SMOKE_IDS))
        graded = [d for r in rows for arm in ("baseline", "treatment") for d in r[arm]["run_results"]]
        self.assertEqual(len(graded), 24)
        run_dirs = [p for p in (me.evals_dir() / DAY).glob("*/*/*-[0-9]") if p.is_dir()]
        self.assertEqual(len(run_dirs), 24)
        self.assertTrue(all(r["offline"] for r in rows))
        rates = {r["task_id"]: (r["baseline"]["pass_rate"], r["treatment"]["pass_rate"]) for r in rows}
        self.assertEqual(rates, {
            "uplift-01-migration-reserved-keywords": (0.0, 1.0),
            "canary-01-unrelated-rename": (1.0, 1.0),
            "contradiction-01-branch-update-workflow": (0.0, 1.0),
            "dreamed-01-pipeline-end-to-end": (0.0, 1.0),
        })
        self.assertEqual(me.gate_check()["state"], "open")

    def test_full_flag_runs_the_old_nine_task_three_arm_suite(self):
        rc, stderr = self.run_offline("--full", "--runs", "1", "--backbone", "m", judge_allowed=True)
        self.assertEqual(rc, 0, stderr)
        rows = me._read_results_file(me.results_path_for_date(DAY))  # noqa: SLF001
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r["full_context"]["runs"] == 1 for r in rows))
        self.assertTrue(all(r.get("suite") == "full" for r in rows))


# ---------------------------------------------------------------------------
# Subscription auth (#1038)
# ---------------------------------------------------------------------------


class SubscriptionAuthTests(LiveFakeSmokeBase):
    def test_oauth_token_in_env_is_passed_and_the_api_key_is_not(self):
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-test-token"
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        calls = _calls(self.log)
        self.assertEqual(len(calls), 24)
        for call in calls:
            self.assertEqual(call["oauth"], "sk-ant-oat-test-token")
            self.assertFalse(call["has_api_key"], "the API key must not reach a subscription arm")
        self.assertIn("arm auth: subscription", stderr)
        self.assertNotIn("sk-ant-oat-test-token", stderr)

    def test_subscription_sessions_cost_zero_in_the_ledger(self):
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-test-token"
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        arm_rows = [r for r in _ledger_rows() if r[4].startswith("eval:arm:")]
        self.assertEqual(len(arm_rows), 24)
        self.assertEqual({r[4] for r in arm_rows}, {"eval:arm:subscription"})
        self.assertEqual({float(r[3]) for r in arm_rows}, {0.0})
        rows = self.rows()
        self.assertTrue(all(r["auth"] == "subscription" for r in rows))
        self.assertTrue(all(r["cost_usd"] == 0.0 for r in rows))

    def test_subscription_sessions_do_not_spend_the_run_cap(self):
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-test-token"
        # A cap far below 24 x the reported $0.05 would abort an API-billed run.
        rc, stderr = self.run_main("--max-total-usd", "0.6")
        self.assertEqual(rc, 0, stderr)
        self.assertEqual(len(_calls(self.log)), 24)

    def test_token_file_is_used_when_no_env_var(self):
        token_file = self.tmp / "oauth-token"
        token_file.write_text("sk-ant-oat-from-file\n", encoding="utf-8")
        os.environ["CCGM_EVAL_OAUTH_TOKEN_FILE"] = str(token_file)
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        self.assertEqual({c["oauth"] for c in _calls(self.log)}, {"sk-ant-oat-from-file"})
        self.assertFalse(any(c["has_api_key"] for c in _calls(self.log)))

    def test_configured_token_file_is_used(self):
        token_file = self.tmp / "configured-token"
        token_file.write_text("sk-ant-oat-configured\n", encoding="utf-8")
        cfg_path = Path(os.environ["CCGM_DREAMING_DIR"]) / "config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"optimistic_integration": {"eval_oauth_token_file": str(token_file)}}))
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        self.assertEqual({c["oauth"] for c in _calls(self.log)}, {"sk-ant-oat-configured"})

    def test_env_var_wins_over_the_token_file(self):
        token_file = self.tmp / "oauth-token"
        token_file.write_text("sk-ant-oat-from-file\n", encoding="utf-8")
        os.environ["CCGM_EVAL_OAUTH_TOKEN_FILE"] = str(token_file)
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-from-env"
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        self.assertEqual({c["oauth"] for c in _calls(self.log)}, {"sk-ant-oat-from-env"})

    def test_no_token_falls_back_to_the_api_key(self):
        rc, stderr = self.run_main()
        self.assertEqual(rc, 0, stderr)
        for call in _calls(self.log):
            self.assertEqual(call["api_key"], "sk-test-fixture")
            self.assertIsNone(call["oauth"])
        self.assertIn("arm auth: api_key", stderr)
        arm_rows = [r for r in _ledger_rows() if r[4].startswith("eval:arm:")]
        self.assertNotIn("eval:arm:subscription", {r[4] for r in arm_rows})
        self.assertTrue(all(r["auth"] == "api_key" for r in self.rows()))

    def test_empty_or_missing_token_file_falls_back_to_the_api_key(self):
        empty = self.tmp / "empty-token"
        empty.write_text("\n", encoding="utf-8")
        for path in (empty, self.tmp / "does-not-exist"):
            os.environ["CCGM_EVAL_OAUTH_TOKEN_FILE"] = str(path)
            self.assertEqual(me.resolve_arm_auth(da.load_config()).kind, "api_key")

    def test_resolve_arm_auth_never_returns_the_token_in_repr(self):
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-secret"
        auth = me.resolve_arm_auth(da.load_config())
        self.assertEqual((auth.kind, auth.token), ("subscription", "sk-ant-oat-secret"))
        self.assertNotIn("sk-ant-oat-secret", repr(auth))


# ---------------------------------------------------------------------------
# Check-level gate rule: treatment fails a check that baseline passes
# ---------------------------------------------------------------------------


def _arm(runs: list[dict[str, bool]]) -> dict:
    results = [
        {"run": i, "executed": True, "pass": all(r.values()), "score": 10.0 * sum(r.values()) / len(r),
         "checks": [{"id": k, "pass": v} for k, v in r.items()]}
        for i, r in enumerate(runs)
    ]
    return {
        "runs": len(runs), "pass_rate": sum(1 for r in results if r["pass"]) / len(runs),
        "format_error_rate": 0.0, "judge_error_rate": 0.0, "run_results": results,
    }


def _row(baseline: list[dict[str, bool]], treatment: list[dict[str, bool]], *, kind: str = "canary") -> dict:
    return {
        "task_id": "canary-x", "kind": kind, "backbone": "m", "runs": 3, "offline": False,
        "baseline": _arm(baseline), "treatment": _arm(treatment), "full_context": {"runs": 0},
        "seed_fingerprint": "fp", "bucket": "neutral",
    }


class CheckLevelGateTests(unittest.TestCase):
    def setUp(self):
        _isolate_env(self)

    def gate(self, row: dict) -> dict:
        me.write_results([row], date=DAY)
        return me.gate_check()

    def test_one_check_regressing_in_two_of_three_closes_the_gate_while_the_others_pass(self):
        # Baseline always fails Y, so the task never passes: the task-level
        # pass-rate rule sees nothing. X passes 3/3 in baseline and fails 2/3 in treatment.
        baseline = [{"X": True, "Y": False, "Z": True}] * 3
        treatment = [
            {"X": False, "Y": False, "Z": True},
            {"X": False, "Y": False, "Z": True},
            {"X": True, "Y": False, "Z": True},
        ]
        row = _row(baseline, treatment)
        self.assertEqual(row["baseline"]["pass_rate"], 0.0)
        self.assertEqual(me.regressed_checks(row), ["X"])
        gate = self.gate(row)
        self.assertEqual((gate["state"], gate["code"]), ("closed", "regression"), gate)
        self.assertIn("X", gate["reason"])
        self.assertNotIn("Z", gate["reason"])

    def test_one_failed_run_of_three_stays_open(self):
        baseline = [{"X": True, "Z": True}] * 3
        treatment = [{"X": False, "Z": True}, {"X": True, "Z": True}, {"X": True, "Z": True}]
        self.assertEqual(self.gate(_row(baseline, treatment))["state"], "open")

    def test_a_check_the_baseline_does_not_reliably_pass_is_not_a_regression(self):
        baseline = [{"X": True}, {"X": False}, {"X": False}]
        treatment = [{"X": False}] * 3
        row = _row(baseline, treatment)
        self.assertEqual(me.regressed_checks(row), [])
        self.assertEqual(self.gate(row)["state"], "open")

    def test_a_check_treatment_improves_is_not_a_regression(self):
        baseline = [{"X": False, "Z": True}] * 3
        treatment = [{"X": True, "Z": True}] * 3
        self.assertEqual(self.gate(_row(baseline, treatment))["state"], "open")

    def test_unchecked_tasks_are_still_skipped(self):
        baseline = [{"X": True}] * 3
        treatment = [{"X": False}] * 3
        row = _row(baseline, treatment, kind="uplift")
        me.write_results([row], date="2026-09-20")
        stamp = 1_700_000_000
        os.utime(me.results_path_for_date("2026-09-20"), (stamp, stamp))
        me.write_results([row], date=DAY)  # same seed fingerprint as the previous run
        self.assertEqual(me.gate_check()["state"], "open")

    def test_rows_without_per_check_results_keep_the_pass_rate_rule(self):
        arm_ok = {"runs": 3, "pass_rate": 1.0, "format_error_rate": 0.0, "judge_error_rate": 0.0}
        arm_bad = {**arm_ok, "pass_rate": 0.0}
        row = {"task_id": "c", "kind": "canary", "backbone": "m", "runs": 3, "baseline": arm_ok,
               "treatment": arm_bad, "full_context": {}, "bucket": "regression"}
        self.assertEqual(me.regressed_checks(row), [])
        self.assertEqual(me.assess_row(row), "regression")

    def test_fewer_than_three_graded_runs_cannot_support_a_check_regression(self):
        baseline = [{"X": True}] * 2
        treatment = [{"X": False}] * 2
        self.assertEqual(me.regressed_checks(_row(baseline, treatment)), [])

    def test_smoke_rows_name_the_regressed_check_and_bucket_regression(self):
        script_dir = self.tmp_dir = Path(tempfile.mkdtemp(prefix="ccgm-smoke-chk-"))
        script, log = _install_fake_claude(script_dir, canary_treatment_fail=2)
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-fixture"
        with mock.patch.object(me, "_mine_and_analyze", side_effect=_mine_stub), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = me.main(["--claude-bin", str(script), "--date", DAY])
        self.assertEqual(rc, 0)
        canary = {r["task_id"]: r for r in me._read_results_file(me.results_path_for_date(DAY))}["canary-01-unrelated-rename"]
        self.assertEqual(canary["bucket"], "regression")
        self.assertIn("Timestamp.tsx calls formatDateTime", canary["regressed_checks"])
        self.assertIn("check:", me.gate_check()["reason"])
        for run in canary["treatment"]["run_results"]:
            self.assertTrue(all({"id", "pass"} == set(c) for c in run["checks"]))


class RunClaudePAuthEnvTests(unittest.TestCase):
    def call(self, **kwargs):
        captured = {}

        def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
            captured["env"] = env
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"is_error": False, "result": "ok"}), stderr="")

        tmp = Path(tempfile.mkdtemp(prefix="ccgm-smoke-env-"))
        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            me.run_claude_p(
                prompt="p", workdir=tmp / "w", config_dir=tmp / "c", home_dir=tmp / "h", model="m", inject=True,
                api_key="sk-api", learnings_dir=tmp / "l", claude_bin="claude", max_budget_usd=0.25, timeout_s=5,
                **kwargs,
            )
        return captured["env"]

    def test_oauth_token_replaces_the_api_key_in_the_child_env(self):
        env = self.call(oauth_token="sk-ant-oat-x")
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat-x")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_without_a_token_the_api_key_is_passed_and_no_oauth_var(self):
        env = self.call()
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-api")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_ambient_oauth_token_never_leaks_into_an_api_key_arm(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-ambient"}):
            env = self.call()
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)


if __name__ == "__main__":
    unittest.main()
