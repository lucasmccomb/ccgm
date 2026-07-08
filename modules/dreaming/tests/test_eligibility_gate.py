#!/usr/bin/env python3
"""
Tests for the composite-eligibility gate integration (composite-eligibility
plan.md Epic E3): apply_dream_proposal.py's enabled-mode waterfall inside
_process_one_proposal(), gather_eligibility_signals() + the per-batch
SessionVerification cache (§3.4), the audit breakdown (§3.7), the near-
duplicate-supersede flag, and the eligibility-dry-run CLI.

Runs in isolation: CCGM_LEARNINGS_DIR + CCGM_DREAMING_DIR + CCGM_CLAUDE_PROJECTS_DIR
+ HOME are redirected to tempdirs BEFORE import (module-level constants freeze
at import time -- learnings_store.LEARNINGS_ROOT and CLAUDE_PROJECTS_ROOT; #793).
No network, no ANTHROPIC_API_KEY, never the real store/dreaming dir/transcripts.
Every transcript is synthetic (transcript_fixtures.py; no real path/username).

Run with: python3 -m pytest modules/dreaming/tests/test_eligibility_gate.py -q
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lib"))

sys.modules.pop("learnings_store", None)
sys.modules.pop("dream_analyze", None)
sys.modules.pop("apply_dream_proposal", None)
sys.modules.pop("transcript_miner", None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-elig-gate-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-elig-gate-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-elig-gate-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-elig-gate-home-")
_ORIG = {
    "CCGM_LEARNINGS_DIR": os.environ.get("CCGM_LEARNINGS_DIR"),
    "CCGM_DREAMING_DIR": os.environ.get("CCGM_DREAMING_DIR"),
    "CCGM_CLAUDE_PROJECTS_DIR": os.environ.get("CCGM_CLAUDE_PROJECTS_DIR"),
    "HOME": os.environ.get("HOME"),
}
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
os.environ["CCGM_CLAUDE_PROJECTS_DIR"] = _TMP_PROJECTS
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import eligibility as elig  # noqa: E402
import learnings_store as ls  # noqa: E402
import transcript_fixtures as tf  # noqa: E402


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


_LONG_SENTENCE = (
    "The Edit tool does not follow symlinks so read the workspace path first "
    "before editing the file"
)


def _iso(dt: datetime) -> str:
    return tf.iso(dt)


class GateTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._pin("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT))
        self._pin("CCGM_DREAMING_DIR", _TMP_DREAMING)
        self._pin("CCGM_CLAUDE_PROJECTS_DIR", str(ls.CLAUDE_PROJECTS_ROOT))
        self._pin("HOME", _TMP_HOME)
        adp.proposals_dir().mkdir(parents=True, exist_ok=True)
        adp._write_optimistic_state_atomic(adp._default_optimistic_state())

    def _pin(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.__setitem__(key, prior) if had else os.environ.pop(key, None))

    # ---- fixtures -------------------------------------------------------

    def _slug(self, label: str = "elig") -> str:
        return f"{label}-{uuid.uuid4().hex[:8]}"

    def _cwd_for(self, slug: str) -> str:
        # A guaranteed-nonexistent absolute path whose basename IS the slug, so
        # detect_project_slug() falls through git resolution to basename==slug.
        return f"/synthetic-nonexistent/code/{slug}"

    def _write_session(
        self, session_id: str, *, slug: str, turns: list, days_ago: float = 1.0,
    ) -> str:
        base = datetime.now(timezone.utc) - timedelta(days=days_ago)
        path = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}" / f"{session_id}.jsonl"
        tf.write_transcript(
            path, turns, session_id=session_id, cwd=self._cwd_for(slug),
            base_ts=_iso(base),
        )
        return str(path)

    def _corroborating_turns(self, *, correction: bool, sentence: str = _LONG_SENTENCE) -> list:
        turns: list = []
        if correction:
            turns.extend(tf.correction_sequence(
                request="Please reformat the config file.",
                correction="No, that's wrong, revert that change to the config entirely.",
            ))
        turns.append(tf.user_turn(sentence, human=True))
        return turns

    def _elig_cfg(self, **overrides) -> dict:
        cfg = elig.default_eligibility()
        cfg["enabled"] = True
        cfg.update(overrides)
        return cfg

    def _optimistic(self, elig_cfg: dict | None = None, **top) -> dict:
        cfg = {"confidence_floor_content": 8, "add_min_sessions": 2}
        cfg.update(top)
        cfg["eligibility"] = elig_cfg if elig_cfg is not None else self._elig_cfg()
        return cfg

    def _add_row(self, *, pid: str, slug: str, session_id: str, excerpt: str,
                 content: str = _LONG_SENTENCE, confidence: int = 6, type_: str = "pitfall",
                 extra_evidence: list | None = None, **extra) -> dict:
        evidence = [{"session_id": session_id, "excerpt": excerpt}]
        if extra_evidence:
            evidence.extend(extra_evidence)
        row = {
            "id": pid, "kind": "learning_add", "project": slug, "target_id": None,
            "content": content, "type": type_, "confidence": confidence,
            "prevalence": {"sessions": 2, "agents": 1}, "evidence": evidence,
            "justification": "test", "fingerprint": f"fp-{pid}",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        row.update(extra)
        return row

    def _write_config(self, optimistic: dict) -> None:
        p = da.dreaming_dir() / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"optimistic_integration": optimistic}), encoding="utf-8")

    def _write_day(self, day: str, rows: list) -> None:
        path = adp.proposals_dir() / f"{day}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")

    def _day(self) -> str:
        return f"2026-test-{uuid.uuid4().hex[:8]}"

    def _pid(self, label: str = "p") -> str:
        # Globally unique: find_proposal() scans EVERY proposals/*.jsonl file, so
        # a pid reused across tests would resolve to an earlier test's already-
        # applied row and be refused. Real proposal ids are uuids; mirror that.
        return f"{label}-{uuid.uuid4().hex[:10]}"

    def _read_day(self, day: str) -> list:
        return adp._read_jsonl(adp.proposals_dir() / f"{day}.jsonl")

    def _status(self, day: str, pid: str) -> str | None:
        for r in self._read_day(day):
            if r.get("id") == pid:
                return r.get("status")
        return None

    def _audit(self) -> list:
        path = adp.apply_audit_path()
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _elig_audit_for(self, pid: str) -> dict | None:
        # LAST match: the shared apply-audit.jsonl accumulates across tests, so
        # a pid reused by an earlier test would otherwise shadow this test's
        # record. Reading immediately after this test's run, the last-written
        # eligibility record for `pid` is ours.
        found = None
        for rec in self._audit():
            if rec.get("audit_kind") == "eligibility" and rec.get("proposal_id") == pid:
                found = rec
        return found

    def _eval(self, row: dict, *, slug: str, heads: dict | None = None,
              elig_cfg: dict | None = None, optimistic: dict | None = None):
        ec = elig_cfg if elig_cfg is not None else self._elig_cfg()
        opt = optimistic if optimistic is not None else self._optimistic(ec)
        return adp.evaluate_proposal_eligibility(
            row, slug=slug, cache={}, heads=heads or {}, cfg=opt, elig_cfg=ec,
        )


# ---------------------------------------------------------------------------
# §3.4 three-part session verification matrix.
# ---------------------------------------------------------------------------


class SessionVerificationMatrixTests(GateTestBase):
    def test_resolvable_corroborated_counts(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE)
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])

    def test_unresolvable_session_not_counted(self):
        slug = self._slug()
        row = self._add_row(pid="a1", slug=slug, session_id="sess-does-not-exist", excerpt=_LONG_SENTENCE)
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [])
        self.assertIn("sess-does-not-exist", ev.unresolved_session_ids)

    def test_slug_mismatch_not_counted(self):
        slug = self._slug()
        other = self._slug("other")
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        # transcript cwd basename == `other`, but row.project == slug -> mismatch
        self._write_session(sid, slug=other, turns=self._corroborating_turns(correction=False))
        row = self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE)
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [])

    def test_garbage_excerpt_not_counted(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(pid="a1", slug=slug, session_id=sid,
                            excerpt="completely unrelated zzzqqq wubwub content nowhere present")
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [])

    def test_paraphrased_excerpt_counted(self):
        # adrev-001: a paraphrased excerpt above excerpt_match_min still counts.
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid,
            excerpt="The Edit tool doesn't follow symlinks, so read the workspace path first before editing the file",
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])

    def test_neutralized_wrapper_excerpt_matches_raw(self):
        # adrev-001: normalization strips [neutralized] wrappers before compare.
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid,
            excerpt="[neutralized]The Edit tool[/neutralized] does not follow symlinks so read the "
                    "workspace path first before editing the file",
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])

    def test_redaction_placeholder_excerpt_still_counts(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        raw = ("the deploy key ghp_ABCD1234SECRET must be set in the settings file before running "
               "the migration script now")
        self._write_session(sid, slug=slug, turns=[tf.user_turn(raw, human=True)])
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid, content=raw,
            excerpt="the deploy key [REDACTED:github_token] must be set in the settings file before "
                    "running the migration script now",
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])

    def test_duplicate_citation_counts_once(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE,
            extra_evidence=[{"session_id": sid, "excerpt": _LONG_SENTENCE}],
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])
        self.assertEqual(len(ev.verified_session_ids), 1)

    def test_null_session_excluded(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE,
            extra_evidence=[{"session_id": None, "excerpt": _LONG_SENTENCE},
                            {"session_id": "", "excerpt": _LONG_SENTENCE}],
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])
        self.assertNotIn(None, ev.cited_session_ids)
        self.assertNotIn("", ev.cited_session_ids)

    def test_oversized_transcript_counts_but_tier_inferred_recency_zero(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        # A human correction WOULD mint user-corrected, but the tiny byte cap
        # forces tier inferred + recency 0 while the excerpt check still streams.
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        ec = self._elig_cfg(max_transcript_bytes=1_000_000)  # config floor
        # Force "oversized" by reporting a file size far above the cap (config
        # validation forbids <1MB caps, so we cannot shrink the cap itself).
        row = self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE)
        with mock.patch.object(adp.os.path, "getsize", return_value=10 ** 9):
            bundle, _ = adp.gather_eligibility_signals(row, slug=slug, cache={}, heads={}, elig_cfg=ec)
        # Excerpt-verified session STILL counts (the check streams), but tier is
        # forced inferred and recency 0 (no timestamp read) -- fail toward weakest.
        self.assertEqual(bundle.verified_sessions, 1)
        self.assertEqual(bundle.evidence_tier, "inferred")
        self.assertIsNone(bundle.newest_evidence_age_days)


# ---------------------------------------------------------------------------
# Guard-(ii) two-sided reconciliation (adrev3-002): one test, both arms.
# ---------------------------------------------------------------------------


class GuardIITwoSidedTests(GateTestBase):
    def test_short_common_rejected_and_redacted_legit_accepted(self):
        slug = self._slug()
        # Arm (a): a short common-token excerpt (2 content tokens) that the LARGE
        # transcript literally CONTAINS -> similarity would clear, but guard (ii)
        # requires >= 3 distinct content tokens, so it is rejected (coincidence
        # prevented, size-independent).
        big_sid = f"sess-big-{uuid.uuid4().hex[:6]}"
        big_line = ("the file was changed here today and then again after that " * 200) + "the file was changed"
        self._write_session(big_sid, slug=slug, turns=[tf.user_turn(big_line, human=True)])
        short_row = self._add_row(pid="short", slug=slug, session_id=big_sid,
                                  content="the file was changed", excerpt="the file was changed")
        short_ev = self._eval(short_row, slug=slug)
        self.assertEqual(short_ev.verified_session_ids, [],
                         "short common-token excerpt must be rejected by guard (ii)")

        # Arm (b): a heavily-redacted BUT substantial legitimate excerpt is
        # accepted -- placeholders are excluded from guard (ii)'s denominator.
        red_sid = f"sess-red-{uuid.uuid4().hex[:6]}"
        raw = ("the production deploy key ghp_TOPSECRET7788 must be exported into the settings file "
               "and the migration script before the nightly build can run")
        self._write_session(red_sid, slug=slug, turns=[tf.user_turn(raw, human=True)])
        red_row = self._add_row(
            pid="red", slug=slug, session_id=red_sid, content=raw,
            excerpt="the production deploy key [REDACTED:github_token] must be exported into the "
                    "settings file and the migration script before the nightly build can run",
        )
        red_ev = self._eval(red_row, slug=slug)
        self.assertEqual(red_ev.verified_session_ids, [red_sid],
                         "heavily-redacted legitimate excerpt must be accepted (adrev-001 preserved)")


# ---------------------------------------------------------------------------
# Tier re-mining (both directions) + spoofing.
# ---------------------------------------------------------------------------


class TierTests(GateTestBase):
    def test_human_origin_correction_mints_user_corrected(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        ev = self._eval(self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE), slug=slug)
        self.assertEqual(ev.evidence_tier, "user-corrected")
        self.assertIsNotNone(ev.tier_source)
        self.assertEqual(ev.tier_source.get("origin_kind"), "human")

    def test_tool_result_only_correction_stays_inferred(self):
        # sec-C1: a negation phrase in a NON-human (tool_result) turn is not a
        # correction (E2's human-origin filter), so tier stays inferred.
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        turns = [
            tf.user_turn("Please reformat the config file.", human=True),
            tf.assistant_turn("Working.", tool_uses=[{"id": "t1", "name": "Bash", "input": {"command": "x"}}]),
            tf.friction_turn(tool_use_id="t1", content="that's wrong, revert that entirely", exit_code=1),
            tf.user_turn(_LONG_SENTENCE, human=True),
        ]
        self._write_session(sid, slug=slug, turns=turns)
        ev = self._eval(self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE), slug=slug)
        self.assertEqual(ev.evidence_tier, "inferred")

    def test_forged_stamped_fields_ignored_skipped_origin(self):
        # arch-C3: a row carrying a forged evidence_tier + stamped_signals but a
        # CORRECTION-FREE transcript is scored on the freshly-computed tier
        # (inferred); a single inferred session < add_min_sessions -> skipped_origin.
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE, confidence=6,
            evidence_tier="user-corrected",
            stamped_signals={"prevalence": 9, "recency": 1.0},
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.evidence_tier, "inferred")
        self.assertEqual(ev.decision.outcome, "skipped_origin")
        self.assertFalse(ev.decision.eligible)


# ---------------------------------------------------------------------------
# Waterfall routing + the disabled-mode spy (eligibility never called).
# ---------------------------------------------------------------------------


class WaterfallRoutingTests(GateTestBase):
    def test_disabled_mode_never_calls_eligibility(self):
        slug = self._slug()
        self._write_config({"eligibility": {"enabled": False}})
        day = self._day()
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id="sess-x",
                                            excerpt=_LONG_SENTENCE, confidence=8)])
        with mock.patch.object(adp.eligibility, "evaluate_eligibility",
                               wraps=adp.eligibility.evaluate_eligibility) as spy:
            adp.run_optimistic_integrate(day)
        self.assertEqual(spy.call_count, 0, "eligibility must not be called on the disabled/legacy path")

    def test_enabled_non_content_kind_takes_legacy_path(self):
        slug = self._slug()
        # seed a target to verify
        e = ls.build_entry(type_="pattern", content="verify target", confidence=5)
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        self._write_day(day, [{
            "id": "v1", "kind": "learning_verify", "project": slug, "target_id": e["id"],
            "content": None, "type": None, "confidence": 8,
            "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": "sess-x", "excerpt": "x"}],
            "justification": "t", "fingerprint": "fp-v1",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }])
        with mock.patch.object(adp.eligibility, "evaluate_eligibility",
                               wraps=adp.eligibility.evaluate_eligibility) as spy:
            summary = adp.run_optimistic_integrate(day)
        self.assertEqual(spy.call_count, 0, "verify must not route through the composite")
        self.assertEqual(summary["applied"], 1)

    def test_enabled_add_routes_through_composite(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        pid = self._pid("add")
        self._write_day(day, [self._add_row(pid=pid, slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6)])
        with mock.patch.object(adp.eligibility, "evaluate_eligibility",
                               wraps=adp.eligibility.evaluate_eligibility) as spy:
            summary = adp.run_optimistic_integrate(day)
        self.assertGreaterEqual(spy.call_count, 1)
        self.assertEqual(summary["applied"], 1)
        self.assertEqual(self._status(day, pid), "auto_applied")


# ---------------------------------------------------------------------------
# Origin gate + composite outcomes end-to-end (through run_optimistic_integrate).
# ---------------------------------------------------------------------------


class OutcomeTests(GateTestBase):
    def test_inferred_single_session_skipped_origin_stays_pending(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(self._status(day, "a1"), "pending")
        rec = self._elig_audit_for("a1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["outcome"], "skipped_origin")

    def test_user_corrected_conf6_eligible_composite(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True), days_ago=1)
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        pid = self._pid("add")
        self._write_day(day, [self._add_row(pid=pid, slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["outcome"], "eligible")
        self.assertEqual(rec["decision_basis"], "composite")

    def test_static_floor_below_min_skipped_floor_no_io(self):
        slug = self._slug()
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        # conf 4 < static_floor 5 -> skipped_floor without any gather I/O.
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id="sess-none",
                                            excerpt=_LONG_SENTENCE, confidence=4)])
        with mock.patch.object(adp, "gather_eligibility_signals",
                               side_effect=AssertionError("gather must not run below static floor")):
            summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0)
        rec = self._elig_audit_for("a1")
        self.assertEqual(rec["outcome"], "skipped_floor")

    def test_conf8_multi_session_legacy_escape(self):
        slug = self._slug()
        s1, s2 = f"sess-{uuid.uuid4().hex[:6]}", f"sess-{uuid.uuid4().hex[:6]}"
        for s in (s1, s2):
            self._write_session(s, slug=slug, turns=self._corroborating_turns(correction=False))
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        pid = self._pid("add")
        row = self._add_row(pid=pid, slug=slug, session_id=s1, excerpt=_LONG_SENTENCE, confidence=8,
                            extra_evidence=[{"session_id": s2, "excerpt": _LONG_SENTENCE}])
        self._write_day(day, [row])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        rec = self._elig_audit_for(pid)
        self.assertEqual(rec["decision_basis"], "legacy_floor")


# ---------------------------------------------------------------------------
# Audit completeness + pending readback (§3.7).
# ---------------------------------------------------------------------------


class AuditTests(GateTestBase):
    def test_every_outcome_carries_full_breakdown(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True), days_ago=1)
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6, type_="pitfall")])
        adp.run_optimistic_integrate(day)
        rec = self._elig_audit_for("a1")
        for field in ("outcome", "decision_basis", "score", "threshold", "margin",
                      "signals", "weakest_signal", "verified_sessions", "evidence_tier",
                      "unresolved_session_ids", "type"):
            self.assertIn(field, rec, field)
        self.assertEqual(set(rec["signals"].keys()), {"confidence", "prevalence", "recency", "novelty"})
        self.assertEqual(rec["type"], "pitfall")
        self.assertNotIn("ok", rec, "eligibility audit must not carry an ok field")

    def test_skipped_composite_records_margin_and_weakest(self):
        # A conf-5, 2-session, stale-evidence inferred add fails the composite.
        slug = self._slug()
        s1, s2 = f"sess-{uuid.uuid4().hex[:6]}", f"sess-{uuid.uuid4().hex[:6]}"
        for s in (s1, s2):
            self._write_session(s, slug=slug, turns=self._corroborating_turns(correction=False), days_ago=120)
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        row = self._add_row(pid="a1", slug=slug, session_id=s1, excerpt=_LONG_SENTENCE, confidence=5,
                            extra_evidence=[{"session_id": s2, "excerpt": _LONG_SENTENCE}])
        self._write_day(day, [row])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(self._status(day, "a1"), "pending")
        rec = self._elig_audit_for("a1")
        self.assertEqual(rec["outcome"], "skipped_composite")
        self.assertIsNotNone(rec["margin"])
        self.assertIn(rec["weakest_signal"], {"confidence", "prevalence", "recency", "novelty"})


# ---------------------------------------------------------------------------
# Per-batch cache: one session cited by many proposals is built once.
# ---------------------------------------------------------------------------


class CacheTests(GateTestBase):
    def test_shared_session_built_once(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        rows = [self._add_row(pid=f"a{i}", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE,
                              content=f"{_LONG_SENTENCE} variant {i}", confidence=6)
                for i in range(5)]
        self._write_day(day, rows)
        calls: list[str] = []
        real = adp._build_session_verification

        def _counting(session_id, elig_cfg):
            calls.append(session_id)
            return real(session_id, elig_cfg)

        with mock.patch.object(adp, "_build_session_verification", side_effect=_counting):
            adp.run_optimistic_integrate(day)
        self.assertEqual(calls.count(sid), 1, f"session built {calls.count(sid)} times, expected 1")


# ---------------------------------------------------------------------------
# Fail-closed: an exception in gathering -> internal_error, batch continues.
# ---------------------------------------------------------------------------


class FailClosedTests(GateTestBase):
    def test_gatherer_exception_is_internal_error_batch_continues(self):
        slug = self._slug()
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        rows = [self._add_row(pid="a1", slug=slug, session_id="sess-1", excerpt=_LONG_SENTENCE, confidence=6),
                self._add_row(pid="a2", slug=slug, session_id="sess-2", excerpt=_LONG_SENTENCE, confidence=6)]
        self._write_day(day, rows)
        with mock.patch.object(adp, "gather_eligibility_signals",
                               side_effect=RuntimeError("unreadable store")):
            summary = adp.run_optimistic_integrate(day)
        outcomes = [r["outcome"] for r in summary["results"]]
        self.assertEqual(outcomes.count("internal_error"), 2, summary)
        self.assertEqual(summary["applied"], 0)
        # both rows remain pending
        self.assertEqual(self._status(day, "a1"), "pending")
        self.assertEqual(self._status(day, "a2"), "pending")


# ---------------------------------------------------------------------------
# Near-duplicate supersede advisory flag (both directions).
# ---------------------------------------------------------------------------


class NearDupSupersedeTests(GateTestBase):
    def _supersede_setup(self, *, new_content: str, target_content: str):
        slug = self._slug()
        e = ls.build_entry(type_="pattern", content=target_content, confidence=8)
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        heads = {h["id"]: h for h in ls.load_all(slug)}
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=[tf.user_turn(new_content, human=True)])
        row = {
            "id": "s1", "kind": "learning_supersede", "project": slug, "target_id": e["id"],
            "content": new_content, "type": "pattern", "confidence": 6,
            "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": sid, "excerpt": new_content}],
            "justification": "t", "fingerprint": "fp-s1",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        return slug, heads, row

    def test_near_dup_fact_flip_flagged(self):
        target = "Deploy to production on port 8080 using the blue pipeline after the nightly build."
        new = "Deploy to production on port 9090 using the blue pipeline after the nightly build."
        slug, heads, row = self._supersede_setup(new_content=new, target_content=target)
        ev = self._eval(row, slug=slug, heads=heads)
        self.assertTrue(ev.near_dup_supersede)
        # near-dup vs target also drives a low novelty (pays twice, #39). Novelty
        # lands in the bundle regardless of which waterfall step the decision
        # short-circuits at, so read it from the bundle directly.
        bundle, _ = adp.gather_eligibility_signals(
            row, slug=slug, cache={}, heads=heads, elig_cfg=self._elig_cfg())
        self.assertLessEqual(bundle.novelty, 0.15)

    def test_substantive_update_not_flagged(self):
        target = "Deploy to production on port 8080 using the blue pipeline after the nightly build."
        new = ("Roll back the deployment entirely and switch every service to the green pipeline; "
               "the blue pipeline is deprecated and must never be used for production traffic again.")
        slug, heads, row = self._supersede_setup(new_content=new, target_content=target)
        ev = self._eval(row, slug=slug, heads=heads)
        self.assertFalse(ev.near_dup_supersede)


# ---------------------------------------------------------------------------
# Novelty semantics.
# ---------------------------------------------------------------------------


class NoveltyTests(GateTestBase):
    def test_add_empty_store_novelty_one(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        bundle, _ = adp.gather_eligibility_signals(
            self._add_row(pid="a1", slug=slug, session_id=sid, excerpt=_LONG_SENTENCE),
            slug=slug, cache={}, heads={}, elig_cfg=self._elig_cfg())
        self.assertEqual(bundle.novelty, 1.0)

    def test_supersede_unresolvable_target_novelty_zero(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=[tf.user_turn(_LONG_SENTENCE, human=True)])
        row = {
            "id": "s1", "kind": "learning_supersede", "project": slug, "target_id": "does-not-exist",
            "content": _LONG_SENTENCE, "type": "pattern", "confidence": 8,
            "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": sid, "excerpt": _LONG_SENTENCE}],
            "justification": "t", "fingerprint": "fp-s1",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        bundle, _ = adp.gather_eligibility_signals(
            row, slug=slug, cache={}, heads={}, elig_cfg=self._elig_cfg())
        self.assertEqual(bundle.novelty, 0.0)


# ---------------------------------------------------------------------------
# eligibility-dry-run CLI: scores, prints, mutates nothing.
# ---------------------------------------------------------------------------


class DryRunTests(GateTestBase):
    def test_dry_run_scores_without_mutating(self):
        import hashlib
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        # Note: eligibility DISABLED in config -- dry-run is a what-if preview.
        self._write_config({"eligibility": {"enabled": False}})
        day = self._day()
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6)])
        path = adp.proposals_dir() / f"{day}.jsonl"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        audit_before = len(self._audit())

        result = adp.run_eligibility_dry_run(day)

        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after, "dry-run must not mutate the proposals file")
        self.assertEqual(len(self._audit()), audit_before, "dry-run must write no audit records")
        self.assertEqual(len(result["proposals"]), 1)
        entry = result["proposals"][0]
        self.assertIn("score", entry)
        self.assertIn("signals", entry)
        self.assertIn("note", entry)  # "what-if preview" note when disabled

    def test_dry_run_cli_exit_zero(self):
        slug = self._slug()
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True))
        self._write_config({"eligibility": {"enabled": True}})
        day = self._day()
        self._write_day(day, [self._add_row(pid="a1", slug=slug, session_id=sid,
                                            excerpt=_LONG_SENTENCE, confidence=6)])
        rc = adp.main(["eligibility-dry-run", "--date", day])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
