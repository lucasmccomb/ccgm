#!/usr/bin/env python3
"""
Tests for the optimistic auto-integration engine (optimistic-memory
plan.md Epic 3): modules/dreaming/lib/apply_dream_proposal.py's
run_optimistic_integrate(), the per-slug blast-radius caps, the batch
eviction-concentration anomaly check, the cross-night accumulation
signal, the windowed circuit breaker, and the weekly cost-capped eval
refresh (run_eval_refresh()).

Runs in isolation: CCGM_LEARNINGS_DIR + CCGM_DREAMING_DIR + HOME are
redirected to tempdirs BEFORE import (mirrors test_apply_dream_proposal.py
-- learnings_store.LEARNINGS_ROOT is frozen at import time; HOME is
sandboxed so _resolve_sibling_bin() falls back to the repo-relative CLIs
under test, not a possibly-stale installed ~/.claude/bin symlink). No
network, no ANTHROPIC_API_KEY, never the real store/dreaming dir (#793).

Every test uses a slug (and, where relevant, a day/proposal id) unique to
that test, so tests never interfere despite sharing one LEARNINGS_ROOT /
dreaming dir for the whole file. The one shared, mutable piece of state
that EVERY call to run_optimistic_integrate() touches regardless of slug
is state/optimistic.json (the circuit breaker) -- setUp() resets it to a
clean, non-suspended, empty-anomaly-log state before every single test, so
an anomaly recorded by one test can never leak into another test's breaker
decision. Tests that specifically exercise the breaker overwrite that
clean default with their own seeded state afterward.

Run with: python3 -m pytest modules/dreaming/tests/test_optimistic_engine.py -q
      or: python3 modules/dreaming/tests/test_optimistic_engine.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

# See module docstring: pop first, then point the store + dreaming dir at
# fresh tempdirs, BEFORE importing apply_dream_proposal (which transitively
# imports dream_analyze -> learnings_store, whose LEARNINGS_ROOT is frozen
# at import time). Mirrors test_apply_dream_proposal.py exactly.
sys.modules.pop("learnings_store", None)
sys.modules.pop("dream_analyze", None)
sys.modules.pop("apply_dream_proposal", None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-dreaming-test-optengine-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-dreaming-test-optengine-dreaming-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-dreaming-test-optengine-home-")
_ORIG_LEARNINGS_DIR = os.environ.get("CCGM_LEARNINGS_DIR")
_ORIG_DREAMING_DIR = os.environ.get("CCGM_DREAMING_DIR")
_ORIG_HOME = os.environ.get("HOME")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import learnings_store as ls  # noqa: E402


def tearDownModule() -> None:
    """Undo the module-level env overrides so they cannot leak into
    whatever test module pytest imports and runs next in the same process
    (#764)."""
    for key, orig in (
        ("CCGM_LEARNINGS_DIR", _ORIG_LEARNINGS_DIR),
        ("CCGM_DREAMING_DIR", _ORIG_DREAMING_DIR),
        ("HOME", _ORIG_HOME),
    ):
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


def _unique_slug(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


def _unique_day() -> str:
    # Not a real calendar date -- nothing in apply_dream_proposal.py parses
    # `day` as one, it is only ever used as a proposals/{day}.jsonl filename
    # component. A random suffix guarantees every test's proposals file is
    # independent of every other test's, with zero manual bookkeeping.
    return f"2026-test-{uuid.uuid4().hex[:10]}"


def _proposal_row(
    *, pid: str, kind: str, project: str, target_id: str | None = None,
    content: str | None = None, type_: str | None = None, confidence: int = 8,
    sessions: int = 2, agents: int = 1, justification: str = "optimistic-engine test",
    compaction_guard_failed: dict | None = None,
) -> dict:
    row: dict = {
        "id": pid, "kind": kind, "project": project, "target_id": target_id,
        "content": content, "type": type_, "confidence": confidence,
        "prevalence": {"sessions": sessions, "agents": agents},
        "evidence": [{"session_id": f"sess-{pid}", "excerpt": "example"}],
        "justification": justification, "fingerprint": f"fp-{pid}",
        "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
    }
    if compaction_guard_failed is not None:
        row["compaction_guard_failed"] = compaction_guard_failed
    return row


class OptimisticEngineTestBase(unittest.TestCase):
    """Shared setUp/helpers for every test class below. Carries no test_
    methods itself."""

    def setUp(self) -> None:
        # Re-assert this module's env at RUN time (not just import time):
        # another test module collected in the same pytest run can have
        # replaced these os.environ values with ITS tempdirs before we run
        # (mirrors test_apply_dream_proposal.py's own rationale).
        self._pin_env("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT))
        self._pin_env("CCGM_DREAMING_DIR", _TMP_DREAMING)
        self._pin_env("HOME", _TMP_HOME)
        adp.proposals_dir().mkdir(parents=True, exist_ok=True)
        # Clean, non-suspended breaker state before EVERY test (see module
        # docstring) -- every call to run_optimistic_integrate() touches
        # this one shared file regardless of slug.
        adp._write_optimistic_state_atomic(adp._default_optimistic_state())

    def _pin_env(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value

        def _restore() -> None:
            if had:
                os.environ[key] = prior
            else:
                os.environ.pop(key, None)

        self.addCleanup(_restore)

    def _write_config(self, overrides: dict | None = None) -> None:
        """Write only the overrides a test cares about -- da.load_config()'s
        own (already-tested, Epic 2) deep-merge fills in every other
        optimistic_integration default."""
        cfg_path = da.dreaming_dir() / "config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"optimistic_integration": overrides or {}}), encoding="utf-8")

    def _seed_learning(self, slug: str, *, content: str = "seed", confidence: int = 8,
                        tags: list[str] | None = None) -> str:
        e = ls.build_entry(type_="pattern", content=content, confidence=confidence, tags=tags or [])
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        return e["id"]

    def _write_day(self, day: str, rows: list[dict]) -> None:
        path = adp.proposals_dir() / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    def _read_day(self, day: str) -> list[dict]:
        return adp._read_jsonl(adp.proposals_dir() / f"{day}.jsonl")

    def _row_by_id(self, day: str, pid: str) -> dict | None:
        for row in self._read_day(day):
            if row.get("id") == pid:
                return row
        return None

    def _status_of(self, day: str, pid: str) -> str | None:
        row = self._row_by_id(day, pid)
        return row.get("status") if row else None

    def _head(self, slug: str, entry_id: str) -> dict | None:
        heads = ls.project_slug(slug, use_snapshot=False)["heads"]
        return next((h for h in heads if h["id"] == entry_id), None)

    def _write_optimistic_state(self, state: dict) -> None:
        adp.optimistic_state_path().parent.mkdir(parents=True, exist_ok=True)
        adp.optimistic_state_path().write_text(json.dumps(state), encoding="utf-8")

    def _read_optimistic_state_file(self) -> dict:
        path = adp.optimistic_state_path()
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_audit(self) -> list[dict]:
        path = adp.apply_audit_path()
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _iso(self, epoch: float) -> str:
        return ls._iso_from_epoch(epoch)  # noqa: SLF001 -- test-only convenience, same as production's own reuse


# ---------------------------------------------------------------------------
# Postures (plan.md §3.3): resolve_posture()-driven behavior end to end.
# ---------------------------------------------------------------------------


class PostureTests(OptimisticEngineTestBase):
    def test_verify_applies_immediately_no_dwell_at_floor(self):
        slug = _unique_slug("verify-immediate")
        self._write_config()
        target_id = self._seed_learning(slug, content="verify target", confidence=5)
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="v1", kind="learning_verify", project=slug,
                                             target_id=target_id, confidence=7)])

        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        self.assertEqual(self._status_of(day, "v1"), "auto_applied")

        head = self._head(slug, target_id)
        self.assertIsNotNone(head)
        self.assertIsNone(head.get("dwell_until"))
        self.assertEqual(head["uses"], 1)

        row = self._row_by_id(day, "v1")
        self.assertEqual(row.get("posture"), "optimistic-immediate")
        self.assertNotIn("dwell_until", row)

    def test_add_applies_with_dwell_at_floor_and_prevalence(self):
        slug = _unique_slug("add-dwell")
        self._write_config({"dwell_hours": 24})
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="a1", kind="learning_add", project=slug,
                                             content="new learning", type_="pattern",
                                             confidence=8, sessions=2)])
        before = time.time()
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        self.assertEqual(self._status_of(day, "a1"), "auto_applied")

        heads = ls.load_all(slug)
        self.assertEqual(len(heads), 1)
        head = heads[0]
        dwell_ts = ls._parse_iso(head["dwell_until"])  # noqa: SLF001
        self.assertGreater(dwell_ts, before + 23 * 3600)
        self.assertLess(dwell_ts, before + 25 * 3600)

        raw_events = adp._raw_op_events(slug)
        add_events = [e for e in raw_events if e.get("op") == "add"]
        self.assertEqual(len(add_events), 1)
        self.assertIs(add_events[0].get("auto"), True)

        row = self._row_by_id(day, "a1")
        self.assertEqual(row.get("posture"), "optimistic-dwell")
        self.assertEqual(row.get("batch_id"), summary["batch_id"])
        self.assertIsNotNone(row.get("dwell_until"))

    def test_contradict_applies_with_mandatory_dwell(self):
        slug = _unique_slug("contradict-dwell")
        self._write_config({"dwell_hours": 12})
        target_id = self._seed_learning(slug, content="to be contradicted", confidence=8)
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="c1", kind="learning_contradict", project=slug,
                                             target_id=target_id, confidence=8)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)

        head = self._head(slug, target_id)
        self.assertIsNotNone(head.get("dwell_until"))
        self.assertEqual(head["contradictions"], 1)

        # §3.2 end-to-end proof: the row is excluded from search() by
        # default while it is dwelling.
        results = ls.search(slug=slug, query="contradicted")
        self.assertNotIn(target_id, [r["id"] for r in results])

    def test_global_add_stays_pending(self):
        self._write_config()
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="g1", kind="learning_add", project=ls.GLOBAL_SLUG,
                                             content="global candidate", type_="pattern",
                                             confidence=10, sessions=5)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(self._status_of(day, "g1"), "pending")


