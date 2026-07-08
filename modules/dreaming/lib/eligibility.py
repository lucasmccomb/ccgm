#!/usr/bin/env python3
"""Pure scoring core for the dreaming optimistic-integration eligibility gate.

This module is the deterministic heart of the composite eligibility gate
described in the composite-eligibility plan (plan.md §3.5). It takes an
already-computed ``SignalBundle`` (scalars in) and returns an
``EligibilityDecision`` (decision out). It performs NO I/O: no filesystem,
no network, no subprocess, and imports nothing beyond the stdlib set
``dataclasses`` / ``math`` / ``difflib`` / ``re`` (plus ``__future__`` for
deferred annotations). The HARD INVARIANT of the dreaming module -- "model
proposes, deterministic rails decide" -- is enforceable here by an AST test
precisely because this file cannot reach the store, the transcripts, or the
network.

Fail-closed doctrine (plan.md §1.4 principle 1, decisions.md #23): a signal
that cannot be computed is 0, never 0.5, and NO signal computation catches an
exception and returns a non-zero default -- it propagates or returns the
signal's floor of 0. This module deliberately contains no ``try``/``except``.

The gatherer (Epic 3, ``apply_dream_proposal.gather_eligibility_signals``)
performs all the I/O -- session resolution, tier re-mining, recency from
embedded timestamps, novelty against the live store's heads -- and hands the
resulting scalars to :func:`evaluate_eligibility`. The only text machinery
that lives here (:func:`similarity`, :func:`novelty_vs`, and the §3.3
normalization) is pure and is called BY the gatherer against the store's
heads; this module never touches the store itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Hard-coded, non-configurable lower bound on the static confidence floor.
# A config whose eligibility.static_floor drops below this fails validation
# closed (plan.md §3.2, §3.6). This is the un-hollowable-by-config floor that
# sits beneath the composite so a config edit cannot admit sub-4 confidence.
MIN_STATIC_FLOOR = 4

# The single, authoritative default config for the eligibility sub-block
# (plan.md §3.6; adrev2-005: E1 is the sole owner of the whole config
# contract). ``dream_analyze.load_config()`` (Epic 2) imports and seeds this;
# E1's own validation tests reference it by import so fixture drift is
# structurally impossible.
#
# Weights rationale (plan.md §3.6):
#   confidence .40 -- the model's own signal; the largest single term, but a
#     minority of the blend and never sufficient alone (it is the ONLY
#     model-assigned scoring input, so its share is deliberately capped).
#   prevalence .30 -- the strongest *verified* signal: distinct
#     transcript-verified cited sessions, which an attacker cannot forge
#     without real on-machine sessions.
#   recency    .20 -- a soft freshness prior over the evidence's own age;
#     backdatable on-machine, so weighted below prevalence and never treated
#     as evidence of origin.
#   novelty    .10 -- informational and attacker-maximizable for adds (or
#     refinement-detecting for supersedes); deliberately the smallest weight.
# threshold θ = 0.58 is calibrated against the plan.md §3.9 worked cases: the
# minimum-viable motivating shape (case (d)) passes at <=15.4 days evidence
# age, while stale junk (case (e)) fails at 0.41. `type` is NOT a scoring
# input (decisions.md #38) -- the blend is four signals, weights sum to 1.0.
DEFAULT_ELIGIBILITY: dict = {
    "enabled": False,
    "static_floor": 5,
    "threshold": 0.58,
    "legacy_floor_admits": True,
    "weights": {
        "confidence": 0.40,
        "prevalence": 0.30,
        "recency": 0.20,
        "novelty": 0.10,
    },
    "prevalence_cap": 4,
    "prevalence_cap_user_corrected": 1,
    "recency_half_life_days": 30,
    "excerpt_match_min": 0.85,
    "max_transcript_bytes": 50000000,
}

# The exact four signal names the weights dict must carry. A stray key
# (e.g. a pre-#38 "type_prior") is a validation FAILURE, catching stale
# configs loudly rather than silently ignoring them (plan.md §3.6).
_WEIGHT_KEYS = ("confidence", "prevalence", "recency", "novelty")

# Deterministic tie-break ordering for weakest_signal selection.
_SIGNAL_ORDER = {name: i for i, name in enumerate(_WEIGHT_KEYS)}

# A small, deterministic stop set for token-Jaccard similarity (plan.md §3.3).
# Kept intentionally small and locale-free.
_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "the", "this", "that", "to",
        "was", "were", "with",
    }
)

# Matches the literal [neutralized] / [/neutralized] wrappers that
# learnings_store.sanitize_content() inserts around injection-shaped text.
# Stripped before any similarity comparison so a sanitized excerpt still
# matches its raw transcript source (plan.md §3.3, §3.4).
_NEUTRALIZED_RE = re.compile(r"\[/?neutralized\]", re.IGNORECASE)

_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+")


# ---------------------------------------------------------------------------
# Frozen contract dataclasses (plan.md §3.5 -- field names are frozen; E3
# imports them verbatim)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalBundle:
    """Already-computed scalars for one proposal (plan.md §3.5).

    Every field is produced deterministically by the gatherer at apply time;
    nothing here is a model-emitted claim except ``confidence`` (the single
    accepted model-assigned scalar).
    """

    kind: str                            # "learning_add" | "learning_supersede"
    confidence: int                      # raw 1-10 from the proposal row
    verified_sessions: int               # §3.4 distinct, transcript-verified count
    evidence_tier: str                   # "user-corrected" | "inferred"
    newest_evidence_age_days: float | None
    novelty: float                       # nov̂, precomputed per-kind (§3.3)


@dataclass(frozen=True)
class EligibilityDecision:
    """The gate's verdict for one proposal (plan.md §3.5).

    ``outcome`` and ``decision_basis`` are a stable, add-only parse contract
    read by the digest, ``/dream-review``, and the weekly scorecard
    (plan.md §1.4).
    """

    eligible: bool
    outcome: str                  # "eligible"|"skipped_floor"|"skipped_origin"|"skipped_composite"
    decision_basis: str | None    # "legacy_floor" | "composite" | None
    score: float | None           # S, when the composite was computed
    threshold: float
    margin: float | None          # S - threshold, when computed
    signals: dict                 # conf̂/prev̂/reĉ/nov̂ as used
    weakest_signal: str | None


# ---------------------------------------------------------------------------
# Pure text helpers (§3.3 content normalization + similarity)
# ---------------------------------------------------------------------------


def normalize_content(text: str) -> str:
    """Normalize text for similarity comparison (plan.md §3.3).

    Lowercase, strip ``[neutralized]``/``[/neutralized]`` wrappers, and
    collapse all runs of whitespace to a single space. Deterministic and
    locale-independent.
    """
    if not text:
        return ""
    stripped = _NEUTRALIZED_RE.sub(" ", text)
    collapsed = _WHITESPACE_RE.sub(" ", stripped)
    return collapsed.strip().lower()


def _tokens(normalized: str) -> set:
    """Content-bearing word tokens (\\w+) of already-normalized text, minus
    the stop set (plan.md §3.3)."""
    return {t for t in _WORD_RE.findall(normalized) if t not in _STOP_WORDS}


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the two texts' stop-filtered token sets.

    Both texts are normalized first. Two empty token sets are treated as
    identical (1.0); an empty set against a non-empty set shares nothing
    (0.0).
    """
    ta = _tokens(normalize_content(a))
    tb = _tokens(normalize_content(b))
    union = ta | tb
    if not union:
        return 1.0
    return len(ta & tb) / len(union)


