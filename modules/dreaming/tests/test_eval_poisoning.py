#!/usr/bin/env python3
"""
Tests for the eval-gate extension + poisoning negative-controls (issue
#802, optimistic-memory plan.md Epic 4).

Covers:
  - Poisoning negative-control fixtures (modules/dreaming/tests/fixtures/
    poisoning-scenarios.json): a plausible-but-false `learning_add` and a
    surgical-but-false `learning_supersede`, each proven to classify
    `regression` via the real classify_bucket(), and proven to close
    gate_check() (both in-process and via the real `dream-eval.sh --gate`
    CLI subprocess) when present as the latest results file.
  - The dwell-leak assertion: a dwell-postured seed row (Epic 1's
    `dwell_until`/`is_dwelling()`) is absent from `learnings_store.search()`
    -- the exact call the SessionStart injection hook makes to assemble a
    live session's injected context (see modules/self-improving/hooks/
    learnings-inject.py's own docstring: "does not re-implement
    ranking/selection") -- while still resolvable via `load_all()`.
  - Staleness (#1098 item 2.1): only dreaming's own `auto: true`
    content-shaping op-events (add/supersede/contradict) landing after the
    results file make the eval stale, which PAUSES the gate (an infra
    state, never a breaker anomaly). A NON-auto op-event an agent writes
    in-session has nothing to do with dreaming and leaves the gate open.
  - The adrev-403 regression-lock: CONTENT_SHAPING_OPS still excludes
    `verify`, both as a constant and behaviorally (a pure verify op-event
    after the results file does not close the gate).

Runs entirely offline: CCGM_LEARNINGS_DIR is redirected to a tempdir
BEFORE import (mirrors test_memory_eval.py's own pattern -- learnings_
store.LEARNINGS_ROOT is a module-level constant frozen at import time).
CCGM_DREAMING_DIR is redirected per-test. No network, no ANTHROPIC_API_KEY,
no `claude` subprocess is ever invoked -- the one subprocess this file DOES
spawn (`bash dream-eval.sh --gate`) is itself network-free: `--gate` mode
short-circuits before memory_eval.py's own ANTHROPIC_API_KEY check.

Run with: python3 -m pytest modules/dreaming/tests/test_eval_poisoning.py -q
      or: python3 modules/dreaming/tests/test_eval_poisoning.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Point the learnings store at a tempdir BEFORE importing memory_eval, which
# imports learnings_store transitively (via transcript_miner) at module
# load time.
_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-eval-poisoning-test-learnings-")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS

sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent / "lib"))

import memory_eval as me  # noqa: E402
import learnings_store  # noqa: E402

FIXTURES_DIR = HERE / "fixtures"
POISONING_SCENARIOS_PATH = FIXTURES_DIR / "poisoning-scenarios.json"
DREAM_EVAL_SCRIPT = HERE.parent / "bin" / "dream-eval.sh"


def _isolate_env(test: unittest.TestCase) -> Path:
    """Fresh CCGM_DREAMING_DIR + CCGM_LEARNINGS_DIR per test; restores both
    (and CCGM_LEARNINGS_CACHE_DIR / CCGM_CLAUDE_PROJECTS_DIR, which
    memory_eval's own _learnings_store_pointed_at() may set) on cleanup.
    Mirrors test_memory_eval.py's identical helper exactly."""
    tmp = tempfile.mkdtemp(prefix="ccgm-eval-poisoning-test-")
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


def _load_poisoning_scenarios() -> list[dict]:
    data = json.loads(POISONING_SCENARIOS_PATH.read_text(encoding="utf-8"))
    return data["scenarios"]


def _arm(mean: float, pass_rate: float, runs: int) -> dict:
    return {"mean_score": mean, "pass_rate": pass_rate, "runs": runs, "format_error_rate": 0.0, "judge_error_rate": 0.0}


def _row_for_scenario(scenario: dict) -> dict:
    """Build a gate_check()-consumable result row from a poisoning
    scenario. The bucket comes from the REAL classify_bucket() (reporting),
    and the per-arm pass rates are what gate_check() reads: the poisoned
    memory makes the treatment arm fail checks the baseline passes."""
    bucket, delta, delta_sat = me.classify_bucket(
        baseline_mean=scenario["baseline_mean"],
        treatment_mean=scenario["treatment_mean"],
        full_context_mean=scenario["full_context_mean"],
    )
    runs = scenario["runs"]
    return {
        "task_id": scenario["id"], "kind": "canary", "bucket": bucket, "backbone": "m", "runs": runs,
        "offline": False, "delta": delta, "delta_sat": delta_sat,
        "baseline": _arm(scenario["baseline_mean"], scenario["baseline_pass_rate"], runs),
        "treatment": _arm(scenario["treatment_mean"], scenario["treatment_pass_rate"], runs),
        "full_context": _arm(scenario["full_context_mean"], scenario["treatment_pass_rate"], runs),
    }


def _healthy_rows() -> list[dict]:
    """Nothing regresses: every checked task passes in both arms."""
    return [
        {
            "task_id": "canary-01", "kind": "canary", "bucket": "redundant", "backbone": "m", "runs": 3,
            "offline": False, "baseline": _arm(9.0, 1.0, 3), "treatment": _arm(9.0, 1.0, 3),
            "full_context": _arm(9.0, 1.0, 3),
        },
        {
            "task_id": "dreamed-01", "kind": "dreamed", "bucket": "inconclusive", "backbone": "m", "runs": 3,
            "offline": False, "baseline": _arm(6.0, 1.0, 3), "treatment": _arm(6.0, 1.0, 3),
            "full_context": _arm(9.0, 1.0, 3), "mining": {"noise_proposals_written": 0, "noise_high_value": False},
        },
    ]


# ---------------------------------------------------------------------------
# Fixture shape: exists, parses, has at least one add and one supersede
# poisoning scenario (plan.md Epic 4 Outputs).
# ---------------------------------------------------------------------------

class PoisoningFixtureShapeTests(unittest.TestCase):
    def test_fixture_file_exists_and_parses(self):
        self.assertTrue(POISONING_SCENARIOS_PATH.is_file(), POISONING_SCENARIOS_PATH)
        scenarios = _load_poisoning_scenarios()
        self.assertGreaterEqual(len(scenarios), 2)

    def test_at_least_one_add_and_one_supersede_scenario(self):
        scenarios = _load_poisoning_scenarios()
        kinds = {s["kind"] for s in scenarios}
        self.assertIn("learning_add", kinds)
        self.assertIn("learning_supersede", kinds)

    def test_every_scenario_declares_a_regression_score_triple(self):
        for s in _load_poisoning_scenarios():
            for field in (
                "baseline_mean", "treatment_mean", "full_context_mean", "expected_bucket",
                "baseline_pass_rate", "treatment_pass_rate", "runs",
            ):
                self.assertIn(field, s, s.get("id"))
            self.assertEqual(s["expected_bucket"], "regression", s["id"])


# ---------------------------------------------------------------------------
# The poisoning scenarios classify `regression` via the REAL classifier
# (so gate_check()'s "any regression row => fail" trips against them).
# ---------------------------------------------------------------------------

class PoisoningScenariosClassifyAsRegressionTests(unittest.TestCase):
    def test_every_poisoning_scenario_classifies_regression(self):
        for s in _load_poisoning_scenarios():
            bucket, delta, _delta_sat = me.classify_bucket(
                baseline_mean=s["baseline_mean"], treatment_mean=s["treatment_mean"],
                full_context_mean=s["full_context_mean"],
            )
            self.assertEqual(bucket, "regression", s["id"])
            self.assertLessEqual(delta, me.REGRESSION_DELTA_THRESHOLD, s["id"])
            self.assertEqual(bucket, s["expected_bucket"], s["id"])


# ---------------------------------------------------------------------------
# The poisoning fixture, as the latest results file, closes gate_check();
# a results file with only legitimate high_value rows still opens it.
# ---------------------------------------------------------------------------

class PoisoningScenariosCloseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)
        self.evals_dir = me.evals_dir()
        self.evals_dir.mkdir(parents=True, exist_ok=True)

    def test_poisoning_fixture_alone_closes_the_gate(self):
        rows = [_row_for_scenario(s) for s in _load_poisoning_scenarios()]
        me.write_results(rows, date=me.today_iso())

        gate = me.gate_check()
        self.assertEqual((gate["state"], gate["code"]), ("closed", "regression"), gate)

    def test_legitimate_results_open_the_gate(self):
        rows = _healthy_rows()
        me.write_results(rows, date=me.today_iso())

        gate = me.gate_check()
        self.assertEqual(gate["state"], "open", gate)