# ---------------------------------------------------------------------------
# Confidence floors.
# ---------------------------------------------------------------------------


class FloorTests(OptimisticEngineTestBase):
    def test_add_below_confidence_floor_stays_pending(self):
        slug = _unique_slug("add-floor")
        self._write_config()  # confidence_floor_content default 8
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="af1", kind="learning_add", project=slug,
                                             content="low conf", type_="pattern",
                                             confidence=7, sessions=5)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(self._status_of(day, "af1"), "pending")

    def test_verify_below_confidence_floor_stays_pending(self):
        slug = _unique_slug("verify-floor")
        self._write_config()  # confidence_floor_verify default 7
        target_id = self._seed_learning(slug)
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="vf1", kind="learning_verify", project=slug,
                                             target_id=target_id, confidence=6)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(self._status_of(day, "vf1"), "pending")


# ---------------------------------------------------------------------------
# Per-slug blast-radius caps (plan.md §3.3).
# ---------------------------------------------------------------------------


class PerSlugCapTests(OptimisticEngineTestBase):
    def test_per_slug_cap_limits_within_one_slug(self):
        slug = _unique_slug("cap-oneslug")
        self._write_config({"max_add_supersede_per_run": 2})
        day = _unique_day()
        rows = [_proposal_row(pid=f"cap{i}", kind="learning_add", project=slug,
                               content=f"content {i}", type_="pattern", confidence=9, sessions=5)
                for i in range(5)]
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 2, summary)
        statuses = [self._status_of(day, f"cap{i}") for i in range(5)]
        self.assertEqual(statuses.count("auto_applied"), 2)
        self.assertEqual(statuses.count("pending"), 3)

    def test_per_slug_cap_is_not_cross_project(self):
        self._write_config({"max_add_supersede_per_run": 2})
        day = _unique_day()
        rows = []
        for i in range(5):
            s = _unique_slug(f"cap-multi-{i}")
            rows.append(_proposal_row(pid=f"mcap{i}", kind="learning_add", project=s,
                                       content=f"content {i}", type_="pattern",
                                       confidence=9, sessions=5))
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 5, summary)
        for i in range(5):
            self.assertEqual(self._status_of(day, f"mcap{i}"), "auto_applied")

    def test_absolute_eviction_cap_dominates(self):
        slug = _unique_slug("evict-abs")
        self._write_config({"max_eviction_absolute": 3, "max_eviction_fraction_per_run": 0.2})
        target_ids = [self._seed_learning(slug, content=f"seed {i}", confidence=8) for i in range(20)]
        day = _unique_day()
        rows = [_proposal_row(pid=f"dep{i}", kind="learning_deprecate", project=slug,
                               target_id=target_ids[i], confidence=9) for i in range(5)]
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)
        # cap = min(3, 0.2 * 20) = min(3, 4.0) = 3 -- the absolute ceiling
        # dominates the fraction, even though 4 > 3 would have allowed one more.
        self.assertEqual(summary["applied"], 3, summary)
        statuses = [self._status_of(day, f"dep{i}") for i in range(5)]
        self.assertEqual(statuses.count("auto_applied"), 3)
        self.assertEqual(statuses.count("pending"), 2)

    def test_fixed_denominator_same_run_adds_do_not_inflate_eviction_cap(self):
        # Numbers chosen so a "recompute live_head_count fresh on every
        # cap check" bug (which self-corrects on the LAST eviction, since
        # each successful eviction lowers the live count right back down)
        # is still distinguishable from the correct fixed-once behavior --
        # a naive test with only 2-3 evictions and a round cap can pass
        # under BOTH the correct and the buggy implementation by
        # coincidence (verified empirically while writing this test: the
        # add inflates the fresh count up, but each eviction's own
        # decrement claws it back down, and the two effects can cancel out
        # at the exact boundary a smaller reproduction checks). With 10
        # seeds, 1 add, 4 evictions, and frac=0.35:
        #   fixed cap  = 0.35 * 10 = 3.5  -- constant all 4 evictions
        #                (k=0,1,2,3 all < 3.5) -> ALL 4 apply.
        #   buggy cap at eviction k = 0.35 * (11 - k) (11 = 10 seeds + the
        #                just-applied add; -k for each PRIOR eviction's own
        #                self-decrement) -- at k=3, buggy cap = 0.35*8=2.8,
        #                and 3 < 2.8 is FALSE -> the 4th eviction is
        #                wrongly blocked under the buggy denominator.
        slug = _unique_slug("fixed-denom")
        self._write_config({
            "max_eviction_absolute": 100, "max_eviction_fraction_per_run": 0.35,
            "max_add_supersede_per_run": 100,
        })
        target_ids = [self._seed_learning(slug, content=f"seed {i}", confidence=8) for i in range(10)]
        day = _unique_day()
        rows = [_proposal_row(pid="fd-add", kind="learning_add", project=slug,
                               content="new one", type_="pattern", confidence=9, sessions=5)]
        for i in range(4):
            rows.append(_proposal_row(pid=f"fd-dep{i}", kind="learning_deprecate", project=slug,
                                       target_id=target_ids[i], confidence=9))
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)

        self.assertEqual(self._status_of(day, "fd-add"), "auto_applied")
        dep_statuses = [self._status_of(day, f"fd-dep{i}") for i in range(4)]
        # Fixed denominator (10, captured before the add landed) yields
        # cap=3.5 for every eviction in this batch -- ALL 4 apply (0,1,2,3
        # are each < 3.5). A same-run-inflated OR self-decrementing fresh
        # recomputation would block the 4th (see arithmetic above).
        self.assertEqual(dep_statuses.count("auto_applied"), 4, summary)
        self.assertEqual(dep_statuses.count("pending"), 0, summary)


