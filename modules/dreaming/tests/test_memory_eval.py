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

import contextlib
import io
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
OFFLINE_DREAMED_FIXTURES = HERE / "fixtures" / "offline-responses-dreamed"
# Real `claude -p --output-format json` stdout, captured from CLI 2.1.258 and
# redacted (session_id/uuid replaced with fixed placeholders). Pins the shape
# run_claude_p() parses (#1027).
CLAUDE_P_RESULT_FIXTURE = HERE / "fixtures" / "claude-p-result-2.1.258.json"


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

    # ---- #784: high_value Path B (efficiency win) ----------------------

    def test_efficiency_path_fires_when_memory_matches_dump_at_far_fewer_tokens(self):
        """#784 Path B: memory MATCHES the full-context dump on score
        (delta_sat=0) but at materially fewer input tokens (3000 vs 20000)
        -- high_value via the efficiency path even though it did not BEAT
        the dump on outcome. This is the case the old delta_sat>0-only
        definition made unreachable for a capable model."""
        bucket, delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=3000, full_context_input_tokens=20000,
        )
        self.assertEqual(delta, 3.0)
        self.assertEqual(delta_sat, 0.0)
        self.assertEqual(bucket, "high_value")

    def test_efficiency_path_inert_when_tokens_not_materially_fewer(self):
        """#784 self-guard: same score shape (delta=+3, delta_sat=0) but
        treatment's input tokens are ~the same as full_context's (3000 vs
        3200, above the 0.5 ratio) -- Path B must NOT fire. This is the
        shape of today's small fixtures, where the two arms' token counts
        are comparable, so the efficiency path is provably inert on them."""
        bucket, _delta, _ = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=3000, full_context_input_tokens=3200,
        )
        self.assertEqual(bucket, "inconclusive")

    def test_efficiency_path_inert_when_treatment_uses_more_tokens_than_dump(self):
        """#784 self-guard (the realistic small-fixture case): treatment
        used MORE input tokens than the full dump (3200 vs 3000) -- memory
        is not cheaper, so Path B stays inert despite the matching score."""
        bucket, _delta, _ = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=3200, full_context_input_tokens=3000,
        )
        self.assertNotEqual(bucket, "high_value")

    def test_efficiency_path_defaults_off_when_token_means_absent(self):
        """#784 self-guard: with no token means supplied (both default to
        0.0), the `full_context_input_tokens > 0` guard fails, so every
        pre-#784 3-arg caller keeps its old classification -- the change
        alone cannot open the gate without the paired realistic fixtures."""
        bucket, _delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
        )
        self.assertEqual(delta_sat, 0.0)
        self.assertNotEqual(bucket, "high_value")

    def test_efficiency_path_inert_when_treatment_arm_has_zero_input_tokens(self):
        """#784 defense-in-depth (Stage-2 Recommend): a degenerate treatment
        arm that recorded ZERO input tokens (a total run failure) is
        trivially <= any ratio of the full dump, and would otherwise
        spuriously satisfy the efficiency condition. The symmetric
        `treatment_input_tokens > 0` guard keeps Path B inert here even with
        a huge full_context arm, a matching score (delta_sat=0), and
        delta >= HIGH_VALUE_DELTA_THRESHOLD."""
        bucket, delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=0, full_context_input_tokens=20000,
        )
        self.assertGreaterEqual(delta, me.HIGH_VALUE_DELTA_THRESHOLD)
        self.assertEqual(delta_sat, 0.0)
        self.assertEqual(bucket, "inconclusive")

    def test_efficiency_path_inert_when_memory_loses_beyond_tolerance(self):
        """#784: memory LOSES to the dump by more than the noise tolerance
        (delta_sat=-2.0 < -0.5) -- not a match, so Path B must NOT fire even
        at a huge token advantage (3000 vs 20000)."""
        bucket, _delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=10.0,
            treatment_input_tokens=3000, full_context_input_tokens=20000,
        )
        self.assertEqual(delta_sat, -2.0)
        self.assertNotEqual(bucket, "high_value")

    def test_efficiency_path_sat_tolerance_boundary_inclusive(self):
        """#784 boundary: delta_sat exactly -HIGH_VALUE_SAT_TOLERANCE
        (-0.5) still counts as a match -- Path B fires at the boundary."""
        bucket, _delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.5,
            treatment_input_tokens=3000, full_context_input_tokens=20000,
        )
        self.assertAlmostEqual(delta_sat, -0.5)
        self.assertEqual(bucket, "high_value")

    def test_efficiency_path_sat_tolerance_boundary_exclusive(self):
        """#784 boundary: just past the tolerance (delta_sat=-0.6) is a
        loss, not a match -- Path B does not fire."""
        bucket, _delta, delta_sat = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.6,
            treatment_input_tokens=3000, full_context_input_tokens=20000,
        )
        self.assertAlmostEqual(delta_sat, -0.6)
        self.assertNotEqual(bucket, "high_value")

    def test_efficiency_path_ratio_boundary_inclusive(self):
        """#784 boundary: treatment_input exactly at the ratio ceiling
        (10000 == 0.5 * 20000) still fires (<=)."""
        bucket, _delta, _ = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=10000, full_context_input_tokens=20000,
        )
        self.assertEqual(bucket, "high_value")

    def test_efficiency_path_ratio_boundary_exclusive(self):
        """#784 boundary: one token over the ratio ceiling (10001 > 0.5 *
        20000) does not fire."""
        bucket, _delta, _ = me.classify_bucket(
            baseline_mean=5.0, treatment_mean=8.0, full_context_mean=8.0,
            treatment_input_tokens=10001, full_context_input_tokens=20000,
        )
        self.assertNotEqual(bucket, "high_value")

    def test_saturated_task_never_high_value_via_efficiency(self):
        """#784 poisoning/canary safety (the critical property): a saturated
        task with no uplift (baseline~10, delta~0) can NEVER reach
        high_value via the efficiency path, even at an extreme token
        advantage -- delta < HIGH_VALUE_DELTA_THRESHOLD keeps execution out
        of the high_value block entirely. It classifies redundant."""
        bucket, delta, _ = me.classify_bucket(
            baseline_mean=10.0, treatment_mean=10.0, full_context_mean=10.0,
            treatment_input_tokens=100, full_context_input_tokens=20000,
        )
        self.assertLess(delta, me.HIGH_VALUE_DELTA_THRESHOLD)
        self.assertNotEqual(bucket, "high_value")
        self.assertEqual(bucket, "redundant")

    def test_outcome_path_a_fires_regardless_of_token_cost(self):
        """#784: Path A (delta_sat>0, memory BEATS the dump) is independent
        of tokens -- it fires even when treatment used MORE input tokens
        than the full dump (20000 vs 3000)."""
        bucket, _delta, delta_sat = me.classify_bucket(
            baseline_mean=3.0, treatment_mean=8.5, full_context_mean=6.0,
            treatment_input_tokens=20000, full_context_input_tokens=3000,
        )
        self.assertGreater(delta_sat, 0)
        self.assertEqual(bucket, "high_value")

    def test_regression_precedence_over_efficiency_path(self):
        """#784: regression is still checked FIRST -- a delta <= -1.0 row
        classifies regression even when its tokens look maximally efficient
        (Path B must never rescue a regression)."""
        bucket, delta, _ = me.classify_bucket(
            baseline_mean=8.0, treatment_mean=6.0, full_context_mean=8.0,
            treatment_input_tokens=100, full_context_input_tokens=20000,
        )
        self.assertLessEqual(delta, me.REGRESSION_DELTA_THRESHOLD)
        self.assertEqual(bucket, "regression")

    def test_789_efficiency_ratio_fires_on_total_tokens_not_marginal(self):
        """#789 regression: the efficiency path must be fed the TRUE prompt
        size (marginal + cached prefix) so the full-context arm's larger
        context is visible to the ratio. On the total counts (treatment
        3000 vs full-context 11000, ratio 0.27 <= 0.5) the efficiency path
        fires; on the marginal-only counts the arms report an identical
        ~3000 each -- ratio 1.0 -- and the path can never fire, which is
        exactly the #788 root cause this change fixes."""
        high_value, _delta, delta_sat = me.classify_bucket(
            baseline_mean=0, treatment_mean=10, full_context_mean=10,
            treatment_input_tokens=3000, full_context_input_tokens=11000,
        )
        self.assertEqual(delta_sat, 0.0)
        self.assertEqual(high_value, "high_value")
        # Same scores, but the marginal-only counts both arms saw (~3000
        # each) leave the efficiency ratio at 1.0 -> no bucket matches.
        inconclusive, _d, _s = me.classify_bucket(
            baseline_mean=0, treatment_mean=10, full_context_mean=10,
            treatment_input_tokens=3000, full_context_input_tokens=3000,
        )
        self.assertEqual(inconclusive, "inconclusive")


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
# run_claude_p(): the isolated arm subprocess env (Stage-2 #771 Recommend)
# must be built from an explicit allowlist, not an inherited-then-denylist-
# popped copy of the operator's ambient environment (defense-in-depth:
# "refuse unless proven safe"). Exercised with a monkeypatched
# subprocess.run -- no real `claude` binary is ever spawned.
# ---------------------------------------------------------------------------

