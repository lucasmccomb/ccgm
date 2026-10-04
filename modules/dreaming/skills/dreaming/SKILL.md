---
name: dreaming
description: >
  Reference for CCGM's nightly dreaming pipeline: transcript mining, proposals, optimistic auto-integration with dwell windows and blast caps, the eval gate, digest, and rollback. Load when working on modules/dreaming, ~/.claude/dreaming, or the /dream commands.
---

# Dreaming: Nightly Durable-Memory Mining

Dreaming is CCGM's nightly, cost-capped, out-of-band pipeline that mines Claude Code session transcripts for cross-session failure patterns and turns them into **evidence-tagged proposals** against the `self-improving` learnings store. With optimistic integration active, every proposal ends integrated or discarded with a reason; nothing waits on a person (#1098 2.3). It is `autoheal`'s capture-analyze-propose pipeline, retargeted at session transcripts instead of permission events. See `modules/self-improving/skills/learnings-store/SKILL.md` for the store this module proposes changes to.

## What dreaming does

1. **Deterministic mining** (`lib/transcript_miner.py`). `discover()` enumerates session-transcript JSONLs under `~/.claude/projects/*/`, re-deriving each transcript's owning learnings-store slug from its own `cwd` field via `learnings_store.detect_project_slug()` — never from a directory-name heuristic (arch-1: the two slug spaces are different and do not agree for the same repo). `mine()` extracts friction events, user-correction sequences, PR links, token economics, and five knowledge signals (human redirections, resolved struggle arcs, assistant conclusions after friction or a redirection, rediscovery across sessions, abandoned work) that take token budget before friction; `cluster()` groups friction; `budget()` trims to a token cap without ever dropping a friction cluster entirely; `schema_canary()` validates a field-level structural contract at mine-time (friction, token-economics, turn-structure), failing loud with the specific broken field + extraction on real drift while passing benign version bumps silently — no version allowlist to maintain.
2. **Map-reduce analysis** (`lib/dream_analyze.py`, `bin/dream-analyze.sh`). One map call per due project slug (evidence bundle → candidate learnings), then one reduce call across every planned slug's candidates plus a current store projection (candidates → per-change proposals). Every model call goes over `curl` to the Anthropic Messages API directly — no nested Claude Code agent runtime, no exec-escape surface, runs headless under launchd. Both calls set `thinking`, effort, and an output schema explicitly in the request body (map: thinking disabled at `effort: low`; reduce: thinking disabled at the default effort; both: `output_config.format` with the JSON schema the response must satisfy), so a model bump cannot change behaviour by omission and the response shape is enforced rather than requested. `max_tokens` is a backstop at 16000, paired with a 300s curl timeout so the cap is reachable. A call that stops at the cap is a failed extraction, never a short answer: the slug's watermark is held so its evidence is re-mined next run, a durable incident is recorded, and the digest banner names it. Every `learning_add` / `learning_supersede` proposal must carry a deterministic `trigger` (`lib/triggers.py`: regex, command prefix, path glob, or phrase set); the finalizer rejects one that fires on none of the proposal's own evidence as `trigger_unverified`. `--offline <dir>` replaces every curl call with a canned fixture response for fully deterministic, no-network testing.
3. **Digest** (`bin/dream-digest.sh`). Renders `~/.claude/dreaming/digests/{date}.md`: today's proposals grouped by project/kind with evidence excerpts, a run summary, a durable canary banner for schema-drift/reduce-failure incidents, and yesterday's applied/rejected tally.
4. **Reconciliation** (`lib/reconcile_automemory.py`, `bin/dream-reconcile.sh`). Read-only comparison between Claude Code's own harness auto-memory (`~/.claude/projects/*/memory/`) and the learnings store, appended to the same digest as a "## Reconciliation" section. Never writes to either store — see "Reconciliation is read-only" below.
5. **Apply, two ways** (`lib/apply_dream_proposal.py`). **Optimistic auto-integration** (`optimistic_integration.enabled`, opt-in, default `false`) runs a per-op-kind posture engine that drives every proposal to a terminal state — see "Optimistic auto-integration" and "No human queue" below. **`/dream-apply`** stays as a manual override for any op-kind at any confidence.
6. **Scheduler** (`bin/dream-daily.sh`, `bin/dream-install.sh`). A macOS `launchd` LaunchAgent chains analyze → eval-refresh (off unless `optimistic_integration.eval_refresh_enabled` is true; when on, a weekly 24-session regression smoke, about $1.50, capped at `eval_refresh_cost_cap_usd` $2; see the README's "The regression smoke") → optimistic-integrate → digest → reconcile → retention once nightly (digest runs AFTER optimistic-integrate so tonight's just-integrated batch is reported while its dwell window is still entirely ahead of it, not after it has already expired). Each step is exit-tolerant — one step's failure never kills the rest of the chain or trips a launchd cooldown.
7. **Eval harness** (`eval/memory_eval.py`, `bin/dream-eval.sh`). With/without-memory A/B on a seed task suite (including one task that exercises the pipeline's own mined output end-to-end) with four-bucket outcome classification. `dream-eval.sh --gate` is the regression gate optimistic auto-integration must pass every night before it is allowed to act at all — missing or red fails closed. The harness resolves the `claude` binary to an absolute path before any task runs (a LaunchAgent's PATH is not a login shell's), and a run where **every** agent run failed to execute aborts with the first failure's raw output on stderr and a non-zero exit instead of writing a results file — see "The eval harness fails loud" below. The judge is a single Messages API call per run: no sampling parameters, `thinking: {"type": "disabled"}`, and `output_config.format` pinning the `{pass, score}` verdict schema. Spend is capped hard: the harness keeps a running total over every `claude -p` session, judge call and in-eval mining call, writes each to `cost.log` (`eval:arm:`, `eval:judge:`, `eval:mine:` rows), refuses to start when a preflight estimate exceeds `--max-total-usd`, and stops before the call that would cross it, writing `evals/<date>.budget-abort` and leaving the gate state untouched. A rolling 30-day `module_budget_usd_30d` (default 25.0) over `cost.log` stops both the analyzer and the eval.
8. **Post-hoc review + rollback** (`/dream-review`, `ccgm-learnings-sync revert`). Surfaces auto-integrated and still-dwelling rows for a human veto, and reverts a bad batch by commit sha — see "Post-hoc review + rollback" below.

## The proposal/evidence/gate contract

Every proposal (`~/.claude/dreaming/proposals/{date}.jsonl`) is a per-change delta against the learnings store — `learning_add|verify|contradict|supersede|deprecate` — never a whole-store swap. Each carries: the evidence sessions that support it (redacted, ≤400-char excerpts), a prevalence count (sessions/agents), a confidence score, and a justification. A proposal starts `pending`. With integration `active` it ends `auto_applied` or `discarded` (with `discard_reason`) within about 48 hours; with integration `off` or `shadow` it stays `pending` untouched until `/dream-apply` acts on it. Untrusted content — proposal text, evidence excerpts, justifications — is sanitized (`learnings_store.sanitize_content()`) before it ever reaches a digest a human or agent reads, and before it is ever handed to a live agent session.

## Poisoning defenses

The "promote what's prevalent" heuristic dreaming is built on is its own top attack surface (MemoryGraft/MINJA-class memory poisoning). Three defenses, in the order they matter for a solo/single-clone user:

- **Origin binding is transcript-verified, not caller-supplied.** A proposal's cited evidence sessions must resolve to real transcript files under `~/.claude/projects/**`; `writer` is derived from that transcript's own recorded `cwd`, never from a freely-exportable env var like `CCGM_AGENT_ID`. A supersede can never *raise* an entry's `source` tier (e.g. `inferred` → `user-stated`) without an independently-verified new session backing it.
- **Breadth is transcript-verified, never claimed.** A `_global` learning_add integrates in `_global` only when its cited sessions resolve to real transcripts, their excerpts corroborate there (subagent files included), and they span `promotion_min_sessions` (3) sessions over `promotion_min_slugs` (2) project slugs, each slug derived from the transcript's own cwd. Short of that it is rescoped into the slug most of its verified evidence comes from (`rescoped_from: "_global"`) and judged like any project add; with no verified session it is discarded `failed_corroboration`. The model's `prevalence` claim plays no part. `needs_manual_promotion` remains a digest label only.
- **`_global` is written through exactly one path.** `learnings_store.promote_to_global()`, called by `apply_dream_proposal.py` after a `/dream-apply` accept or a breadth-verified engine decision (marked `auto`, with the usual dwell). Ops on an existing `_global` row (verify, contradict, supersede, deprecate) are never automated; the engine discards them `global_manual_only` and `/dream-apply` remains their path. The `CCGM_LEARNINGS_ADMIN=1` hatch (see the `learnings-store` skill) is a terminal-only manual one-off; nothing in this module sets it.

## Optimistic auto-integration: posture, dwell, caps, breaker

`optimistic_integration.enabled` (`~/.claude/dreaming/config.json`) takes `off | shadow | active` (a persisted boolean reads as active/off via `lib/rollout_mode.py`; shadow logs would-integrate decisions to `state/shadow-optimistic.jsonl` and writes nothing else; promote to active only after 20+ decided decisions at 90%+ agreement with zero false positives on evictions, shown in `/dream-scorecard`). It is **`false` (off) by default** — the shipped-module posture; the operator opts in on their own machine, never by hand-editing JSON. `memory-setup.sh`'s write-path step offers it as an explicit prompt ("enable auto-integration with a 24h dwell window + daily report?") the same way it already offers dreaming itself — this is the deliberate activation forcing-function, not a buried config key. A legacy config that already had the OLD verify-only `auto_apply_counters` flag set to `true` is migrated automatically: `dream_analyze.load_config()` synthesizes `optimistic_integration.enabled = true` with the same conservative defaults so a prior opt-in survives the rename. This migration is an in-memory synthesis on read — it never rewrites config.json on disk, and `dream-daily.sh`'s own activation gate deliberately still requires the new block present on disk, not just the legacy flag (a legacy-flag-alone config stays inactive at the nightly-chain level; re-run `memory-setup.sh` or set the block by hand to actually activate the engine).

When enabled, every pending proposal is resolved to a **posture** (`dream_analyze.OPTIMISTIC_POSTURE`, the single source of truth every gate reads instead of hardcoding an `if kind == ...` check):

| Op-kind | Posture | Dwell? | Confidence floor | Per-run cap |
|---|---|---|---|---|
| `learning_verify` | `optimistic-immediate` | no | 7 | none |
| `learning_add` | `optimistic-dwell` | yes | composite eligibility gate (see below); **default OFF → flat floor 8 + prevalence ≥ 2 verified sessions** | `max_add_supersede_per_run` (default 10) |
| `learning_supersede` | `optimistic-dwell` | yes | composite eligibility gate (see below); **default OFF → flat floor 8** + compaction guard must pass | shared with `learning_add` |
| `learning_contradict` | `dwell-quarantine` | yes (mandatory) | 8 | `min(max_eviction_absolute, fraction × live slug heads)` |
| `learning_deprecate` | `dwell-quarantine` | yes (mandatory) | 8 | shared with `learning_contradict` |
| `learning_add` → `_global`, breadth verified | `optimistic-dwell` | yes | 8 | `max_add_supersede_per_run` for `_global` |
| other op → existing `_global` row | `gated` | n/a | n/a | never automated; discarded `global_manual_only` |

### No human queue (#1098 2.3)

Every proposal the active engine decides reaches a terminal state the same night, recorded on the row (`status`, `discard_reason`, `discarded_at`) and as a `discarded` apply-audit record (no `ok` field):

| Outcome | Status | Reason |
|---|---|---|
| integrated | `auto_applied` | dwell, then live |
| under the confidence floor | `discarded` | `low_confidence` |
| add with too few sessions | `discarded` | `low_prevalence` |
| eligibility origin gate / composite | `discarded` | `failed_corroboration` / `low_composite_score` |
| per-run cap reached | `discarded` | `cap_exceeded` |
| eviction concentration | `discarded` | `batch_anomaly` |
| supersede drops fact tokens | `discarded` | `compaction_guard_failed` |
| op on a `_global` row; unknown kind | `discarded` | `global_manual_only`; `unsupported_kind` |
| target gone, invalid row, failed promotion | `discarded` | `target_gone`, `invalid`, `promotion_failed` |
| malformed row | `discarded` | `malformed` |
| still pending after `pending_max_age_hours` (48) | `discarded` | `expired` |

Infra hiccups (`internal_error`, CAS exhaustion, an unexpected exit, a suspended breaker, a mid-batch timeout) leave the row `pending`: the engine also re-reads yesterday's pending rows each night, and the nightly `expire-pending` step ends anything older than 48 hours, whatever the gate said. Retention deletes a proposals file only after its pending rows are audited `expired`.

**Off means hold.** With integration `off` or `shadow`, nothing is discarded: the engine does not run (shadow writes nothing), `expire-pending` and `retention-check` read the on-disk flag the way `dream-daily.sh` does and hold, and retention keeps any proposals file that still holds a pending row.

**The one-off backlog close** (`bin/dream-close-backlog.sh`, #1098 2.4) replays every pending row, gz included, through the loaded-context prefilter (`already_encoded`), hook-error routing (`routed_to_autoheal`) and trigger validation (`trigger_invalid`, `trigger_unverified`); the rest are discarded `expired` with detail `pre-redesign`. Dry run by default; `--apply` writes. Run by hand at bring-up only.

**The daily notice.** `lib/health.py` writes the engine's integrations and retirements from the last week to `health.json`'s `recent_changes`; `hooks/dreaming-health.py` prints one line in the first session of the day when anything changed since the last notice (`state/notice.json` is the sentinel), as `systemMessage` for the user and `additionalContext` for the model. No question, nothing to acknowledge. A red health notice takes precedence.

### Eligibility composite (add/supersede only, default OFF)

`optimistic_integration.eligibility.enabled` is **`false` by default** — a second, independent opt-in *beneath* the outer engine, offered by `memory-setup.sh` only when you turn optimistic integration on (enabling it can never leave the outer flag off; an eligibility opt-in with the outer engine disabled is inert, since the nightly skips `optimistic-integrate` entirely on the outer gate). While disabled, `learning_add`/`learning_supersede` keep the exact flat floors above (8 + prevalence ≥ 2 verified sessions for add; 8 for supersede) — bit-for-bit today's behavior, and an invalid eligibility config fails closed to this same disabled path.

When enabled, those two op-kinds pass through a **deterministic composite gate** (composite-eligibility plan.md §3.2) — no LLM anywhere in the write decision. In waterfall order: a hard **static floor** (`static_floor`, default 5, never below the hard-coded `MIN_STATIC_FLOOR = 4` a config edit cannot hollow out); a **legacy escape** (a conf ≥ 8 add with ≥ 2 *verified* sessions — or conf ≥ 8 supersede — still admits, so enabling only *widens* what admits, never narrows it); a non-compensatory **origin gate** (admit only if the evidence tier is user-corrected OR ≥ 2 transcript-verified sessions — no soft signal rescues a weak origin); then a **composite score** `S = Σ wᵢ·signalᵢ ≥ θ` (θ default 0.58) over four signals — `confidence` .40 (the only model-assigned input), `prevalence` .30 (distinct transcript-verified sessions), `recency` .20 (evidence age, 30-day half-life), `novelty` .10 — all re-derived from the transcripts and live store at apply time, never trusted from the proposal row.

The point is admitting the useful conf-5–7 memories the flat floor held back (user-corrected or seen-across-sessions) while making every newly-admitted class *harder* to forge than confidence inflation. Every scored row — eligible or skipped — writes its full per-signal breakdown + margin to the audit trail, rendered per-row by `/dream-digest` and `/dream-review` (§3.7). **Evictions (`learning_contradict`/`learning_deprecate`) and `learning_verify` are untouched** — they keep their flat floors and dwell-quarantine rails bit-for-bit; the composite gates adds/supersedes only.

**The dwell window** (`dwell_hours`, default 24) is the mechanism, not just a `learning_add`/`supersede`/`contradict`/`deprecate` label: a row is written (committed) immediately, but carries a `dwell_until` timestamp that excludes it from `search()` — and therefore from SessionStart injection and the mining reduce projection — until the window elapses. `learning_verify` alone skips it (`optimistic-immediate`): it is purely additive (bounded `+0.25/use`, capped `+2.0`) and reversible by a later contradict, so there is nothing to dwell.

**Per-run blast-radius controls, scoped per project slug** (a legitimate focused night on one project is topically narrow by nature, so caps evaluate one slug's proposals at a time, never cross-project):

- `max_add_supersede_per_run` (default 10) caps `learning_add` + `learning_supersede` together.
- The eviction cap (`max_eviction_absolute` default 3, or `max_eviction_fraction_per_run` of that slug's *live* head count, whichever is smaller) caps `learning_contradict` + `learning_deprecate` together — an absolute small ceiling dominates at solo-operator scale, where a bare 20% fraction could still evict many true memories from a small store. The live head count is computed once, before any write, so same-run adds cannot inflate it.
- The **batch-anomaly check** keys on eviction *concentration* (contradict/deprecate piling onto one row or tag), never on `add`-tag overlap, so a legitimate all-one-tag night of adds never false-trips it.
- A **cross-night accumulation signal** tracks `add`/`supersede` volume per slug over a rolling window (default 14 nights, threshold 40) — a patient attacker who drips one plausible add per night stays under every per-run cap, so this is the one control that looks across nights. It bounds, not eliminates, the slow-poison case (dwell + decay + per-row report + eval gate still apply).
- A **windowed circuit breaker** with two anomaly classes (`lib/breaker.py`). *Infra* anomalies (eval gate paused, gate script failure, analyzer failure, timeout, dirty tree, a regression no batch explains) pause that night and never count. *Content* anomalies (batch-anomaly fire, an eval regression a batch integrated since the last green run explains, a recurrence spike) revert the batch they name at once with `ccgm-learnings-sync revert <sha>` (audited `batch_auto_reverted`) and count toward suspension: 2 within 7 nights suspend integration. Eviction concentration names no batch, because its rows are withheld before apply.
- **Resume** runs first in every nightly chain (`apply_dream_proposal.py breaker-check`), independent of the gate: 7 nights with no content anomaly resume the breaker and clear only the content anomalies. `apply_dream_proposal.py optimistic-resume` is the manual override.
- The eval gate (`dream-eval.sh --gate`) is three-way: `open` unless a supported regression (treatment fails a check baseline passes, each in at least 2 of 3 runs, on a canary or a task whose seed changed), `closed` on one, `paused` when no usable eval exists (missing, broken, budget-aborted, older than `eval_freshness_days` (7), or followed by more than `max_unevaluated_writes` (15) of dreaming's own writes). Integration runs only on `open`; no `high_value` row is required. `dream-eval.sh --offline` never writes the live `~/.claude/dreaming` unless given `--allow-real-dir`.

**`learning_contradict`/`learning_deprecate` are never *silently* auto-applied** — they are written immediately like everything else in `dwell-quarantine`, but withheld from every read path for the full dwell window, capped per run, and the report surfaces them during that window for an optional veto. This preserves the pre-optimistic module's intent (a model-proposed eviction is a silent-suppression vector) while giving the operator a real, time-bounded chance to catch it before it reaches agent context.

## Safety does not depend on the report being read

The operator will not reliably read a daily report, so **prevention** cannot depend on anyone reading anything:

- **Prevention** (zero reads required): the eval gate, per-slug blast-radius caps, the batch-anomaly check, the cross-night accumulation signal, the circuit breaker, confidence floors + prevalence, and confidence decay.
- **Exposure bounding** (zero reads required): the dwell window delays a bad row from ever reaching agent context for `dwell_hours` — time-based, never contingent on a human acting.
- **Correction** (needs a read, but only for *undo*, never *prevent*): the daily report + `/dream-review` + `ccgm-learnings-sync revert <sha>`. If the operator never reads the report, no *additional* harm occurs beyond what prevention already bounded — the row decays on schedule or is caught by a later eval run.

The honest residual: the dwell window shrinks the *pre-exposure* blind spot to zero, but nothing shrinks the *post-exposure* one except a shorter `dwell_hours` (more report lead time) and decay — once a row has been exposed and a live session has already read it into its frozen SessionStart context, only a human catching it and reverting removes it from *future* sessions (see the `learnings-store` skill's Rollback section).

## The eval harness fails loud

A gate that fails closed only helps if a closed gate means what it says. From 2026-07-15 to 2026-09-02 every nightly eval recorded `format_error_rate: 1.0` on all 54 rows and the gate read that as a memory failure. The cause was neither memory nor the API: the LaunchAgent exports a fixed PATH (`/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`), Claude Code's native installer puts the CLI in `~/.local/bin`, and every arm subprocess died with `FileNotFoundError` before it ran. The runs that looked healthy were the ones an operator started from a login shell. Two rules now hold that shut:

- **The `claude` binary is resolved to an absolute path before any task runs.** `resolve_claude_bin()` tries the ambient PATH first, then the known install directories, and raises — naming everything it searched, and pointing at `--claude-bin` / `CCGM_EVAL_CLAUDE_BIN` — rather than letting the run start. Nothing is spent on a harness that cannot launch.
- **A whole-run format-error rate of 1.0 aborts.** One failed arm run stays non-fatal (it is recorded and the eval carries on); a run where *every* arm failed is not a measurement, so the harness prints the first failure's raw output to stderr, exits non-zero, and writes no results file — it drops any partial file it wrote this run, and records the failure in `evals/<date>.harness-broken` instead. That marker is what keeps the gate honest: `evals/` always holds prior runs, so an abort that wrote nothing would otherwise leave `--gate` reading last week's file and reporting `open` while tonight's harness is provably broken. While a marker is newer than the newest results file, `--gate` reports `harness broken: every agent run failed to execute on <date>` — "the harness never ran" — instead of a regression nobody measured. The next run that produces results clears it.

**A launch failure may only move a row toward a closed gate, never toward an open one.** Three rules implement that one invariant:

- **A run that never executed moves no score, in either direction.** It is not sent to the judge — there is nothing to grade, the untouched fixture would score whatever it already scored (10.0 on a canary task, for a run that did no work), and on a broken harness that is a whole task's judge calls spent before the abort fires. It is also excluded from every mean the classifier reads, not just floored to zero: an untagged zero pulls the arm's mean down, and two failed launches in a five-run baseline arm are enough to classify a row `high_value`. Cost is the one exception — a run stopped against `--max-budget-usd` spent real money, and spend is not a quality metric.
- **A row is only as good as its worst arm.** Any arm holding a failed run downgrades the row to `error`, naming the arm and the failed/total count. `error` is a bucket the classifier never returns; it marks the row as a harness observation.
- **The gate reads pass rates, and a flake never opens it.** A checked row with a failed launch or judge error still closes the gate if its surviving runs show a regression; otherwise it pauses the gate (`unmeasured_rows`).

Take a closed gate at its word only after checking the run wrote rows at all.

## Post-hoc review + rollback

`/dream-review` surfaces auto-integrated and still-dwelling rows for a human veto — pass `--include-dwelling` (`ccgm-learnings-search` / `learnings_store.search()`) to see rows agent context cannot. Reverting a bad batch is `ccgm-learnings-sync revert <sha>` — **not** a raw `git revert`, which is unsound against this store's `merge=union` shard files (see the `learnings-store` skill's Rollback section for why, and how the real mechanism works instead).

## Reconciliation is read-only

`lib/reconcile_automemory.py` compares Claude Code's own harness auto-memory against the learnings store and reports two signals: auto-memory facts absent from the store (import candidates) and store rows that dispute a topic auto-memory still presents as current (deprecated/superseded/contradicted — flagged for `/consolidate`). It **never** writes to `~/.claude/projects/` — the harness's own `autoDream` consolidator owns that file, and colliding writers on it is exactly the failure class this whole system exists to prevent (decisions.md #10). Do not extend this module to write auto-memory facts, "helpfully" sync a reconciled fact back into `MEMORY.md`, or otherwise take ownership of that file. If bidirectional sync is ever wanted, it is a deliberate, separately-reviewed design change — not a natural extension of the report.

## Quick checks

```bash
# Verify the module's own tests pass (never against the real store).
python3 -m pytest modules/dreaming/tests/ -q

# Offline end-to-end chain smoke, no network, no ANTHROPIC_API_KEY:
CCGM_DREAMING_DIR=$(mktemp -d) CCGM_LEARNINGS_DIR=$(mktemp -d) \
  bash modules/dreaming/bin/dream-daily.sh \
    --offline modules/dreaming/tests/fixtures/offline-responses \
    --force-day 2026-01-02

# Status + config (real environment):
/dream
cat ~/.claude/dreaming/config.json
```

## Slash commands

| Command | Purpose |
|---------|---------|
| `/dream` | Status overview + subcommand surface. Read-only. |
| `/dream-digest [date]` | Render today's (or a specific date's) digest. |
| `/dream-apply [id\|list]` | List pending proposals, or accept/reject one by id — the manual override. Nothing waits for it when integration is active. |
| `/dream-review [id\|list]` | Post-hoc review of auto-integrated and still-dwelling rows; veto one before or shortly after it goes live. |
| `/dream-scorecard [week]` | Read-only weekly observability scorecard (captured / injected / reused / applied, plus auto-integrated / mid-dwell / reverted / breaker-trips + store health). Renders to `~/.claude/dreaming/scorecards/{date}.md`. |

## When NOT to invoke

- **Do not hand-edit `~/.claude/dreaming/proposals/*.jsonl`.** Proposals are write-once by the analyzer and mutated only through `/dream-apply`'s or the optimistic engine's status transitions; hand-editing breaks the fingerprint-dedup and audit trail.
- **Do not flip `optimistic_integration.enabled` to `true` by hand-editing config.json.** Use `memory-setup.sh` (re-runnable any time) so the activation is a confirmed, logged choice, not a silent config edit — and confirm a live `dream-eval.sh --gate` pass first; the gate must be green or the engine fails closed regardless.
- **Do not treat a `needs_manual_promotion` proposal as already applied.** It is still `pending`; the label only changes how the digest presents it.
- **Do not treat a dwelling row as gone just because `search()`/injection can't see it.** A row auto-integrated by the optimistic engine is already committed to the store — it is written and will go live (visible to `search()`/injection) at `dwell_until` unless you `/dream-review` it first.
- **Do not extend `reconcile_automemory.py` (or anything in this module) to write to `~/.claude/projects/`.** See "Reconciliation is read-only" above.
- **Do not enable this module expecting fleet-wide cross-agent memory on day one.** For a solo or single-clone setup, the near-term value is per-slug cross-*session* mining (Epics 1/4/5's store hardening + injection + git durability); the dreaming service itself earns its cost as multi-agent usage grows.

## Cross-references

- `modules/self-improving/skills/learnings-store/SKILL.md` — the store every proposal here targets; schema, confidence decay, supersede chains, `dwell_until`/`include_dwelling`, git sync, and the `ccgm-learnings-sync revert` rollback mechanism.
- `modules/autoheal/skills/autoheal-reference/SKILL.md` — the sibling pipeline this module's capture-analyze-propose shape is modeled on (permission events, not transcripts).
- Plan (mining/apply/eval/scheduler foundation): `~/code/plans/ccgm-durable-memory-system/plan.md` §3 (architecture), §5 Epics 1–8 (per-epic specs), §11 (risk register — origin binding, promotion guard, and auto-apply gating each have a dedicated row).
- Plan (optimistic auto-integration): `~/code/plans/ccgm-optimistic-memory/plan.md` §3 (dwell-window architecture, per-op-kind posture, blast-radius caps, circuit breaker), §5 Epics 1–8 (per-epic specs), §11 (risk register).
- `modules/dreaming/docs/composite-eligibility-poisoning-analysis.md` — the adversarial poisoning analysis of the composite eligibility gate ("Eligibility composite" above) when enabled: threat model, per-signal forgeability table, attack walkthroughs, and the residual-risk register, every claim cited to a passing test.