# ---------------------------------------------------------------------------
# Batch eviction-concentration anomaly check (plan.md §3.3).
# ---------------------------------------------------------------------------


class BatchAnomalyTests(OptimisticEngineTestBase):
    def test_batch_anomaly_skips_evictions_for_that_slug_only(self):
        slug_a = _unique_slug("anomaly-a")
        slug_b = _unique_slug("anomaly-b")
        self._write_config({
            "batch_anomaly_max_same_tag_fraction": 0.6,
            "max_eviction_absolute": 100, "max_eviction_fraction_per_run": 1.0,
        })
        # slug_a: 5 deprecate candidates, 4/5 (80%) share "shared-tag".
        a_targets = []
        for i in range(5):
            tags = ["shared-tag"] if i < 4 else ["other-tag"]
            a_targets.append(self._seed_learning(slug_a, content=f"a-seed {i}", confidence=8, tags=tags))
        # slug_b: normal, focused batch -- 3 deprecates, each a DIFFERENT tag.
        b_targets = [self._seed_learning(slug_b, content=f"b-seed {i}", confidence=8, tags=[f"tag-{i}"])
                     for i in range(3)]

        day = _unique_day()
        rows = [_proposal_row(pid=f"a-dep{i}", kind="learning_deprecate", project=slug_a,
                               target_id=a_targets[i], confidence=9) for i in range(5)]
        rows += [_proposal_row(pid=f"b-dep{i}", kind="learning_deprecate", project=slug_b,
                                target_id=b_targets[i], confidence=9) for i in range(3)]
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)

        for i in range(5):
            self.assertEqual(self._status_of(day, f"a-dep{i}"), "pending", f"a-dep{i}")
        for i in range(3):
            self.assertEqual(self._status_of(day, f"b-dep{i}"), "auto_applied", f"b-dep{i}")

        self.assertTrue(any(a["slug"] == slug_a for a in summary["anomalies"]), summary)
        self.assertFalse(any(a["slug"] == slug_b for a in summary["anomalies"]), summary)

    def test_single_eviction_proposal_never_flagged_anomalous(self):
        # A batch of size 1 is trivially "100% concentrated" on its own
        # single target -- MIN_EVICTION_BATCH_FOR_ANOMALY_CHECK guards
        # against treating that as an anomaly.
        rows = [{"target_id": "t1"}]
        self.assertFalse(adp._batch_anomaly_fires(rows, {}, {"batch_anomaly_max_same_tag_fraction": 0.6}))

    def test_two_evictions_same_target_flagged_anomalous(self):
        rows = [{"target_id": "t1"}, {"target_id": "t1"}]
        self.assertTrue(adp._batch_anomaly_fires(rows, {}, {"batch_anomaly_max_same_tag_fraction": 0.6}))

    def test_two_evictions_different_targets_different_tags_not_anomalous(self):
        heads_by_id = {"t1": {"tags": ["x"]}, "t2": {"tags": ["y"]}}
        rows = [{"target_id": "t1"}, {"target_id": "t2"}]
        self.assertFalse(adp._batch_anomaly_fires(rows, heads_by_id, {"batch_anomaly_max_same_tag_fraction": 0.6}))


