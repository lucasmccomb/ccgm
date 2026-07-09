# Composite Eligibility Gate — Adversarial Poisoning Analysis

**Status: shipped, default-off.** The composite eligibility gate is inert until an operator
opts in on their own machine (`optimistic_integration.eligibility.enabled = true`, plus the outer
`optimistic_integration.enabled`). This document analyzes the gate's poisoning resistance *when
enabled*, for the two op-kinds it scopes — `learning_add` and `learning_supersede`. Evictions
(`learning_contradict` / `learning_deprecate`), `learning_verify`, and `_global` promotion are out
of scope and keep today's rails bit-for-bit.

**Honesty rule (decisions.md #17).** This analysis never claims a residual is "fixed." Where the
gate does not close a gap, it says so plainly and, where possible, encodes the residual in an
executable test so a future "hardening" that silently changes the behavior is caught. Overclaiming
is a defect, not a nicety.

**Every code-behavior claim below cites a test that proves it**, in `file::Class::test` form so a
reader can `grep`-and-run it. A citation index is at the end. All cited tests live under
`modules/dreaming/tests/` and `modules/self-improving/tests/` and pass on the shipped code.

---

## 1. Threat model

CCGM's dreaming module runs on a single operator's machine. There is no network trust boundary
inside the write decision (the gate makes no LLM or network call — that is the module's HARD
INVARIANT), so the threat model is about who can influence the *inputs* the deterministic gate
reads, and what the gate refuses to trust.

### 1.1 Who writes the transcripts

Transcripts under `~/.claude/projects/**` are written by Claude Code sessions running as the
operator's own OS user. Any agent in any session — benign, buggy, or prompt-injected by content it
read (a `WebFetch`'d page, an MCP tool result, a `Read` file, a subagent `Task` result) — can:

- emit arbitrary text into a transcript it is running in;
- read any existing transcript (`ls ~/.claude/projects/*/*.jsonl` is trivial);
- edit any transcript file's bytes, including embedded per-line `timestamp` fields, or `touch` its
  mtime — there is no integrity binding (no HMAC/signature/checksum) anywhere in the module.

What an on-machine actor **cannot** cheaply do is *manufacture a genuinely distinct, real,
slug-matching session that independently corroborates a claim* — that requires actually running
separate sessions in the target project, which is the real cost the origin gate charges.

### 1.2 What the reduce LLM controls

The nightly analyze step's reduce-phase LLM call authors proposal rows. By the module's own poisoning
doctrine the reduce output is **fully untrusted**. It controls:

- `content`, `type`, `justification`, `confidence` (the integer), `prevalence` (the claimed counts),
  and the `evidence[]` array's `session_id`/`excerpt` pairs;
- any *stamped* fields (`evidence_tier`, `stamped_signals`, `evidence[].started_at`) — these are
  written by deterministic post-reduce code from the mining bundle, but a malicious row on disk
  could carry forged values.

The gate structurally refuses to read the stamped fields as scoring input: `gather_eligibility_signals()`
takes the **bare** row (session_id/excerpt pairs + row scalars) and has **no parameter** for
`evidence_tier`/`stamped_signals`, so a future edit cannot wire trust in by accident (decisions.md
#20). Everything except the single `confidence` integer and the schema-constrained `kind` is
recomputed at apply time from the verified transcript files and the live store.

**Confidence is the one exception**: it is the only model-assigned scalar the gate consumes as-is,
with no deterministic cross-check. This is inherited from the pre-existing flat floor and is the
headline residual (§3.1).

### 1.3 What config trusts

The eligibility sub-block (`~/.claude/dreaming/config.json` → `optimistic_integration.eligibility`)
is operator-owned. It cannot hollow out the safety floor: `MIN_STATIC_FLOOR = 4` is hard-coded in
`eligibility.py`, non-configurable, and a config with `static_floor < 4` fails validation *closed*
(eligibility treated as disabled, legacy path). `validate_eligibility_config()` runs after
defaulting and rejects every malformed shape (bad types, weights not summing to 1, a stray
pre-#38 `type_prior` weight key, out-of-range threshold/caps/half-life).

Proof: `test_eligibility.py::ValidateConfigTests::test_static_floor_below_min_fails`;
`test_eligibility.py::PurityTests::test_only_allowed_stdlib_imports` (no I/O/network/LLM imports in
the pure core, so no signal function can smuggle in a trust source).

### 1.4 Attacker goal and success condition

The attacker wants a poisoned memory **auto-integrated** (written live, or written dwelling and later
live) into the learnings store without a human accept. "Success" is an `eligible` decision. Anything
that lands `skipped_floor` / `skipped_origin` / `skipped_composite` / `internal_error` leaves the row
`pending` for human `/dream-apply` — the attack failed to auto-integrate. Downstream rails (dwell,
per-run caps, batch anomaly, circuit breaker, read-time decay, `/dream-review`) apply *after*
eligibility and are unchanged by this work (§5).

---

## 2. Per-signal forgeability table

This lifts and updates the security review's table (`reviews/security.md`) to the shipped 4-signal
design. Two changes from that review's five-signal sketch: **`type_prior` was removed entirely**
(decisions.md #38 — it is no longer a signal; see §3.6) and the weights were re-tuned to
`{confidence .40, prevalence .30, recency .20, novelty .10}` with threshold θ = 0.58. The
mitigations column reflects code that shipped, not a sketch.

| Signal | Weight | Attacker capability required | Cost to forge | Shipped mitigation | Residual after mitigation |
|---|---|---|---|---|---|
| `confidence` (conf̂) | 0.40 (largest) | Influence the reduce LLM's self-reported integer (injected text it reads, or miscalibration) | Near-zero — no crafted session structure, just text the model reads | None — it is the only model-assigned scoring input, used as-is, and it also gates the step-4 legacy escape which runs **before** the origin gate | **Full.** conf≥8 gains no new protection (headline residual, §3.1). For `add` the legacy escape additionally requires ≥2 *verified* sessions now (strictly harder than the model integer legacy trusted); for `supersede` it is floor-only. |
| `verified_sessions` / prevalence (prev̂) | 0.30 | Cite ≥ `add_min_sessions` (2) session_ids that pass §3.4's three-part check each | High — each must **resolve** to a real transcript, **slug-match** the proposal's project, and carry an **excerpt-corroborating** window; distinct ids only | Three-part verification (decisions.md #16), reusing `resolve_session_transcript()`; distinctness dedup; per-batch session-citation anomaly detector | On-machine actor who actually runs ≥2 real, on-topic sessions clears it — but that is the genuine cost the origin gate is designed to charge, not a cheap forgery. |
| `evidence_tier == "user-corrected"` (origin-gate escape) | n/a (gate, not weighted) | A **human-origin** turn (`origin.kind=="human"` / `promptSource=="typed"`) carrying a negation phrase within 2 turns of friction, in a resolvable+slug-matched+excerpt-corroborated cited session | Higher than pre-fix — a synthetic `tool_result`/notification turn no longer qualifies (E2's human-origin filter); requires a genuinely human-typed correction | Miner correction extraction restricted to human-origin turns (decisions.md #15); tier recomputed at apply time, never read from the row | A human-typed correction *inside an attacker-influenced session* still mints the tier; and the tier is **session-scoped, not claim-scoped** (adrev-006) — a real correction about topic X mints the tier for an unrelated memory Y from the same session. Both documented in §3.3 / §6. |
| `recency` (reĉ) | 0.20 | Hand-edit a cited transcript's embedded per-line `timestamp`, or `touch` its mtime | Low for an on-machine actor — no integrity binding on transcript bytes | Read from embedded per-line timestamps (never mtime), re-derived at apply; weighted below prevalence; never gate-opening | **Backdatable.** An on-machine actor can set evidence age ≈ 0 to award reĉ ≈ 1.0. Soft tiebreaker, never evidence (§3.4, adrev-005/R4). |
| `novelty` (nov̂) | 0.10 (smallest) | `add`: maximize by making content dissimilar to live heads. `supersede`: near-duplicate the target to *minimize* it | Free for `add` (content is model-controlled); for `supersede`, a near-dup *lowers* it and also trips the advisory flag | `add`: 1 − max-sim vs live heads. `supersede`: 1 − sim vs the **target's own old content** (decisions.md #39) + a near-dup digest flag | Soft 0.10-weight term, never a block. A fresh, well-verified `add` in a sparse store gets nov̂ ≈ 1.0 "for free" (adrev-009 non-stationarity, §6). A near-dup `supersede` "pays twice" (low nov̂ + flag) but is still not hard-blocked (§3.7). |
| ~~`type_prior`~~ | **removed** | — | — | **Not a signal.** `type` is on the row and in the digest for human review, but has **zero** effect on any score or decision | The A-MAC type-prior transfer was retracted (§3.6); `type` cannot influence a decision even by future accident. Proof: `test_eligibility_redteam.py::TypeNeutralityTests::test_no_type_input_exists_on_bundle_or_weights`. |

---

## 3. Attack walkthroughs

Each walkthrough states the attack, its cost, the shipped defense (with a proving test), and the
honest residual.

### 3.1 Confidence inflation — the HEADLINE residual

**Attack.** Inject text into a mined transcript so the reduce LLM self-reports a high `confidence`
(≥ `confidence_floor_content`, default 8). Confidence is the only model-assigned scoring input and
has no deterministic cross-check.

**Cost.** Near-zero. No crafted session structure — just text the reduce model reads.

**What the gate does — and does not — do.** The legacy escape (waterfall step 4) runs **before** the
origin gate (step 5). A `conf ≥ 8` proposal that satisfies the escape is admitted with
`decision_basis="legacy_floor"` and never reaches the origin gate or the composite. So:

- **`learning_supersede`, conf ≥ 8**: admitted floor-only, with **no** origin requirement — *exactly
  as forgeable as today*. The composite adds **zero** protection to this band. Proof (residual
  encoded, not hidden): `test_eligibility_redteam.py::ConfidenceInflationTests::test_conf8_supersede_admits_via_legacy_floor_residual`.
- **`learning_add`, conf ≥ 8**: the escape reproduces **both** legacy conditions — `conf ≥ floor`
  **and** `verified_sessions ≥ add_min_sessions`. Crucially, that session count is now the
  *transcript-verified* count (§3.4), where legacy trusted the model-claimed
  `prevalence.sessions` integer. So confidence inflation alone does **not** admit a single-session
  add: a conf-10 lone inferred add is rejected at the origin gate. Proof:
  `test_eligibility_redteam.py::ConfidenceInflationTests::test_conf10_single_session_inferred_add_rejected`;
  `test_eligibility_parity.py::TargetBehaviorMatrixTests::test_f_conf9_1sess_inferred_skipped_origin`;
  `test_eligibility.py::WorkedCaseTests::test_case_f_add_conf9_inferred_1sess_skips_origin`. For a
  conf-8 add with two *real* verified sessions, the escape does fire (that is legacy behavior
  preserved): `test_eligibility_gate.py::OutcomeTests::test_conf8_multi_session_legacy_escape`.

**Residual (stated plainly).** For the conf ≥ 8 band this change fixes nothing on the `supersede`
side, and on the `add` side it is *strictly harder* than legacy only insofar as the second session
must now be transcript-verified rather than a model integer. Confidence inflation remains the single
cheapest, least-defended attack lever after this plan ships. The documented (non-default) mitigation
is the strict-mode knob `legacy_floor_admits: false`, which makes the origin gate bind the conf ≥ 8
band too. Proof it works: `test_eligibility_redteam.py::ConfidenceInflationTests::test_strict_mode_binds_conf8_supersede_to_origin_gate`.

### 3.2 Session padding

**Attack.** Fake `verified_sessions ≥ add_min_sessions` by stuffing `evidence[]` with cheap
citations: a made-up `session_id`, an unrelated real session filename, the same real session cited
several times, or a real session cited with a fabricated excerpt.

**Cost.** Near-zero to *attempt* — session filenames are enumerable and the reduce output is
untrusted.

**Defense.** Each cited session must pass all three of §3.4's checks to count, and duplicates dedupe
to a set:

- unresolvable id → not counted: `test_eligibility_gate.py::SessionVerificationMatrixTests::test_unresolvable_session_not_counted`;
- wrong slug → not counted: `...::test_slug_mismatch_not_counted`;
- garbage / non-corroborating excerpt → not counted: `...::test_garbage_excerpt_not_counted`;
- one real session cited twice → counted once: `...::test_duplicate_citation_counts_once`;
- null/empty session_id → excluded from counts and recency: `...::test_null_session_excluded`.

The composed attack (unresolvable + wrong-slug + excerpt-less citations stacked to fake prevalence,
and one real session cited thrice) is red-teamed end-to-end and yields `skipped_origin`:
`test_eligibility_redteam.py::SessionPaddingAttackTests::test_padding_unresolvable_wrongslug_excerptless_fails_origin`,
`...::test_one_real_session_cited_thrice_still_fails_origin`. A session cited across an unusual number
of proposals in one batch additionally feeds the circuit-breaker anomaly path:
`test_eligibility_gate.py::SessionCitationAnomalyTests::test_at_threshold_fires_and_feeds_breaker_path`.

**Residual.** An on-machine actor who *actually runs* ≥2 real, on-topic sessions clears the breadth
gate — but that is the intended cost, not a forgery. The excerpt-corroboration check itself is
copy-paste-forgeable by an actor who can read the cited transcript (§6, adrev2-003 residual) — the
anti-coincidence guards restore size-independence but do not defeat an on-machine reader; this is
inherent to the solo threat model and unchanged from the exact-substring check it replaced.

### 3.3 Correction forging (the `user-corrected` tier)

**Attack.** The `user-corrected` tier is the highest-trust origin-gate escape — it passes the origin
gate with a *single* session (and saturates the prevalence cap to 1). Pre-fix, the miner counted any
`type:"user"` turn, so a synthetic `tool_result` echo or a system notification containing one of the
21 negation phrases (common words like "incorrect" appear in ordinary linter/traceback output)
minted the tier with zero human interaction.

**Cost.** Pre-fix: one self-run session. Post-fix: a genuinely human-typed correction turn.

**Defense.** E2 restricts correction extraction to human-origin turns (`origin.kind=="human"` /
`promptSource=="typed"`), and the tier is recomputed at apply time by re-running the filtered
extractor on the cited transcript — the reduce LLM cannot set it, and a forged `evidence_tier` on
the row is ignored:

- tool_result-only negation → no correction (miner): `test_transcript_miner.py::CorrectionOriginFilterTests::test_negation_in_tool_result_turn_is_not_a_correction`;
- human-origin / typed turn → correction: `...::test_origin_kind_human_turn_mints_correction`, `...::test_prompt_source_typed_turn_mints_correction`;
- missing origin fields → fail closed: `...::test_missing_origin_fields_fail_closed`;
- at the gate, a human-origin correction mints the tier: `test_eligibility_gate.py::TierTests::test_human_origin_correction_mints_user_corrected`;
- a tool_result-only correction stays `inferred`: `...::test_tool_result_only_correction_stays_inferred`;
- a **forged** `evidence_tier="user-corrected"` + forged `stamped_signals` on a correction-free
  transcript is recomputed to `inferred` → `skipped_origin`:
  `test_eligibility_gate.py::TierTests::test_forged_stamped_fields_ignored_skipped_origin`, and the
  composed attack variant `test_eligibility_redteam.py::ForgedTierAttackTests::test_forged_tier_and_stamped_signals_are_recomputed_skipped_origin`.

**Residuals (two, stated plainly).**

1. A human-typed correction *inside an attacker-influenced session* still mints the tier. If an
   injected prompt convinces the operator to type a corrective phrase, the miner correctly records a
   real human correction — the filter cannot distinguish a manipulated human from a spontaneous one.
   Tier alone only *opens* the origin gate; the composite and static floor still apply, and the
   solo-operator threat model bounds this.
2. **Session-scoped, not claim-scoped (adrev-006).** The tier is minted if the *session* contains any
   human correction — not necessarily one about the memory being admitted. A genuine correction about
   topic X mints `user-corrected` for an unrelated conf-6 memory Y proposed from the same session,
   weakening the tier↔usefulness correlation that justifies the single-session pass and the
   tier-aware prevalence cap. Binding the correction excerpt to the proposal's cited evidence is a
   possible future tightening; it is **not** implemented, and citing "the composite still applies" is
   not a sufficient answer for this residual.

### 3.4 Recency backdating

**Attack.** Set a cited transcript's embedded per-line `timestamp` (or its mtime) to "now" so the
evidence looks maximally fresh, awarding reĉ ≈ 1.0.

**Cost.** Low for an on-machine actor — transcript bytes carry no integrity binding.

**Defense (partial, by design).** Recency is read from embedded per-line timestamps (never mtime),
re-derived at apply time, and — deliberately — carries only weight **0.20** and never opens the
origin gate. Its 30-day half-life scores the *evidence's* age; it is a different clock from the
store's own read-time `effective_confidence()` decay (90-day half-life on the admitted row's age),
so the two are non-duplicative (decisions.md #14). An oversized transcript forces recency to 0 (fail
toward weakest): `test_eligibility_gate.py::SessionVerificationMatrixTests::test_oversized_transcript_counts_but_tier_inferred_recency_zero`.

**Residual (stated plainly).** Recency is a **soft, on-machine-forgeable tiebreaker, not evidence**
(adrev-005/R4). The design does not claim otherwise. Its low weight caps the blast radius; the origin
gate, not recency, is the barrier.

### 3.5 Novelty gaming

**Attack (add).** Maximize nov̂ by making `content` dissimilar to every live head — trivial, since
content is model-controlled.

**Cost.** Free for `add`.

**Defense.** nov̂ is the smallest weight (0.10) and **cannot rescue a failing origin** — it is a soft
term evaluated only *after* the non-compensatory origin gate passes. Maximizing every soft signal
(conf, recency, novelty) at once never admits a weak-origin proposal:
`test_eligibility_redteam.py::NonCompensabilityTests::test_maxed_soft_signals_never_rescue_a_weak_origin`
(property sweep over kind × verified_sessions∈{0,1} × conf 5-10 × novelty × age, all →
`skipped_origin`); `test_eligibility.py::OriginGateTests::test_inferred_below_min_sessions_always_skips_origin`.
Empty-store novelty is a deliberate, tested 1.0: `test_eligibility_gate.py::NoveltyTests::test_add_empty_store_novelty_one`.

**Residual.** nov̂ is store-density-dependent and non-stationary (adrev-009, §6): in a sparse store it
is ≈1.0 "for free" and effectively lowers θ; in a dense store it trends toward 0 for refinements. It
is informational, not a barrier.

### 3.6 Type self-selection — now inert (A-MAC transfer correction)

**Attack (historical).** Under the pre-#38 five-signal design the model could self-select the
highest-`type_prior` enum (e.g. `pitfall`, prior 1.0) to inflate S by up to its weight, with no
cross-check against content plausibility.

**Status: the signal was removed.** decisions.md #38 (reversing the earlier decision #4) **drops
`type_prior` entirely.** `type` remains on proposal rows and in the digest for human review but is
**not a scoring input** — it cannot influence any score or decision.

- Two proposals identical except `type` (specifically `pitfall` vs `preference`, the extreme ends of
  the removed prior table) produce **byte-identical** `EligibilityDecision`s and identical
  `SignalBundle`s: `test_eligibility_redteam.py::TypeNeutralityTests::test_type_has_zero_effect_on_the_decision_and_bundle`.
- Structurally, neither the pure `SignalBundle` nor the default `weights` expose a `type`/`type_prior`
  field, so `type` cannot influence a score even by future accident:
  `test_eligibility_redteam.py::TypeNeutralityTests::test_no_type_input_exists_on_bundle_or_weights`. A
  stray `type_prior` weight key in a user config fails validation loudly:
  `test_eligibility.py::ValidateConfigTests` (weights-keys-exactly-four check).

**The A-MAC transfer correction (adrev2-004, decisions.md #38).** Research finding KI-1 originally
adopted A-MAC's result that the categorical *type-prior* is the dominant admission discriminator
(ΔF1 ≈ −0.107, ~4× any other axis). That result **assumed an honest label** produced by the dataset
pipeline. It does **not** transfer to CCGM, where `type` is chosen by the untrusted proposer: a
dominant discriminator on honest labels becomes a free, model-controlled lever on adversarial ones.
Rather than carry a bounded-but-model-controlled term (worst-case ≈ +0.06 to S) plus a 6-key
never-retuned config table for ~zero honest discrimination, the signal was removed. Dropping it also
lowered the model-controlled share of the blend from 50% (conf̂+typê) to 40% (conf̂ alone). This is
the honest correction of the research's rationale, not a claim the original research was applied.

### 3.7 Near-duplicate supersede

**Attack.** Take a real, trusted head and supersede it with 0.95+-similar text carrying one flipped
fact (a port number, a credential-handling instruction, a security-relevant claim). `add`-style
novelty (vs *other* heads) would score this ≈1.0 "novel" and never notice.

**Cost.** Low — the attacker reuses a real head's wording.

**Defense.** For `supersede`, nov̂ is computed against the **target's own old content** (decisions.md
#39), so a near-duplicate scores nov̂ ≈ 0, and a separate advisory digest flag fires when
`similarity(content, target) ≥ 0.9` **and** the fact-token set changed (reusing
`compact_preserves_facts`'s token machinery). The same fixture fires both — the attack "pays twice":
`test_eligibility_redteam.py::SupersedeNearDupAttackTests::test_near_dup_fact_flip_scores_low_novelty_and_trips_flag`
(sim ≥ 0.95 → nov̂ ≤ 0.05 **and** the flag). Directional checks:
`test_eligibility_gate.py::NearDupSupersedeTests::test_near_dup_fact_flip_flagged` and
`...::test_substantive_update_not_flagged`; a substantive rewrite is eligible while a cosmetic conf-6
refinement routes to pending (`test_eligibility_parity.py::TargetBehaviorMatrixTests::test_h_supersede_near_dup_skipped_composite`,
`...::test_i_supersede_substantive_eligible_composite`).

**Residual (stated plainly).** The near-dup flag is **advisory — it never blocks**, and nov̂ is a soft
0.10-weight term, not a hard gate. A conf ≥ 8 near-dup escapes on the legacy floor *before* novelty
is ever scored, yet is still flagged for human review — the composite *surfaced* the high-confidence
corruption, it did not fix it: `test_eligibility_redteam.py::SupersedeNearDupAttackTests::test_conf8_near_dup_admits_via_legacy_but_flag_still_fires_residual`.
Even below conf 8, a *fresh, well-verified* near-dup can clear θ (the ≈0.06 novelty dock is not
decisive on its own); the advisory flag, the dwell window, and `/dream-review` are the real catches,
not the score.

---

## 4. The no-easier-than-flat-floor argument

**Claim.** Enabling the composite adds no attack path cheaper than the cheapest path that already
existed against the flat floor.

**Structure.** The enabled-mode admission set decomposes as:

```
enabled_admits  =  legacy_surface  ∪  new_surface
```

- **`legacy_surface`** — the conf ≥ `confidence_floor_content` legacy escape (step 4), default-on via
  `legacy_floor_admits`. Its cheapest lever is **confidence inflation** (§3.1), unchanged. But it is
  never *weaker* than legacy on this path:
  - for `learning_add`, the escape reproduces **both** legacy conditions and the session count is now
    *transcript-verified* rather than a model-claimed integer — i.e. **strictly harder** on the
    forged-evidence axis;
  - for `learning_supersede`, legacy truly had no session check, so floor-only is faithful (no
    change, no regression).
- **`new_surface`** — the conf 5-7 band, which the flat floor rejected outright. Every entry here must
  pass the **non-compensatory origin gate**: a real human correction (`user-corrected` tier) **or**
  ≥2 *verified, relevant* sessions. That is **categorically more expensive** than confidence
  inflation — it costs real on-machine evidence, not a model integer. Soft signals cannot substitute
  for it (§3.5 non-compensability sweep).

Therefore every newly-admitted class (the conf 5-7 band) is *harder* to forge than the pre-existing
cheapest path, and the pre-existing path itself is never made easier. The parity corpus proves the
boundary mechanically:

- widening-only for resolvable evidence — no legacy-admitted resolvable row is rejected by enabled
  defaults: `test_eligibility_parity.py::WideningOnlyTests::test_no_resolvable_legacy_admit_is_rejected_by_enabled_defaults`;
- the deliberate forged-evidence exceptions (legacy admits on model-claimed evidence, enabled rejects
  on verification) are enumerated and asserted: `...::test_forged_evidence_exceptions_are_enumerated`;
- default-off is byte-identical to legacy: `test_eligibility_parity.py::TrueDefaultParityTests::test_disabled_block_outcome_record_identical_to_legacy`;
- the parity theorem (conf-only config ≡ legacy boolean for resolvable rows): `test_eligibility_parity.py::ParityTheoremTests::test_conf_only_config_equals_legacy_boolean_for_resolvable_rows`;
- the red regression (inferred-once conf-9 add rejected in both modes): `test_eligibility_parity.py::RedRegressionTests::test_red_rows_rejected_in_both_modes`.

### 4.1 The adrev-003 qualifier — safe superset, not utility superset

The widening claim is scoped, and the scoping is load-bearing:

```
enabled_admits  =  (legacy admits WITH re-verifiable evidence)  ∪  (new conf 5-7 verified-origin band)
```

Enabled mode is a **safety** superset of legacy — it never admits anything legacy would reject given
verified evidence, and it *rejects* legacy-admitted rows whose evidence was only model-claimed
(forged, paraphrased-past-threshold, slug-drifted, or transcript-rotated since the proposal was
written). It is **not** a strict *utility* superset: a legitimate proposal whose real evidence
*under-verifies* — a heavily paraphrased excerpt that misses `excerpt_match_min`, a redacted long
secret (§6, #846), a session whose transcript moved — is admitted by legacy but **rejected** by
enabled. The poisoning proof survives (nothing forged gets in more cheaply); the utility claim does
not (some legitimate rows get held back). This is the honest statement of the widening property.

---

## 5. Interaction with existing rails

Eligibility is a gate *in front of* the pre-existing optimistic-integration rails; it changes only
the admit/reject decision for `add`/`supersede`, and every downstream rail runs unchanged **after**
an `eligible` verdict:

- **Dwell window** — an eligible `add`/`supersede` is still written dwelling (excluded from
  `search()`/injection for `dwell_hours`), unchanged: `test_optimistic_engine.py::PostureTests::test_add_applies_with_dwell_at_floor_and_prevalence` (and `test_verify_applies_immediately_no_dwell_at_floor`, `test_contradict_applies_with_mandatory_dwell` for the other postures).
- **Per-run / per-slug blast-radius caps** — unchanged: `test_optimistic_engine.py::PerSlugCapTests::test_per_slug_cap_limits_within_one_slug`, `...::test_absolute_eviction_cap_dominates`.
- **Batch-anomaly check** — unchanged; the new session-citation counter feeds the *same* windowed
  anomaly path without touching the eviction-concentration check:
  `test_optimistic_engine.py::BatchAnomalyTests::test_batch_anomaly_skips_evictions_for_that_slug_only`;
  `test_eligibility_gate.py::SessionCitationAnomalyTests::test_disabled_mode_never_counts_citations`,
  `...::test_firing_anomaly_does_not_change_per_row_outcomes`.
- **Circuit breaker** — unchanged: `test_optimistic_engine.py::CircuitBreakerTests::{test_breaker_trips_when_two_anomalies_fall_within_window, test_breaker_auto_resumes_after_quiet_period}`.
- **Read-time confidence decay** — `learnings_store.effective_confidence()` is untouched by this plan
  (a different clock from the gate's evidence-recency term, §3.4); an admitted row still decays by its
  own age on every read.
- **Evictions are never routed through the composite** — `learning_contradict`/`learning_deprecate`
  (and `learning_verify`, `_global`) take the legacy path bit-for-bit:
  `test_eligibility_parity.py::TargetBehaviorMatrixTests::test_g_eviction_takes_legacy_path_both_confidences`;
  `test_eligibility_gate.py::WaterfallRoutingTests::test_enabled_non_content_kind_takes_legacy_path`.
- **Fail-closed** — any exception inside signal gathering becomes `internal_error` (never eligible)
  and the batch continues: `test_eligibility_gate.py::FailClosedTests::test_gatherer_exception_is_internal_error_batch_continues`.

**Safety does not depend on the report being read.** Prevention (origin gate, static floor,
non-compensability, caps, anomaly, breaker) requires zero reads; the dwell window bounds pre-exposure
blast radius with zero reads; only *undoing* an already-integrated row needs a human to read the
digest/`/dream-review`. That property is unchanged by this work.

---

## 6. Residual-risk register

Ordered roughly by severity for a solo operator. None is claimed "fixed."

| # | Residual | Why it persists | Bound / mitigation | Proof / tracking |
|---|---|---|---|---|
| R1 | **Confidence-inflation band (conf ≥ 8)** — the cheapest attack, unchanged. `supersede` admits floor-only; `add` needs 2 verified sessions | Legacy escape (step 4) runs before the origin gate; `confidence` has no deterministic cross-check | Strict-mode knob `legacy_floor_admits:false` binds the band to the origin gate; dwell/caps/anomaly/breaker/decay still apply | `test_eligibility_redteam.py::ConfidenceInflationTests::test_conf8_supersede_admits_via_legacy_floor_residual`, `...::test_strict_mode_binds_conf8_supersede_to_origin_gate` |
| R2 | **conf̂ noise near θ / composite is a soft ranker, not the barrier** — conf̂ is 0.40 of the blend, model-assigned and non-deterministic across nights; ±1 confidence ≈ ±0.04, dominating margins of 0.01-0.02 | The origin gate (non-compensatory) is the real barrier; the composite ranks what already cleared it | **Max self-awardable score once past the origin gate ≈ 0.70** (conf̂ 0.40 + backdated reĉ 0.20 + maximized nov̂ 0.10) > θ = 0.58 — so a motivated on-machine actor who clears the origin gate can always also clear the composite. The composite is a soft ranker/UX signal; the origin gate + static floor are the barrier | `test_eligibility.py::OriginGateTests::test_user_corrected_rescues_origin_with_zero_sessions`; `test_eligibility_redteam.py::NonCompensabilityTests::test_maxed_soft_signals_never_rescue_a_weak_origin` (adrev-005) |
| R3 | **Recency backdatability** — an on-machine actor can set evidence age ≈ 0 for reĉ ≈ 1.0 | No integrity binding on transcript bytes; solo threat model | Weight 0.20, never gate-opening, read from embedded timestamps not mtime; treated as a soft tiebreaker, never evidence | §3.4 (adrev-005/R4) |
| R4 | **Session-scoped, not claim-scoped `user-corrected` tier** — a real correction about topic X mints the tier for an unrelated memory Y from the same session | The miner detects corrections per session, not per claim; binding the correction excerpt to the proposal's evidence is unimplemented | Tier only *opens* the origin gate; composite + static floor + dwell still apply | §3.3 (adrev-006) |
| R5 | **Near-duplicate supersede is flagged, not blocked** — the digest flag is advisory; nov̂ is a soft 0.10 dock; a conf ≥ 8 near-dup escapes on the legacy floor before novelty is scored | Blocking would break widening-only; the flag routes to human review instead | Flag + collapsed nov̂ ("pays twice") + dwell + `/dream-review`; strict mode binds the conf ≥ 8 case | §3.7 (decisions.md #30/#39, sec-R2/biz-N1) |
| R6 | **Novelty non-stationarity vs store density** — nov̂ is ≈1.0 "free" in a sparse store (effectively lowers θ) and → 0 for refinements in a dense store; §3.9's exact-S worked values are **arithmetic fixtures, not real-data predictions** | novelty is computed against the live store, whose size changes over time; any single calibration is a moving target | Documented as store-state-dependent; §3.9 values are the regression floor only; H1 real-data replay recalibrates; low weight caps effect | §3.5 (adrev-009); plan.md §3.9 |
| R7 | **Excerpt corroboration is copy-paste-forgeable on-machine** — an actor who can read a cited transcript can craft a clearing excerpt | Inherent to the solo threat model; unchanged from the exact-substring check it replaced | Anti-coincidence guards restore size-independence (excerpt-sized window, min absolute distinct-token intersection, SequenceMatcher-primary/Jaccard-floor) | `test_eligibility_gate.py::GuardIITwoSidedTests::test_short_common_rejected_and_redacted_legit_accepted`, `...::test_proportional_arm_binds_beyond_absolute_floor` (adrev2-003/adrev3-002) |
| R8 | **The `< 3`-content-token excerpt corroboration floor** — an excerpt with fewer than 3 distinct non-stop content tokens can **never** corroborate any session | Guard (ii) requires `max(3, ceil(0.5 × content_tokens))` distinct tokens present, so a 1-2-token excerpt never clears | **Fails closed**: such a citation is simply not counted; the row stays `pending` for `/dream-apply`. A safety residual (under-admits), never an over-admission | `test_eligibility_gate.py::GuardIITwoSidedTests::test_short_common_rejected_and_redacted_legit_accepted` (E3 residual) |
| R9 | **Redacted-long-secret window under-count** — a legitimate excerpt whose redaction placeholder stands in for a raw secret *longer* than the window's per-placeholder slack can still fail to corroborate | The slack is a bounded plausible-length allowance, not a guarantee: unbounding the cap — or scaling it with transcript size — would erode guard (i)'s size-independence (adrev2-003), so raw values above the cap (`authorization_bearer` JWTs, long `env_var_kv` values — the unbounded-upper patterns) still under-span the comparison window | **Mitigated (#846, bounded per-placeholder window slack, cap 200):** each `[REDACTED:kind]` placeholder extends the comparison window by up to `_MAX_REDACTED_SECRET_LEN` (200) chars — applied ONLY for redacted excerpts, never transcript-proportional, with guard (ii)'s placeholder-excluded token denominator and the ratio/jaccard thresholds unchanged. Placeholder-bearing excerpts for secrets ≤ 200 chars now corroborate; longer raw values keep the pre-existing SAFE under-count, which **fails closed** (session unverified → row stays `pending` for `/dream-apply`) — a safety under-admission, never an over-admission | Issue **#846** (mitigated, bounded slack); `test_eligibility_gate.py::RedactionWindowSlackTests::{test_long_redacted_secret_now_corroborates, test_long_redacted_secret_rejected_without_slack, test_placeholder_free_window_unaffected_by_slack, test_slack_cannot_clear_coincidence, test_slack_cap_pinned}` |
| R10 | **A-MAC type-prior transfer was retracted** — the research's "type-prior is the dominant discriminator" assumed honest labels and does not transfer to CCGM's proposer-chosen `type` | `type` is proposer-controlled and untrusted | The signal was **removed** (decisions.md #38); `type` has zero scoring effect and cannot influence a decision even by accident | `test_eligibility_redteam.py::TypeNeutralityTests::test_no_type_input_exists_on_bundle_or_weights`, `...::test_type_has_zero_effect_on_the_decision_and_bundle` (adrev2-004) |

---

## 7. Test-citation index

Every code-behavior claim above maps to at least one of these tests (all pass on the shipped code;
paths relative to repo root under `modules/dreaming/tests/` and `modules/self-improving/tests/`):

| Claim | Test(s) |
|---|---|
| Forged tier/stamped fields recomputed → `skipped_origin` | `test_eligibility_gate.py::TierTests::test_forged_stamped_fields_ignored_skipped_origin`; `test_eligibility_redteam.py::ForgedTierAttackTests::test_forged_tier_and_stamped_signals_are_recomputed_skipped_origin` |
| Human-origin correction filter (miner) | `test_transcript_miner.py::CorrectionOriginFilterTests::{test_negation_in_tool_result_turn_is_not_a_correction, test_origin_kind_human_turn_mints_correction, test_prompt_source_typed_turn_mints_correction, test_missing_origin_fields_fail_closed}` |
| Tier re-mined at the gate (both directions) | `test_eligibility_gate.py::TierTests::{test_human_origin_correction_mints_user_corrected, test_tool_result_only_correction_stays_inferred}` |
| §3.4 three-part verification + dedup + null | `test_eligibility_gate.py::SessionVerificationMatrixTests::{test_unresolvable_session_not_counted, test_slug_mismatch_not_counted, test_garbage_excerpt_not_counted, test_paraphrased_excerpt_counted, test_neutralized_wrapper_excerpt_matches_raw, test_redaction_placeholder_excerpt_still_counts, test_duplicate_citation_counts_once, test_null_session_excluded, test_oversized_transcript_counts_but_tier_inferred_recency_zero}` |
| Session padding attack composed | `test_eligibility_redteam.py::SessionPaddingAttackTests::{test_padding_unresolvable_wrongslug_excerptless_fails_origin, test_one_real_session_cited_thrice_still_fails_origin}` |
| Non-compensability (soft signals never rescue origin) | `test_eligibility_redteam.py::NonCompensabilityTests::test_maxed_soft_signals_never_rescue_a_weak_origin`; `test_eligibility.py::OriginGateTests::{test_inferred_below_min_sessions_always_skips_origin, test_legacy_on_below_floor_still_skips_origin, test_user_corrected_rescues_origin_with_zero_sessions, test_unknown_tier_fails_origin_like_inferred}` |
| Confidence inflation: conf-10 single inferred add rejected | `test_eligibility_redteam.py::ConfidenceInflationTests::test_conf10_single_session_inferred_add_rejected`; `test_eligibility_parity.py::TargetBehaviorMatrixTests::test_f_conf9_1sess_inferred_skipped_origin`; `test_eligibility.py::WorkedCaseTests::test_case_f_add_conf9_inferred_1sess_skips_origin` |
| Confidence inflation: conf≥8 supersede residual + strict-mode mitigation | `test_eligibility_redteam.py::ConfidenceInflationTests::{test_conf8_supersede_admits_via_legacy_floor_residual, test_strict_mode_binds_conf8_supersede_to_origin_gate}`; `test_eligibility_gate.py::OutcomeTests::test_conf8_multi_session_legacy_escape` |
| Static floor / MIN_STATIC_FLOOR / config validation | `test_eligibility_gate.py::OutcomeTests::test_static_floor_below_min_skipped_floor_no_io`; `test_eligibility.py::ValidateConfigTests::test_static_floor_below_min_fails`; `test_eligibility.py::BoundaryTests::test_conf_equals_static_floor_reaches_composite`; `test_eligibility.py::PurityTests::test_only_allowed_stdlib_imports` |
| Type-neutrality (type is not a scoring input) | `test_eligibility_redteam.py::TypeNeutralityTests::{test_type_has_zero_effect_on_the_decision_and_bundle, test_no_type_input_exists_on_bundle_or_weights}` |
| Novelty semantics | `test_eligibility_gate.py::NoveltyTests::{test_add_empty_store_novelty_one, test_supersede_unresolvable_target_novelty_zero}`; `test_eligibility.py::SimilarityTests::{test_novelty_empty_store_is_one, test_similarity_neutralized_wrapper_matches_raw}` |
| Near-duplicate supersede (pays twice + advisory-only residual) | `test_eligibility_redteam.py::SupersedeNearDupAttackTests::{test_near_dup_fact_flip_scores_low_novelty_and_trips_flag, test_conf8_near_dup_admits_via_legacy_but_flag_still_fires_residual}`; `test_eligibility_gate.py::NearDupSupersedeTests::{test_near_dup_fact_flip_flagged, test_substantive_update_not_flagged}`; `test_eligibility_parity.py::TargetBehaviorMatrixTests::{test_h_supersede_near_dup_skipped_composite, test_i_supersede_substantive_eligible_composite}` |
| Excerpt anti-coincidence guards (size-independence) | `test_eligibility_gate.py::GuardIITwoSidedTests::{test_short_common_rejected_and_redacted_legit_accepted, test_proportional_arm_binds_beyond_absolute_floor}`; `test_eligibility_gate.py::RedactionWindowSlackTests::test_slack_cannot_clear_coincidence` (slack-widened window: proportional arm + similarity arm both still bind, cap-size-independent) |
| Placeholder-aware window slack (#846): long redacted secret corroborates; slack bounded, per-placeholder, redacted-excerpts-only; cap pinned | `test_eligibility_gate.py::RedactionWindowSlackTests::{test_long_redacted_secret_now_corroborates, test_long_redacted_secret_rejected_without_slack, test_placeholder_free_window_unaffected_by_slack, test_slack_cap_pinned}` |
| No-easier-than-flat-floor / widening-only / parity | `test_eligibility_parity.py::WideningOnlyTests::{test_no_resolvable_legacy_admit_is_rejected_by_enabled_defaults, test_forged_evidence_exceptions_are_enumerated}`; `test_eligibility_parity.py::TrueDefaultParityTests::test_disabled_block_outcome_record_identical_to_legacy`; `test_eligibility_parity.py::ParityTheoremTests::test_conf_only_config_equals_legacy_boolean_for_resolvable_rows`; `test_eligibility_parity.py::RedRegressionTests::test_red_rows_rejected_in_both_modes` |
| Downstream rails unchanged | `test_optimistic_engine.py::PostureTests::{test_add_applies_with_dwell_at_floor_and_prevalence, test_verify_applies_immediately_no_dwell_at_floor, test_contradict_applies_with_mandatory_dwell}`; `test_optimistic_engine.py::PerSlugCapTests::{test_per_slug_cap_limits_within_one_slug, test_absolute_eviction_cap_dominates}`; `test_optimistic_engine.py::BatchAnomalyTests::test_batch_anomaly_skips_evictions_for_that_slug_only`; `test_optimistic_engine.py::CircuitBreakerTests::{test_breaker_trips_when_two_anomalies_fall_within_window, test_breaker_auto_resumes_after_quiet_period}` |
| Evictions never routed through composite | `test_eligibility_parity.py::TargetBehaviorMatrixTests::test_g_eviction_takes_legacy_path_both_confidences`; `test_eligibility_gate.py::WaterfallRoutingTests::test_enabled_non_content_kind_takes_legacy_path` |
| Session-citation anomaly (padding detector) | `test_eligibility_gate.py::SessionCitationAnomalyTests::{test_at_threshold_fires_and_feeds_breaker_path, test_disabled_mode_never_counts_citations, test_firing_anomaly_does_not_change_per_row_outcomes}` |
| Fail-closed on gather exception | `test_eligibility_gate.py::FailClosedTests::test_gatherer_exception_is_internal_error_batch_continues` |

Run the red-team suite: `python3 -m pytest modules/dreaming/tests/test_eligibility_redteam.py -q`.
Run the full touched surface: `python3 -m pytest modules/dreaming/tests/ modules/self-improving/tests/ -q`.