class RunClaudePEnvIsolationTests(unittest.TestCase):
    def test_ambient_leak_vars_never_reach_the_subprocess_env(self):
        captured = {}

        def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
            captured["env"] = env
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "is_error": False, "result": "ok", "num_turns": 1, "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }),
                stderr="",
            )

        polluted = {
            "HOME": "/tmp/should-never-survive",
            "CLAUDE_CONFIG_DIR": "/tmp/should-never-survive-config",
            "ANTHROPIC_API_KEY": "sk-leak-should-never-survive",
            "CCGM_LEARNINGS_INJECT": "leak-should-never-survive",
            "XDG_CONFIG_HOME": "/tmp/leak-xdg",
            "ANTHROPIC_BASE_URL": "https://leak.invalid/v1",
            "CLAUDE_CODE_ENTRYPOINT": "leak-entrypoint",
            "CLAUDE_SOME_FUTURE_VAR": "leak-future",
            "PATH": "/usr/bin:/bin",
        }
        prev = {k: os.environ.get(k) for k in polluted}
        os.environ.update(polluted)
        try:
            tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-envisol-"))
            with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
                me.run_claude_p(
                    prompt="p", workdir=tmp / "work", config_dir=tmp / "cfg", home_dir=tmp / "home",
                    model="fixture-model", inject=True, api_key="sk-real-isolated",
                    learnings_dir=tmp / "learnings", claude_bin="claude", max_budget_usd=0.1, timeout_s=5,
                )
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        env = captured["env"]
        self.assertEqual(env["HOME"], str(tmp / "home"))
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(tmp / "cfg"))
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-real-isolated")
        self.assertEqual(env["CCGM_LEARNINGS_INJECT"], "true")
        self.assertEqual(env["CCGM_LEARNINGS_DIR"], str(tmp / "learnings"))
        self.assertNotIn("XDG_CONFIG_HOME", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", env)
        self.assertNotIn("CLAUDE_SOME_FUTURE_VAR", env)
        # An allowlisted plumbing var DOES pass through unmodified.
        self.assertEqual(env.get("PATH"), "/usr/bin:/bin")


# ---------------------------------------------------------------------------
# run_claude_p(): the parse step, pinned against REAL captured CLI output
# (#1027). The eval recorded 100% format errors for seven weeks; this class
# separates "the CLI's output shape changed" from "the CLI never launched",
# which is what the regression actually was.
# ---------------------------------------------------------------------------

class RunClaudePParseTests(unittest.TestCase):
    def test_real_cli_json_output_parses_into_the_fields_the_harness_reads(self):
        raw = CLAUDE_P_RESULT_FIXTURE.read_text(encoding="utf-8")

        def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
            return types.SimpleNamespace(returncode=0, stdout=raw, stderr="")

        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-parse-"))
        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            result = me.run_claude_p(
                prompt="p", workdir=tmp / "work", config_dir=tmp / "cfg", home_dir=tmp / "home",
                model="claude-sonnet-5", inject=False, api_key="sk-test-fixture",
                learnings_dir=tmp / "learnings", claude_bin="/usr/bin/true", max_budget_usd=0.5, timeout_s=5,
            )

        # Every field _run_one() reads off the result must survive the parse.
        self.assertFalse(result["is_error"])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["num_turns"], 1)
        self.assertGreater(result["total_cost_usd"], 0.0)
        usage = result["usage"]
        self.assertEqual(usage["input_tokens"], 2)
        self.assertEqual(usage["output_tokens"], 4)
        # #789's total-input accounting depends on both cache fields being
        # present in the CLI's own usage block.
        self.assertIn("cache_read_input_tokens", usage)
        self.assertIn("cache_creation_input_tokens", usage)

    def test_unparseable_stdout_degrades_to_a_non_fatal_format_error(self):
        def fake_run(cmd, *, cwd, env, capture_output, text, timeout):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom: not json")

        tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-parse-bad-"))
        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            result = me.run_claude_p(
                prompt="p", workdir=tmp / "work", config_dir=tmp / "cfg", home_dir=tmp / "home",
                model="m", inject=False, api_key="k", learnings_dir=tmp / "learnings",
                claude_bin="/usr/bin/true", max_budget_usd=0.5, timeout_s=5,
            )

        self.assertTrue(result["is_error"])
        self.assertIn("boom: not json", result["result"])


# ---------------------------------------------------------------------------
# resolve_claude_bin(): the root cause of #1027. The dreaming LaunchAgent
# exports a fixed PATH that does not include ~/.local/bin, where Claude
# Code's native installer puts the CLI -- so every arm subprocess died with
# FileNotFoundError and scored a silent format error.
# ---------------------------------------------------------------------------

class ResolveClaudeBinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-eval-test-bin-"))
        self._prev_path = os.environ.get("PATH")
        self.addCleanup(self._restore_path)

    def _restore_path(self):
        if self._prev_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._prev_path

    def _make_executable(self, directory: Path, name: str = "claude") -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
        return target

    def test_resolves_from_path_to_an_absolute_path(self):
        bin_dir = self.tmp / "onpath"
        self._make_executable(bin_dir)
        os.environ["PATH"] = str(bin_dir)
        resolved = me.resolve_claude_bin("claude")
        self.assertTrue(Path(resolved).is_absolute())
        self.assertEqual(Path(resolved).name, "claude")

    def test_a_symlinked_entry_point_is_not_followed(self):
        """~/.local/bin/claude is a symlink into a versioned binary. A CLI
        update mid-run swings that link and can delete the version behind
        it, so the harness keeps the stable entry point."""
        real_dir = self.tmp / "versions"
        real = self._make_executable(real_dir, name="2.1.258")
        link_dir = self.tmp / "linked"
        link_dir.mkdir(parents=True, exist_ok=True)
        link = link_dir / "claude"
        link.symlink_to(real)
        os.environ["PATH"] = str(link_dir)
        self.assertEqual(Path(me.resolve_claude_bin("claude")), link)

    def test_falls_back_to_a_known_install_dir_when_path_misses_it(self):
        """The launchd case: PATH resolves nothing, but the native
        installer's directory has the binary."""
        install_dir = self.tmp / "home" / ".local" / "bin"
        self._make_executable(install_dir)
        os.environ["PATH"] = "/nonexistent-dir-for-test"
        with mock.patch.object(me, "CLAUDE_BIN_FALLBACK_DIRS", (str(install_dir),)):
            resolved = me.resolve_claude_bin("claude")
        self.assertEqual(Path(resolved), install_dir / "claude")

    def test_raises_naming_what_it_searched_when_nowhere(self):
        os.environ["PATH"] = "/nonexistent-dir-for-test"
        with mock.patch.object(me, "CLAUDE_BIN_FALLBACK_DIRS", (str(self.tmp / "absent"),)):
            with self.assertRaises(me.ClaudeBinaryNotFoundError) as ctx:
                me.resolve_claude_bin("claude")
        message = str(ctx.exception)
        self.assertIn("PATH=", message)
        self.assertIn(str(self.tmp / "absent"), message)
        self.assertIn("CCGM_EVAL_CLAUDE_BIN", message)

    def test_an_explicit_path_is_taken_at_its_word(self):
        explicit = self._make_executable(self.tmp / "explicit")
        os.environ["PATH"] = "/nonexistent-dir-for-test"
        self.assertEqual(Path(me.resolve_claude_bin(str(explicit))), explicit)

    def test_an_explicit_path_that_is_not_executable_raises(self):
        not_exec = self.tmp / "explicit" / "claude"
        not_exec.parent.mkdir(parents=True, exist_ok=True)
        not_exec.write_text("", encoding="utf-8")
        not_exec.chmod(0o644)
        with self.assertRaises(me.ClaudeBinaryNotFoundError):
            me.resolve_claude_bin(str(not_exec))


# ---------------------------------------------------------------------------
# whole_run_format_error_rate(): the pure half of the fail-loud contract
# (#1027).
# ---------------------------------------------------------------------------

