#!/usr/bin/env python3
"""
Tests for the per-op-kind posture policy in modules/dreaming/lib/dream_analyze.py
(optimistic-memory plan.md §5 Epic 2): OPTIMISTIC_POSTURE, resolve_posture(),
and the optimistic_integration config block's deep-merge behavior in
load_config().

Runs in isolation: CCGM_LEARNINGS_DIR is redirected to a tempdir before
import (dream_analyze imports learnings_store transitively at module load
time -- mirrors test_dream_analyze.py's own pattern). CCGM_DREAMING_DIR is
redirected per-test for any config-file I/O; neither the real
~/.claude/dreaming nor ~/.claude/learnings is ever touched.

Run with: python3 -m pytest modules/dreaming/tests/test_posture_policy.py -q
      or: python3 modules/dreaming/tests/test_posture_policy.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

# Point the learnings store at a tempdir BEFORE importing dream_analyze,
# which imports learnings_store transitively at module load time.
_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-dreaming-test-posture-learnings-")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS

import dream_analyze as da  # noqa: E402


def _isolate_dreaming_dir(test: unittest.TestCase) -> Path:
    """Fresh CCGM_DREAMING_DIR per test; restores the prior value on
    cleanup. Mirrors test_dream_analyze.py's _isolate_env() helper, scoped
    to just the one env var these tests need (no --offline/API calls here,
    so the .env-path overrides that helper also sets are not needed)."""
    tmp = tempfile.mkdtemp(prefix="ccgm-dreaming-test-posture-")
    previous = os.environ.get("CCGM_DREAMING_DIR")
    os.environ["CCGM_DREAMING_DIR"] = tmp

    def _restore():
        if previous is None:
            os.environ.pop("CCGM_DREAMING_DIR", None)
        else:
            os.environ["CCGM_DREAMING_DIR"] = previous

    test.addCleanup(_restore)
    return Path(tmp)


# ---------------------------------------------------------------------------
# resolve_posture(): the per-op-kind policy table (§3.3).
# ---------------------------------------------------------------------------


class ResolvePostureTests(unittest.TestCase):
    def test_verify_is_optimistic_immediate(self):
        result = da.resolve_posture("learning_verify", "some-project")
        self.assertEqual(result["posture"], "optimistic-immediate")
        self.assertFalse(result["needs_dwell"])

    def test_add_is_optimistic_dwell(self):
        result = da.resolve_posture("learning_add", "some-project")
        self.assertEqual(result["posture"], "optimistic-dwell")
        self.assertTrue(result["needs_dwell"])

    def test_supersede_is_optimistic_dwell(self):
        result = da.resolve_posture("learning_supersede", "some-project")
        self.assertEqual(result["posture"], "optimistic-dwell")
        self.assertTrue(result["needs_dwell"])

    def test_contradict_is_dwell_quarantine(self):
        result = da.resolve_posture("learning_contradict", "some-project")
        self.assertEqual(result["posture"], "dwell-quarantine")
        self.assertTrue(result["needs_dwell"])

    def test_deprecate_is_dwell_quarantine(self):
        result = da.resolve_posture("learning_deprecate", "some-project")
        self.assertEqual(result["posture"], "dwell-quarantine")
        self.assertTrue(result["needs_dwell"])

    def test_unknown_kind_is_gated_fail_safe(self):
        result = da.resolve_posture("bogus_kind", "some-project")
        self.assertEqual(result["posture"], "gated")

    def test_add_targeting_global_is_gated(self):
        result = da.resolve_posture("learning_add", da.GLOBAL_SLUG)
        self.assertEqual(result["posture"], "gated")

    def test_global_gates_every_known_op_kind(self):
        # §3.3: "any -> _global" is `gated` regardless of kind. Assert it
        # for every kind the policy table actually knows about, not just
        # one representative sample.
        for kind in da.OPTIMISTIC_POSTURE:
            with self.subTest(kind=kind):
                result = da.resolve_posture(kind, da.GLOBAL_SLUG)
                self.assertEqual(result["posture"], "gated")

    def test_global_gates_unknown_kind_too(self):
        result = da.resolve_posture("bogus_kind", da.GLOBAL_SLUG)
        self.assertEqual(result["posture"], "gated")

    def test_returned_dict_is_a_copy_not_the_shared_constant(self):
        result = da.resolve_posture("learning_verify", "some-project")
        result["posture"] = "mutated"
        fresh = da.resolve_posture("learning_verify", "some-project")
        self.assertEqual(fresh["posture"], "optimistic-immediate")


# ---------------------------------------------------------------------------
# load_config(): optimistic_integration deep-merge (§3.5).
# ---------------------------------------------------------------------------


class LoadConfigOptimisticIntegrationTests(unittest.TestCase):
    def test_defaults_present_with_no_config_file(self):
        _isolate_dreaming_dir(self)
        cfg = da.load_config()
        self.assertIn("optimistic_integration", cfg)
        self.assertEqual(cfg["optimistic_integration"]["enabled"], False)
        self.assertEqual(cfg["optimistic_integration"]["max_add_supersede_per_run"], 10)

    def test_partial_override_deep_merges_with_defaults(self):
        tmp = _isolate_dreaming_dir(self)
        (tmp / "config.json").write_text(
            json.dumps({"optimistic_integration": {"dwell_hours": 6}}),
            encoding="utf-8",
        )
        cfg = da.load_config()
        self.assertEqual(cfg["optimistic_integration"]["dwell_hours"], 6)
        # Every other default in the sub-dict must survive the partial
        # override -- this is the deep-merge requirement itself.
        self.assertEqual(cfg["optimistic_integration"]["max_add_supersede_per_run"], 10)
        self.assertEqual(cfg["optimistic_integration"]["max_eviction_absolute"], 3)
        self.assertEqual(cfg["optimistic_integration"]["confidence_floor_verify"], 7)

    def test_partial_override_does_not_mutate_shared_default_constant(self):
        tmp = _isolate_dreaming_dir(self)
        (tmp / "config.json").write_text(
            json.dumps({"optimistic_integration": {"dwell_hours": 999}}),
            encoding="utf-8",
        )
        da.load_config()
        self.assertEqual(da.DEFAULT_OPTIMISTIC_INTEGRATION["dwell_hours"], 24)

    def test_top_level_override_still_works_alongside_optimistic_integration(self):
        tmp = _isolate_dreaming_dir(self)
        (tmp / "config.json").write_text(
            json.dumps({"lookback_days": 3, "optimistic_integration": {"dwell_hours": 6}}),
            encoding="utf-8",
        )
        cfg = da.load_config()
        self.assertEqual(cfg["lookback_days"], 3)
        self.assertEqual(cfg["optimistic_integration"]["dwell_hours"], 6)

    def test_config_without_optimistic_integration_key_still_gets_full_defaults(self):
        tmp = _isolate_dreaming_dir(self)
        (tmp / "config.json").write_text(json.dumps({"lookback_days": 3}), encoding="utf-8")
        cfg = da.load_config()
        self.assertEqual(cfg["lookback_days"], 3)
        # optimistic_integration now ALSO carries the seeded eligibility
        # sub-block (composite-eligibility plan.md §3.6, Epic E2). The
        # non-eligibility defaults still equal the constant; the eligibility
        # block equals its own eligibility.py-owned default (adrev2-005).
        oi = dict(cfg["optimistic_integration"])
        elig = oi.pop("eligibility")
        self.assertEqual(oi, da.DEFAULT_OPTIMISTIC_INTEGRATION)
        self.assertEqual(elig, da.eligibility.default_eligibility())


if __name__ == "__main__":
    unittest.main()
