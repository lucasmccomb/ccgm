#!/usr/bin/env python3
"""
Tests for modules/dreaming/eval/memory_eval.py.

Runs in isolation: CCGM_LEARNINGS_DIR is redirected to a tempdir BEFORE
import (mirrors modules/dreaming/tests/test_dream_analyze.py's own pattern
-- learnings_store.LEARNINGS_ROOT is a module-level constant frozen at
import time). CCGM_DREAMING_DIR is redirected per-test (memory_eval's own
path helpers read the env var dynamically, so no import-time freeze
applies there). Every claude -p / judge call in these tests goes through
memory_eval's own --offline short-circuit (offline_score is not None) --
no network, no ANTHROPIC_API_KEY, no `claude` subprocess is ever invoked
by this file.

Run with: python3 -m pytest modules/dreaming/tests/test_memory_eval.py -q
      or: python3 modules/dreaming/tests/test_memory_eval.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent

# Point the learnings store at a tempdir BEFORE importing memory_eval, which
# imports learnings_store transitively (via transcript_miner) at module
# load time.
_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-eval-test-learnings-")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS

sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent / "lib"))

import memory_eval as me  # noqa: E402
import learnings_store  # noqa: E402

TASKS_DIR = HERE.parent / "eval" / "tasks"
OFFLINE_FIXTURES = HERE / "fixtures" / "offline-responses"


def _isolate_env(test: unittest.TestCase) -> Path:
    """Fresh CCGM_DREAMING_DIR + CCGM_LEARNINGS_DIR per test; restores both
    (and CCGM_LEARNINGS_CACHE_DIR / CCGM_CLAUDE_PROJECTS_DIR, which
    memory_eval's own _learnings_store_pointed_at() may set) on cleanup."""
    tmp = tempfile.mkdtemp(prefix="ccgm-eval-test-")
    keys = (
        "CCGM_DREAMING_DIR", "CCGM_LEARNINGS_DIR", "CCGM_LEARNINGS_CACHE_DIR",
        "CCGM_CLAUDE_PROJECTS_DIR", "CCGM_DREAMING_ENV_FILE", "CCGM_DREAMING_AUTOHEAL_ENV_FILE",
    )
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["CCGM_DREAMING_DIR"] = str(Path(tmp) / "dreaming")
    os.environ["CCGM_LEARNINGS_DIR"] = str(Path(tmp) / "learnings")
    os.environ["CCGM_DREAMING_ENV_FILE"] = str(Path(tmp) / "nonexistent.env")
    os.environ["CCGM_DREAMING_AUTOHEAL_ENV_FILE"] = str(Path(tmp) / "nonexistent-autoheal.env")

    def _restore():
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    test.addCleanup(_restore)
    return Path(tmp)


# ---------------------------------------------------------------------------
# classify_bucket(): pure function, synthetic scores (decisions.md #8,
# bizlogic-002's Δ_sat precondition).
# ---------------------------------------------------------------------------

class ClassifyBucketTests(unittest.TestCase):
    def test_high_value_requires_delta_sat_positive(self):
        bucket, delta, delta_sat = me.classify_bucket(baseline_mean=3.0, treatment_mean=8.5, full_context_mean=6.0)
        self.assertEqual(bucket, "high_value")
        self.assertAlmostEqual(delta, 5.5)
        self.assertAlmostEqual(delta_sat, 2.5)
        self.assertGreater(delta_sat, 0)

    def test_beats_baseline_but_not_full_context_is_not_high_value(self):
        """bizlogic-002: a task that beats baseline (delta >= 1.5) but does
        NOT beat the full-context-dump arm (delta_sat <= 0) must NOT be
        classified high_value -- the memory must add value beyond what a
        naive full dump of the same facts already supplies."""
        bucket, delta, delta_sat = me.classify_bucket(baseline_mean=3.0, treatment_mean=8.5, full_context_mean=9.0)
        self.assertGreaterEqual(delta, me.HIGH_VALUE_DELTA_THRESHOLD)
        self.assertLessEqual(delta_sat, 0)
        self.assertNotEqual(bucket, "high_value")

    def test_high_value_boundary_exact_threshold(self):
        bucket, delta, delta_sat = me.classify_bucket(baseline_mean=5.0, treatment_mean=6.5, full_context_mean=6.4)
        self.assertEqual(delta, 1.5)
        self.assertGreater(delta_sat, 0)
        self.assertEqual(bucket, "high_value")

    def test_regression(self):
        bucket, delta, _ = me.classify_bucket(baseline_mean=8.0, treatment_mean=6.0, full_context_mean=8.0)
        self.assertEqual(bucket, "regression")
        self.assertAlmostEqual(delta, -2.0)

    def test_regression_boundary_exact_threshold(self):
        bucket, delta, _ = me.classify_bucket(baseline_mean=8.0, treatment_mean=7.0, full_context_mean=8.0)
        self.assertEqual(delta, -1.0)
        self.assertEqual(bucket, "regression")

    def test_redundant(self):
        bucket, delta, _ = me.classify_bucket(baseline_mean=9.0, treatment_mean=8.5, full_context_mean=8.9)
        self.assertEqual(bucket, "redundant")
        self.assertLess(abs(delta), me.REDUNDANT_DELTA_ABS_THRESHOLD)

    def test_redundant_requires_high_baseline(self):
        """A small delta with a LOW baseline is not redundant -- redundant
        means 'already scored well without help', not merely 'no change'."""
        bucket, _delta, _ = me.classify_bucket(baseline_mean=5.0, treatment_mean=5.3, full_context_mean=5.2)
        self.assertNotEqual(bucket, "redundant")

    def test_gap(self):
        bucket, delta, _ = me.classify_bucket(baseline_mean=3.0, treatment_mean=4.0, full_context_mean=3.5)
        self.assertEqual(bucket, "gap")
        self.assertLess(delta, me.HIGH_VALUE_DELTA_THRESHOLD)

    def test_regression_takes_precedence_over_gap_on_overlap(self):
        """baseline=4.0, treatment=2.9: both means < 5.0 (gap-shaped) AND
        delta=-1.1 <= -1.0 (regression-shaped) -- regression must win; a
        real regression must never be silently reclassified as a mere gap."""
        bucket, delta, _ = me.classify_bucket(baseline_mean=4.0, treatment_mean=2.9, full_context_mean=4.0)
        self.assertLessEqual(delta, me.REGRESSION_DELTA_THRESHOLD)
        self.assertLess(4.0, 5.0)  # sanity: baseline is gap-shaped too
        self.assertEqual(bucket, "regression")

    def test_inconclusive_when_no_bucket_matches(self):
        bucket, _delta, _ = me.classify_bucket(baseline_mean=5.5, treatment_mean=6.2, full_context_mean=6.0)
        self.assertEqual(bucket, "inconclusive")


# ---------------------------------------------------------------------------
# Isolated config guard (adrev-003a).
# ---------------------------------------------------------------------------

class IsolatedConfigGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-isoconf-"))
        self.hook_path = self.tmp / "fake-learnings-inject.py"
        self.hook_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def test_build_isolated_config_passes_its_own_guard(self):
        config_dir = self.tmp / "config"
        me.build_isolated_config(config_dir, hook_path=self.hook_path)
        # Does not raise -- re-running the guard against the same dir must
        # also pass (idempotent check).
        me.assert_isolated_config_registers_only_injection_hook(config_dir)

    def test_guard_rejects_extra_hook_event(self):
        config_dir = self.tmp / "config-extra-event"
        config_dir.mkdir(parents=True)
        settings = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": f"python3 {self.hook_path}"}]}],
                "PreToolUse": [{"hooks": [{"type": "command", "command": "python3 some-other-gate.py"}]}],
            }
        }
        (config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        with self.assertRaises(me.IsolatedConfigError):
            me.assert_isolated_config_registers_only_injection_hook(config_dir)

    def test_guard_rejects_unexpected_command_under_session_start(self):
        config_dir = self.tmp / "config-extra-command"
        config_dir.mkdir(parents=True)
        settings = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": f"python3 {self.hook_path}"}]},
                    {"hooks": [{"type": "command", "command": "python3 relevance-inject.py"}]},
                ]
            }
        }
        (config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        with self.assertRaises(me.IsolatedConfigError):
            me.assert_isolated_config_registers_only_injection_hook(config_dir)

    def test_guard_rejects_missing_settings_file(self):
        config_dir = self.tmp / "config-missing"
        config_dir.mkdir(parents=True)
        with self.assertRaises(me.IsolatedConfigError):
            me.assert_isolated_config_registers_only_injection_hook(config_dir)

    def test_guard_rejects_no_hooks_at_all(self):
        config_dir = self.tmp / "config-empty"
        config_dir.mkdir(parents=True)
        (config_dir / "settings.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        with self.assertRaises(me.IsolatedConfigError):
            me.assert_isolated_config_registers_only_injection_hook(config_dir)


# ---------------------------------------------------------------------------
# Fixture-builder writes exactly the declared files.
# ---------------------------------------------------------------------------

class FixtureWorkdirTests(unittest.TestCase):
    def test_writes_exactly_the_declared_files(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-fixture-"))
        dest = tmp / "workdir"
        files = {
            "a.txt": "hello\n",
            "nested/b.txt": "world\n",
            "deep/er/nested/c.md": "# doc\n",
        }
        me.build_fixture_workdir(files, dest)

        found = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
        self.assertEqual(found, set(files.keys()))
        for rel, content in files.items():
            self.assertEqual((dest / rel).read_text(encoding="utf-8"), content)

    def test_empty_fixture_creates_empty_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-fixture-empty-"))
        dest = tmp / "workdir"
        me.build_fixture_workdir({}, dest)
        self.assertTrue(dest.is_dir())
        self.assertEqual(list(dest.rglob("*")), [])

    def test_snapshot_workdir_round_trips_written_content(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-snapshot-"))
        dest = tmp / "workdir"
        files = {"x.py": "print('hi')\n", "sub/y.md": "notes\n"}
        me.build_fixture_workdir(files, dest)
        snap = me.snapshot_workdir(dest)
        self.assertEqual(snap, files)

    def test_snapshot_workdir_skips_git_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-snapshot-git-"))
        dest = tmp / "workdir"
        me.build_fixture_workdir({"a.txt": "keep\n"}, dest)
        (dest / ".git").mkdir()
        (dest / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        snap = me.snapshot_workdir(dest)
        self.assertEqual(snap, {"a.txt": "keep\n"})


# ---------------------------------------------------------------------------
# Judge-prompt blindness: no condition strings anywhere in the payload sent
# to the judge (adrev-003a test contract).
# ---------------------------------------------------------------------------

class JudgeBlindnessTests(unittest.TestCase):
    def test_payload_never_names_the_condition(self):
        payload = me.build_judge_payload(
            prompt="Do the thing.",
            criteria=["The thing was done."],
            final_files={"a.txt": "done"},
            agent_summary="I did the thing.",
        )
        blob = json.dumps(payload).lower()
        for forbidden in ("baseline", "treatment", "full_context", "full-context", "injection", "memory on", "memory off"):
            self.assertNotIn(forbidden, blob, f"judge payload must never leak {forbidden!r}")

    def test_judge_system_prompt_file_documents_blindness(self):
        text = me.judge_prompt_path().read_text(encoding="utf-8").lower()
        self.assertIn("blind", text)
        # The instruction text is allowed to NAME baseline/treatment as
        # concepts it must never leak into scoring rationale -- but the
        # ACTUAL data payload (tested above) never carries those words.
        self.assertIn("pass", text)
        self.assertIn("score", text)


# ---------------------------------------------------------------------------
# _call_judge_api(): the live judge-call transport. --offline short-circuits
# judge_output() before this function is ever reached, so without this class
# the request shape / 429-retry / response-parse logic has zero automated
# coverage. Exercised here with a monkeypatched subprocess.run -- no
# network, no ANTHROPIC_API_KEY, no `curl` subprocess is ever spawned.
# ---------------------------------------------------------------------------

class CallJudgeApiTransportTests(unittest.TestCase):
    @staticmethod
    def _fake_proc(*, returncode: int = 0, body: str = "", http_code: str = "200", stderr: str = ""):
        return types.SimpleNamespace(returncode=returncode, stdout=f"{body}\n{http_code}", stderr=stderr)

    @staticmethod
    def _messages_api_body(parsed_obj: dict, *, input_tokens: int = 42, output_tokens: int = 7) -> str:
        return json.dumps({
            "content": [{"type": "text", "text": json.dumps(parsed_obj)}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        })

    def test_request_carries_temperature_zero_model_system_and_messages(self):
        captured = {}

        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002 - matches subprocess.run's own kwarg name
            captured["cmd"] = cmd
            captured["input"] = input
            return self._fake_proc(body=self._messages_api_body({"pass": True, "score": 8.5}))

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="You are a blind judge.",
                user_obj={"task_prompt": "Do X.", "criteria": ["done"], "final_files": {}, "agent_summary": "done"},
                max_output_tokens=200, api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertEqual(parsed, {"pass": True, "score": 8.5})
        self.assertEqual(usage, {"input_tokens": 42, "output_tokens": 7})

        request_body = json.loads(captured["input"])
        self.assertEqual(request_body["temperature"], 0)
        self.assertEqual(request_body["model"], "claude-judge-fixture")
        self.assertEqual(request_body["system"], "You are a blind judge.")
        self.assertEqual(request_body["max_tokens"], 200)
        self.assertEqual(len(request_body["messages"]), 1)
        self.assertEqual(request_body["messages"][0]["role"], "user")
        # The user_obj is JSON-encoded into the message content, not
        # flattened -- round-trips back to the exact payload sent in.
        self.assertEqual(json.loads(request_body["messages"][0]["content"]), {
            "task_prompt": "Do X.", "criteria": ["done"], "final_files": {}, "agent_summary": "done",
        })
        self.assertIn("sk-test-fixture", " ".join(captured["cmd"]))

    def test_429_retries_then_succeeds_on_the_next_attempt(self):
        calls = []

        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002
            calls.append(input)
            if len(calls) == 1:
                return self._fake_proc(body="", http_code="429")
            return self._fake_proc(body=self._messages_api_body({"pass": False, "score": 3.0}))

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run), \
                mock.patch("memory_eval.time.sleep", return_value=None) as fake_sleep:
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="sys",
                user_obj={"a": 1}, max_output_tokens=100,
                api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertEqual(len(calls), 2)
        self.assertTrue(fake_sleep.called)
        self.assertEqual(parsed, {"pass": False, "score": 3.0})
        self.assertEqual(usage, {"input_tokens": 42, "output_tokens": 7})

    def test_429_exhausts_retries_and_returns_none(self):
        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002
            return self._fake_proc(body="", http_code="429")

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run), \
                mock.patch("memory_eval.time.sleep", return_value=None):
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="sys",
                user_obj={"a": 1}, max_output_tokens=100,
                api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertIsNone(parsed)
        self.assertEqual(usage, {"input_tokens": 0, "output_tokens": 0})

    def test_non_200_non_429_returns_none(self):
        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002
            return self._fake_proc(body="server error", http_code="500")

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="sys",
                user_obj={"a": 1}, max_output_tokens=100,
                api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertIsNone(parsed)
        self.assertEqual(usage, {"input_tokens": 0, "output_tokens": 0})

    def test_curl_launch_failure_returns_none_without_raising(self):
        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002
            raise OSError("curl: command not found")

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="sys",
                user_obj={"a": 1}, max_output_tokens=100,
                api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertIsNone(parsed)
        self.assertEqual(usage, {"input_tokens": 0, "output_tokens": 0})


# ---------------------------------------------------------------------------
# seed_temp_store(): basic add + the contradiction chain (supersede
# filtering) the kind:contradiction task depends on.
# ---------------------------------------------------------------------------

class SeedTempStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_basic_add_is_searchable(self):
        learnings_dir = self.tmp / "store"
        seed_temp_store_input = [{"type": "pitfall", "content": "Quote reserved keywords.", "confidence": 8, "tags": ["sql"]}]
        me.seed_temp_store(seed_temp_store_input, learnings_dir=learnings_dir, project_slug="proj-a")

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            heads = learnings_store.load_all("proj-a")
        contents = [h["content"] for h in heads]
        self.assertIn("Quote reserved keywords.", contents)

    def test_supersedes_previous_builds_a_real_chain_and_hides_the_old_head(self):
        learnings_dir = self.tmp / "store"
        seed = [
            {"type": "preference", "content": "Old guidance.", "confidence": 6},
            {"type": "preference", "content": "New guidance.", "confidence": 8, "supersedes_previous": True, "supersede_reason": "reversed"},
        ]
        me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug="proj-b")

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            all_heads = learnings_store.load_all("proj-b")
            searched = learnings_store.search(slug="proj-b", max_results=10)

        # load_all() still returns both heads (superseded rows stay present
        # pre-filter, matching v1 behavior) -- but the OLD one must carry
        # superseded_by, and search()'s default filtering must exclude it.
        old = next(h for h in all_heads if h["content"] == "Old guidance.")
        self.assertIsNotNone(old.get("superseded_by"))
        searched_contents = [h["content"] for h in searched]
        self.assertIn("New guidance.", searched_contents)
        self.assertNotIn("Old guidance.", searched_contents)

    def test_supersedes_previous_without_preceding_entry_raises(self):
        learnings_dir = self.tmp / "store"
        seed = [{"type": "preference", "content": "Orphan supersede.", "supersedes_previous": True}]
        with self.assertRaises(ValueError):
            me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug="proj-c")


# ---------------------------------------------------------------------------
# full_context_facts() / build_full_context_prompt().
# ---------------------------------------------------------------------------

class FullContextFactsTests(unittest.TestCase):
    def test_defaults_from_seed_learnings(self):
        task = {"seed_learnings": [{"content": "fact one"}, {"content": "fact two"}]}
        self.assertEqual(me.full_context_facts(task), ["fact one", "fact two"])

    def test_explicit_override_wins(self):
        task = {"seed_learnings": [{"content": "fact one"}], "full_context_facts": ["custom fact"]}
        self.assertEqual(me.full_context_facts(task), ["custom fact"])

    def test_build_full_context_prompt_prepends_facts(self):
        prompt = me.build_full_context_prompt("Do X.", ["fact A", "fact B"])
        self.assertIn("fact A", prompt)
        self.assertIn("fact B", prompt)
        self.assertTrue(prompt.endswith("Do X."))

    def test_build_full_context_prompt_no_facts_is_unmodified(self):
        self.assertEqual(me.build_full_context_prompt("Do X.", []), "Do X.")


# ---------------------------------------------------------------------------
# Real task JSON files parse and carry the required fields.
# ---------------------------------------------------------------------------

class TaskFixtureTests(unittest.TestCase):
    def test_nine_seed_tasks_present_with_expected_kind_distribution(self):
        tasks = me.load_tasks(str(TASKS_DIR / "*.json"))
        self.assertEqual(len(tasks), 9)
        kinds = [t["kind"] for t in tasks]
        self.assertEqual(kinds.count("uplift"), 5)
        self.assertEqual(kinds.count("canary"), 2)
        self.assertEqual(kinds.count("contradiction"), 1)
        self.assertEqual(kinds.count("dreamed"), 1)

    def test_non_dreamed_tasks_have_prompt_fixture_criteria(self):
        tasks = me.load_tasks(str(TASKS_DIR / "*.json"))
        for t in tasks:
            if t["kind"] == "dreamed":
                continue
            self.assertTrue(t.get("prompt"), t["id"])
            self.assertIn("files", t.get("fixture", {}), t["id"])
            self.assertTrue(t.get("criteria"), t["id"])

    def test_dreamed_task_has_corpora_and_follow_up(self):
        tasks = me.load_tasks(str(TASKS_DIR / "*.json"))
        dreamed = next(t for t in tasks if t["kind"] == "dreamed")
        self.assertIn("transcript_corpus", dreamed)
        self.assertIn("noise_corpus", dreamed)
        self.assertIn("follow_up", dreamed)
        self.assertNotEqual(dreamed["transcript_corpus"]["slug"], dreamed["noise_corpus"]["slug"])
        for filename in dreamed["transcript_corpus"]["files"] + dreamed["noise_corpus"]["files"]:
            self.assertTrue((TASKS_DIR / "fixtures" / filename).is_file(), filename)


# ---------------------------------------------------------------------------
# Offline score lookup.
# ---------------------------------------------------------------------------

class OfflineScoresTests(unittest.TestCase):
    def test_falls_back_to_default_for_unknown_task(self):
        scores = me.load_offline_scores(OFFLINE_FIXTURES)
        self.assertIn("default", scores)
        looked_up = me.offline_scores_for_task(scores, "some-task-id-not-in-the-file")
        self.assertEqual(looked_up, scores["default"])

    def test_known_task_returns_its_own_entry(self):
        scores = me.load_offline_scores(OFFLINE_FIXTURES)
        looked_up = me.offline_scores_for_task(scores, "uplift-01-migration-reserved-keywords")
        self.assertEqual(looked_up["baseline"]["score"], 3.2)
        self.assertEqual(looked_up["treatment"]["score"], 8.7)


# ---------------------------------------------------------------------------
# _aggregate_arm_runs(): the memory-write-format-error-rate arithmetic
# (bizlogic-003) -- a pure-function test that a run marked is_error=True
# actually surfaces as a non-zero rate, not just that the happy path stays
# at zero (which PerBackboneReportingTests below already covers).
# ---------------------------------------------------------------------------

class AggregateArmRunsTests(unittest.TestCase):
    def _run(self, *, score=7.0, is_error=False):
        return {
            "score": score, "pass": score >= 6.0, "input_tokens": 100, "output_tokens": 20,
            "turns": 2, "run_cost_usd": 0.01, "judge_input_tokens": 10, "judge_output_tokens": 5,
            "is_error": is_error,
        }

    def test_format_error_rate_zero_when_no_failures(self):
        agg = me._aggregate_arm_runs([self._run(), self._run(), self._run()])  # noqa: SLF001
        self.assertEqual(agg["format_error_rate"], 0.0)

    def test_format_error_rate_reflects_fraction_of_failed_runs(self):
        runs = [self._run(is_error=True), self._run(), self._run(), self._run()]
        agg = me._aggregate_arm_runs(runs)  # noqa: SLF001
        self.assertAlmostEqual(agg["format_error_rate"], 0.25)

    def test_empty_runs_list_is_a_safe_zeroed_default(self):
        agg = me._aggregate_arm_runs([])  # noqa: SLF001
        self.assertEqual(agg["runs"], 0)
        self.assertEqual(agg["format_error_rate"], 0.0)
        self.assertEqual(agg["mean_score"], 0.0)


# ---------------------------------------------------------------------------
# Per-backbone reporting (bizlogic-003): run a real (small, fast) task
# offline under >=2 backbones and assert both appear, distinctly, in both
# the returned rows and the rendered summary table.
# ---------------------------------------------------------------------------

class PerBackboneReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_two_backbones_produce_two_distinct_rows(self):
        task = me.load_task(TASKS_DIR / "07-canary-unrelated-math-util.json")
        offline_scores = me.load_offline_scores(OFFLINE_FIXTURES)
        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()

        rows = me.run_task(
            task, backbones=["fixture-model-a", "fixture-model-b"], runs=1, api_key="",
            claude_bin="claude", max_budget_usd=0.1, timeout_s=5, judge_model="fixture-judge",
            judge_system_prompt="unused in offline mode", api_url="http://unused.invalid",
            offline_all_scores=offline_scores, sandbox_root=sandbox,
        )

        self.assertEqual(len(rows), 2)
        backbones_seen = {r["backbone"] for r in rows}
        self.assertEqual(backbones_seen, {"fixture-model-a", "fixture-model-b"})
        for row in rows:
            self.assertIn("bucket", row)
            self.assertIn("delta_sat", row)
            self.assertIn("baseline", row)
            self.assertIn("treatment", row)
            self.assertIn("full_context", row)
            self.assertEqual(row["treatment"]["format_error_rate"], 0.0)

        table = me.render_summary_table(rows)
        self.assertIn("fixture-model-a", table)
        self.assertIn("fixture-model-b", table)


# ---------------------------------------------------------------------------
# render_summary_table(): an offline dreamed row is a plumbing/regression
# check only and must be visibly labeled as NOT evidence of value in the
# printed stdout summary (adrev-305 part (b)) -- the JSONL already carries
# this in `note`, but a human running dream-eval.sh interactively and
# reading only stdout would otherwise miss the distinction.
# ---------------------------------------------------------------------------

class SummaryTableOfflineDreamedLabelTests(unittest.TestCase):
    @staticmethod
    def _row(*, kind: str, offline: bool, bucket: str = "high_value") -> dict:
        arm = {"mean_score": 8.0, "format_error_rate": 0.0}
        return {
            "task_id": f"{kind}-task", "kind": kind, "backbone": "fixture-model",
            "baseline": arm, "treatment": arm, "full_context": arm,
            "delta": 0.0, "delta_sat": 0.0, "bucket": bucket, "offline": offline,
        }

    def test_offline_dreamed_row_is_marked_and_footnoted(self):
        table = me.render_summary_table([self._row(kind="dreamed", offline=True)])
        self.assertIn("high_value*", table)
        self.assertIn("NOT evidence of value", table)

    def test_live_dreamed_row_is_not_marked(self):
        table = me.render_summary_table([self._row(kind="dreamed", offline=False)])
        self.assertNotIn("high_value*", table)
        self.assertNotIn("NOT evidence of value", table)

    def test_offline_non_dreamed_row_is_not_marked(self):
        """Only the dreamed task's offline run carries adrev-305's
        NOT-evidence caveat -- the other 8 tasks running under --offline
        are a general plumbing check with no such per-task caveat."""
        table = me.render_summary_table([self._row(kind="uplift", offline=True)])
        self.assertNotIn("high_value*", table)
        self.assertNotIn("NOT evidence of value", table)

    def test_bucket_counts_summary_line_is_unaffected_by_the_marker(self):
        rows = [self._row(kind="dreamed", offline=True), self._row(kind="uplift", offline=False)]
        table = me.render_summary_table(rows)
        self.assertIn("Buckets: high_value=2", table)


# ---------------------------------------------------------------------------
# --gate (adrev-006/adrev-403/adrev-305): freshness (both bounds, both
# directions), regression, no-high-value, and the live-dreamed requirement.
# ---------------------------------------------------------------------------

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)
        self.evals_dir = me.evals_dir()
        self.evals_dir.mkdir(parents=True, exist_ok=True)

    def _healthy_rows(self, *, dreamed_offline: bool = False, dreamed_delta_sat: float = 2.0) -> list[dict]:
        return [
            {"task_id": "uplift-01", "kind": "uplift", "bucket": "high_value", "offline": False, "delta_sat": 2.0},
            {
                "task_id": "dreamed-01", "kind": "dreamed", "bucket": "high_value",
                "offline": dreamed_offline, "delta_sat": dreamed_delta_sat,
            },
        ]

    def _write_results(self, rows: list[dict], *, mtime_offset_s: float | None = None) -> Path:
        path = self.evals_dir / "2026-07-02.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        if mtime_offset_s is not None:
            target = time.time() + mtime_offset_s
            os.utime(path, (target, target))
        return path

    def test_no_results_on_clean_machine(self):
        # evals_dir exists but is empty (setUp already created it).
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertEqual(reason, "no results")

    def test_no_results_when_evals_dir_absent_entirely(self):
        import shutil as _shutil
        _shutil.rmtree(self.evals_dir)
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertEqual(reason, "no results")

    def test_stale_by_freshness_bound(self):
        self._write_results(self._healthy_rows(), mtime_offset_s=-20 * 86400)  # 20 days old
        is_open, reason = me.gate_check(freshness_days=14)
        self.assertFalse(is_open)
        self.assertIn("stale", reason)
        self.assertIn("freshness", reason)

    def test_fresh_by_freshness_bound_alone_can_open(self):
        self._write_results(self._healthy_rows(), mtime_offset_s=-1 * 86400)  # 1 day old, well within 14d
        is_open, reason = me.gate_check(freshness_days=14)
        self.assertTrue(is_open, reason)

    def test_stale_by_content_shaping_mutation(self):
        """Results written, THEN a real add lands in the store -- the
        results predate the mutation and must close the gate."""
        results_path = self._write_results(self._healthy_rows(), mtime_offset_s=-3600)  # 1h ago
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Freshly learned fact.", project="proj-x")
            learnings_store.append_entry(entry, slug="proj-x")

        is_open, reason = me.gate_check()
        self.assertFalse(is_open, reason)
        self.assertIn("content-shaping", reason)
        self.assertTrue(results_path.is_file())

    def test_stays_green_across_a_pure_verify_mutation(self):
        """adrev-403, both directions: a `verify` counter-op landing AFTER
        the results file must NOT close the gate -- only content-shaping
        ops (add/supersede/deprecate/contradict) count."""
        self._write_results(self._healthy_rows(), mtime_offset_s=-3600)  # 1h ago
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Some fact.", project="proj-y")
            learnings_store.append_entry(entry, slug="proj-y")
            # This add() itself is content-shaping and lands AFTER the
            # results mtime -- reset the results mtime to be freshly AFTER
            # this add so we isolate the test to the verify-op that follows.
        results_path = self.evals_dir / "2026-07-02.jsonl"
        now = time.time()
        os.utime(results_path, (now, now))
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            heads = learnings_store.load_all("proj-y")
            target_id = heads[0]["id"]
            learnings_store.update_entry_by_id(target_id, slug="proj-y", verify=True)

        is_open, reason = me.gate_check()
        self.assertTrue(is_open, reason)

    def test_regression_present_closes_gate(self):
        rows = self._healthy_rows()
        rows.append({"task_id": "canary-01", "kind": "canary", "bucket": "regression", "offline": False, "delta_sat": -1.0})
        self._write_results(rows)
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("regression", reason)

    def test_no_high_value_rows_closes_gate(self):
        rows = [{"task_id": "canary-01", "kind": "canary", "bucket": "redundant", "offline": False, "delta_sat": 0.0}]
        self._write_results(rows)
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertEqual(reason, "no high_value rows")

    def test_offline_dreamed_row_does_not_satisfy_gate(self):
        """adrev-305: an offline (plumbing-only) dreamed high_value row
        must never open the auto-apply gate -- only a LIVE run counts."""
        self._write_results(self._healthy_rows(dreamed_offline=True))
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("live", reason)

    def test_dreamed_row_with_non_positive_delta_sat_does_not_satisfy_gate(self):
        self._write_results(self._healthy_rows(dreamed_offline=False, dreamed_delta_sat=0.0))
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("Δ_sat", reason)

    def test_noise_only_corpus_producing_high_value_proposal_closes_gate(self):
        """adrev-305's own Acceptance sentence: a live dreamed task
        classifying high_value with Δ_sat>0 is necessary but NOT
        sufficient -- the paired noise-only corpus mined alongside it must
        ALSO have yielded no high-value proposal. mining.noise_high_value
        is the pipeline's own record of that; True means noise produced a
        proposal (a caught mining false-positive/poisoning bug), and the
        gate must stay CLOSED even though the signal-side row looks
        healthy in every other respect. Mirrors the Stage-1 review's
        prove_gap.py reproduction as a permanent regression test."""
        rows = self._healthy_rows()
        for r in rows:
            if r["kind"] == "dreamed":
                r["mining"] = {"noise_proposals_written": 1, "noise_high_value": True}
        self._write_results(rows)

        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("noise", reason)

    def test_noise_clean_dreamed_row_still_opens_gate(self):
        """The paired positive case: an explicit, clean mining record
        (noise corpus was actually mined and yielded nothing) alongside a
        live high_value+Δ_sat>0 dreamed row must open the gate -- the fix
        must not make the gate impossible to open."""
        rows = self._healthy_rows()
        for r in rows:
            if r["kind"] == "dreamed":
                r["mining"] = {"noise_proposals_written": 0, "noise_high_value": False}
        self._write_results(rows)

        is_open, reason = me.gate_check()
        self.assertTrue(is_open, reason)

    def test_gate_open_when_healthy(self):
        """_healthy_rows()'s dreamed row deliberately carries no `mining`
        key at all (pre-adrev-305-fix results shape) -- confirms the noise
        check above degrades to "no evidence of contamination" rather than
        hard-failing on an absent field, so the existing all-good scenario
        still opens."""
        self._write_results(self._healthy_rows())
        is_open, reason = me.gate_check()
        self.assertTrue(is_open, reason)
        self.assertEqual(reason, "ok")

    def test_main_gate_mode_exit_code_0_when_open(self):
        self._write_results(self._healthy_rows())
        self.assertEqual(me.main(["--gate"]), 0)

    def test_main_gate_mode_exit_code_1_when_closed(self):
        # evals_dir exists but is empty -> "no results".
        self.assertEqual(me.main(["--gate"]), 1)

    def test_main_gate_mode_exit_code_1_on_regression(self):
        rows = self._healthy_rows()
        rows.append({"task_id": "canary-01", "kind": "canary", "bucket": "regression", "offline": False, "delta_sat": -1.0})
        self._write_results(rows)
        self.assertEqual(me.main(["--gate"]), 1)


if __name__ == "__main__":
    unittest.main()