class WholeRunFormatErrorRateTests(unittest.TestCase):
    @staticmethod
    def _row(rates: tuple[float, float, float], *, runs: int = 5) -> dict:
        return {arm: {"runs": runs, "format_error_rate": rate} for arm, rate in zip(me.ARMS, rates)}

    def test_all_arms_failing_is_one(self):
        self.assertEqual(me.whole_run_format_error_rate([self._row((1.0, 1.0, 1.0))]), 1.0)

    def test_one_healthy_row_keeps_it_below_one(self):
        rows = [self._row((0.0, 0.0, 0.0)), self._row((1.0, 1.0, 1.0))]
        self.assertLess(me.whole_run_format_error_rate(rows), 1.0)

    def test_a_single_failed_arm_is_not_a_broken_harness(self):
        self.assertLess(me.whole_run_format_error_rate([self._row((0.0, 1.0, 0.0))]), 1.0)

    def test_rows_with_no_runs_return_none_rather_than_a_fabricated_rate(self):
        """An all-`error`-row run means nothing ran; "nothing ran" must not
        be reported as "everything failed"."""
        self.assertIsNone(me.whole_run_format_error_rate([self._row((0.0, 0.0, 0.0), runs=0)]))

    def test_no_rows_at_all_return_none(self):
        self.assertIsNone(me.whole_run_format_error_rate([]))


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

    def test_request_never_carries_temperature_and_pins_thinking_and_schema(self):
        """#1029: the judge request carries NO sampling parameter (every
        judge model from Opus 4.7 / Sonnet 5 on returns 400 for one, and the
        default judge is claude-opus-4-8), pins `thinking: disabled` so a
        model bump cannot spend the output cap on thinking (#1026), and
        pins the verdict schema via output_config.format (#1028). Exactly
        one request is made -- the old probe-and-retry made two."""
        captured = []

        def fake_run(cmd, *, input, capture_output, text):  # noqa: A002 - matches subprocess.run's own kwarg name
            captured.append({"cmd": cmd, "input": input})
            return self._fake_proc(body=self._messages_api_body({"pass": True, "score": 8.5}))

        with mock.patch("memory_eval.subprocess.run", side_effect=fake_run):
            parsed, usage = me._call_judge_api(  # noqa: SLF001
                model="claude-judge-fixture", system_prompt="You are a blind judge.",
                user_obj={"task_prompt": "Do X.", "criteria": ["done"], "final_files": {}, "agent_summary": "done"},
                max_output_tokens=1024, api_key="sk-test-fixture", api_url="https://api.anthropic.com/v1/messages",
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(parsed, {"pass": True, "score": 8.5})
        self.assertEqual(usage, {"input_tokens": 42, "output_tokens": 7})

        request_body = json.loads(captured[0]["input"])
        self.assertNotIn("temperature", request_body)
        self.assertNotIn("top_p", request_body)
        self.assertNotIn("top_k", request_body)
        self.assertEqual(request_body["thinking"], {"type": "disabled"})
        self.assertEqual(
            request_body["output_config"],
            {"format": {"type": "json_schema", "schema": me.JUDGE_VERDICT_SCHEMA}},
        )
        # Effort is left at the model default: disabling thinking is
        # rejected only at `xhigh`/`max`, which nothing here sets.
        self.assertNotIn("effort", request_body["output_config"])
        self.assertEqual(request_body["model"], "claude-judge-fixture")
        self.assertEqual(request_body["system"], "You are a blind judge.")
        self.assertEqual(request_body["max_tokens"], 1024)
        self.assertEqual(len(request_body["messages"]), 1)
        self.assertEqual(request_body["messages"][0]["role"], "user")
        # The user_obj is JSON-encoded into the message content, not
        # flattened -- round-trips back to the exact payload sent in.
        self.assertEqual(json.loads(request_body["messages"][0]["content"]), {
            "task_prompt": "Do X.", "criteria": ["done"], "final_files": {}, "agent_summary": "done",
        })
        self.assertIn("sk-test-fixture", " ".join(captured[0]["cmd"]))

    def test_verdict_schema_avoids_keywords_structured_outputs_rejects(self):
        """The structured-outputs schema subset 400s on numeric range
        keywords ("For 'number' type, properties maximum, minimum are not
        supported"), which a first cut of this schema hit against
        claude-opus-4-8. The 0-10 range lives in judge-prompt.md and is
        clamped in judge_output(); the schema pins the field set and types."""
        score_schema = me.JUDGE_VERDICT_SCHEMA["properties"]["score"]
        self.assertEqual(score_schema, {"type": "number"})
        self.assertFalse(me.JUDGE_VERDICT_SCHEMA["additionalProperties"])
        self.assertEqual(sorted(me.JUDGE_VERDICT_SCHEMA["required"]), ["pass", "score"])

    def test_default_judge_output_cap_is_a_backstop_not_a_tuning_knob(self):
        """#1026: a two-field verdict never needs 1024 tokens; the point is
        that a truncated verdict cannot happen, including on a model that
        thinks by default before the `thinking: disabled` pin takes effect."""
        self.assertEqual(me.DEFAULT_JUDGE_MAX_OUTPUT_TOKENS, 1024)

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
# _parse_judge_verdict(): the judge's OWN parse (#1029). The response is
# schema-valid by construction, so this is json.loads plus the shape check
# the harness has always applied -- deliberately NOT dream_analyze.py's
# lenient `_parse_json_object`, whose fence-stripping and first-`{` scan
# exist for the unconstrained map/reduce prompts.
# ---------------------------------------------------------------------------

class ParseJudgeVerdictTests(unittest.TestCase):
    def test_plain_schema_valid_verdict_round_trips(self):
        self.assertEqual(me._parse_judge_verdict('{"pass": true, "score": 8}'), {"pass": True, "score": 8})  # noqa: SLF001

    def test_float_score_is_accepted(self):
        self.assertEqual(me._parse_judge_verdict('{"pass": false, "score": 3.5}'), {"pass": False, "score": 3.5})  # noqa: SLF001

    def test_non_json_returns_none(self):
        self.assertIsNone(me._parse_judge_verdict("not json at all"))  # noqa: SLF001

    def test_non_object_json_returns_none(self):
        self.assertIsNone(me._parse_judge_verdict("[1, 2, 3]"))  # noqa: SLF001

    def test_missing_score_returns_none(self):
        self.assertIsNone(me._parse_judge_verdict('{"pass": true}'))  # noqa: SLF001

    def test_non_numeric_score_returns_none(self):
        self.assertIsNone(me._parse_judge_verdict('{"pass": true, "score": "eight"}'))  # noqa: SLF001

    def test_boolean_score_is_not_a_number(self):
        self.assertIsNone(me._parse_judge_verdict('{"pass": true, "score": true}'))  # noqa: SLF001

    def test_non_boolean_pass_returns_none(self):
        self.assertIsNone(me._parse_judge_verdict('{"pass": "yes", "score": 8}'))  # noqa: SLF001

    def test_fenced_output_is_rejected_rather_than_stripped(self):
        """The lenient fence-stripper is gone on purpose: with
        output_config.format in place, a fenced response means the schema
        was not honoured, and that should surface as a judge error rather
        than be quietly repaired."""
        self.assertIsNone(me._parse_judge_verdict('```json\n{"pass": true, "score": 8}\n```'))  # noqa: SLF001


# ---------------------------------------------------------------------------
# judge_output(): Stage-2 #771 Blocking fix -- a judge-API transport/parse
# failure must be tagged with "error" rather than silently coerced into a
# fabricated score=0.0 indistinguishable from a genuine low score.
# ---------------------------------------------------------------------------

class JudgeErrorPropagationTests(unittest.TestCase):
    def test_transport_failure_is_tagged_with_an_error(self):
        with mock.patch("memory_eval._call_judge_api", return_value=(None, {"input_tokens": 0, "output_tokens": 0})):
            judged = me.judge_output(
                {"task_prompt": "p"}, judge_model="m", judge_system_prompt="s",
                api_key="k", api_url="http://unused.invalid", offline_score=None,
            )
        self.assertEqual(judged["score"], 0.0)
        self.assertFalse(judged["pass"])
        self.assertIn("error", judged)
        self.assertTrue(judged["error"])

    def test_non_numeric_score_is_tagged_with_an_error(self):
        with mock.patch(
            "memory_eval._call_judge_api",
            return_value=({"pass": True, "score": "not-a-number"}, {"input_tokens": 1, "output_tokens": 1}),
        ):
            judged = me.judge_output(
                {"task_prompt": "p"}, judge_model="m", judge_system_prompt="s",
                api_key="k", api_url="http://unused.invalid", offline_score=None,
            )
        self.assertEqual(judged["score"], 0.0)
        self.assertIn("error", judged)
        self.assertTrue(judged["error"])

    def test_offline_short_circuit_never_carries_an_error(self):
        judged = me.judge_output(
            {"task_prompt": "p"}, judge_model="m", judge_system_prompt="s",
            api_key=None, api_url="http://unused.invalid", offline_score={"score": 7.0},
        )
        self.assertNotIn("error", judged)
        self.assertEqual(judged["score"], 7.0)

    def test_live_success_never_carries_an_error(self):
        with mock.patch(
            "memory_eval._call_judge_api",
            return_value=({"pass": True, "score": 8.0}, {"input_tokens": 1, "output_tokens": 1}),
        ):
            judged = me.judge_output(
                {"task_prompt": "p"}, judge_model="m", judge_system_prompt="s",
                api_key="k", api_url="http://unused.invalid", offline_score=None,
            )
        self.assertNotIn("error", judged)
        self.assertEqual(judged["score"], 8.0)


# ---------------------------------------------------------------------------
# _aggregate_arm_runs(): Stage-2 #771 Blocking fix -- a run whose judge call
# failed must be EXCLUDED from mean_score/pass_rate (not averaged in as a
# fabricated 0.0/False), and judge_error_rate must reflect the fraction of
# judge-failed runs.
# ---------------------------------------------------------------------------

class AggregateArmRunsJudgeErrorTests(unittest.TestCase):
    def _run(self, *, score=7.0, is_error=False, judge_error=None):
        return {
            "score": score, "pass": score >= 6.0, "input_tokens": 100, "total_input_tokens": 100, "output_tokens": 20,
            "turns": 2, "run_cost_usd": 0.01, "judge_input_tokens": 10, "judge_output_tokens": 5,
            "is_error": is_error, "judge_error": judge_error,
        }

    def test_judge_errored_run_excluded_from_mean_score(self):
        runs = [self._run(score=8.0), self._run(score=0.0, judge_error="judge did not return parseable {pass, score}")]
        agg = me._aggregate_arm_runs(runs)  # noqa: SLF001
        # The fabricated 0.0 must not drag the mean down -- only the one
        # genuinely-scored run counts.
        self.assertEqual(agg["mean_score"], 8.0)

    def test_judge_errored_run_excluded_from_pass_rate(self):
        runs = [self._run(score=8.0), self._run(score=0.0, judge_error="x")]
        agg = me._aggregate_arm_runs(runs)  # noqa: SLF001
        self.assertEqual(agg["pass_rate"], 1.0)

    def test_judge_error_rate_reflects_fraction_of_judge_failed_runs(self):
        runs = [self._run(judge_error="x"), self._run(), self._run(), self._run()]
        agg = me._aggregate_arm_runs(runs)  # noqa: SLF001
        self.assertAlmostEqual(agg["judge_error_rate"], 0.25)

    def test_all_runs_judge_errored_is_a_safe_zeroed_mean_not_a_crash(self):
        runs = [self._run(score=0.0, judge_error="x"), self._run(score=0.0, judge_error="y")]
        agg = me._aggregate_arm_runs(runs)  # noqa: SLF001
        self.assertEqual(agg["mean_score"], 0.0)
        self.assertEqual(agg["pass_rate"], 0.0)
        self.assertEqual(agg["judge_error_rate"], 1.0)

    def test_no_judge_errors_rate_is_zero(self):
        agg = me._aggregate_arm_runs([self._run(), self._run()])  # noqa: SLF001
        self.assertEqual(agg["judge_error_rate"], 0.0)

    def test_empty_runs_list_includes_zeroed_judge_error_rate(self):
        agg = me._aggregate_arm_runs([])  # noqa: SLF001
        self.assertEqual(agg["judge_error_rate"], 0.0)

    def test_run_dict_missing_judge_error_key_entirely_is_not_excluded(self):
        """Backward compatibility: a run dict built before this fix (no
        judge_error key at all, e.g. an older row shape) must not be
        treated as judge-errored."""
        run_no_key = {
            "score": 8.0, "pass": True, "input_tokens": 100, "total_input_tokens": 100, "output_tokens": 20,
            "turns": 2, "run_cost_usd": 0.01, "judge_input_tokens": 10, "judge_output_tokens": 5,
            "is_error": False,
        }
        agg = me._aggregate_arm_runs([run_no_key])  # noqa: SLF001
        self.assertEqual(agg["mean_score"], 8.0)
        self.assertEqual(agg["judge_error_rate"], 0.0)


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
            "score": score, "pass": score >= 6.0, "input_tokens": 100, "total_input_tokens": 100, "output_tokens": 20,
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
# #789: _run_one() must fold the CACHED prompt prefix (cache_read +
# cache_creation input tokens) into a new total_input_tokens row field, so
# the efficiency ratio sees the TRUE prompt size, not just the marginal
# uncached remainder. input_tokens keeps its billable-marginal meaning, and
# _aggregate_arm_runs() surfaces mean_total_input_tokens alongside it.
# ---------------------------------------------------------------------------

class TotalInputTokensCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def _run_one_row(self, usage):
        """Drive the real _run_one() row-construction with run_claude_p and
        judge_output mocked, so only the usage->row token capture is under
        test (not the curl/agent subprocess plumbing)."""
        sandbox = self.tmp / "sandbox"
        sandbox.mkdir(exist_ok=True)
        agent_result = {
            "is_error": False, "result": "ok", "num_turns": 1,
            "total_cost_usd": 0.0, "usage": usage,
        }
        judged = {"pass": True, "score": 8.0, "usage": {"input_tokens": 1, "output_tokens": 1}}
        with mock.patch("memory_eval.run_claude_p", return_value=agent_result), \
                mock.patch("memory_eval.judge_output", return_value=judged):
            return me._run_one(  # noqa: SLF001
                task_id="t", project_slug="proj", arm="treatment", run_index=0,
                prompt="Do X.", fixture_files={}, learnings_dir=self.tmp / "learnings",
                backbone="fixture-model", inject=True, api_key="sk-fixture",
                claude_bin="claude", max_budget_usd=0.5, timeout_s=5,
                judge_model="fixture-judge", judge_system_prompt="sys", criteria=["done"],
                api_url="https://api.anthropic.com/v1/messages", offline_score=None,
                sandbox_root=sandbox,
            )

    def test_cache_tokens_folded_into_total_input_tokens(self):
        row = self._run_one_row(
            {"input_tokens": 3000, "cache_read_input_tokens": 8000, "cache_creation_input_tokens": 0}
        )
        # total = 3000 marginal + 8000 cached-read + 0 cached-creation.
        self.assertEqual(row["total_input_tokens"], 11000)
        # input_tokens preserves its billable-marginal meaning, unchanged.
        self.assertEqual(row["input_tokens"], 3000)

    def test_aggregate_surfaces_mean_total_input_tokens(self):
        row = self._run_one_row(
            {"input_tokens": 3000, "cache_read_input_tokens": 8000, "cache_creation_input_tokens": 0}
        )
        agg = me._aggregate_arm_runs([row])  # noqa: SLF001
        self.assertEqual(agg["mean_total_input_tokens"], 11000)
        self.assertEqual(agg["mean_input_tokens"], 3000)


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
# Stage-2 #771 Blocking: reproduces the review's own repro scenario -- a
# judge-API outage confined to the baseline arm's runs while
# treatment/full_context judge calls succeed normally -- and confirms the
# fix's full chain: the affected arm's judge_error_rate is nonzero,
# mean_score is NOT the fabricated 0.0 treated as real evidence, and (even
# though classify_bucket(), a judge-error-unaware pure function, still
# nominally computes a high_value-shaped delta from the excluded-to-zero
# mean) gate_check() refuses to open on the resulting row. Exercised via a
# single monkeypatched subprocess.run that distinguishes the `claude -p`
# agent call from the `curl` judge call by argv[0] -- no network, no real
# `claude` binary, no ANTHROPIC_API_KEY.
# ---------------------------------------------------------------------------

class LiveJudgeOutageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_baseline_arm_judge_outage_does_not_fabricate_a_trusted_high_value_gate_open(self):
        runs = 3
        call_state = {"n": 0}

        def fake_subprocess_run(cmd, **kwargs):
            if cmd and cmd[0] == "curl":
                idx = call_state["n"]
                call_state["n"] += 1
                if idx < runs:
                    # First `runs` judge calls == the baseline arm (arms run
                    # strictly sequentially in run_arms()) -- simulated outage.
                    raise OSError("simulated curl transport failure (baseline arm outage)")
                remaining = idx - runs
                score = 8.0 if remaining < runs else 6.0  # treatment, then full_context
                body = json.dumps({
                    "content": [{"type": "text", "text": json.dumps({"pass": score >= 6.0, "score": score})}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                })
                return types.SimpleNamespace(returncode=0, stdout=f"{body}\n200", stderr="")
            # claude -p agent call -- irrelevant to this test, always "succeeds".
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "is_error": False, "result": "ok", "num_turns": 1, "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 5, "output_tokens": 5},
                }),
                stderr="",
            )

        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()
        with mock.patch("memory_eval.subprocess.run", side_effect=fake_subprocess_run):
            arms = me.run_arms(
                task_id="dreamed-repro", project_slug="dreamed-repro", prompt="Do X.",
                fixture_files={}, criteria=["done"], facts=[], learnings_dir=self.tmp / "learnings",
                backbone="fixture-model", runs=runs, api_key="sk-fixture", claude_bin="claude",
                max_budget_usd=0.5, timeout_s=5, judge_model="fixture-judge", judge_system_prompt="sys",
                api_url="https://api.anthropic.com/v1/messages", offline_scores=None, sandbox_root=sandbox,
            )

        # The affected arm: fabricated-0.0 is excluded, not averaged in.
        self.assertEqual(arms["baseline"]["mean_score"], 0.0)
        self.assertEqual(arms["baseline"]["judge_error_rate"], 1.0)
        self.assertEqual(arms["treatment"]["mean_score"], 8.0)
        self.assertEqual(arms["treatment"]["judge_error_rate"], 0.0)
        self.assertEqual(arms["full_context"]["mean_score"], 6.0)
        self.assertEqual(arms["full_context"]["judge_error_rate"], 0.0)

        bucket, delta, delta_sat = me.classify_bucket(
            baseline_mean=arms["baseline"]["mean_score"], treatment_mean=arms["treatment"]["mean_score"],
            full_context_mean=arms["full_context"]["mean_score"],
        )
        # classify_bucket() is judge-error-unaware by design (a pure
        # function over three floats) -- it still nominally computes a
        # high_value-shaped delta from the excluded-to-zero baseline mean.
        # This IS the review's own reproduced fabrication; the fix's
        # safety property lives in gate_check() below, not here.
        self.assertEqual(bucket, "high_value")
        self.assertEqual(delta, 8.0)
        self.assertEqual(delta_sat, 2.0)

        row = me._build_result_row(  # noqa: SLF001
            task_id="dreamed-repro", kind="dreamed", backbone="fixture-model", runs=runs, offline=False,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat,
            extra={"mining": {"noise_proposals_written": 0, "noise_high_value": False}},
        )
        me.write_results([row], date=me.today_iso())

        is_open, reason = me.gate_check()
        self.assertFalse(is_open, reason)
        self.assertIn("judge", reason)

    def test_all_arms_clean_judge_calls_still_open_the_gate(self):
        """The paired positive case: the SAME integration shape (three
        sequential arms, each judged via the real _call_judge_api/
        run_claude_p chain) but with NO simulated outage anywhere -- each
        arm genuinely earns a distinct score in call order -- must still
        classify high_value and open the gate. The fix must not make the
        gate impossible to open."""
        runs = 2
        call_state = {"n": 0}
        # baseline scores low, treatment high, full_context mid -- a
        # genuine high_value + delta_sat>0 shape (same canonical numbers
        # as ClassifyBucketTests.test_high_value_requires_delta_sat_positive),
        # driven by the mocked judge responses in strict arm call order.
        arm_scores = [3.0] * runs + [8.5] * runs + [6.0] * runs

        def fake_subprocess_run(cmd, **kwargs):
            if cmd and cmd[0] == "curl":
                idx = call_state["n"]
                call_state["n"] += 1
                score = arm_scores[idx]
                body = json.dumps({
                    "content": [{"type": "text", "text": json.dumps({"pass": score >= 6.0, "score": score})}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                })
                return types.SimpleNamespace(returncode=0, stdout=f"{body}\n200", stderr="")
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "is_error": False, "result": "ok", "num_turns": 1, "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 5, "output_tokens": 5},
                }),
                stderr="",
            )

        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()
        with mock.patch("memory_eval.subprocess.run", side_effect=fake_subprocess_run):
            arms = me.run_arms(
                task_id="dreamed-repro-clean", project_slug="dreamed-repro-clean", prompt="Do X.",
                fixture_files={}, criteria=["done"], facts=[], learnings_dir=self.tmp / "learnings",
                backbone="fixture-model", runs=runs, api_key="sk-fixture", claude_bin="claude",
                max_budget_usd=0.5, timeout_s=5, judge_model="fixture-judge", judge_system_prompt="sys",
                api_url="https://api.anthropic.com/v1/messages", offline_scores=None, sandbox_root=sandbox,
            )

        for arm in me.ARMS:
            self.assertEqual(arms[arm]["judge_error_rate"], 0.0)
        self.assertEqual(arms["baseline"]["mean_score"], 3.0)
        self.assertEqual(arms["treatment"]["mean_score"], 8.5)
        self.assertEqual(arms["full_context"]["mean_score"], 6.0)

        bucket, delta, delta_sat = me.classify_bucket(
            baseline_mean=arms["baseline"]["mean_score"], treatment_mean=arms["treatment"]["mean_score"],
            full_context_mean=arms["full_context"]["mean_score"],
        )
        self.assertEqual(bucket, "high_value")

        row = me._build_result_row(  # noqa: SLF001
            task_id="dreamed-repro-clean", kind="dreamed", backbone="fixture-model", runs=runs, offline=False,
            arms=arms, bucket=bucket, delta=delta, delta_sat=delta_sat,
            extra={"mining": {"noise_proposals_written": 0, "noise_high_value": False}},
        )
        me.write_results([row], date=me.today_iso())

        is_open, reason = me.gate_check()
        self.assertTrue(is_open, reason)


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

    def test_dreamed_high_value_via_efficiency_delta_sat_zero_opens_gate(self):
        """#784: the gate no longer independently re-checks Δ_sat>0 -- that
        is subsumed by classify_bucket()'s two-path high_value definition. A
        live dreamed row the classifier deemed high_value via the EFFICIENCY
        path (it matched the full-context dump within noise, so delta_sat can
        be 0, at materially fewer input tokens) must now OPEN the gate.
        Before #784 this exact row (bucket=high_value, delta_sat=0) was
        force-closed by the gate's own Δ_sat>0 clause."""
        self._write_results(self._healthy_rows(dreamed_offline=False, dreamed_delta_sat=0.0))
        is_open, reason = me.gate_check()
        self.assertTrue(is_open, reason)

    def test_non_high_value_dreamed_row_does_not_satisfy_gate(self):
        """#784: the replacement negative control for the removed Δ_sat>0
        clause -- a live dreamed row that is NOT high_value (via either
        path) still fails the dreamed condition, and the reason no longer
        names Δ_sat (that check moved into the classifier)."""
        rows = self._healthy_rows()
        for r in rows:
            if r["kind"] == "dreamed":
                r["bucket"] = "inconclusive"
        self._write_results(rows)
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("dreamed", reason)
        self.assertNotIn("Δ_sat", reason)

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

    def test_dreamed_row_with_judge_error_rate_does_not_satisfy_gate(self):
        """Stage-2 #771 Blocking: a live dreamed high_value row whose own
        arms show a nonzero judge_error_rate must not open the gate -- the
        classification it rests on may be built on a fabricated judge-
        failure score, not real evidence."""
        rows = self._healthy_rows()
        for r in rows:
            if r["kind"] == "dreamed":
                r["baseline"] = {"mean_score": 0.0, "judge_error_rate": 0.33}
                r["treatment"] = {"mean_score": 8.5, "judge_error_rate": 0.0}
                r["full_context"] = {"mean_score": 6.0, "judge_error_rate": 0.0}
                r["mining"] = {"noise_proposals_written": 0, "noise_high_value": False}
        self._write_results(rows)

        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertIn("judge", reason)

    def test_dreamed_row_with_zero_judge_error_rate_still_opens_gate(self):
        """The paired positive case: explicit judge_error_rate=0.0 on
        every arm must not itself block the gate."""
        rows = self._healthy_rows()
        for r in rows:
            if r["kind"] == "dreamed":
                r["baseline"] = {"mean_score": 3.0, "judge_error_rate": 0.0}
                r["treatment"] = {"mean_score": 8.5, "judge_error_rate": 0.0}
                r["full_context"] = {"mean_score": 6.0, "judge_error_rate": 0.0}
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