# ---------------------------------------------------------------------------
# Windowed, self-healing circuit breaker (plan.md §3.5).
# ---------------------------------------------------------------------------


class CircuitBreakerTests(OptimisticEngineTestBase):
    def test_breaker_trips_when_two_anomalies_fall_within_window(self):
        self._write_config({
            "circuit_breaker_window_nights": 7, "circuit_breaker_max_anomalies": 2,
            "batch_anomaly_max_same_tag_fraction": 0.5,
        })
        now = time.time()
        self._write_optimistic_state({
            "suspended": False, "suspended_at": None,
            "anomaly_log": [self._iso(now - 1 * 86400)],  # 1 day ago -- within a 7-night window
            "last_run": None,
        })

        slug = _unique_slug("breaker-trip")
        t0 = self._seed_learning(slug, content="s0", confidence=8, tags=["x"])
        t1 = self._seed_learning(slug, content="s1", confidence=8, tags=["x"])
        day = _unique_day()
        self._write_day(day, [
            _proposal_row(pid="bt0", kind="learning_deprecate", project=slug, target_id=t0, confidence=9),
            _proposal_row(pid="bt1", kind="learning_deprecate", project=slug, target_id=t1, confidence=9),
        ])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["circuit_breaker"], "tripped", summary)

        state = self._read_optimistic_state_file()
        self.assertTrue(state["suspended"])
        self.assertIsNotNone(state["suspended_at"])

        audit = self._read_audit()
        self.assertTrue(any(a.get("outcome") == "circuit_breaker_tripped" for a in audit))

    def test_breaker_does_not_trip_when_anomalies_are_outside_window(self):
        self._write_config({
            "circuit_breaker_window_nights": 7, "circuit_breaker_max_anomalies": 2,
            "batch_anomaly_max_same_tag_fraction": 0.5,
        })
        now = time.time()
        self._write_optimistic_state({
            "suspended": False, "suspended_at": None,
            "anomaly_log": [self._iso(now - 20 * 86400)],  # 20 days ago -- OUTSIDE a 7-night window
            "last_run": None,
        })

        slug = _unique_slug("breaker-notrip")
        t0 = self._seed_learning(slug, content="s0", confidence=8, tags=["x"])
        t1 = self._seed_learning(slug, content="s1", confidence=8, tags=["x"])
        day = _unique_day()
        self._write_day(day, [
            _proposal_row(pid="bn0", kind="learning_deprecate", project=slug, target_id=t0, confidence=9),
            _proposal_row(pid="bn1", kind="learning_deprecate", project=slug, target_id=t1, confidence=9),
        ])
        summary = adp.run_optimistic_integrate(day)
        # This run's own batch anomaly still fires (only 1 within the
        # window after the 20-day-old entry ages out) -- below max=2.
        self.assertNotEqual(summary["circuit_breaker"], "tripped", summary)
        state = self._read_optimistic_state_file()
        self.assertFalse(state["suspended"])

    def test_breaker_auto_resumes_after_quiet_period(self):
        self._write_config({"circuit_breaker_auto_resume_nights": 7})
        now = time.time()
        self._write_optimistic_state({
            "suspended": True, "suspended_at": self._iso(now - 8 * 86400),
            "anomaly_log": [self._iso(now - 8 * 86400), self._iso(now - 8.1 * 86400)],
            "last_run": None,
        })
        slug = _unique_slug("breaker-resume")
        target_id = self._seed_learning(slug, confidence=8)
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="ar1", kind="learning_verify", project=slug,
                                             target_id=target_id, confidence=8)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["circuit_breaker"], "auto_resumed", summary)
        self.assertEqual(summary["applied"], 1, summary)  # the resume actually let this batch through

        state = self._read_optimistic_state_file()
        self.assertFalse(state["suspended"])

        audit = self._read_audit()
        self.assertTrue(any(a.get("outcome") == "circuit_breaker_auto_resumed" for a in audit))

    def test_breaker_stays_suspended_before_quiet_period_elapses(self):
        self._write_config({"circuit_breaker_auto_resume_nights": 7})
        now = time.time()
        self._write_optimistic_state({
            "suspended": True, "suspended_at": self._iso(now - 1 * 86400),  # only 1 quiet day, not 7
            "anomaly_log": [],
            "last_run": None,
        })
        slug = _unique_slug("breaker-still-suspended")
        target_id = self._seed_learning(slug, confidence=8)
        day = _unique_day()
        self._write_day(day, [_proposal_row(pid="ss1", kind="learning_verify", project=slug,
                                             target_id=target_id, confidence=8)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["circuit_breaker"], "suspended", summary)
        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(self._status_of(day, "ss1"), "pending")

    def test_optimistic_resume_forces_immediate_reenable(self):
        now = time.time()
        self._write_optimistic_state({
            "suspended": True, "suspended_at": self._iso(now),  # just tripped -- would NOT auto-resume
            "anomaly_log": [self._iso(now)],
            "last_run": None,
        })
        result = adp.optimistic_resume()
        self.assertTrue(result["ok"])
        self.assertTrue(result["was_suspended"])

        state = self._read_optimistic_state_file()
        self.assertFalse(state["suspended"])
        self.assertIsNone(state["suspended_at"])

        audit = self._read_audit()
        self.assertTrue(any(a.get("outcome") == "circuit_breaker_manual_resume" for a in audit))

    def test_corrupt_state_file_fails_closed_to_suspended(self):
        adp.optimistic_state_path().parent.mkdir(parents=True, exist_ok=True)
        adp.optimistic_state_path().write_text("{not valid json", encoding="utf-8")
        state = adp._read_optimistic_state()
        self.assertTrue(state["suspended"])
        self.assertIsNotNone(state["suspended_at"])


# ---------------------------------------------------------------------------
# Cross-night accumulation signal (plan.md §3.8).
# ---------------------------------------------------------------------------


class CrossNightSignalTests(OptimisticEngineTestBase):
    def test_cross_night_rate_signal_records_anomaly_when_exceeded(self):
        self._write_config({"rolling_add_rate_window_nights": 14, "rolling_add_rate_max": 2,
                             "max_add_supersede_per_run": 100})
        slug = _unique_slug("rate-signal")
        day = _unique_day()
        rows = [_proposal_row(pid=f"rate{i}", kind="learning_add", project=slug,
                               content=f"c{i}", type_="pattern", confidence=9, sessions=5)
                for i in range(3)]
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 3, summary)
        self.assertTrue(any(a["kind"] == "rolling_add_rate_exceeded" for a in summary["anomalies"]), summary)

    def test_cross_night_rate_signal_not_recorded_when_under_threshold(self):
        self._write_config({"rolling_add_rate_window_nights": 14, "rolling_add_rate_max": 10,
                             "max_add_supersede_per_run": 100})
        slug = _unique_slug("rate-signal-ok")
        day = _unique_day()
        rows = [_proposal_row(pid=f"rateok{i}", kind="learning_add", project=slug,
                               content=f"c{i}", type_="pattern", confidence=9, sessions=5)
                for i in range(3)]
        self._write_day(day, rows)
        summary = adp.run_optimistic_integrate(day)
        self.assertFalse(any(a["kind"] == "rolling_add_rate_exceeded" for a in summary["anomalies"]), summary)