class DreamEvalGateCliTests(unittest.TestCase):
    """Acceptance criterion: the real `bash dream-eval.sh --gate` CLI
    subprocess -- the exact entrypoint dream-daily.sh's auto-apply step
    invokes -- must itself exit non-zero on the poisoning fixture, not just
    the in-process me.gate_check()/me.main(['--gate']) already covered
    above. No network, no ANTHROPIC_API_KEY: --gate mode short-circuits
    before memory_eval.py's own API-key check."""

    def setUp(self):
        self.tmp = _isolate_env(self)
        self.evals_dir = me.evals_dir()
        self.evals_dir.mkdir(parents=True, exist_ok=True)
        self.assertTrue(DREAM_EVAL_SCRIPT.is_file(), DREAM_EVAL_SCRIPT)

    def _run_cli_gate(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(DREAM_EVAL_SCRIPT), "--gate"],
            capture_output=True, text=True, env=dict(os.environ), timeout=30,
        )

    def test_cli_gate_exits_nonzero_on_poisoning_fixture(self):
        rows = [_row_for_scenario(s) for s in _load_poisoning_scenarios()]
        me.write_results(rows, date=me.today_iso())

        proc = self._run_cli_gate()
        self.assertEqual(proc.returncode, 1, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn('"gate": "closed"', proc.stdout)
        self.assertIn("regression", proc.stdout.lower())

    def test_cli_gate_exits_zero_when_results_are_healthy(self):
        """Paired positive control: proves the subprocess wiring itself is
        sound (correctly reports open/closed based on content) rather than
        e.g. always exiting non-zero regardless of the fixture."""
        rows = _healthy_rows()
        me.write_results(rows, date=me.today_iso())

        proc = self._run_cli_gate()
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn('"gate": "open"', proc.stdout)


# ---------------------------------------------------------------------------
# Staleness (#1098 item 2.1): only dreaming's own auto-integrated
# content-shaping writes make the eval stale, and stale PAUSES the gate.
# An agent's in-session (non-auto) write never counts.
# ---------------------------------------------------------------------------

class StaleOnlyOnDreamingsOwnWritesTests(unittest.TestCase):
    """Dreaming's own writes since the last eval change what a re-run
    would measure, so the results no longer describe the live store and
    the gate pauses until the next eval. In-session writes through
    `ccgm-learnings-log` have nothing to do with dreaming; before #1098
    they made the eval stale on 15 of 30 nights."""

    def setUp(self):
        self.tmp = _isolate_env(self)
        self.evals_dir = me.evals_dir()
        self.evals_dir.mkdir(parents=True, exist_ok=True)

    def _write_results(self, *, mtime_offset_s: float | None = None) -> Path:
        path = me.write_results(_healthy_rows(), date=me.today_iso())
        if mtime_offset_s is not None:
            target = time.time() + mtime_offset_s
            os.utime(path, (target, target))
        return path

    def _touch_results_to_now(self) -> None:
        """Results written just before the write under test. One second back:
        op timestamps carry milliseconds, so a write in the same millisecond
        as the touch would otherwise read as older than the results."""
        path = me.results_path_for_date(me.today_iso())
        then = time.time() - 1
        os.utime(path, (then, then))

    def _assert_paused_stale(self) -> None:
        gate = me.gate_check()
        self.assertEqual((gate["state"], gate["code"]), ("paused", "stale_own_writes"), gate)

    def test_auto_add_after_results_pauses_the_gate(self):
        self._write_results(mtime_offset_s=-3600)
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Auto-integrated fact.", project="proj-auto-add")
            learnings_store.append_entry(entry, slug="proj-auto-add", auto=True)
        self._assert_paused_stale()

    def test_auto_supersede_after_results_pauses_the_gate(self):
        self._write_results(mtime_offset_s=-3600)
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Original fact.", project="proj-auto-sup")
            learnings_store.append_entry(entry, slug="proj-auto-sup")
        self._touch_results_to_now()
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            new_entry = learnings_store.supersede_entry(
                entry["id"], content="Refined fact.", slug="proj-auto-sup",
                expected_sha256=learnings_store.content_sha256(entry["content"]), auto=True,
            )
        self.assertIsNotNone(new_entry)
        self._assert_paused_stale()

    def test_auto_contradict_after_results_pauses_the_gate(self):
        self._write_results(mtime_offset_s=-3600)
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Some fact.", project="proj-auto-contra")
            learnings_store.append_entry(entry, slug="proj-auto-contra")
        self._touch_results_to_now()
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            ok = learnings_store.update_entry_by_id(entry["id"], slug="proj-auto-contra", contradict=True, auto=True)
        self.assertTrue(ok)
        self._assert_paused_stale()

    def test_non_auto_add_after_results_leaves_the_gate_open(self):
        self._write_results(mtime_offset_s=-3600)
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Human-written fact.", project="proj-human")
            learnings_store.append_entry(entry, slug="proj-human")  # auto=False (default)
        gate = me.gate_check()
        self.assertEqual(gate["state"], "open", gate)


# ---------------------------------------------------------------------------
# adrev-403 regression-lock: CONTENT_SHAPING_OPS still excludes `verify`.
# ---------------------------------------------------------------------------

class ContentShapingOpsExcludesVerifyConstantTests(unittest.TestCase):
    def test_content_shaping_ops_constant_excludes_verify(self):
        self.assertNotIn("verify", me.CONTENT_SHAPING_OPS)
        self.assertEqual(me.CONTENT_SHAPING_OPS, {"add", "supersede", "deprecate", "contradict"})


class VerifyMutationDoesNotCloseGateTests(unittest.TestCase):
    """Behavioral counterpart to the constant check above: a pure `verify`
    op-event landing after the results file must not close the gate (a
    compact re-assertion of test_memory_eval.py's own
    test_stays_green_across_a_pure_verify_mutation, kept here so Epic 4's
    own test file is a self-contained proof of the adrev-403 fix it
    depends on)."""

    def setUp(self):
        self.tmp = _isolate_env(self)
        self.evals_dir = me.evals_dir()
        self.evals_dir.mkdir(parents=True, exist_ok=True)

    def test_pure_verify_after_results_does_not_close_gate(self):
        rows = _healthy_rows()
        me.write_results(rows, date=me.today_iso())
        learnings_dir = Path(os.environ["CCGM_LEARNINGS_DIR"])
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            entry = learnings_store.build_entry(type_="pattern", content="Some fact.", project="proj-verify")
            learnings_store.append_entry(entry, slug="proj-verify")
        # This add() itself is content-shaping and lands after the results
        # mtime -- reset the results mtime to be freshly after it so the
        # test isolates to the verify-op that follows.
        path = me.results_path_for_date(me.today_iso())
        now = time.time()
        os.utime(path, (now, now))
        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            learnings_store.update_entry_by_id(entry["id"], slug="proj-verify", verify=True, auto=True)

        gate = me.gate_check()
        self.assertEqual(gate["state"], "open", gate)


# ---------------------------------------------------------------------------
# Dwell-leak assertion (Epic 1's dwell exclusion protects agent context,
# proven end-to-end through THIS harness's own seeding + search() path).
# ---------------------------------------------------------------------------

class DwellLeakProtectionTests(unittest.TestCase):
    """`search()` is exactly and only what the SessionStart injection hook
    calls to assemble a live session's injected context (integration-map.md
    section B: "this hook calls learnings_store.search() directly -- it
    does not re-implement ranking/selection"). Seeding a dwelling row
    through THIS harness's own seed_temp_store() and then calling
    learnings_store.search() against that same store is therefore the
    correct, minimal, offline-safe proxy for "is a dwelling row absent from
    the treatment arm's injected context" -- without needing to spawn a
    live `claude -p` subprocess."""

    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_dwelling_add_is_absent_from_search_but_resolvable_by_id(self):
        learnings_dir = self.tmp / "learnings"
        project_slug = "dwell-leak-add-task"
        seed = [
            {"content": "Live fact: safe to inject immediately.", "type": "pattern", "confidence": 8},
            {
                "content": "Dwelling fact: written last night, still inside its dwell window.",
                "type": "pattern", "confidence": 8, "dwell_hours": 24,
            },
        ]
        me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug=project_slug)

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            injected = learnings_store.search(slug=project_slug, max_results=10, token_budget=4000)
            all_heads = learnings_store.load_all(project_slug)

        injected_contents = {e["content"] for e in injected}
        self.assertIn("Live fact: safe to inject immediately.", injected_contents)
        self.assertNotIn("Dwelling fact: written last night, still inside its dwell window.", injected_contents)

        # The row is LIVE, just not read-eligible yet -- load_all() (the
        # by-id resolution path apply_dream_proposal.py's own CAS re-check
        # depends on) must still see it.
        all_contents = {h["content"] for h in all_heads}
        self.assertIn("Dwelling fact: written last night, still inside its dwell window.", all_contents)

    def test_dwelling_supersede_is_absent_from_search_but_resolvable_by_id(self):
        learnings_dir = self.tmp / "learnings"
        project_slug = "dwell-leak-supersede-task"
        seed = [
            {"content": "Old guidance, immediately live.", "type": "preference", "confidence": 6},
            {
                "content": "New guidance, still dwelling.", "type": "preference", "confidence": 8,
                "supersedes_previous": True, "dwell_hours": 24,
            },
        ]
        me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug=project_slug)

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            injected = learnings_store.search(slug=project_slug, max_results=10, token_budget=4000)
            all_heads = learnings_store.load_all(project_slug)

        injected_contents = {e["content"] for e in injected}
        self.assertNotIn("New guidance, still dwelling.", injected_contents)
        self.assertNotIn("Old guidance, immediately live.", injected_contents)  # superseded -- excluded regardless of dwell

        all_contents = {h["content"] for h in all_heads}
        self.assertIn("New guidance, still dwelling.", all_contents)

    def test_no_dwell_hours_seeds_an_immediately_live_row(self):
        """Regression guard on the seed_temp_store() extension itself: a
        seed spec WITHOUT dwell_hours (the pre-existing, overwhelmingly
        common case -- every one of the 9 real eval tasks today) must seed
        an immediately-live row, exactly as before this harness extension."""
        learnings_dir = self.tmp / "learnings"
        project_slug = "dwell-leak-no-dwell-task"
        seed = [{"content": "Ordinary immediately-live fact.", "type": "pattern", "confidence": 7}]
        me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug=project_slug)

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            injected = learnings_store.search(slug=project_slug, max_results=10, token_budget=4000)

        self.assertIn("Ordinary immediately-live fact.", {e["content"] for e in injected})

    def test_expired_dwell_window_is_injectable_again(self):
        """The paired positive case: a row whose dwell window has ALREADY
        closed (dwell_until in the past -- dwell_hours=-1) is not a
        permanent quarantine. It must appear in search() like any other
        live row, exactly as a real optimistically-integrated row becomes
        read-eligible once its dwell window elapses. Deterministic (no
        sleep, no monkeypatched clock): a negative dwell_hours computes a
        past dwell_until directly via the store's own
        dwell_until_from_hours()."""
        learnings_dir = self.tmp / "learnings"
        project_slug = "dwell-leak-expired-task"
        seed = [{
            "content": "Dwell window already closed -- should be injectable.",
            "type": "pattern", "confidence": 8, "dwell_hours": -1,
        }]
        me.seed_temp_store(seed, learnings_dir=learnings_dir, project_slug=project_slug)

        with me._learnings_store_pointed_at(learnings_dir):  # noqa: SLF001
            injected = learnings_store.search(slug=project_slug, max_results=10, token_budget=4000)

        self.assertIn(
            "Dwell window already closed -- should be injectable.", {e["content"] for e in injected},
        )


if __name__ == "__main__":
    unittest.main()