# ---------------------------------------------------------------------------
# main()'s task-level isolation (Stage-2 #771 Recommend): a single task's
# own orchestration exception must not discard earlier tasks' already-
# completed results.
# ---------------------------------------------------------------------------

class TaskLevelIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_one_task_raising_does_not_discard_earlier_tasks_results(self):
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        ok_task = {"id": "iso-ok", "kind": "canary", "prompt": "p", "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"]}
        fail_task = {"id": "iso-fail", "kind": "canary", "prompt": "p", "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"]}
        (tasks_dir / "01-ok.json").write_text(json.dumps(ok_task), encoding="utf-8")
        (tasks_dir / "02-fail.json").write_text(json.dumps(fail_task), encoding="utf-8")

        real_run_task = me.run_task

        def fake_run_task(task, **kwargs):
            if task["id"] == "iso-fail":
                raise RuntimeError("synthetic failure for isolation test")
            return real_run_task(task, **kwargs)

        with mock.patch("memory_eval.run_task", side_effect=fake_run_task):
            exit_code = me.main([
                "--tasks", str(tasks_dir / "*.json"),
                "--offline", str(OFFLINE_FIXTURES),
                "--runs", "1",
                "--backbone", "fixture-model",
            ])

        self.assertEqual(exit_code, 0)
        results = me._read_results_file(me._find_latest_results_file())  # noqa: SLF001
        task_ids = {r["task_id"] for r in results}
        self.assertEqual(task_ids, {"iso-ok", "iso-fail"})

        ok_rows = [r for r in results if r["task_id"] == "iso-ok"]
        self.assertEqual(len(ok_rows), 1)
        self.assertNotEqual(ok_rows[0]["bucket"], "error")

        fail_rows = [r for r in results if r["task_id"] == "iso-fail"]
        self.assertEqual(len(fail_rows), 1)
        self.assertEqual(fail_rows[0]["bucket"], "error")
        self.assertIn("synthetic failure for isolation test", fail_rows[0]["task_error"])

        # render_summary_table()/gate_check() must not crash on a mix of
        # real rows and a synthetic error row.
        table = me.render_summary_table(results)
        self.assertIn("iso-ok", table)
        self.assertIn("iso-fail", table)
        self.assertIn("error", table)
        is_open, _reason = me.gate_check()
        self.assertFalse(is_open)  # no high_value rows in this fixture -- just must not crash

    def test_results_survive_an_uncaught_basexception_via_incremental_writes(self):
        """A BaseException the per-task `except Exception` deliberately
        does NOT catch (e.g. KeyboardInterrupt) must not erase an EARLIER
        task's already-completed results -- this only holds if results
        are written inside the loop after each task, not solely once at
        the very end (which, pre-fix, is never even reached here since
        the loop never completes)."""
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        ok_task = {"id": "iso-ok-2", "kind": "canary", "prompt": "p", "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"]}
        fatal_task = {"id": "iso-fatal", "kind": "canary", "prompt": "p", "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"]}
        (tasks_dir / "01-ok.json").write_text(json.dumps(ok_task), encoding="utf-8")
        (tasks_dir / "02-fatal.json").write_text(json.dumps(fatal_task), encoding="utf-8")

        real_run_task = me.run_task

        def fake_run_task(task, **kwargs):
            if task["id"] == "iso-fatal":
                raise KeyboardInterrupt("simulated Ctrl-C mid-task")
            return real_run_task(task, **kwargs)

        with mock.patch("memory_eval.run_task", side_effect=fake_run_task):
            with self.assertRaises(KeyboardInterrupt):
                me.main([
                    "--tasks", str(tasks_dir / "*.json"),
                    "--offline", str(OFFLINE_FIXTURES),
                    "--runs", "1",
                    "--backbone", "fixture-model",
                ])

        results = me._read_results_file(me._find_latest_results_file())  # noqa: SLF001
        # iso-ok-2's already-completed row survived even though the run
        # never reached the loop's end (let alone the post-loop
        # write_results() call) -- only the within-loop incremental write
        # can explain this.
        self.assertEqual({r["task_id"] for r in results}, {"iso-ok-2"})