def similarity(a: str, b: str) -> float:
    """Text similarity in [0, 1] = max(SequenceMatcher.ratio, token_jaccard)
    on normalized text (plan.md §3.3).

    ``SequenceMatcher.ratio`` is the primary, order-sensitive arm;
    ``token_jaccard`` is a set-based floor. Taking the max means a match on
    either arm counts, which is the tolerant behavior the excerpt check and
    novelty both rely on.
    """
    na = normalize_content(a)
    nb = normalize_content(b)
    seq_ratio = SequenceMatcher(None, na, nb).ratio()
    return max(seq_ratio, token_jaccard(a, b))


def novelty_vs(content: str, others: list) -> float:
    """nov̂ = 1 - max(similarity(content, o) for o in others).

    The gatherer calls this against the slug's live heads (learning_add) or
    a single-element list holding the target head's old content
    (learning_supersede). An EMPTY ``others`` yields novelty 1.0 -- an empty
    store makes any content maximally novel (plan.md §3.3, deliberate and
    tested). This helper is pure text machinery: it never touches the store.
    """
    best = 0.0
    for other in others:
        s = similarity(content, other)
        if s > best:
            best = s
    return 1.0 - best


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _recency_score(newest_evidence_age_days: float | None, half_life_days: float) -> float:
    """reĉ = 0.5 ** (age_days / half_life_days); no verified evidence -> 0.

    Two clocks, deliberately non-duplicative (decisions.md #14):
      * This score decays the EVIDENCE's age at admission with a 30-day
        half-life -- "how fresh is the observation this memory rests on?"
      * ``learnings_store.effective_confidence()`` separately decays an
        ALREADY-ADMITTED row by ITS OWN age with a 90-day half-life -- "how
        old is this memory now?"
    They measure different ages against different clocks; scoring evidence
    recency here does not double-count the store's own read-time decay.

    A ``None`` age (no verified session, or an oversized transcript whose
    recency was forced to 0 per §3.4) scores 0 -- fail toward the weakest
    value, never a 0.5 default.
    """
    if newest_evidence_age_days is None:
        return 0.0
    return 0.5 ** (newest_evidence_age_days / half_life_days)


