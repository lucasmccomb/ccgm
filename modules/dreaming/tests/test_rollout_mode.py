#!/usr/bin/env python3
"""
Tests for optimistic integration's off/shadow/active rollout (#1087):
  - rollout_mode.resolve_mode: boolean back-compat + fail-closed
  - rollout_mode.shadow_tally arithmetic
  - run_optimistic_integrate(shadow=True): decides and logs, writes nothing
  - scorecard shadow section
  - dream-daily.sh routes the three modes

Run with: python3 -m pytest modules/dreaming/tests/test_rollout_mode.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))

# Reuse the engine test base: it pins env tempdirs before importing the engine.
import test_optimistic_engine as toe  # noqa: E402
import rollout_mode as rm  # noqa: E402
import scorecard  # noqa: E402

adp = toe.adp
da = toe.da
ls = toe.ls


class ResolveModeTests(unittest.TestCase):
    def test_true_reads_as_active(self):
        self.assertEqual(rm.resolve_mode(True), "active")

    def test_false_and_missing_read_as_off(self):
        self.assertEqual(rm.resolve_mode(False), "off")
        self.assertEqual(rm.resolve_mode(None), "off")

    def test_strings_pass_through(self):
        for mode in ("off", "shadow", "active"):
            self.assertEqual(rm.resolve_mode(mode), mode)
        self.assertEqual(rm.resolve_mode(" Shadow "), "shadow")

    def test_unrecognised_values_fail_closed(self):
        for bad in ("on", "yes", 1, 0, [], {}, "true"):
            self.assertEqual(rm.resolve_mode(bad), "off", bad)


def _d(pid, would, kind="learning_add"):
    return {"proposal_id": pid, "would_integrate": would, "kind": kind}


class ShadowTallyTests(unittest.TestCase):
    def test_counts_would_integrate_and_would_skip(self):
        s = rm.shadow_tally([_d("a", True), _d("b", False), _d("c", True)])
        self.assertEqual(s, {"decisions": 3, "would_integrate": 2, "would_skip": 1})

    def test_latest_record_per_proposal_wins(self):
        s = rm.shadow_tally([_d("p", False), _d("p", True)])
        self.assertEqual(s, {"decisions": 1, "would_integrate": 1, "would_skip": 0})

    def test_records_without_a_proposal_id_are_ignored(self):
        self.assertEqual(rm.shadow_tally([{"would_integrate": True}])["decisions"], 0)

    def test_agreement_statistic_is_retired(self):
        for name in ("agreement", "promotion_verdict", "PROMOTION_MIN_DECIDED"):
            self.assertFalse(hasattr(rm, name), name)


class LoadConfigModeTests(toe.OptimisticEngineTestBase):
    def test_integration_mode_maps_persisted_booleans(self):
        for raw, expected in ((True, "active"), (False, "off"), ("shadow", "shadow")):
            self._write_config({"enabled": raw})
            self.assertEqual(da.integration_mode(), expected, raw)

    def test_legacy_counters_flag_reads_as_active(self):
        cfg_path = da.dreaming_dir() / "config.json"
        cfg_path.write_text(json.dumps({"auto_apply_counters": True}), encoding="utf-8")
        self.assertEqual(da.integration_mode(), "active")


class ShadowEngineTests(toe.OptimisticEngineTestBase):
    def _shadow_rows(self):
        path = adp.shadow_log_path()
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def test_shadow_logs_would_integrate_and_changes_nothing(self):
        slug = toe._unique_slug("shadow-add")
        self._write_config({"enabled": "shadow"})
        target = self._seed_learning(slug, content="verify me", confidence=5)
        day = toe._unique_day()
        self._write_day(day, [
            toe._proposal_row(pid="sa-add", kind="learning_add", project=slug,
                              content="a brand new learning", type_="pattern", confidence=8, sessions=2),
            toe._proposal_row(pid="sa-verify", kind="learning_verify", project=slug,
                              target_id=target, confidence=7),
            toe._proposal_row(pid="sa-low", kind="learning_add", project=slug,
                              content="weak", type_="pattern", confidence=1, sessions=2),
        ])
        heads_before = ls.load_all(slug)
        audit_before = self._read_audit()
        state_before = self._read_optimistic_state_file()

        summary = adp.run_optimistic_integrate(day, shadow=True)

        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(summary["would_integrate"], 2, summary)
        # Nothing written: store heads, proposal status, audit, breaker state.
        self.assertEqual(ls.load_all(slug), heads_before)
        for pid in ("sa-add", "sa-verify", "sa-low"):
            self.assertEqual(self._status_of(day, pid), "pending")
        self.assertEqual(self._read_audit(), audit_before)
        self.assertEqual(self._read_optimistic_state_file(), state_before)

        rows = {r["proposal_id"]: r for r in self._shadow_rows() if r["day"] == day}
        self.assertTrue(rows["sa-add"]["would_integrate"])
        self.assertTrue(rows["sa-verify"]["would_integrate"])
        self.assertFalse(rows["sa-low"]["would_integrate"])
        self.assertEqual(rows["sa-low"]["reason"], "skipped_floor")
        self.assertEqual(rows["sa-add"]["kind"], "learning_add")
        self.assertIn("ts", rows["sa-add"])

    def test_shadow_applies_the_per_run_cap(self):
        slug = toe._unique_slug("shadow-cap")
        self._write_config({"enabled": "shadow", "max_add_supersede_per_run": 1})
        day = toe._unique_day()
        self._write_day(day, [
            toe._proposal_row(pid=f"cap-{i}", kind="learning_add", project=slug,
                              content=f"learning number {i}", type_="pattern", confidence=8, sessions=2)
            for i in range(3)
        ])
        summary = adp.run_optimistic_integrate(day, shadow=True)
        self.assertEqual(summary["would_integrate"], 1, summary)
        reasons = sorted(r["reason"] for r in self._shadow_rows() if r["day"] == day)
        self.assertEqual(reasons.count("skipped_over_cap"), 2, reasons)

    def test_shadow_respects_a_suspended_breaker_without_resuming_it(self):
        slug = toe._unique_slug("shadow-breaker")
        self._write_config({"enabled": "shadow"})
        suspended = {"suspended": True, "suspended_at": self._iso(1.0), "anomaly_log": [], "last_run": None}
        self._write_optimistic_state(suspended)
        day = toe._unique_day()
        self._write_day(day, [toe._proposal_row(pid="br-1", kind="learning_add", project=slug,
                                                content="blocked", type_="pattern")])
        summary = adp.run_optimistic_integrate(day, shadow=True)
        self.assertEqual(summary["circuit_breaker"], "suspended")
        self.assertEqual(summary["would_integrate"], 0)
        self.assertEqual(self._read_optimistic_state_file(), suspended)

    def test_gated_kinds_are_not_logged(self):
        slug = toe._unique_slug("shadow-gated")
        self._write_config({"enabled": "shadow"})
        day = toe._unique_day()
        self._write_day(day, [toe._proposal_row(pid="g-1", kind="learning_add", project="_global",
                                                content="global", type_="pattern")])
        adp.run_optimistic_integrate(day, shadow=True)
        self.assertEqual([r for r in self._shadow_rows() if r["day"] == day], [])

    def test_active_path_is_unchanged(self):
        slug = toe._unique_slug("shadow-active")
        self._write_config({"enabled": "active"})
        day = toe._unique_day()
        self._write_day(day, [toe._proposal_row(pid="act-1", kind="learning_add", project=slug,
                                                content="real write", type_="pattern",
                                                confidence=8, sessions=2)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        self.assertEqual([r for r in self._shadow_rows() if r["day"] == day], [])


class ScorecardShadowTests(unittest.TestCase):
    def _render(self, tmp: Path, shadow_rows, proposal_rows):
        (tmp / "state").mkdir()
        (tmp / "proposals").mkdir()
        (tmp / "state" / "shadow-optimistic.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in shadow_rows), encoding="utf-8")
        (tmp / "proposals" / "2026-09-01.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in proposal_rows), encoding="utf-8")
        return scorecard.render(
            "2026-09-01", "2026-09-08",
            learnings_dir=tmp / "learnings", injection_log_dir=tmp / "inj",
            proposals_dir=tmp / "proposals", apply_audit_path=tmp / "state" / "apply-audit.jsonl",
            store_api=ls, generated_at="2026-09-08",
        )

    def test_section_tallies_would_integrate_and_would_skip(self):
        with tempfile.TemporaryDirectory() as d:
            shadow = [_d("p1", True), _d("p2", True), _d("p3", False), _d("p4", True)]
            md = self._render(Path(d), shadow, [])
        self.assertIn("## Shadow integration — 4 decisions logged", md)
        self.assertIn("- shadow decisions: 4", md)
        self.assertIn("- would integrate: 3", md)
        self.assertIn("- would skip: 1", md)
        self.assertNotIn("promotion bar", md)
        self.assertNotIn("agreed", md)

    def test_section_absent_without_a_shadow_log(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = scorecard.render(
                "2026-09-01", "2026-09-08",
                learnings_dir=tmp / "l", injection_log_dir=tmp / "i", proposals_dir=tmp / "p",
                apply_audit_path=tmp / "state" / "apply-audit.jsonl",
                store_api=ls, generated_at="2026-09-08",
            )
        self.assertNotIn("## Shadow integration", md)


class DailyRoutingTests(unittest.TestCase):
    """_optimistic_integration_mode in dream-daily.sh reads the three modes."""

    def _mode(self, config: dict | None) -> str:
        with tempfile.TemporaryDirectory() as d:
            if config is not None:
                (Path(d) / "config.json").write_text(json.dumps(config), encoding="utf-8")
            script = HERE.parent / "bin" / "dream-daily.sh"
            src = script.read_text(encoding="utf-8")
            start = src.index("_optimistic_integration_mode() {")
            end = src.index("\n}\n", start) + 3
            proc = subprocess.run(
                ["bash", "-c", f'DREAMING_DIR="{d}"; MODULE_ROOT="{HERE.parent}"\n{src[start:end]}\n_optimistic_integration_mode'],
                capture_output=True, text=True, check=False,
            )
        return proc.stdout.strip()

    def test_modes(self):
        self.assertEqual(self._mode(None), "off")
        self.assertEqual(self._mode({"optimistic_integration": {"enabled": True}}), "active")
        self.assertEqual(self._mode({"optimistic_integration": {"enabled": False}}), "off")
        self.assertEqual(self._mode({"optimistic_integration": {"enabled": "shadow"}}), "shadow")
        self.assertEqual(self._mode({"optimistic_integration": {"enabled": "active"}}), "active")
        self.assertEqual(self._mode({"optimistic_integration": {"enabled": "bogus"}}), "off")


if __name__ == "__main__":
    unittest.main()
