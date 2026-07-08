#!/usr/bin/env python3
"""Exhaustive tests for modules/dreaming/lib/eligibility.py (composite-eligibility E1).

Covers the plan.md §5 Epic E1 test list: the nine §3.9 worked cases pinned to
exact 3-decimal S values, boundary pins, monotonicity sweeps, the origin-gate
non-compensability property, per-kind legacy escape, the full
validate_eligibility_config matrix (§3.6), AST-based purity + no-broad-except
lints, frozen-dataclass assertions, and similarity/normalization pins.

eligibility.py is pure (no env, no I/O), so no CCGM_* env redirection is
needed before import -- unlike the store/miner tests.

Run: python3 -m pytest modules/dreaming/tests/test_eligibility.py -q
  or: python3 modules/dreaming/tests/test_eligibility.py
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "lib"
sys.path.insert(0, str(LIB))

import eligibility as elig  # noqa: E402
from eligibility import (  # noqa: E402
    DEFAULT_ELIGIBILITY,
    MIN_STATIC_FLOOR,
    EligibilityDecision,
    SignalBundle,
    composite_score,
    evaluate_eligibility,
    normalize_content,
    novelty_vs,
    similarity,
    token_jaccard,
    validate_eligibility_config,
)

ELIGIBILITY_SRC = LIB / "eligibility.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def opt(cfc: int = 8, add_min: int = 2, **elig_overrides) -> dict:
    """A merged optimistic dict with a fully-defaulted eligibility block plus
    any top-level eligibility overrides."""
    o = {
        "confidence_floor_content": cfc,
        "add_min_sessions": add_min,
        "eligibility": copy.deepcopy(DEFAULT_ELIGIBILITY),
    }
    o["eligibility"].update(elig_overrides)
    return o


def bundle(
    kind="learning_add",
    confidence=6,
    verified_sessions=2,
    evidence_tier="inferred",
    newest_evidence_age_days=10.0,
    novelty=0.5,
) -> SignalBundle:
    return SignalBundle(
        kind=kind,
        confidence=confidence,
        verified_sessions=verified_sessions,
        evidence_tier=evidence_tier,
        newest_evidence_age_days=newest_evidence_age_days,
        novelty=novelty,
    )


# ---------------------------------------------------------------------------
# §3.9 worked cases (exact S to 3 decimals)
# ---------------------------------------------------------------------------


class WorkedCaseTests(unittest.TestCase):
    def test_case_a_add_user_corrected(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=1,
                   evidence_tier="user-corrected", newest_evidence_age_days=2.0, novelty=0.6)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.791)
        d = evaluate_eligibility(b, opt())
        self.assertTrue(d.eligible)
        self.assertEqual(d.outcome, "eligible")
        self.assertEqual(d.decision_basis, "composite")

    def test_case_b_add_inferred_3sess(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=3,
                   evidence_tier="inferred", newest_evidence_age_days=7.0, novelty=0.5)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.685)
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "eligible")

    def test_case_c_add_inferred_1sess_skips_origin(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=1,
                   evidence_tier="inferred", newest_evidence_age_days=2.0, novelty=0.5)
        d = evaluate_eligibility(b, opt())
        self.assertFalse(d.eligible)
        self.assertEqual(d.outcome, "skipped_origin")
        self.assertIsNone(d.score)  # never reaches S
        self.assertEqual(d.signals, {})

    def test_case_d_add_inferred_2sess_crossover(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=10.0, novelty=0.5)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.599)
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "eligible")

    def test_case_e_add_conf5_stale_skips_composite(self):
        b = bundle(kind="learning_add", confidence=5, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=60.0, novelty=0.1)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.410)
        d = evaluate_eligibility(b, opt())
        self.assertFalse(d.eligible)
        self.assertEqual(d.outcome, "skipped_composite")

    def test_case_f_add_conf9_inferred_1sess_skips_origin(self):
        # conf-9 clears the legacy floor but not the session count -> matches today.
        b = bundle(kind="learning_add", confidence=9, verified_sessions=1,
                   evidence_tier="inferred", newest_evidence_age_days=2.0, novelty=0.5)
        d = evaluate_eligibility(b, opt())
        self.assertFalse(d.eligible)
        self.assertEqual(d.outcome, "skipped_origin")

    def test_case_g_eviction_not_scored_by_pure_core(self):
        # (g) contradict/deprecate take the legacy path bit-for-bit and are
        # NEVER routed to evaluate_eligibility (unreachable for kinds outside
        # {add, supersede} by construction, plan.md §3.2). Documented here:
        # the pure core exposes no branch for eviction kinds.
        self.assertNotIn("learning_contradict", ("learning_add", "learning_supersede"))
        self.assertNotIn("learning_deprecate", ("learning_add", "learning_supersede"))

    def test_case_h_supersede_near_dup_skips_composite(self):
        b = bundle(kind="learning_supersede", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=5.0, novelty=0.05)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.573)
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "skipped_composite")

    def test_case_i_supersede_substantive_eligible(self):
        b = bundle(kind="learning_supersede", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=5.0, novelty=0.6)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(round(s, 3), 0.628)
        d = evaluate_eligibility(b, opt())
        self.assertTrue(d.eligible)
        self.assertEqual(d.decision_basis, "composite")


# ---------------------------------------------------------------------------
# Normalized-signal pins (the values that feed §3.9)
# ---------------------------------------------------------------------------


class SignalNormalizationTests(unittest.TestCase):
    def test_prevalence_cap_user_corrected_saturates_at_one(self):
        b = bundle(evidence_tier="user-corrected", verified_sessions=1)
        _, sig = composite_score(b, DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["prevalence"], 1.0)

    def test_prevalence_inferred_uses_cap_four(self):
        _, sig = composite_score(bundle(evidence_tier="inferred", verified_sessions=2), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["prevalence"], 0.5)

    def test_prevalence_clamped_at_one_when_over_cap(self):
        _, sig = composite_score(bundle(evidence_tier="inferred", verified_sessions=99), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["prevalence"], 1.0)

    def test_confidence_normalized_over_ten(self):
        _, sig = composite_score(bundle(confidence=6), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["confidence"], 0.6)

    def test_confidence_clamped_to_ten(self):
        _, sig = composite_score(bundle(confidence=99), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["confidence"], 1.0)

    def test_recency_none_age_is_zero(self):
        _, sig = composite_score(bundle(newest_evidence_age_days=None), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["recency"], 0.0)

    def test_recency_at_one_half_life_is_half(self):
        _, sig = composite_score(bundle(newest_evidence_age_days=30.0), DEFAULT_ELIGIBILITY)
        self.assertAlmostEqual(sig["recency"], 0.5, places=6)

    def test_recency_at_zero_age_is_one(self):
        _, sig = composite_score(bundle(newest_evidence_age_days=0.0), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["recency"], 1.0)

    def test_novelty_passed_through_and_clamped(self):
        _, sig = composite_score(bundle(novelty=0.42), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["novelty"], 0.42)
        _, sig2 = composite_score(bundle(novelty=5.0), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig2["novelty"], 1.0)

    def test_unknown_tier_treated_as_inferred_in_prevalence(self):
        # Fail-closed: a bogus tier uses the wider cap-4 (inferred), never cap-1.
        _, sig = composite_score(bundle(evidence_tier="bogus", verified_sessions=2), DEFAULT_ELIGIBILITY)
        self.assertEqual(sig["prevalence"], 0.5)


# ---------------------------------------------------------------------------
# Boundary pins
# ---------------------------------------------------------------------------


class BoundaryTests(unittest.TestCase):
    def test_conf_equals_static_floor_reaches_composite(self):
        # static_floor default 5; conf 5 passes the strict-< floor.
        b = bundle(kind="learning_add", confidence=5, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=10.0, novelty=0.5)
        d = evaluate_eligibility(b, opt())
        self.assertIn(d.outcome, ("eligible", "skipped_composite"))
        self.assertIsNotNone(d.score)

    def test_conf_below_static_floor_skips_floor(self):
        b = bundle(confidence=4)
        d = evaluate_eligibility(b, opt())
        self.assertFalse(d.eligible)
        self.assertEqual(d.outcome, "skipped_floor")
        self.assertIsNone(d.score)
        self.assertEqual(d.signals, {})

    def test_score_equal_threshold_admits(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=10.0, novelty=0.5)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        d = evaluate_eligibility(b, opt(threshold=s))  # threshold == S exactly
        self.assertTrue(d.eligible)
        self.assertEqual(d.decision_basis, "composite")
        self.assertGreaterEqual(d.score, d.threshold)

    def test_score_just_below_threshold_rejects(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=10.0, novelty=0.5)
        s, _ = composite_score(b, DEFAULT_ELIGIBILITY)
        # nudge threshold a hair above S
        d = evaluate_eligibility(b, opt(threshold=min(1.0, s + 1e-9)))
        self.assertFalse(d.eligible)
        self.assertEqual(d.outcome, "skipped_composite")

    def test_margin_is_score_minus_threshold(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=10.0, novelty=0.5)
        d = evaluate_eligibility(b, opt())
        self.assertAlmostEqual(d.margin, d.score - d.threshold, places=9)


# ---------------------------------------------------------------------------
# Monotonicity + contribution bounds
# ---------------------------------------------------------------------------


class MonotonicityTests(unittest.TestCase):
    def test_S_nondecreasing_in_confidence(self):
        prev = -1.0
        for c in range(5, 11):
            s, _ = composite_score(bundle(confidence=c), DEFAULT_ELIGIBILITY)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_S_nondecreasing_in_verified_sessions(self):
        prev = -1.0
        for vs in range(0, 6):
            s, _ = composite_score(bundle(verified_sessions=vs, evidence_tier="inferred"), DEFAULT_ELIGIBILITY)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_S_nondecreasing_in_novelty(self):
        prev = -1.0
        for nov in (0.0, 0.25, 0.5, 0.75, 1.0):
            s, _ = composite_score(bundle(novelty=nov), DEFAULT_ELIGIBILITY)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_S_nonincreasing_in_age(self):
        prev = 2.0
        for age in (0.0, 5.0, 30.0, 60.0, 120.0):
            s, _ = composite_score(bundle(newest_evidence_age_days=age), DEFAULT_ELIGIBILITY)
            self.assertLessEqual(s, prev)
            prev = s

    def test_per_signal_contribution_bounded_by_weight(self):
        weights = DEFAULT_ELIGIBILITY["weights"]
        for conf in (5, 8, 10):
            for vs in (0, 2, 4):
                for age in (0.0, 30.0, None):
                    for nov in (0.0, 0.5, 1.0):
                        b = bundle(confidence=conf, verified_sessions=vs,
                                   newest_evidence_age_days=age, novelty=nov)
                        _, sig = composite_score(b, DEFAULT_ELIGIBILITY)
                        for name, w in weights.items():
                            self.assertLessEqual(w * sig[name], w + 1e-12)
                            self.assertGreaterEqual(sig[name], 0.0)
                            self.assertLessEqual(sig[name], 1.0)

    def test_S_in_unit_interval(self):
        for conf in (0, 5, 10):
            for vs in (0, 3, 10):
                for age in (0.0, 45.0, None):
                    for nov in (0.0, 1.0):
                        s, _ = composite_score(
                            bundle(confidence=conf, verified_sessions=vs,
                                   newest_evidence_age_days=age, novelty=nov),
                            DEFAULT_ELIGIBILITY,
                        )
                        self.assertGreaterEqual(s, 0.0)
                        self.assertLessEqual(s, 1.0)


# ---------------------------------------------------------------------------
# Origin gate non-compensability (property sweep)
# ---------------------------------------------------------------------------


class OriginGateTests(unittest.TestCase):
    def test_inferred_below_min_sessions_always_skips_origin(self):
        # legacy_floor_admits off isolates the origin gate; no soft-signal
        # value (conf/recency/novelty) rescues a failing origin.
        cfg = opt(legacy_floor_admits=False)
        for kind in ("learning_add", "learning_supersede"):
            for vs in (0, 1):
                for conf in (5, 6, 7, 8, 9, 10):
                    for nov in (0.0, 0.5, 1.0):
                        for age in (0.0, 5.0, None):
                            b = bundle(kind=kind, confidence=conf, verified_sessions=vs,
                                       evidence_tier="inferred", newest_evidence_age_days=age, novelty=nov)
                            d = evaluate_eligibility(b, cfg)
                            self.assertEqual(d.outcome, "skipped_origin",
                                             msg=f"{kind} vs={vs} conf={conf} nov={nov} age={age}")

    def test_legacy_on_below_floor_still_skips_origin(self):
        # With legacy on but conf below the content floor, add/supersede with a
        # failing origin still skip_origin (legacy escape does not fire).
        cfg = opt()  # legacy on, cfc 8
        for kind in ("learning_add", "learning_supersede"):
            for vs in (0, 1):
                for conf in (5, 6, 7):
                    b = bundle(kind=kind, confidence=conf, verified_sessions=vs,
                               evidence_tier="inferred", newest_evidence_age_days=5.0, novelty=1.0)
                    self.assertEqual(evaluate_eligibility(b, cfg).outcome, "skipped_origin")

    def test_user_corrected_rescues_origin_with_zero_sessions(self):
        # A user-corrected tier passes the origin gate even at 0 verified sessions.
        b = bundle(kind="learning_add", confidence=6, verified_sessions=0,
                   evidence_tier="user-corrected", newest_evidence_age_days=2.0, novelty=0.6)
        d = evaluate_eligibility(b, opt())
        self.assertNotEqual(d.outcome, "skipped_origin")
        self.assertIsNotNone(d.score)

    def test_unknown_tier_fails_origin_like_inferred(self):
        b = bundle(kind="learning_add", confidence=6, verified_sessions=1,
                   evidence_tier="totally-bogus", newest_evidence_age_days=2.0, novelty=0.9)
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "skipped_origin")


# ---------------------------------------------------------------------------
# Legacy escape (per-kind)
# ---------------------------------------------------------------------------


class LegacyEscapeTests(unittest.TestCase):
    def test_add_needs_floor_and_sessions(self):
        # conf>=8 AND vs>=2 -> legacy_floor eligible.
        b = bundle(kind="learning_add", confidence=8, verified_sessions=2, evidence_tier="inferred")
        d = evaluate_eligibility(b, opt())
        self.assertTrue(d.eligible)
        self.assertEqual(d.decision_basis, "legacy_floor")
        self.assertIsNone(d.score)  # legacy path never computes S

    def test_add_floor_without_sessions_falls_to_origin(self):
        b = bundle(kind="learning_add", confidence=9, verified_sessions=1, evidence_tier="inferred")
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "skipped_origin")

    def test_add_below_floor_with_sessions_reaches_composite(self):
        b = bundle(kind="learning_add", confidence=7, verified_sessions=2, evidence_tier="inferred",
                   newest_evidence_age_days=5.0, novelty=0.5)
        d = evaluate_eligibility(b, opt())
        self.assertIsNotNone(d.score)
        self.assertNotEqual(d.decision_basis, "legacy_floor")

    def test_supersede_floor_only(self):
        # supersede at conf>=8 admits on floor alone, even with 0 verified sessions.
        b = bundle(kind="learning_supersede", confidence=8, verified_sessions=0, evidence_tier="inferred")
        d = evaluate_eligibility(b, opt())
        self.assertTrue(d.eligible)
        self.assertEqual(d.decision_basis, "legacy_floor")

    def test_supersede_below_floor_needs_origin(self):
        b = bundle(kind="learning_supersede", confidence=7, verified_sessions=0, evidence_tier="inferred")
        self.assertEqual(evaluate_eligibility(b, opt()).outcome, "skipped_origin")

    def test_legacy_floor_admits_false_disables_step_four_add(self):
        # add conf9 vs2 with legacy off -> reaches composite (basis != legacy_floor).
        b = bundle(kind="learning_add", confidence=9, verified_sessions=2, evidence_tier="inferred",
                   newest_evidence_age_days=5.0, novelty=0.5)
        d = evaluate_eligibility(b, opt(legacy_floor_admits=False))
        self.assertIsNotNone(d.score)
        self.assertNotEqual(d.decision_basis, "legacy_floor")

    def test_legacy_floor_admits_false_disables_step_four_supersede(self):
        # supersede conf9 vs0 inferred: legacy-on would admit; legacy-off -> origin fails.
        b = bundle(kind="learning_supersede", confidence=9, verified_sessions=0, evidence_tier="inferred")
        self.assertTrue(evaluate_eligibility(b, opt()).eligible)  # legacy on admits
        self.assertEqual(evaluate_eligibility(b, opt(legacy_floor_admits=False)).outcome, "skipped_origin")


# ---------------------------------------------------------------------------
# validate_eligibility_config matrix (§3.6)
# ---------------------------------------------------------------------------


class ValidateConfigTests(unittest.TestCase):
    def _bad(self, **elig_overrides):
        ok, errors = validate_eligibility_config(opt(**elig_overrides))
        self.assertFalse(ok)
        self.assertTrue(errors)
        return errors

    def test_default_config_valid(self):
        ok, errors = validate_eligibility_config(opt())
        self.assertTrue(ok, msg=str(errors))
        self.assertEqual(errors, [])

    def test_single_key_override_still_valid_after_defaulting(self):
        # {"eligibility": {"threshold": 0.7}} preserves every sibling default.
        ok, errors = validate_eligibility_config(opt(threshold=0.7))
        self.assertTrue(ok, msg=str(errors))

    def test_static_floor_below_min_fails(self):
        self._bad(static_floor=MIN_STATIC_FLOOR - 1)

    def test_static_floor_above_confidence_floor_content_fails(self):
        ok, errors = validate_eligibility_config(opt(cfc=8, static_floor=9))
        self.assertFalse(ok)
        self.assertTrue(any("confidence_floor_content" in e for e in errors))

    def test_static_floor_at_min_boundary_valid(self):
        ok, _ = validate_eligibility_config(opt(cfc=8, static_floor=MIN_STATIC_FLOOR))
        self.assertTrue(ok)

    def test_static_floor_equal_cfc_valid(self):
        ok, _ = validate_eligibility_config(opt(cfc=6, static_floor=6))
        self.assertTrue(ok)

    def test_static_floor_non_int_fails(self):
        self._bad(static_floor=5.0)

    def test_static_floor_bool_fails(self):
        # bool is an int subclass; must be rejected as a static_floor.
        self._bad(static_floor=True)

    def test_weights_sum_not_one_fails(self):
        self._bad(weights={"confidence": 0.3, "prevalence": 0.3, "recency": 0.3, "novelty": 0.3})

    def test_weights_sum_within_tolerance_valid(self):
        ok, _ = validate_eligibility_config(
            opt(weights={"confidence": 0.4005, "prevalence": 0.2995, "recency": 0.2, "novelty": 0.1})
        )
        self.assertTrue(ok)

    def test_weights_stray_type_prior_key_fails(self):
        errors = self._bad(weights={"confidence": 0.4, "prevalence": 0.3, "recency": 0.2,
                                    "novelty": 0.05, "type_prior": 0.05})
        self.assertTrue(any("weights keys" in e for e in errors))

    def test_weights_missing_key_fails(self):
        self._bad(weights={"confidence": 0.5, "prevalence": 0.3, "recency": 0.2})

    def test_weights_negative_fails(self):
        self._bad(weights={"confidence": -0.1, "prevalence": 0.4, "recency": 0.4, "novelty": 0.3})

    def test_weights_non_number_fails(self):
        self._bad(weights={"confidence": "x", "prevalence": 0.3, "recency": 0.2, "novelty": 0.1})

    def test_weights_bool_value_fails(self):
        self._bad(weights={"confidence": True, "prevalence": 0.3, "recency": 0.2, "novelty": 0.1})

    def test_weights_not_a_dict_fails(self):
        self._bad(weights=[0.4, 0.3, 0.2, 0.1])

    def test_threshold_out_of_range_fails(self):
        self._bad(threshold=1.5)

    def test_threshold_non_number_fails(self):
        self._bad(threshold="high")

    def test_threshold_boundary_zero_and_one_valid(self):
        self.assertTrue(validate_eligibility_config(opt(threshold=0.0))[0])
        self.assertTrue(validate_eligibility_config(opt(threshold=1.0))[0])

    def test_excerpt_match_min_out_of_range_fails(self):
        self._bad(excerpt_match_min=1.2)

    def test_excerpt_match_min_non_number_fails(self):
        self._bad(excerpt_match_min=None)

    def test_prevalence_cap_below_one_fails(self):
        self._bad(prevalence_cap=0)

    def test_prevalence_cap_non_int_fails(self):
        self._bad(prevalence_cap=4.0)

    def test_prevalence_cap_user_corrected_below_one_fails(self):
        self._bad(prevalence_cap_user_corrected=0)

    def test_prevalence_cap_user_corrected_non_int_fails(self):
        self._bad(prevalence_cap_user_corrected="1")

    def test_half_life_non_positive_fails(self):
        self._bad(recency_half_life_days=0)
        self._bad(recency_half_life_days=-5)

    def test_half_life_non_number_fails(self):
        self._bad(recency_half_life_days="30")

    def test_max_transcript_bytes_too_small_fails(self):
        self._bad(max_transcript_bytes=999_999)

    def test_max_transcript_bytes_non_int_fails(self):
        self._bad(max_transcript_bytes=5.0e7)

    def test_enabled_non_bool_fails(self):
        self._bad(enabled="yes")

    def test_legacy_floor_admits_non_bool_fails(self):
        self._bad(legacy_floor_admits=1)

    def test_confidence_floor_content_missing_fails(self):
        o = opt()
        del o["confidence_floor_content"]
        ok, errors = validate_eligibility_config(o)
        self.assertFalse(ok)
        self.assertTrue(any("confidence_floor_content" in e for e in errors))

    def test_confidence_floor_content_non_int_fails(self):
        o = opt()
        o["confidence_floor_content"] = "8"
        self.assertFalse(validate_eligibility_config(o)[0])

    def test_eligibility_block_missing_fails(self):
        ok, errors = validate_eligibility_config({"confidence_floor_content": 8, "add_min_sessions": 2})
        self.assertFalse(ok)
        self.assertTrue(any("eligibility block" in e for e in errors))

    def test_eligibility_block_not_dict_fails(self):
        self.assertFalse(validate_eligibility_config(
            {"confidence_floor_content": 8, "eligibility": []})[0])

    def test_optimistic_not_dict_fails(self):
        ok, errors = validate_eligibility_config(["not", "a", "dict"])
        self.assertFalse(ok)
        self.assertTrue(errors)


# ---------------------------------------------------------------------------
# similarity / normalization pins
# ---------------------------------------------------------------------------


class SimilarityTests(unittest.TestCase):
    def test_normalize_strips_neutralized_wrappers(self):
        self.assertEqual(normalize_content("[neutralized]drop tables[/neutralized]"), "drop tables")

    def test_normalize_lowercases_and_collapses_whitespace(self):
        self.assertEqual(normalize_content("  Hello   WORLD \n Foo\t"), "hello world foo")

    def test_normalize_empty(self):
        self.assertEqual(normalize_content(""), "")
        self.assertEqual(normalize_content("   "), "")

    def test_similarity_identical_is_one(self):
        self.assertEqual(similarity("hello world", "hello world"), 1.0)

    def test_similarity_neutralized_wrapper_matches_raw(self):
        # Stripping the wrapper before comparison -> identical to the raw text.
        self.assertEqual(
            similarity("[neutralized]foo bar baz[/neutralized]", "foo bar baz"), 1.0
        )

    def test_similarity_case_and_whitespace_insensitive(self):
        self.assertEqual(similarity("Foo   Bar", "foo bar"), 1.0)

    def test_similarity_disjoint_is_low(self):
        self.assertLess(similarity("aaaaa", "bbbbb"), 0.5)

    def test_token_jaccard_half(self):
        # {quick,brown,fox} vs {quick,brown,cat} -> 2/4 = 0.5
        self.assertEqual(token_jaccard("quick brown fox", "quick brown cat"), 0.5)

    def test_token_jaccard_stop_words_ignored(self):
        # "the cat" vs "a cat" -> both reduce to {cat} -> 1.0
        self.assertEqual(token_jaccard("the cat", "a cat"), 1.0)

    def test_token_jaccard_both_empty_is_one(self):
        self.assertEqual(token_jaccard("", ""), 1.0)

    def test_token_jaccard_empty_vs_nonempty_is_zero(self):
        self.assertEqual(token_jaccard("", "cat dog"), 0.0)

    def test_similarity_is_max_of_arms(self):
        # Reordered tokens: SequenceMatcher.ratio drops but jaccard stays 1.0,
        # so the max is 1.0.
        self.assertEqual(similarity("alpha beta gamma", "gamma beta alpha"), 1.0)

    def test_novelty_empty_store_is_one(self):
        self.assertEqual(novelty_vs("anything at all", []), 1.0)

    def test_novelty_identical_head_is_zero(self):
        self.assertEqual(novelty_vs("same content here", ["same content here"]), 0.0)

    def test_novelty_takes_max_similarity(self):
        # Nearest head is identical -> novelty 0 regardless of other far heads.
        nov = novelty_vs("target text", ["totally unrelated", "target text", "nope"])
        self.assertEqual(nov, 0.0)

    def test_novelty_partial(self):
        nov = novelty_vs("quick brown fox", ["quick brown cat"])
        # 1 - max(ratio, 0.5); both < 1 -> novelty strictly between 0 and 1.
        self.assertGreater(nov, 0.0)
        self.assertLess(nov, 1.0)


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


class FrozenDataclassTests(unittest.TestCase):
    def test_signal_bundle_frozen(self):
        b = bundle()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            b.confidence = 10  # type: ignore[misc]

    def test_eligibility_decision_frozen(self):
        d = evaluate_eligibility(bundle(), opt())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            d.eligible = False  # type: ignore[misc]

    def test_signal_bundle_is_dataclass(self):
        self.assertTrue(dataclasses.is_dataclass(SignalBundle))
        params = SignalBundle.__dataclass_params__
        self.assertTrue(params.frozen)

    def test_decision_field_names_frozen_contract(self):
        # E3 imports these verbatim -- guard the names.
        names = {f.name for f in dataclasses.fields(EligibilityDecision)}
        self.assertEqual(
            names,
            {"eligible", "outcome", "decision_basis", "score", "threshold",
             "margin", "signals", "weakest_signal"},
        )

    def test_bundle_field_names_frozen_contract(self):
        names = {f.name for f in dataclasses.fields(SignalBundle)}
        self.assertEqual(
            names,
            {"kind", "confidence", "verified_sessions", "evidence_tier",
             "newest_evidence_age_days", "novelty"},
        )


# ---------------------------------------------------------------------------
# weakest_signal + outcome-string stability
# ---------------------------------------------------------------------------


class WeakestSignalTests(unittest.TestCase):
    def test_weakest_is_lowest_normalized_signal(self):
        b = bundle(kind="learning_supersede", confidence=6, verified_sessions=2,
                   evidence_tier="inferred", newest_evidence_age_days=5.0, novelty=0.05)
        d = evaluate_eligibility(b, opt())
        self.assertEqual(d.weakest_signal, "novelty")

    def test_weakest_tie_break_is_canonical_order(self):
        # conf̂=.60 and nov̂=.60 tie for the min; canonical order picks confidence.
        b = bundle(kind="learning_add", confidence=6, verified_sessions=1,
                   evidence_tier="user-corrected", newest_evidence_age_days=2.0, novelty=0.6)
        d = evaluate_eligibility(b, opt())
        self.assertEqual(d.weakest_signal, "confidence")

    def test_outcome_strings_are_the_stable_set(self):
        outcomes = set()
        outcomes.add(evaluate_eligibility(bundle(confidence=3), opt()).outcome)  # floor
        outcomes.add(evaluate_eligibility(
            bundle(kind="learning_add", confidence=6, verified_sessions=1, evidence_tier="inferred"),
            opt()).outcome)  # origin
        outcomes.add(evaluate_eligibility(
            bundle(kind="learning_add", confidence=5, verified_sessions=2, evidence_tier="inferred",
                   newest_evidence_age_days=60.0, novelty=0.1), opt()).outcome)  # composite reject
        outcomes.add(evaluate_eligibility(
            bundle(kind="learning_add", confidence=6, verified_sessions=1, evidence_tier="user-corrected",
                   newest_evidence_age_days=2.0, novelty=0.6), opt()).outcome)  # eligible
        self.assertEqual(outcomes, {"skipped_floor", "skipped_origin", "skipped_composite", "eligible"})

    def test_decision_basis_values(self):
        legacy = evaluate_eligibility(
            bundle(kind="learning_supersede", confidence=8, verified_sessions=0, evidence_tier="inferred"),
            opt())
        composite = evaluate_eligibility(
            bundle(kind="learning_add", confidence=6, verified_sessions=1, evidence_tier="user-corrected",
                   newest_evidence_age_days=2.0, novelty=0.6), opt())
        floor = evaluate_eligibility(bundle(confidence=3), opt())
        self.assertEqual(legacy.decision_basis, "legacy_floor")
        self.assertEqual(composite.decision_basis, "composite")
        self.assertIsNone(floor.decision_basis)


# ---------------------------------------------------------------------------
# AST purity + no-broad-except lints (HARD INVARIANT enforcement)
# ---------------------------------------------------------------------------


class PurityTests(unittest.TestCase):
    ALLOWED_IMPORTS = {"__future__", "dataclasses", "math", "difflib", "re", "typing"}

    def _tree(self):
        return ast.parse(ELIGIBILITY_SRC.read_text(encoding="utf-8"))

    def test_only_allowed_stdlib_imports(self):
        tree = self._tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertIn(top, self.ALLOWED_IMPORTS,
                                  msg=f"disallowed import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                # relative imports (node.level > 0) would reach into the package
                # -- forbidden for a pure module.
                self.assertEqual(node.level, 0, msg="relative import forbidden in pure core")
                top = (node.module or "").split(".")[0]
                self.assertIn(top, self.ALLOWED_IMPORTS,
                              msg=f"disallowed from-import: {node.module}")

    def test_no_dynamic_io_calls(self):
        # AST-level (not substring, so docstrings are ignored): the pure core
        # must not reach I/O dynamically either -- no open()/eval()/exec()/
        # compile()/__import__() call escapes the import allowlist.
        tree = self._tree()
        banned_calls = {"open", "eval", "exec", "compile", "__import__"}
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in banned_calls:
                    offenders.append(node.func.id)
            # Attribute access on a banned I/O root (os.*, subprocess.*, ...);
            # unreachable without an import (guarded above) but asserted anyway.
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in {"os", "subprocess", "socket", "urllib", "pathlib", "shutil"}:
                    offenders.append(f"{node.value.id}.{node.attr}")
        self.assertEqual(offenders, [], msg=f"pure core reaches I/O: {offenders}")

    def test_no_broad_except_returning_nonzero(self):
        # decisions.md #23: no signal computation may catch an exception and
        # return a non-zero default. Flag any except-handler whose body returns
        # a truthy/nonzero constant.
        tree = self._tree()
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Constant):
                    val = child.value.value
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and val != 0:
                        violations.append(ast.dump(child))
                    elif val not in (None, 0, 0.0, False):
                        violations.append(ast.dump(child))
        self.assertEqual(violations, [], msg=f"broad-except nonzero returns: {violations}")

    def test_module_has_no_try_blocks(self):
        # Stronger than the spec: the pure core contains no try/except at all,
        # so a signal error propagates rather than being swallowed.
        tree = self._tree()
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Try)], [])

    def test_min_static_floor_is_four(self):
        self.assertEqual(MIN_STATIC_FLOOR, 4)

    def test_default_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_ELIGIBILITY["weights"].values()), 1.0, places=9)

    def test_default_config_is_valid_and_disabled(self):
        self.assertFalse(DEFAULT_ELIGIBILITY["enabled"])
        ok, errors = validate_eligibility_config(opt())
        self.assertTrue(ok, msg=str(errors))


if __name__ == "__main__":
    unittest.main()