# ---------------------------------------------------------------------------
# Composite score (§3.3 normalized signals -> S)
# ---------------------------------------------------------------------------


def composite_score(bundle: SignalBundle, elig_cfg: dict) -> tuple[float, dict]:
    """Compute S = Σ wᵢ·signal̂ᵢ and return (S, normalized-signals dict).

    ``elig_cfg`` is the (already-validated, already-defaulted) eligibility
    sub-block. Each normalized signal is in [0, 1]; the weights sum to 1, so
    S is in [0, 1] and each signal's contribution is bounded by its weight.
    """
    weights = elig_cfg["weights"]

    conf_hat = _clamp(bundle.confidence, 0, 10) / 10.0

    # Prevalence cap tightens to 1 for a user-corrected tier: a single
    # human-verified corrective session saturates prevalence, so multi-session
    # dilution is not required on top of a genuine origin signal (§3.3).
    if bundle.evidence_tier == "user-corrected":
        cap = elig_cfg["prevalence_cap_user_corrected"]
    else:
        cap = elig_cfg["prevalence_cap"]
    prev_hat = _clamp(min(bundle.verified_sessions, cap) / cap, 0.0, 1.0)

    rec_hat = _recency_score(bundle.newest_evidence_age_days, elig_cfg["recency_half_life_days"])

    nov_hat = _clamp(bundle.novelty, 0.0, 1.0)

    signals = {
        "confidence": conf_hat,
        "prevalence": prev_hat,
        "recency": rec_hat,
        "novelty": nov_hat,
    }
    score = sum(weights[name] * signals[name] for name in _WEIGHT_KEYS)
    return score, signals


def _weakest_signal(signals: dict) -> str:
    """The signal name with the smallest normalized value, tie-broken by the
    canonical signal order for determinism."""
    return min(signals, key=lambda name: (signals[name], _SIGNAL_ORDER[name]))


# ---------------------------------------------------------------------------
# Gate waterfall (plan.md §3.2 steps 2, 4, 5, 6)
# ---------------------------------------------------------------------------


