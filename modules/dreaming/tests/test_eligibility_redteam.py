#!/usr/bin/env python3
"""
Executable red-team suite for the composite-eligibility gate (composite-
eligibility plan.md Epic E5). One test class per attack walkthrough in
``modules/dreaming/docs/composite-eligibility-poisoning-analysis.md``, each
asserting the SHIPPED defense holds against the attack-shaped input.

These are the adversarial *variants* of the mechanism tests in
test_eligibility_gate.py / test_eligibility_parity.py / test_eligibility.py:
where a gate test proves one mechanism in isolation (e.g. "an unresolvable
session is not counted"), the poisoning doc cites that test and this file
exercises the composed ATTACK that stacks the mechanisms (e.g. "an attacker
pads evidence[] with an unresolvable + a wrong-slug + an excerpt-less citation
to fake prevalence >= add_min_sessions -> still skipped_origin"). Two honest-
residual tests deliberately assert a defense does NOT close a gap (the conf>=8
legacy escape, the advisory-only near-dup flag), so a future "hardening" that
silently changed that behavior is caught (decisions.md #17: overclaiming is a
defect).

Runs in isolation: CCGM_LEARNINGS_DIR + CCGM_DREAMING_DIR + CCGM_CLAUDE_PROJECTS_DIR
+ HOME redirected to tempdirs BEFORE import (module-level constants freeze at
import; #793). No network, no ANTHROPIC_API_KEY, never the real store/dreaming/
transcripts. Every transcript is synthetic (transcript_fixtures.py; no real
path/username -- public-repo rule, plan.md §1.4).

Run with: python3 -m pytest modules/dreaming/tests/test_eligibility_redteam.py -q
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import time
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

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-elig-redteam-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-elig-redteam-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-elig-redteam-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-elig-redteam-home-")
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
import eligibility as elig  # noqa: E402
import learnings_store as ls  # noqa: E402
import transcript_fixtures as tf  # noqa: E402


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


# The corroborating sentence the "honest" transcript carries; cited excerpts are
# verbatim/paraphrase/garbage variants of it.
_LONG = ("The Edit tool does not follow symlinks so read the workspace path first "
         "before editing the file")

# A long supersede target and a 0.95+-similar near-duplicate with ONE flipped
# fact (a port number). Kept long so the single-token flip is a small fraction of
# the string and SequenceMatcher.ratio clears 0.95 (novelty-vs-target <= 0.05).
_SUP_TARGET = ("When deploying the analytics service to the production cluster always route "
               "inbound traffic through port 8080 on the blue pipeline after the nightly build "
               "has fully completed")
_SUP_NEARDUP = ("When deploying the analytics service to the production cluster always route "
                "inbound traffic through port 9090 on the blue pipeline after the nightly build "
                "has fully completed")


class RedTeamBase(unittest.TestCase):
    """Shared world-building, mirroring the E3/E4 gate-test conventions
    (before-import env redirection above; per-test env pinning here)."""

    def setUp(self) -> None:
        self._pin("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT))
        self._pin("CCGM_DREAMING_DIR", _TMP_DREAMING)
        self._pin("CCGM_CLAUDE_PROJECTS_DIR", str(ls.CLAUDE_PROJECTS_ROOT))
        self._pin("HOME", _TMP_HOME)

    def _pin(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.__setitem__(key, prior) if had else os.environ.pop(key, None))

    # ---- fixtures -----------------------------------------------------------

    def _slug(self, label: str = "rt") -> str:
        return f"{label}-{uuid.uuid4().hex[:8]}"

    def _cwd_for(self, slug: str) -> str:
        # A guaranteed-nonexistent absolute path whose basename IS the slug, so
        # detect_project_slug() falls through git resolution to basename==slug.
        return f"/synthetic-nonexistent/code/{slug}"

    def _sid(self, label: str = "sess") -> str:
        return f"{label}-{uuid.uuid4().hex[:10]}"

    def _write_session(self, session_id: str, *, slug: str, turns: list, days_ago: float = 1.0) -> None:
        base = datetime.now(timezone.utc) - timedelta(days=days_ago)
        path = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}" / f"{session_id}.jsonl"
        tf.write_transcript(path, turns, session_id=session_id, cwd=self._cwd_for(slug),
                            base_ts=tf.iso(base))

    def _corroborating_turns(self, *, correction: bool, sentence: str = _LONG) -> list:
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
                 content: str = _LONG, confidence: int = 6, type_: str = "pitfall",
                 extra_evidence: list | None = None, **extra) -> dict:
        evidence = [{"session_id": session_id, "excerpt": excerpt}]
        if extra_evidence:
            evidence.extend(extra_evidence)
        row = {
            "id": pid, "kind": "learning_add", "project": slug, "target_id": None,
            "content": content, "type": type_, "confidence": confidence,
            "prevalence": {"sessions": 2, "agents": 1}, "evidence": evidence,
            "justification": "redteam", "fingerprint": f"fp-{pid}",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        row.update(extra)
        return row

    def _eval(self, row: dict, *, slug: str, heads: dict | None = None, elig_cfg: dict | None = None):
        ec = elig_cfg if elig_cfg is not None else self._elig_cfg()
        opt = self._optimistic(ec)
        return adp.evaluate_proposal_eligibility(
            row, slug=slug, cache={}, heads=heads or {}, cfg=opt, elig_cfg=ec,
        )

    def _supersede_setup(self, *, new_content: str, target_content: str, confidence: int = 6):
        slug = self._slug()
        e = ls.build_entry(type_="pattern", content=target_content, confidence=8)
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        heads = {h["id"]: h for h in ls.load_all(slug)}
        sid = self._sid()
        # Corroborating text is the NEW content, cited verbatim, so the excerpt
        # check passes and the row reaches the near-dup/novelty computation.
        self._write_session(sid, slug=slug, turns=[tf.user_turn(new_content, human=True)])
        row = {
            "id": f"sup-{uuid.uuid4().hex[:10]}", "kind": "learning_supersede", "project": slug,
            "target_id": e["id"], "content": new_content, "type": "pattern", "confidence": confidence,
            "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": sid, "excerpt": new_content}],
            "justification": "redteam", "fingerprint": f"fp-sup-{uuid.uuid4().hex[:6]}",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        return slug, heads, row


# ---------------------------------------------------------------------------
# Attack 1: forged evidence_tier / stamped_signals.
# The reduce LLM (untrusted) stamps a high-trust tier + fat signal block onto a
# proposal whose transcript contains no human correction. gather_eligibility_
# signals()'s signature carries no parameter for stamped fields (decisions.md
# #20), recomputes the tier from the transcript, and rejects.
# ---------------------------------------------------------------------------


class ForgedTierAttackTests(RedTeamBase):
    def test_forged_tier_and_stamped_signals_are_recomputed_skipped_origin(self):
        slug = self._slug()
        sid = self._sid()
        # A single, correction-FREE (inferred) session.
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid=self._sid("p"), slug=slug, session_id=sid, excerpt=_LONG, confidence=6,
            # The forgeries the untrusted reduce phase could stamp:
            evidence_tier="user-corrected",
            stamped_signals={"prevalence": 9, "recency": 1.0, "verified_sessions": 5,
                             "evidence_tier": "user-corrected"},
        )
        ev = self._eval(row, slug=slug)
        # Tier recomputed from the transcript (no human correction) -> inferred;
        # a lone inferred session < add_min_sessions -> non-compensatory origin
        # gate rejects. The forged fields changed nothing.
        self.assertEqual(ev.evidence_tier, "inferred")
        self.assertEqual(ev.verified_session_ids, [sid])
        self.assertEqual(ev.decision.outcome, "skipped_origin")
        self.assertFalse(ev.decision.eligible)
        self.assertIsNone(ev.decision.decision_basis)


# ---------------------------------------------------------------------------
# Attack 2: session padding. Fake verified_sessions >= add_min_sessions by
# citing sessions that fail one of §3.4's three checks each.
# ---------------------------------------------------------------------------


class SessionPaddingAttackTests(RedTeamBase):
    def test_padding_unresolvable_wrongslug_excerptless_fails_origin(self):
        slug = self._slug()
        # (b) a real transcript in a DIFFERENT slug (slug-match fails).
        wrong_slug_sid = self._sid("wrong")
        self._write_session(wrong_slug_sid, slug=self._slug("other"),
                            turns=self._corroborating_turns(correction=False))
        # (c) a real, slug-matching transcript but cited with a garbage excerpt
        #     (excerpt-corroboration fails).
        excerptless_sid = self._sid("bad-excerpt")
        self._write_session(excerptless_sid, slug=slug,
                            turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid=self._sid("p"), slug=slug,
            # (a) an unresolvable session_id (resolution fails).
            session_id="ghost-does-not-resolve-anywhere", excerpt=_LONG, confidence=6,
            extra_evidence=[
                {"session_id": wrong_slug_sid, "excerpt": _LONG},
                {"session_id": excerptless_sid, "excerpt": "completely unrelated zzzqqq wubwub payload"},
            ],
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [],
                         "three padded citations, none passing §3.4, must yield zero verified sessions")
        self.assertIn("ghost-does-not-resolve-anywhere", ev.unresolved_session_ids)
        self.assertEqual(ev.decision.outcome, "skipped_origin")
        self.assertFalse(ev.decision.eligible)

    def test_one_real_session_cited_thrice_still_fails_origin(self):
        # Distinctness dedup: cite ONE genuine inferred session 3x to fake
        # prevalence >= add_min_sessions. It counts once -> 1 < 2 -> skipped_origin.
        slug = self._slug()
        sid = self._sid()
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(
            pid=self._sid("p"), slug=slug, session_id=sid, excerpt=_LONG, confidence=6,
            extra_evidence=[{"session_id": sid, "excerpt": _LONG},
                            {"session_id": sid, "excerpt": _LONG}],
        )
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.verified_session_ids, [sid])
        self.assertEqual(len(ev.verified_session_ids), 1)
        self.assertEqual(ev.decision.outcome, "skipped_origin")


# ---------------------------------------------------------------------------
# Attack 3: soft-signal compensation. Maximize every attacker-controllable soft
# signal (confidence, novelty, recency) simultaneously; the non-compensatory
# origin gate rejects a weak origin regardless. Property sweep over the full
# attacker-maximal cross product, with legacy escape OFF so the origin gate is
# isolated across the WHOLE confidence band (incl. conf 8-10).
# ---------------------------------------------------------------------------


class NonCompensabilityTests(RedTeamBase):
    def test_maxed_soft_signals_never_rescue_a_weak_origin(self):
        ec = self._elig_cfg(legacy_floor_admits=False)
        opt = self._optimistic(ec)
        checked = 0
        for kind in ("learning_add", "learning_supersede"):
            for verified_sessions in (0, 1):            # < add_min_sessions
                for confidence in range(5, 11):         # >= static_floor, incl. 8-10
                    for novelty in (0.0, 0.5, 1.0):     # attacker-maximizable
                        for age in (0.0, 1.0, None):    # recency backdated to now
                            bundle = elig.SignalBundle(
                                kind=kind, confidence=confidence,
                                verified_sessions=verified_sessions, evidence_tier="inferred",
                                newest_evidence_age_days=age, novelty=novelty,
                            )
                            d = elig.evaluate_eligibility(bundle, opt)
                            self.assertEqual(
                                d.outcome, "skipped_origin",
                                msg=(f"soft signals compensated a weak origin: kind={kind} "
                                     f"vs={verified_sessions} conf={confidence} nov={novelty} age={age}"))
                            self.assertFalse(d.eligible)
                            self.assertIsNone(d.decision_basis)
                            checked += 1
        self.assertEqual(checked, 2 * 2 * 6 * 3 * 3)


# ---------------------------------------------------------------------------
# Attack 4: confidence inflation (the HEADLINE residual). Confidence is the only
# model-assigned scoring input and cannot be cross-checked. Inflating it does not
# admit a single-session inferred ADD (add's legacy escape reproduces BOTH legacy
# conditions, now with a VERIFIED session count) -- but a conf>=8 SUPERSEDE still
# escapes via the floor with no origin requirement, exactly as forgeable as today
# (decisions.md #17). Both facts are pinned so neither can silently change.
# ---------------------------------------------------------------------------


class ConfidenceInflationTests(RedTeamBase):
    def test_conf10_single_session_inferred_add_rejected(self):
        slug = self._slug()
        sid = self._sid()
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=False))
        row = self._add_row(pid=self._sid("p"), slug=slug, session_id=sid, excerpt=_LONG,
                            confidence=10)
        ev = self._eval(row, slug=slug)
        self.assertEqual(ev.decision.outcome, "skipped_origin",
                         "max confidence does not admit a single-session inferred add "
                         "(add's legacy escape now requires >= 2 VERIFIED sessions)")

    def test_conf8_supersede_admits_via_legacy_floor_residual(self):
        # HONEST residual (decisions.md #17): the composite adds NO protection to
        # the conf>=8 supersede band -- it escapes on the floor alone with no
        # origin requirement. Encoded so a future change is caught, not hidden.
        b = elig.SignalBundle(kind="learning_supersede", confidence=8, verified_sessions=0,
                              evidence_tier="inferred", newest_evidence_age_days=None, novelty=0.0)
        d = elig.evaluate_eligibility(b, self._optimistic())
        self.assertTrue(d.eligible)
        self.assertEqual(d.decision_basis, "legacy_floor")

    def test_strict_mode_binds_conf8_supersede_to_origin_gate(self):
        # The documented (non-default) mitigation: legacy_floor_admits=false makes
        # the origin gate bind the conf>=8 band too -- the same conf-8 supersede
        # with no origin is then rejected.
        ec = self._elig_cfg(legacy_floor_admits=False)
        b = elig.SignalBundle(kind="learning_supersede", confidence=8, verified_sessions=0,
                              evidence_tier="inferred", newest_evidence_age_days=None, novelty=0.0)
        d = elig.evaluate_eligibility(b, self._optimistic(ec))
        self.assertEqual(d.outcome, "skipped_origin")


# ---------------------------------------------------------------------------
# Attack 5: type self-selection. Under the REMOVED 5-signal design the model
# could self-award the highest type_prior. `type` is now not a scoring input at
# all (decisions.md #38): two rows identical except `type` produce byte-identical
# decisions, and neither the pure bundle nor the weights expose a type input.
# ---------------------------------------------------------------------------


class TypeNeutralityTests(RedTeamBase):
    def test_type_has_zero_effect_on_the_decision_and_bundle(self):
        slug = self._slug()
        sid = self._sid()
        # A user-corrected conf-6 session so BOTH rows reach ELIGIBLE via the full
        # composite -- proving type-independence on a SCORED row, not an early skip.
        self._write_session(sid, slug=slug, turns=self._corroborating_turns(correction=True), days_ago=1)
        base = {
            "id": "tn", "kind": "learning_add", "project": slug, "target_id": None,
            "content": _LONG, "confidence": 6, "prevalence": {"sessions": 2, "agents": 1},
            "evidence": [{"session_id": sid, "excerpt": _LONG}],
            "justification": "redteam", "fingerprint": "fp-tn",
            "generated_at": "2026-01-01T00:00:00.000Z", "status": "pending",
        }
        # `pitfall` and `preference` were the extreme ends (prior 1.0 vs 0.6) of
        # the removed type_priors table -- the maximum-possible pre-#38 swing.
        row_pitfall = dict(base, type="pitfall")
        row_pref = dict(base, type="preference")

        # Freeze the wall clock across both evaluations: recency's age_days reads
        # time.time() at gather, so two un-frozen calls microseconds apart would
        # differ in the ~15th decimal and defeat a byte-identity comparison. The
        # freeze isolates the ONE thing under test (type) from clock drift.
        with mock.patch.object(adp.time, "time", return_value=time.time()):
            ev_a = self._eval(row_pitfall, slug=slug)
            ev_b = self._eval(row_pref, slug=slug)
            bundle_a, _ = adp.gather_eligibility_signals(row_pitfall, slug=slug, cache={}, heads={},
                                                         elig_cfg=self._elig_cfg())
            bundle_b, _ = adp.gather_eligibility_signals(row_pref, slug=slug, cache={}, heads={},
                                                         elig_cfg=self._elig_cfg())
        self.assertTrue(ev_a.decision.eligible)
        self.assertEqual(ev_a.decision, ev_b.decision, "type must not change the EligibilityDecision")
        self.assertEqual(repr(ev_a.decision), repr(ev_b.decision), "decisions must be byte-identical")
        self.assertEqual(bundle_a, bundle_b, "type must not change the SignalBundle")

    def test_no_type_input_exists_on_bundle_or_weights(self):
        # Structural pin (decisions.md #38, A-MAC-transfer correction): `type`
        # cannot influence a score even by future accident, because there is no
        # place to put it.
        fields = {f.name for f in dataclasses.fields(elig.SignalBundle)}
        self.assertNotIn("type", fields)
        self.assertNotIn("type_prior", fields)
        weights = elig.default_eligibility()["weights"]
        self.assertNotIn("type_prior", weights)
        self.assertEqual(set(weights), {"confidence", "prevalence", "recency", "novelty"})


# ---------------------------------------------------------------------------
# Attack 6: near-duplicate supersede corruption. Take a real trusted head and
# supersede it with 0.95+-similar text carrying ONE flipped fact. The attack
# pays twice (decisions.md #39): novelty-vs-target collapses AND the advisory
# digest flag fires -- both asserted on the same fixture. A conf>=8 variant
# encodes the honest residual: the flag is advisory and never blocks.
# ---------------------------------------------------------------------------


class SupersedeNearDupAttackTests(RedTeamBase):
    def test_near_dup_fact_flip_scores_low_novelty_and_trips_flag(self):
        slug, heads, row = self._supersede_setup(new_content=_SUP_NEARDUP, target_content=_SUP_TARGET,
                                                 confidence=6)
        # Precondition of the construction (fail loudly if the fixtures drift):
        # the single similarity value drives BOTH the flag threshold (>= 0.9) and
        # novelty-vs-target (1 - similarity <= 0.05).
        sim = elig.similarity(_SUP_NEARDUP, _SUP_TARGET)
        self.assertGreaterEqual(sim, 0.95, f"near-dup fixture must be >= 0.95 similar (got {sim})")

        ev = self._eval(row, slug=slug, heads=heads)
        self.assertTrue(ev.near_dup_supersede, "0.95-similar fact-flip must trip the digest flag")

        bundle, _ = adp.gather_eligibility_signals(row, slug=slug, cache={}, heads=heads,
                                                   elig_cfg=self._elig_cfg())
        self.assertLessEqual(bundle.novelty, 0.05,
                             "novelty-vs-target must collapse for a near-duplicate refinement (pays twice, #39)")
        # NB: the exact skip outcome for a scored (2-session) near-dup is a
        # recency-dependent §3.9 (h) fact pinned by E4's
        # test_h_supersede_near_dup_skipped_composite -- and the novelty dock is
        # a soft 0.10-weight tiebreaker, NOT a hard block (a fresh, well-verified
        # near-dup can still clear θ; the ADVISORY flag + dwell + human review are
        # the real catches). This red-team test pins only the two deterministic
        # defenses the same fixture fires: collapsed novelty AND the digest flag.

    def test_conf8_near_dup_admits_via_legacy_but_flag_still_fires_residual(self):
        # HONEST residual (decisions.md #17/#39): the near-dup flag is ADVISORY,
        # never a block. A conf>=8 near-dup fact-flip supersede admits via the
        # legacy floor (step 4, before novelty is scored), yet the flag still
        # fires so a human reviewer can catch it. The composite surfaced the
        # high-confidence corruption; it did not "fix" it.
        slug, heads, row = self._supersede_setup(new_content=_SUP_NEARDUP, target_content=_SUP_TARGET,
                                                 confidence=8)
        ev = self._eval(row, slug=slug, heads=heads)
        self.assertTrue(ev.decision.eligible)
        self.assertEqual(ev.decision.decision_basis, "legacy_floor")
        self.assertTrue(ev.near_dup_supersede, "the advisory flag fires even when legacy admits the row")


if __name__ == "__main__":
    unittest.main()