# ---------------------------------------------------------------------------
# Human-race lock (adrev-opt-011): a concurrent run_optimistic_integrate()
# and a human apply_proposal() accept on the SAME pending id must never
# both invoke the handler. Mirrors test-dream-apply.sh's own white-box
# monkeypatch technique for the analogous pre-Epic-3 guarantee.
# ---------------------------------------------------------------------------


class HumanRaceLockTests(OptimisticEngineTestBase):
    def test_concurrent_integrate_and_accept_never_double_apply(self):
        slug = _unique_slug("race-lock")
        self._write_config()
        target_id = self._seed_learning(slug, confidence=8)
        day = _unique_day()
        pid = "race1"
        self._write_day(day, [_proposal_row(pid=pid, kind="learning_verify", project=slug,
                                             target_id=target_id, confidence=8)])

        invocations = {"n": 0}
        counter_lock = threading.Lock()
        original = adp._apply_counter_op

        def slow_apply_counter_op(row, op, *, auto=False, dwell_hours=None):
            with counter_lock:
                invocations["n"] += 1
            time.sleep(0.4)  # widen the race window deterministically
            return original(row, op, auto=auto, dwell_hours=dwell_hours)

        adp._apply_counter_op = slow_apply_counter_op
        self.addCleanup(lambda: setattr(adp, "_apply_counter_op", original))

        results: list = [None, None]
        barrier = threading.Barrier(2)

        def worker_integrate():
            barrier.wait()
            results[0] = adp.run_optimistic_integrate(day)

        def worker_accept():
            barrier.wait()
            results[1] = adp.apply_proposal(pid, method="human_accept", reviewed_by="tester")

        t1 = threading.Thread(target=worker_integrate)
        t2 = threading.Thread(target=worker_accept)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertFalse(t1.is_alive() or t2.is_alive(), "race threads did not complete -- suspected deadlock")
        self.assertEqual(invocations["n"], 1, "handler invoked exactly once across both paths")

        integrate_summary, accept_result = results
        applied_via_integrate = bool(integrate_summary) and integrate_summary.get("applied") == 1
        applied_via_accept = bool(accept_result) and accept_result.get("ok")
        self.assertEqual(int(applied_via_integrate) + int(applied_via_accept), 1,
                          f"exactly one path should have applied: {results}")
        self.assertIn(self._status_of(day, pid), ("auto_applied", "accepted"))