# ---------------------------------------------------------------------------
# #1027: a run where EVERY agent run failed to execute is the harness, not a
# memory result. It must abort loudly (raw first failure on stderr, non-zero
# exit) rather than write a red results file that gate_check() then reads as
# a regression -- while a run with SOME failures stays non-fatal.
# ---------------------------------------------------------------------------

class WholeRunAbortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)
        me.reset_agent_error_samples()
        self.addCleanup(me.reset_agent_error_samples)
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def _write_task(self, filename: str, task_id: str) -> None:
        task = {
            "id": task_id, "kind": "canary", "prompt": f"prompt for {task_id}",
            "fixture": {"files": {"a.txt": "x\n"}}, "criteria": ["c"],
        }
        (self.tasks_dir / filename).write_text(json.dumps(task), encoding="utf-8")

    @staticmethod
    def _launch_failure() -> dict:
        return {
            "is_error": True,
            "result": "claude -p failed to launch: [Errno 2] No such file or directory: 'claude'",
            "usage": {}, "num_turns": 0, "total_cost_usd": 0.0,
        }

    @staticmethod
    def _healthy_result() -> dict:
        return {
            "is_error": False, "result": "done", "num_turns": 2, "total_cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }

    def _run_main(self, run_claude_p_side_effect):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fixture"}), \
                mock.patch("memory_eval.run_claude_p", side_effect=run_claude_p_side_effect), \
                mock.patch(
                    "memory_eval._call_judge_api",
                    return_value=({"pass": True, "score": 7.0}, {"input_tokens": 10, "output_tokens": 5}),
                ), \
                contextlib.redirect_stderr(stderr):
            exit_code = me.main([
                "--tasks", str(self.tasks_dir / "*.json"),
                "--runs", "1",
                "--backbone", "fixture-model",
                "--claude-bin", "/usr/bin/true",
            ])
        return exit_code, stderr.getvalue()

    def test_every_run_failing_aborts_with_the_raw_output_and_writes_nothing(self):
        self._write_task("01-a.json", "abort-a")
        self._write_task("02-b.json", "abort-b")

        exit_code, stderr = self._run_main(lambda **kwargs: self._launch_failure())

        self.assertEqual(exit_code, 1)
        self.assertIn("every agent run failed to execute", stderr)
        # The RAW subprocess detail is attached, not just a rate.
        self.assertIn("No such file or directory", stderr)
        # Nothing was written, so --gate reports "no results" (harness
        # broken) rather than a fabricated memory regression.
        self.assertIsNone(me._find_latest_results_file())  # noqa: SLF001
        is_open, reason = me.gate_check()
        self.assertFalse(is_open)
        self.assertEqual(reason, "no results")

    def test_a_partially_failing_run_stays_non_fatal_and_writes_results(self):
        self._write_task("01-ok.json", "partial-ok")
        self._write_task("02-bad.json", "partial-bad")

        def side_effect(**kwargs):
            return self._launch_failure() if "partial-bad" in kwargs["prompt"] else self._healthy_result()

        exit_code, stderr = self._run_main(side_effect)

        self.assertEqual(exit_code, 0)
        self.assertNotIn("every agent run failed to execute", stderr)
        results_path = me._find_latest_results_file()  # noqa: SLF001
        self.assertIsNotNone(results_path)
        rows = {r["task_id"]: r for r in me._read_results_file(results_path)}  # noqa: SLF001
        self.assertEqual(rows["partial-ok"]["baseline"]["format_error_rate"], 0.0)
        self.assertEqual(rows["partial-bad"]["baseline"]["format_error_rate"], 1.0)

    def test_an_unresolvable_claude_binary_fails_before_any_task_runs(self):
        self._write_task("01-a.json", "unresolvable")
        ran = []

        def side_effect(**kwargs):
            ran.append(kwargs["prompt"])
            return self._healthy_result()

        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fixture"}), \
                mock.patch("memory_eval.run_claude_p", side_effect=side_effect), \
                mock.patch(
                    "memory_eval.resolve_claude_bin",
                    side_effect=me.ClaudeBinaryNotFoundError("'claude' not found. Searched: PATH=''"),
                ), \
                contextlib.redirect_stderr(stderr):
            exit_code = me.main([
                "--tasks", str(self.tasks_dir / "*.json"),
                "--runs", "1", "--backbone", "fixture-model",
            ])

        self.assertEqual(exit_code, 1)
        self.assertIn("not found", stderr.getvalue())
        self.assertEqual(ran, [], "no task may run once the binary cannot be resolved")
        self.assertIsNone(me._find_latest_results_file())  # noqa: SLF001

    def test_offline_mode_skips_binary_resolution_entirely(self):
        """--offline never spawns `claude`, so a machine with no CLI at all
        must still be able to run the plumbing check."""
        stderr = io.StringIO()
        with mock.patch(
            "memory_eval.resolve_claude_bin",
            side_effect=AssertionError("resolve_claude_bin must not run in --offline mode"),
        ), contextlib.redirect_stderr(stderr):
            exit_code = me.main([
                "--tasks", str(TASKS_DIR / "06-canary-unrelated-rename.json"),
                "--offline", str(OFFLINE_FIXTURES),
                "--runs", "1", "--backbone", "fixture-model",
            ])
        self.assertEqual(exit_code, 0)