def evaluate_eligibility(bundle: SignalBundle, optimistic: dict) -> EligibilityDecision:
    """Run the enabled-mode waterfall for a ``learning_add`` /
    ``learning_supersede`` proposal and return the decision (plan.md §3.2).

    The caller (Epic 3) is responsible for steps 0-1 (posture resolution,
    config-invalid/disabled -> legacy path) and for gathering the bundle;
    this function owns steps 2, 4, 5, 6. It reads the eligibility sub-block
    plus ``confidence_floor_content`` and ``add_min_sessions`` from the whole
    merged ``optimistic`` dict.
    """
    elig = optimistic["eligibility"]
    threshold = elig["threshold"]
    static_floor = elig["static_floor"]
    legacy_floor_admits = elig["legacy_floor_admits"]
    confidence_floor_content = optimistic["confidence_floor_content"]
    add_min_sessions = optimistic["add_min_sessions"]

    # Step 2: STATIC FLOOR (strict <, matching legacy).
    if bundle.confidence < static_floor:
        return EligibilityDecision(
            eligible=False,
            outcome="skipped_floor",
            decision_basis=None,
            score=None,
            threshold=threshold,
            margin=None,
            signals={},
            weakest_signal=None,
        )

    # Step 4: LEGACY ESCAPE (per-kind; disabled when legacy_floor_admits=false).
    # add       -> reproduces BOTH legacy conditions (floor AND session count)
    #              so an inferred-once conf-9 add stays rejected as today.
    # supersede -> legacy truly has no session check, so floor-only is faithful.
    if legacy_floor_admits:
        if bundle.kind == "learning_add":
            if bundle.confidence >= confidence_floor_content and bundle.verified_sessions >= add_min_sessions:
                return _legacy_eligible(threshold)
        elif bundle.kind == "learning_supersede":
            if bundle.confidence >= confidence_floor_content:
                return _legacy_eligible(threshold)

    # Step 5: ORIGIN GATE (non-compensatory -- no soft-signal value rescues it).
    # An unknown evidence_tier string is not "user-corrected", so it fails
    # this arm and falls through to the session-count arm: fail-closed.
    origin_ok = (bundle.evidence_tier == "user-corrected") or (bundle.verified_sessions >= add_min_sessions)
    if not origin_ok:
        return EligibilityDecision(
            eligible=False,
            outcome="skipped_origin",
            decision_basis=None,
            score=None,
            threshold=threshold,
            margin=None,
            signals={},
            weakest_signal=None,
        )

    # Step 6: COMPOSITE (S >= threshold admits).
    score, signals = composite_score(bundle, elig)
    margin = score - threshold
    weakest = _weakest_signal(signals)
    if score >= threshold:
        return EligibilityDecision(
            eligible=True,
            outcome="eligible",
            decision_basis="composite",
            score=score,
            threshold=threshold,
            margin=margin,
            signals=signals,
            weakest_signal=weakest,
        )
    return EligibilityDecision(
        eligible=False,
        outcome="skipped_composite",
        decision_basis=None,
        score=score,
        threshold=threshold,
        margin=margin,
        signals=signals,
        weakest_signal=weakest,
    )


def _legacy_eligible(threshold: float) -> EligibilityDecision:
    return EligibilityDecision(
        eligible=True,
        outcome="eligible",
        decision_basis="legacy_floor",
        score=None,
        threshold=threshold,
        margin=None,
        signals={},
        weakest_signal=None,
    )


# ---------------------------------------------------------------------------
# Config validation (§3.6; runs AFTER defaulting, fail-closed)
# ---------------------------------------------------------------------------