# ---------------------------------------------------------------------------
# Transaction & consistency model (adrev-opt-011/012/013/014).
# ---------------------------------------------------------------------------


class TransactionModelTests(OptimisticEngineTestBase):
    def _init_learnings_git(self) -> None:
        sync_bin = str(HERE.parent.parent / "self-improving" / "bin" / "ccgm-learnings-sync")
        subprocess.run([sys.executable, sync_bin, "init"], check=True, capture_output=True, text=True)

    def _git_log_subjects(self) -> list[str]:
        proc = subprocess.run(
            ["git", "-C", str(ls.LEARNINGS_ROOT), "log", "--format=%s"],
            check=True, capture_output=True, text=True,
        )
        return proc.stdout.splitlines()

    def test_suppressed_autocommit_overrides_ambient_env_for_its_duration(self):
        self._pin_env("CCGM_LEARNINGS_AUTOCOMMIT", "true")
        self.assertEqual(os.environ.get("CCGM_LEARNINGS_AUTOCOMMIT"), "true")
        with adp._suppressed_autocommit():
            self.assertEqual(os.environ.get("CCGM_LEARNINGS_AUTOCOMMIT"), "false")
        self.assertEqual(os.environ.get("CCGM_LEARNINGS_AUTOCOMMIT"), "true")  # restored

    def test_batch_produces_exactly_one_commit_tagged_with_batch_id(self):
        self._init_learnings_git()
        slug = _unique_slug("txn-onecommit")
        self._write_config({"max_add_supersede_per_run": 100})
        day = _unique_day()
        rows = [_proposal_row(pid=f"tx{i}", kind="learning_add", project=slug,
                               content=f"content {i}", type_="pattern", confidence=9, sessions=5)
                for i in range(4)]
        self._write_day(day, rows)

        before_log = self._git_log_subjects()
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 4, summary)
        self.assertIsNotNone(summary.get("commit"))
        self.assertTrue(summary["commit"].get("ok"), summary["commit"])

        after_log = self._git_log_subjects()
        new_commits = after_log[: len(after_log) - len(before_log)]
        self.assertEqual(len(new_commits), 1, after_log)
        self.assertIn(summary["batch_id"], new_commits[0])

    def test_force_day_rerun_of_integrated_night_is_idempotent(self):
        self._init_learnings_git()
        slug = _unique_slug("txn-idempotent")
        self._write_config({"max_add_supersede_per_run": 100})
        day = _unique_day()
        rows = [_proposal_row(pid=f"idem{i}", kind="learning_add", project=slug,
                               content=f"content {i}", type_="pattern", confidence=9, sessions=5)
                for i in range(3)]
        self._write_day(day, rows)

        first = adp.run_optimistic_integrate(day)
        self.assertEqual(first["applied"], 3, first)

        log_after_first = self._git_log_subjects()
        second = adp.run_optimistic_integrate(day)  # simulates a --force-day re-run
        self.assertEqual(second["applied"], 0, second)
        self.assertEqual(second["evaluated"], 3, second)  # rows still read
        self.assertIsNone(second.get("commit"))  # never even attempted a commit

        log_after_second = self._git_log_subjects()
        self.assertEqual(log_after_first, log_after_second, "no new commit on an idempotent re-run")

    def test_batch_commit_does_not_deadlock_with_per_proposal_lock(self):
        self._init_learnings_git()
        slug = _unique_slug("txn-deadlock")
        self._write_config({"max_add_supersede_per_run": 100})
        day = _unique_day()
        rows = [_proposal_row(pid=f"dl{i}", kind="learning_add", project=slug,
                               content=f"content {i}", type_="pattern", confidence=9, sessions=5)
                for i in range(6)]
        self._write_day(day, rows)

        result_holder: dict = {}

        def _run():
            result_holder["summary"] = adp.run_optimistic_integrate(day)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=15)
        self.assertFalse(t.is_alive(), "run_optimistic_integrate hung -- suspected lock self-deadlock")
        self.assertEqual(result_holder.get("summary", {}).get("applied"), 6)

    def test_state_file_write_is_atomic_no_tmp_left_behind(self):
        state = {
            "suspended": True, "suspended_at": "2026-01-01T00:00:00.000Z",
            "anomaly_log": ["2026-01-01T00:00:00.000Z"], "last_run": "2026-01-01T00:00:00.000Z",
        }
        adp._write_optimistic_state_atomic(state)
        path = adp.optimistic_state_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        self.assertFalse(tmp_path.exists(), "temp file should never survive an atomic write")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, state)