# ---------------------------------------------------------------------------
# Stage-2 #771 Recommend: the noise corpus's map-phase offline fixture must
# exist so run_dreamed_task's own offline plumbing check actually exercises
# the per-slug map-candidate path for BOTH corpora, not just the signal one
# (previously fell through dream_analyze's missing-fixture-treat-as-empty
# fallback, silently).
# ---------------------------------------------------------------------------

class DreamedTaskOfflineNoiseFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    def test_noise_slug_map_fixture_exists_and_offline_run_does_not_warn(self):
        self.assertTrue(
            (OFFLINE_DREAMED_FIXTURES / "map-dreamed-noise-repo.json").is_file(),
            "map-dreamed-noise-repo.json must exist so the noise slug's map "
            "phase does not fall through dream_analyze's missing-fixture "
            "fallback in offline mode",
        )

        task = me.load_task(TASKS_DIR / "09-dreamed-pipeline-end-to-end.json")
        offline_scores = me.load_offline_scores(OFFLINE_FIXTURES)
        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()

        stderr_capture = io.StringIO()
        with contextlib.redirect_stderr(stderr_capture):
            rows = me.run_dreamed_task(
                task, backbones=["fixture-model"], runs=1, api_key="", claude_bin="claude",
                max_budget_usd=0.1, timeout_s=5, judge_model="fixture-judge",
                judge_system_prompt="unused in offline mode", api_url="http://unused.invalid",
                offline=True, offline_dir=OFFLINE_FIXTURES, offline_all_scores=offline_scores,
                sandbox_root=sandbox,
            )

        stderr_text = stderr_capture.getvalue()
        self.assertNotIn("map-dreamed-noise-repo.json", stderr_text)
        self.assertNotIn("no offline fixture found", stderr_text)

        self.assertEqual(len(rows), 1)
        mining = rows[0]["mining"]
        # The map-phase fixture is now real/non-empty (proven above via
        # the absent warning), but reduce.json -- the ONLY thing that
        # determines the final proposals list in offline mode -- is
        # deliberately left unchanged, so the negative control must still
        # correctly report no noise-side proposal.
        self.assertEqual(mining["noise_proposals_written"], 0)
        self.assertFalse(mining["noise_high_value"])
        self.assertEqual(mining["signal_proposals_written"], 1)


