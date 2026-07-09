#!/usr/bin/env python3
"""End-to-end proof for the multi-session citation fix (#853).

The reduce phase reliably emits ONE evidence citation per proposal even when it
claims prevalence.sessions=2, which caps the composite eligibility gate's
verified_sessions at 1 -- so the origin gate's "verified_sessions >=
add_min_sessions" arm was unreachable on real nightly data and a genuinely
multi-session mid-confidence memory could never auto-admit.

This test wires the WHOLE path the fix touches:
  mine two real synthetic transcripts -> map candidate cites both sessions ->
  reduce-shaped proposal cites ONE session -> dream_analyze.enrich_proposal_evidence()
  attaches the second session's transcript-derived excerpt ->
  apply_dream_proposal.evaluate_proposal_eligibility() re-verifies BOTH sessions
  against the transcripts and passes the origin gate.

It asserts the exact before/after the issue is about:
  * BEFORE enrichment (single citation): verified_sessions==1, outcome=skipped_origin.
  * AFTER  enrichment (two citations):  verified_sessions==2, origin gate PASSES
    (outcome=eligible, decision_basis=composite).

Runs in isolation: CCGM_LEARNINGS_DIR / CCGM_DREAMING_DIR / CCGM_CLAUDE_PROJECTS_DIR
/ HOME are redirected to tempdirs BEFORE import (learnings_store freezes
CLAUDE_PROJECTS_ROOT at import time). No network, no ANTHROPIC_API_KEY, never the
real store/dreaming/transcripts. Every transcript is synthetic (transcript_fixtures.py).

Kept in its own file (not test_eligibility_gate.py) to avoid overlapping the
parallel #846 work on that file's excerpt-matcher region.

Run with: python3 -m pytest modules/dreaming/tests/test_multi_citation_evidence.py -q
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lib"))

sys.modules.pop("learnings_store", None)
sys.modules.pop("dream_analyze", None)
sys.modules.pop("apply_dream_proposal", None)
sys.modules.pop("transcript_miner", None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-multicite-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-multicite-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-multicite-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-multicite-home-")
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
import transcript_miner as tm  # noqa: E402


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


# A long, distinctive friction sentence: present verbatim in each session's
# transcript AND the excerpt the miner extracts, so it corroborates at the gate
# and has enough content tokens to clear the coincidence guard.
FRICTION = (
    "migration failed because the reserved keyword position was not double "
    "quoted in the create table statement for the widget schema"
)
CONTENT = (
    "Always double-quote PostgreSQL reserved keywords like position and order "
    "when used as column identifiers in a migration"
)


class MultiCitationEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.slug = f"multicite-{uuid.uuid4().hex[:8]}"
        self.sid_a = f"sess-{uuid.uuid4().hex[:10]}"
        self.sid_b = f"sess-{uuid.uuid4().hex[:10]}"
        self.path_a = self._seed_session(self.sid_a)
        self.path_b = self._seed_session(self.sid_b)

    # ---- fixtures -------------------------------------------------------

    def _cwd(self) -> str:
        # Guaranteed-nonexistent absolute path whose basename IS the slug, so
        # detect_project_slug() falls through to basename == slug.
        return f"/synthetic-nonexistent/code/{self.slug}"

    def _seed_session(self, session_id: str, *, days_ago: float = 2.0) -> str:
        base = datetime.now(timezone.utc) - timedelta(days=days_ago)
        # Same friction command in both sessions -> they cluster together, so the
        # bundle carries a transcript-derived exemplar excerpt for each session.
        # No negation phrase in the following user turn -> INFERRED tier (this is
        # the "genuinely multi-session, not user-corrected" shape #853 is about).
        turns = [
            tf.user_turn("Run the widget schema migration.", human=True),
            tf.assistant_turn(
                "Applying the migration.",
                tool_uses=[{"id": "tool_1", "name": "Bash", "input": {"command": "psql -f migrate_widget.sql"}}],
            ),
            tf.friction_turn(tool_use_id="tool_1", content=FRICTION, exit_code=1),
            tf.user_turn("Understood, please quote the identifier and retry.", human=True),
        ]
        path = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}" / f"{session_id}.jsonl"
        tf.write_transcript(path, turns, session_id=session_id, cwd=self._cwd(), base_ts=tf.iso(base))
        return str(path)

    def _bundles(self) -> dict:
        # enrich_proposal_evidence() expects bundles keyed by project slug.
        return {self.slug: tm.mine_to_evidence_bundle([self.path_a, self.path_b])}

    def _map_results(self) -> dict:
        # The map candidate associates BOTH sessions with the learning (what the
        # map phase produces from a friction cluster spanning two sessions).
        return {
            self.slug: [{
                "type": "pitfall",
                "content": CONTENT,
                "evidence": [
                    {"session_id": self.sid_a, "excerpt": FRICTION},
                    {"session_id": self.sid_b, "excerpt": FRICTION},
                ],
                "occurrence_count": 2,
            }]
        }

    def _reduce_shaped_row(self) -> dict:
        # The exact starved shape: cites ONE session, claims prevalence.sessions=2.
        raw = {
            "kind": "learning_add", "project": self.slug, "target_id": None,
            "content": CONTENT, "type": "pitfall", "confidence": 6,
            "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": self.sid_a, "excerpt": FRICTION}],
            "justification": "Reserved-keyword quoting bit twice across sessions; the fix generalizes.",
        }
        row, reason = da.finalize_proposal(
            raw, store_by_id={self.slug: {}}, cfg=dict(da.DEFAULT_CONFIG),
            proposal_schema=da._load_proposal_schema(),  # noqa: SLF001
        )
        self.assertIsNone(reason, reason)
        return row

    def _optimistic(self) -> dict:
        elig_cfg = elig.default_eligibility()
        elig_cfg["enabled"] = True
        return {"confidence_floor_content": 8, "add_min_sessions": 2, "eligibility": elig_cfg}

    def _evaluate(self, row: dict):
        opt = self._optimistic()
        return adp.evaluate_proposal_eligibility(
            row, slug=self.slug, cache={}, heads={}, cfg=opt, elig_cfg=opt["eligibility"],
        )

    # ---- the proof ------------------------------------------------------

    def test_single_citation_is_starved_at_origin_gate(self):
        # Baseline: the reduce-shaped row, UN-enriched, only verifies ONE session
        # and is held back at the origin gate -- exactly the #853 symptom.
        row = self._reduce_shaped_row()
        ev = self._evaluate(row)
        self.assertEqual(len(ev.verified_session_ids), 1)
        self.assertEqual(ev.evidence_tier, "inferred")
        self.assertEqual(ev.decision.outcome, "skipped_origin")

    def test_enrichment_attaches_second_session(self):
        row = self._reduce_shaped_row()
        self.assertEqual([e["session_id"] for e in row["evidence"]], [self.sid_a])
        da.enrich_proposal_evidence([row], self._map_results(), self._bundles())
        cited = sorted(e["session_id"] for e in row["evidence"])
        self.assertEqual(cited, sorted([self.sid_a, self.sid_b]))
        # Each cited session carries a non-empty excerpt.
        self.assertTrue(all(e.get("excerpt", "").strip() for e in row["evidence"]))

    def test_two_citations_reach_verified_sessions_two_and_pass_origin_gate(self):
        row = self._reduce_shaped_row()
        da.enrich_proposal_evidence([row], self._map_results(), self._bundles())
        ev = self._evaluate(row)
        # The whole point of the fix: both cited sessions verify.
        self.assertEqual(len(ev.verified_session_ids), 2)
        self.assertEqual(sorted(ev.verified_session_ids), sorted([self.sid_a, self.sid_b]))
        # tier stays "inferred" -> the origin gate is passed via the transcript-
        # verified prevalence arm (verified_sessions >= add_min_sessions), NOT the
        # user-corrected arm. This is the arm #853 says was unreachable.
        self.assertEqual(ev.evidence_tier, "inferred")
        self.assertNotEqual(ev.decision.outcome, "skipped_origin")
        self.assertEqual(ev.decision.outcome, "eligible")
        self.assertEqual(ev.decision.decision_basis, "composite")

    def test_enrichment_is_deterministic_end_to_end(self):
        map_results = self._map_results()
        bundle = self._bundles()
        row1 = self._reduce_shaped_row()
        da.enrich_proposal_evidence([row1], map_results, bundle)
        first = copy.deepcopy(row1["evidence"])
        # Re-running does not double-attach.
        da.enrich_proposal_evidence([row1], map_results, bundle)
        self.assertEqual(row1["evidence"], first)


if __name__ == "__main__":
    unittest.main()