# ---------------------------------------------------------------------------
# Malformed-input defense (a proposal row's own gating logic must never
# abort the rest of the batch).
# ---------------------------------------------------------------------------


class MalformedInputTests(OptimisticEngineTestBase):
    def test_missing_proposals_file_returns_empty_summary(self):
        summary = adp.run_optimistic_integrate(_unique_day())
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(summary["evaluated"], 0)

    def test_malformed_project_field_is_skipped_not_crashed(self):
        self._write_config()
        day = _unique_day()
        row = _proposal_row(pid="bad1", kind="learning_add", project="placeholder",
                             content="x", type_="pattern", confidence=9, sessions=5)
        row["project"] = None
        self._write_day(day, [row])
        summary = adp.run_optimistic_integrate(day)  # must not raise
        self.assertEqual(summary["applied"], 0, summary)
        self.assertEqual(self._status_of(day, "bad1"), "pending")


# ---------------------------------------------------------------------------
# Weekly, cost-capped eval refresh (fix (b) for adrev-opt-001).
#
# Each test here gets its OWN isolated CCGM_DREAMING_DIR (on top of the
# base class's env pins) because _latest_eval_results_age_days() and the
# cost ledger are dreaming-dir-WIDE, not proposal-scoped -- sharing the
# file-level dreaming dir across these tests would let one test's results
# file or ledger spend affect another test's freshness/cost-cap check.
# ---------------------------------------------------------------------------