# ---------------------------------------------------------------------------
# #789: pin the CALLER wiring. run_task() and run_dreamed_task() must feed
# classify_bucket()'s efficiency args from mean_total_input_tokens, NOT
# mean_input_tokens. With run_arms() mocked to return arms whose two token
# means DIFFER (TOTAL 3000 vs 11000 across treatment/full_context, but
# MARGINAL 3000 vs 3000 everywhere), the efficiency ratio only clears 0.5 on
# the total counts -> bucket high_value. If either caller reverts to
# mean_input_tokens the ratio is 1.0 and the bucket collapses to
# inconclusive, failing these -- the mutation Stage-1 review found unpinned.
# ---------------------------------------------------------------------------

class CallerWiringToTotalInputTokensTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _isolate_env(self)

    @staticmethod
    def _arm(*, mean_score, mean_total_input_tokens, mean_input_tokens=3000.0):
        """Mirror _aggregate_arm_runs()'s output shape (every key
        _build_result_row and classify_bucket read). mean_input_tokens is
        pinned at 3000 across ALL arms so the OLD (buggy) metric sees a 1.0
        ratio; only mean_total_input_tokens carries the real spread."""
        return {
            "mean_score": mean_score, "pass_rate": 1.0 if mean_score >= 6.0 else 0.0,
            "mean_input_tokens": mean_input_tokens, "mean_total_input_tokens": mean_total_input_tokens,
            "mean_output_tokens": 10.0, "mean_turns": 1.0, "mean_cost_usd": 0.0,
            "format_error_rate": 0.0, "judge_error_rate": 0.0, "runs": 1,
        }

    def _efficiency_arms(self):
        # treatment MATCHES full_context on score (delta_sat 0) at far fewer
        # TOTAL input tokens (3000 vs 11000, ratio 0.27 <= 0.5) -> Path B.
        return {
            "baseline": self._arm(mean_score=0.0, mean_total_input_tokens=3000.0),
            "treatment": self._arm(mean_score=10.0, mean_total_input_tokens=3000.0),
            "full_context": self._arm(mean_score=10.0, mean_total_input_tokens=11000.0),
        }

    def test_run_task_feeds_total_input_tokens_to_classify_bucket(self):
        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()
        task = {"id": "wiring-task", "kind": "uplift", "prompt": "Do X.",
                "seed_learnings": [], "criteria": ["done"]}
        with mock.patch("memory_eval.run_arms", return_value=self._efficiency_arms()):
            rows = me.run_task(
                task, backbones=["fixture-model"], runs=1, api_key="", claude_bin="claude",
                max_budget_usd=0.1, timeout_s=5, judge_model="fixture-judge",
                judge_system_prompt="unused", api_url="http://unused.invalid",
                offline_all_scores=None, sandbox_root=sandbox,
            )
        self.assertEqual(len(rows), 1)
        # high_value ONLY if the caller passed mean_total_input_tokens;
        # mean_input_tokens (3000 vs 3000, ratio 1.0) classifies inconclusive.
        self.assertEqual(rows[0]["bucket"], "high_value")

    def test_run_dreamed_task_feeds_total_input_tokens_to_classify_bucket(self):
        task = me.load_task(TASKS_DIR / "09-dreamed-pipeline-end-to-end.json")
        offline_scores = me.load_offline_scores(OFFLINE_FIXTURES)
        sandbox = self.tmp / "sandbox"
        sandbox.mkdir()
        # The real offline mine->analyze->apply machinery runs as in
        # DreamedTaskOfflineNoiseFixtureTests; only run_arms is replaced, so
        # the crafted differing-token arms reach classify_bucket unchanged.
        with contextlib.redirect_stderr(io.StringIO()), \
                mock.patch("memory_eval.run_arms", return_value=self._efficiency_arms()):
            rows = me.run_dreamed_task(
                task, backbones=["fixture-model"], runs=1, api_key="", claude_bin="claude",
                max_budget_usd=0.1, timeout_s=5, judge_model="fixture-judge",
                judge_system_prompt="unused", api_url="http://unused.invalid",
                offline=True, offline_dir=OFFLINE_FIXTURES, offline_all_scores=offline_scores,
                sandbox_root=sandbox,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bucket"], "high_value")


# ---------------------------------------------------------------------------
# --runs validation (Stage-2 #771 Recommend): --runs 0 (or negative) used
# to be silently accepted and produce a meaningless, plausible-looking
# results file.
# ---------------------------------------------------------------------------

class RunsValidationTests(unittest.TestCase):
    def test_runs_zero_is_rejected(self):
        with self.assertRaises(SystemExit):
            me.build_arg_parser().parse_args(["--runs", "0"])

    def test_runs_negative_is_rejected(self):
        with self.assertRaises(SystemExit):
            me.build_arg_parser().parse_args(["--runs", "-1"])

    def test_runs_positive_is_accepted(self):
        args = me.build_arg_parser().parse_args(["--runs", "3"])
        self.assertEqual(args.runs, 3)

    def test_default_runs_is_positive(self):
        args = me.build_arg_parser().parse_args([])
        self.assertGreaterEqual(args.runs, 1)


if __name__ == "__main__":
    unittest.main()