def validate_eligibility_config(optimistic: dict) -> tuple[bool, list]:
    """Validate the eligibility sub-block of a merged ``optimistic`` dict.

    Runs AFTER defaulting (the caller seeds :data:`DEFAULT_ELIGIBILITY` then
    overlays the user's block). Returns ``(ok, errors)``; ANY failure means
    the caller treats eligibility as disabled (plan.md §3.6, decisions.md
    #18/#22). Takes the whole merged optimistic dict because the
    ``static_floor <= confidence_floor_content`` bound is cross-field.

    Checks (plan.md §3.6):
      * every key type-checked;
      * weights: keys EXACTLY the four signal names (a stray ``type_prior``
        fails), each a number >= 0, sum = 1 ± 0.001;
      * threshold ∈ [0, 1]; excerpt_match_min ∈ [0, 1];
      * prevalence caps integers >= 1; half-life a number > 0;
      * max_transcript_bytes an integer >= 1_000_000;
      * MIN_STATIC_FLOOR <= static_floor <= confidence_floor_content.
    """
    errors: list = []

    if not isinstance(optimistic, dict):
        return False, ["optimistic config is not a dict"]

    elig = optimistic.get("eligibility")
    if not isinstance(elig, dict):
        return False, ["eligibility block is missing or not a dict"]

    # enabled
    if not isinstance(elig.get("enabled"), bool):
        errors.append("eligibility.enabled must be a bool")

    # legacy_floor_admits
    if not isinstance(elig.get("legacy_floor_admits"), bool):
        errors.append("eligibility.legacy_floor_admits must be a bool")

    # static_floor (int; cross-field bound applied below)
    static_floor = elig.get("static_floor")
    if not _is_int(static_floor):
        errors.append("eligibility.static_floor must be an int")

    # threshold ∈ [0, 1]
    threshold = elig.get("threshold")
    if not _is_number(threshold):
        errors.append("eligibility.threshold must be a number")
    elif not (0.0 <= threshold <= 1.0):
        errors.append("eligibility.threshold must be in [0, 1]")

    # excerpt_match_min ∈ [0, 1]
    emm = elig.get("excerpt_match_min")
    if not _is_number(emm):
        errors.append("eligibility.excerpt_match_min must be a number")
    elif not (0.0 <= emm <= 1.0):
        errors.append("eligibility.excerpt_match_min must be in [0, 1]")

    # prevalence caps (ints >= 1)
    for key in ("prevalence_cap", "prevalence_cap_user_corrected"):
        val = elig.get(key)
        if not _is_int(val):
            errors.append(f"eligibility.{key} must be an int")
        elif val < 1:
            errors.append(f"eligibility.{key} must be >= 1")

    # recency_half_life_days (number > 0)
    hl = elig.get("recency_half_life_days")
    if not _is_number(hl):
        errors.append("eligibility.recency_half_life_days must be a number")
    elif hl <= 0:
        errors.append("eligibility.recency_half_life_days must be > 0")

    # max_transcript_bytes (int >= 1_000_000)
    mtb = elig.get("max_transcript_bytes")
    if not _is_int(mtb):
        errors.append("eligibility.max_transcript_bytes must be an int")
    elif mtb < 1_000_000:
        errors.append("eligibility.max_transcript_bytes must be >= 1_000_000")

    # weights: exactly the four signal names, each number >= 0, sum = 1 ± 0.001
    weights = elig.get("weights")
    if not isinstance(weights, dict):
        errors.append("eligibility.weights must be a dict")
    else:
        if set(weights.keys()) != set(_WEIGHT_KEYS):
            errors.append(
                "eligibility.weights keys must be exactly "
                f"{sorted(_WEIGHT_KEYS)} (got {sorted(weights.keys())})"
            )
        bad_weight = False
        for name, w in weights.items():
            if not _is_number(w):
                errors.append(f"eligibility.weights[{name!r}] must be a number")
                bad_weight = True
            elif w < 0:
                errors.append(f"eligibility.weights[{name!r}] must be >= 0")
                bad_weight = True
        if not bad_weight:
            total = sum(weights[name] for name in weights)
            if abs(total - 1.0) > 0.001:
                errors.append(f"eligibility.weights must sum to 1 ± 0.001 (got {total})")

    # Cross-field: MIN_STATIC_FLOOR <= static_floor <= confidence_floor_content
    cfc = optimistic.get("confidence_floor_content")
    if not _is_int(cfc):
        errors.append("confidence_floor_content must be an int")
    if _is_int(static_floor):
        if static_floor < MIN_STATIC_FLOOR:
            errors.append(
                f"eligibility.static_floor ({static_floor}) must be >= MIN_STATIC_FLOOR ({MIN_STATIC_FLOOR})"
            )
        if _is_int(cfc) and static_floor > cfc:
            errors.append(
                f"eligibility.static_floor ({static_floor}) must be <= confidence_floor_content ({cfc})"
            )

    return (not errors), errors