class EvalRefreshTests(OptimisticEngineTestBase):
    def setUp(self) -> None:
        super().setUp()
        fresh_dreaming = tempfile.mkdtemp(prefix="ccgm-dreaming-test-optengine-evalrefresh-")
        self._pin_env("CCGM_DREAMING_DIR", fresh_dreaming)

    def test_eval_refresh_skips_when_results_too_fresh(self):
        self._write_config({"eval_refresh_min_age_days": 7})
        evals_dir = da.dreaming_dir() / "evals"
        evals_dir.mkdir(parents=True, exist_ok=True)
        (evals_dir / "2026-05-01.jsonl").write_text("{}\n", encoding="utf-8")  # mtime = now
        cfg = da.load_config()
        should_run, reason = adp._eval_refresh_preconditions(_unique_day(), cfg)
        self.assertFalse(should_run)
        self.assertIn("old", reason)

    def test_eval_refresh_skips_when_no_api_key(self):
        self._write_config({"eval_refresh_min_age_days": 7})
        prior = os.environ.pop("ANTHROPIC_API_KEY", None)
        self.addCleanup(lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", prior) if prior else None)
        cfg = da.load_config()
        should_run, reason = adp._eval_refresh_preconditions(_unique_day(), cfg)
        self.assertFalse(should_run)
        self.assertIn("ANTHROPIC_API_KEY", reason)

    def test_eval_refresh_skips_when_cost_cap_exhausted(self):
        self._write_config({"eval_refresh_min_age_days": 7, "eval_refresh_cost_cap_usd": 1.0})
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        self.addCleanup(lambda: os.environ.pop("ANTHROPIC_API_KEY", None))
        day = _unique_day()
        adp.da._append_cost(  # noqa: SLF001 -- test-only direct ledger seed
            adp.da.cost_log_path(), day, 0, 0, 1.50, adp.EVAL_REFRESH_COST_LABEL,
        )
        cfg = da.load_config()
        should_run, reason = adp._eval_refresh_preconditions(day, cfg)
        self.assertFalse(should_run)
        self.assertIn("exhausted", reason)

    def test_eval_refresh_preconditions_pass_when_all_clear(self):
        self._write_config({"eval_refresh_min_age_days": 7, "eval_refresh_cost_cap_usd": 5.0})
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        self.addCleanup(lambda: os.environ.pop("ANTHROPIC_API_KEY", None))
        cfg = da.load_config()
        should_run, reason = adp._eval_refresh_preconditions(_unique_day(), cfg)
        self.assertTrue(should_run, reason)

    def _write_fake_eval_refresh_script(self, *, cost_usd: float = 0.42, exit_code: int = 0) -> Path:
        """A tiny, self-contained fake standing in for memory_eval.py's
        --date/results-file contract -- written to a fresh tempdir at test
        run time (not a committed fixture file), so this test file stays
        fully offline and the only new committed file remains this one."""
        script_dir = Path(tempfile.mkdtemp(prefix="ccgm-fake-eval-refresh-"))
        script_path = script_dir / "fake_memory_eval.py"
        script_path.write_text(
            "import argparse, json, os, sys\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--date', required=True)\n"
            "args, _ = p.parse_known_args()\n"
            f"row = {{'id': 'fake-task', 'bucket': 'high_value', 'cost_usd': {cost_usd}}}\n"
            "evals_dir = os.path.join(os.environ['CCGM_DREAMING_DIR'], 'evals')\n"
            "os.makedirs(evals_dir, exist_ok=True)\n"
            "with open(os.path.join(evals_dir, args.date + '.jsonl'), 'w') as fh:\n"
            "    fh.write(json.dumps(row) + chr(10))\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )
        return script_path

    def test_run_eval_refresh_end_to_end_with_fake_script(self):
        self._write_config({"eval_refresh_min_age_days": 7, "eval_refresh_cost_cap_usd": 5.0})
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        self.addCleanup(lambda: os.environ.pop("ANTHROPIC_API_KEY", None))
        script = self._write_fake_eval_refresh_script(cost_usd=0.42)
        self._pin_env("CCGM_DREAMING_EVAL_REFRESH_SCRIPT", str(script))

        day = _unique_day()
        summary = adp.run_eval_refresh(day)
        self.assertTrue(summary["ran"], summary)
        self.assertAlmostEqual(summary["cost_usd"], 0.42, places=6)

        spent = adp._read_cost_spent_today_by_label(da.cost_log_path(), day, adp.EVAL_REFRESH_COST_LABEL)
        self.assertAlmostEqual(spent, 0.42, places=6)

    def test_run_eval_refresh_skips_without_invoking_script_when_preconditions_fail(self):
        self._write_config({"eval_refresh_min_age_days": 7, "eval_refresh_cost_cap_usd": 5.0})
        prior = os.environ.pop("ANTHROPIC_API_KEY", None)
        self.addCleanup(lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", prior) if prior else None)
        # A script that would raise if ever invoked -- proves the
        # precondition gate short-circuits before any subprocess call.
        script_dir = Path(tempfile.mkdtemp(prefix="ccgm-fake-eval-refresh-must-not-run-"))
        script_path = script_dir / "must_not_run.py"
        script_path.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        self._pin_env("CCGM_DREAMING_EVAL_REFRESH_SCRIPT", str(script_path))

        summary = adp.run_eval_refresh(_unique_day())
        self.assertFalse(summary["ran"])
        self.assertIn("ANTHROPIC_API_KEY", summary["reason"])
        self.assertNotIn("exit_code", summary)


if __name__ == "__main__":
    unittest.main()
