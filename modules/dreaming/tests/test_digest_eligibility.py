"""Digest renderer unit test for the composite-eligibility "Composite
eligibility" subsection (composite-eligibility plan.md §3.7 / §5 Epic E6).

Like test_daily_report.py, this drives modules/dreaming/bin/dream-digest.sh as
a subprocess (its rendering logic is an inline python3 heredoc, not an
importable module) and asserts the rendered digests/{date}.md.

The renderer indexes apply-audit.jsonl records with audit_kind == "eligibility"
by proposal_id and renders a per-scored-row breakdown for the "## Proposals"
section -- for ELIGIBLE and SKIPPED rows alike, rejections especially
(decisions.md #28). It must NOT leak excerpt/transcript text: the eligibility
audit record only carries scalar score/signal/session data (§3.7).
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent
DREAM_DIGEST = MODULE_ROOT / "bin" / "dream-digest.sh"

DAY = "2026-07-05"
YESTERDAY = "2026-07-04"


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _proposal(*, pid, kind, project, confidence, content, type_="pattern",
              target_id=None):
    row = {
        "id": pid,
        "kind": kind,
        "project": project,
        "target_id": target_id,
        "content": content,
        "type": type_,
        "confidence": confidence,
        "prevalence": {"sessions": 2, "agents": 1},
        "evidence": [{"session_id": "sess-1", "excerpt": "some evidence excerpt"}],
        "justification": "test justification",
        "fingerprint": f"fp-{pid}",
        "generated_at": "2026-07-05T00:00:00.000Z",
        "status": "pending",
    }
    return row


def _elig_audit(*, proposal_id, kind, project, outcome, decision_basis,
                score, threshold, margin, signals, weakest_signal,
                verified_sessions, evidence_tier, unresolved_session_ids,
                type_="pattern", evidence_tier_source=None,
                near_duplicate_supersede=None):
    rec = {
        "audit_kind": "eligibility",
        "outcome": outcome,
        "decision_basis": decision_basis,
        "score": score,
        "threshold": threshold,
        "margin": margin,
        "signals": signals,
        "weakest_signal": weakest_signal,
        "verified_sessions": verified_sessions,
        "evidence_tier": evidence_tier,
        "unresolved_session_ids": unresolved_session_ids,
        "type": type_,
        "batch_id": "optbatch_testbatch01",
        "proposal_id": proposal_id,
        "kind": kind,
        "project": project,
    }
    if evidence_tier_source is not None:
        rec["evidence_tier_source"] = evidence_tier_source
    if near_duplicate_supersede is not None:
        rec["near_duplicate_supersede"] = near_duplicate_supersede
    return rec


class DigestEligibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Path(tempfile.mkdtemp(prefix="ccgm-digest-elig-test-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.dreaming_dir = self.sandbox / "dreaming"
        self.learnings_dir = self.sandbox / "learnings"
        self.home_dir = self.sandbox / "home"
        for d in (self.dreaming_dir, self.learnings_dir, self.home_dir):
            d.mkdir(parents=True)

        self.env = dict(os.environ)
        self.env["HOME"] = str(self.home_dir)
        self.env["CCGM_DREAMING_DIR"] = str(self.dreaming_dir)
        self.env["CCGM_LEARNINGS_DIR"] = str(self.learnings_dir)
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.env["CCGM_LEARNINGS_AUTOCOMMIT"] = "false"

    def _run_digest(self, date: str) -> str:
        proc = subprocess.run(
            ["bash", str(DREAM_DIGEST), date],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"digest failed: {proc.stderr}")
        return (self.dreaming_dir / "digests" / f"{date}.md").read_text(encoding="utf-8")

    def test_renders_breakdown_for_eligible_and_skipped_rows(self) -> None:
        proposals = [
            _proposal(pid="add-eligible", kind="learning_add", project="proj-a",
                      confidence=6, content="use rev-parse to find the repo root"),
            _proposal(pid="add-skipped", kind="learning_add", project="proj-a",
                      confidence=5, content="stale advice about branch cleanup"),
            _proposal(pid="add-origin", kind="learning_add", project="proj-a",
                      confidence=6, content="inferred-once conf-6 memory"),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{DAY}.jsonl", proposals)

        audit = [
            # (a) eligible via composite -- score present, positive margin.
            _elig_audit(
                proposal_id="add-eligible", kind="learning_add", project="proj-a",
                outcome="eligible", decision_basis="composite",
                score=0.791, threshold=0.58, margin=0.211,
                signals={"confidence": 0.60, "prevalence": 1.00,
                         "recency": 0.955, "novelty": 0.60},
                weakest_signal="confidence", verified_sessions=1,
                evidence_tier="user-corrected", unresolved_session_ids=[],
                evidence_tier_source={"session_id": "sess-1", "line": 42,
                                      "origin_kind": "human"},
            ),
            # (b) skipped_composite -- score present, NEGATIVE margin (short).
            _elig_audit(
                proposal_id="add-skipped", kind="learning_add", project="proj-a",
                outcome="skipped_composite", decision_basis=None,
                score=0.410, threshold=0.58, margin=-0.170,
                signals={"confidence": 0.50, "prevalence": 0.50,
                         "recency": 0.25, "novelty": 0.10},
                weakest_signal="novelty", verified_sessions=2,
                evidence_tier="inferred", unresolved_session_ids=["sess-gone"],
            ),
            # (c) skipped_origin -- no composite score computed.
            _elig_audit(
                proposal_id="add-origin", kind="learning_add", project="proj-a",
                outcome="skipped_origin", decision_basis=None,
                score=None, threshold=0.58, margin=None,
                signals={}, weakest_signal=None, verified_sessions=1,
                evidence_tier="inferred", unresolved_session_ids=[],
            ),
        ]
        _write_jsonl(self.dreaming_dir / "state" / "apply-audit.jsonl", audit)

        md = self._run_digest(DAY)

        # Every scored row gets a "Composite eligibility" subsection.
        self.assertEqual(md.count("**Composite eligibility**"), 3, msg=md)

        # (a) eligible/composite: score, θ, "over" margin, weakest, basis.
        self.assertIn("`eligible` (basis: composite) — S=0.791 (θ=0.58, over 0.211; "
                      "weakest: confidence)", md)
        self.assertIn("signals: confidence=0.60, prevalence=1.00, recency=0.95, "
                      "novelty=0.60", md)
        self.assertIn("evidence tier: user-corrected (from `sess-1` line 42, "
                      "origin=human)", md)
        self.assertIn("verified sessions: 1; unresolved: 0", md)

        # (b) skipped_composite: NEGATIVE margin renders as "short" -- the
        # rejection-visibility requirement (decisions.md #28).
        self.assertIn("`skipped_composite` — S=0.410 (θ=0.58, short 0.170; "
                      "weakest: novelty)", md)
        self.assertIn("verified sessions: 2; unresolved: 1", md)

        # (c) skipped_origin: no composite score, no signals line.
        self.assertIn("`skipped_origin` — score not computed (θ=0.58)", md)

    def test_no_eligibility_section_when_no_audit_records(self) -> None:
        """Legacy / disabled-mode nights (no eligibility audit records) render
        the proposal with NO Composite eligibility subsection."""
        proposals = [
            _proposal(pid="add-legacy", kind="learning_add", project="proj-a",
                      confidence=8, content="a plain proposal"),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{DAY}.jsonl", proposals)
        # no apply-audit.jsonl at all
        md = self._run_digest(DAY)
        self.assertIn("add-legacy", md)
        self.assertNotIn("**Composite eligibility**", md)

    def test_near_duplicate_supersede_flag_renders(self) -> None:
        proposals = [
            _proposal(pid="sup-1", kind="learning_supersede", project="proj-a",
                      confidence=6, content="refined near-dup content",
                      target_id="target-xyz"),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{DAY}.jsonl", proposals)
        audit = [
            _elig_audit(
                proposal_id="sup-1", kind="learning_supersede", project="proj-a",
                outcome="skipped_composite", decision_basis=None,
                score=0.573, threshold=0.58, margin=-0.007,
                signals={"confidence": 0.60, "prevalence": 0.50,
                         "recency": 0.891, "novelty": 0.05},
                weakest_signal="novelty", verified_sessions=2,
                evidence_tier="inferred", unresolved_session_ids=[],
                near_duplicate_supersede=True,
            ),
        ]
        _write_jsonl(self.dreaming_dir / "state" / "apply-audit.jsonl", audit)
        md = self._run_digest(DAY)
        self.assertIn("near-duplicate supersede with changed facts — review", md)
        self.assertIn("`skipped_composite` — S=0.573 (θ=0.58, short 0.007", md)


if __name__ == "__main__":
    unittest.main()
