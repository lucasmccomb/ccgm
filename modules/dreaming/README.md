# dreaming

Nightly, cost-capped dreaming service that mines Claude Code session
transcripts for cross-session failure patterns and proposes evidence-tagged
memory-store changes. Extends the `self-improving` learnings store with an
out-of-band analyzer -- `autoheal`'s capture-analyze-propose pipeline,
retargeted at session transcripts instead of permission events. Every
proposal is human-reviewed via `/dream-apply` by default; an opt-in
`optimistic_integration` mode (default off) auto-integrates instead, behind
a per-op-kind posture engine, a dwell window, blast-radius caps, an eval
gate, and a circuit breaker -- see "The gate and the breaker" below.

Status: **beta**. This module ships incrementally; see "What's implemented
so far" below.

## Why this module exists

`self-improving` gives agents an in-band way to log a learning as they work.
`autoheal` proves out-of-band mining works for permission events. Neither
mines the richer session-transcript JSONL directly -- tool errors, hook
errors, user corrections, token/cache economics, PR links. `dreaming` closes
that gap: a nightly job reads the transcripts every session already writes,
extracts patterns a single in-session agent cannot see, and proposes
per-change memory-store updates for a human to accept/reject, or for the
opt-in optimistic engine to integrate on its own, subject to its own gates.

Full design: `~/code/plans/ccgm-durable-memory-system/plan.md` (the mining /
map-reduce analyzer / apply path / eval harness / scheduler foundation) and
`~/code/plans/ccgm-optimistic-memory/plan.md` (the dwell-window,
per-op-kind-posture optimistic auto-integration engine built on top of it).

## What's implemented so far (composite-eligibility)

An **opt-in composite eligibility gate** in front of the optimistic engine's
`learning_add`/`learning_supersede` admission -- a second, independent opt-in
*beneath* `optimistic_integration.enabled`, both flags `false` by default:

- `lib/eligibility.py` -- the pure, I/O-free scoring core
  (`DEFAULT_ELIGIBILITY`, `evaluate_eligibility()`,
  `validate_eligibility_config()`). When
  `optimistic_integration.eligibility.enabled` is on, an `add`/`supersede`
  passes a deterministic waterfall with no LLM in the write decision: a static
  floor (`static_floor` default 5, never below the hard-coded
  `MIN_STATIC_FLOOR = 4` a config edit cannot hollow out); a legacy escape (so
  enabling only widens what admits, never narrows it); a non-compensatory
  origin gate (user-corrected tier OR >= 2 transcript-verified sessions -- no
  soft signal rescues a weak origin); then a composite score
  `S = Σ wᵢ·signalᵢ >= θ` (θ default 0.58) over four signals -- `confidence`
  .40, `prevalence` .30, `recency` .20, `novelty` .10 -- all re-derived from
  the transcripts and live store at apply time, never trusted from the row.
  Evictions (`contradict`/`deprecate`) and `verify` are untouched; the gate
  scopes adds/supersedes only.
- `lib/apply_dream_proposal.py` -- the `eligibility-dry-run` CLI: a read-only
  what-if inspector that scores a day's pending add/supersede proposals and
  prints the per-signal breakdown, applying nothing and writing no audit. It
  force-scores even while the gate is disabled in config, so you can preview a
  day before opting in:
  `python3 modules/dreaming/lib/apply_dream_proposal.py eligibility-dry-run [--date YYYY-MM-DD]`.
- [`docs/composite-eligibility-poisoning-analysis.md`](docs/composite-eligibility-poisoning-analysis.md)
  -- the adversarial poisoning analysis of the gate when enabled (threat model,
  per-signal forgeability table, attack walkthroughs, residual-risk register),
  every code-behavior claim cited to a passing test.
- `.github/workflows/module-tests.yml` -- a required, blocking PR check
  (ubuntu + macOS) running the `dreaming` + `self-improving` pytest suites, the
  disabled- and enabled-mode offline chain smokes, and the offline eval harness.

`optimistic_integration.eligibility.enabled` is `false` by default; the
operator opts in via `memory-setup.sh` (offered only once optimistic mode
itself is on), never a hand JSON edit. Full contract:
`modules/dreaming/skills/dreaming/SKILL.md` > "Eligibility composite".

## What's implemented so far (optimistic-memory Epics 1-8)

The **opt-in optimistic auto-integration engine**, on top of the map-reduce
analyzer below:

- `lib/learnings_store.py` (in `self-improving`) -- the `dwell_until` field,
  `is_dwelling()`, and the `include_dwelling` kwarg / `--include-dwelling`
  CLI flag that excludes a still-dwelling row from `search()` (and therefore
  from SessionStart injection) without hiding it from `load_all()`/by-id
  lookups.
- `lib/dream_analyze.py` -- `OPTIMISTIC_POSTURE` (the per-op-kind policy
  table: `optimistic-immediate` for `verify`, `optimistic-dwell` for
  `add`/`supersede`, `dwell-quarantine` for `contradict`/`deprecate`,
  `gated` for anything targeting `_global`), the `optimistic_integration`
  config block (`~/.claude/dreaming/config.json`, `enabled: false` shipped
  default), and the legacy `auto_apply_counters` migration in
  `load_config()`.
- `lib/apply_dream_proposal.py` -- `run_optimistic_integrate()`: the actual
  engine. Per-slug blast-radius caps, a batch eviction-concentration
  anomaly check, a cross-night accumulation signal, and a windowed,
  self-healing circuit breaker, all evaluated before any write; every
  proposal it applies routes through the same `apply_proposal()` (and the
  same human-race lock) `/dream-apply` already uses.
- `bin/dream-daily.sh` -- the nightly chain gained an eval-refresh step and
  an `optimistic-integrate` step, both config- and eval-gated (eval-refresh
  also needs `optimistic_integration.eval_refresh_enabled: true`, default
  `false`, because one full live run cost about $21), placed
  BEFORE the digest step (so tonight's just-integrated batch is reported
  while its dwell window is still entirely ahead of it).
- `bin/dream-eval.sh` -- extended with poisoning negative-control fixtures
  so the regression gate optimistic integration must pass every night
  actually exercises the attack shapes the engine is designed against.
  It also fails loud now (see "The eval harness fails loud" below).
- `commands/dream-review.md` (`/dream-review`) -- post-hoc review of
  auto-integrated and still-dwelling rows.
- `bin/ccgm-learnings-sync` (in `self-improving`) -- `revert <sha>`: a
  line-set-difference rollback that does NOT shell out to `git revert`
  (unsound against this store's `merge=union` shard files -- see
  `modules/self-improving/skills/learnings-store/SKILL.md`'s Rollback section).
- `lib/scorecard.py` -- extended with auto-integrated / mid-dwell /
  reverted / breaker-trip counts.
- `bin/memory-setup.sh` (in `self-improving`) -- the activation
  forcing-function: an explicit prompt offering optimistic mode, the same
  script that already activates dreaming itself.

`optimistic_integration.enabled` is `false` by default in every case; the
operator opts in on their own machine via `memory-setup.sh`, never a hand
JSON edit.

### Rollout: off, shadow, active

`optimistic_integration.enabled` takes `"off"`, `"shadow"` or `"active"`.
Configs written before shadow mode hold a boolean; `lib/rollout_mode.py`
reads `true` as `active` and `false` as `off` and never rewrites the file.
Every reader of the flag goes through its `resolve_mode`.

- **shadow** runs the nightly decision pass (posture, floors, caps, anomaly
  check, breaker read) and appends one record per decision to
  `~/.claude/dreaming/state/shadow-optimistic.jsonl`:
  `{ts, day, batch_id, proposal_id, kind, project, would_integrate, reason, posture}`.
  It writes nothing to the learnings store, the apply-audit, the proposals
  or the breaker state, makes no commit, and skips the paid eval refresh.
  `memory-setup.sh` offers shadow first.
- **Agreement.** `/dream-scorecard` compares each would-integrate decision
  with your `/dream-apply` choice (the proposal's `accepted` or `rejected`
  status): would-integrate and accepted, or would-skip and rejected, is
  agreed; would-integrate and rejected is a false positive; would-skip and
  accepted is a false negative; no decision yet is pending.
- **Promotion bar.** Move to `active` only when the scorecard shows at least
  20 decided (non-pending) decisions, at 90% agreement or better, with zero
  false positives on evictions (`learning_contradict`, `learning_deprecate`).
  The numbers are `PROMOTION_MIN_DECIDED`, `PROMOTION_MIN_AGREEMENT` and
  `PROMOTION_MAX_GUARDED_FALSE_POSITIVES` in `lib/rollout_mode.py`; the
  scorecard computes the verdict from them.

## What's implemented so far (Epic 3)

**Cost safety.** Every billed call writes a `cost.log` row: analyzer map
and reduce calls, and for the eval `eval:arm:<model>` (each `claude -p`
session), `eval:judge:<model>` and `eval:mine:<model>` rows, manual
`dream-eval.sh` runs included. Two caps apply on top of `daily_cost_cap_usd`:

- `module_budget_usd_30d` (default 25.0) is a rolling 30-day ceiling summed
  from `cost.log`. `dream_analyze.py` and `memory_eval.py` both refuse to
  start at or above it.
- `memory_eval.py` keeps a running total over one run and stops before the
  call that would cross `--max-total-usd` (default config
  `eval_run_cost_cap_usd`, 5.0, and never more than what is left of the
  30-day budget). A preflight estimate (sessions x $0.08, a judge call per
  session, $0.50 per dreamed task) refuses to start when it exceeds the cap.
  A stopped run writes `evals/<date>.budget-abort` and restores the results
  file it found; the marker pauses `--gate` until a later run writes results.

The **nightly map->reduce analyzer**, on top of Epic 2's miner:

- `bin/dream-analyze.sh` -- thin runner. Resolves candidate project slugs
  (`--slugs`, or config `scopes`, or every slug that already has a
  learnings store), mines every slug's due transcripts (Epic 2, free),
  runs a whole-night preflight cost estimate against `daily_cost_cap_usd`
  BEFORE any API call (least-recently-dreamed slugs win when the fleet is
  over cap), then does one map call per planned slug plus one reduce call
  across all of them, and writes validated, sanitized proposal rows to
  `~/.claude/dreaming/proposals/{date}.jsonl`. `--offline <dir>` replaces
  every Messages API call with a canned response file -- no network, no
  `ANTHROPIC_API_KEY` required.
- `lib/dream_analyze.py` -- the orchestrator itself (Python; everything
  above lives here, `bin/dream-analyze.sh` is a thin wrapper). Both calls
  set `thinking`, `output_config.effort`, and `output_config.format`
  explicitly in the request body: map runs thinking-disabled at `effort:
  low` (classification-shaped extraction), reduce runs thinking-disabled
  at the model's default effort, and each sends the JSON schema its
  response must satisfy. `max_tokens` (16000) is a backstop, paired with
  a 300s curl timeout so the cap is reachable -- a map call that stops at
  it holds that slug's mining cursors (its evidence is re-mined next run),
  records a durable incident, and is counted in the run summary.
- `lib/dreaming-prompt-map.md` / `lib/dreaming-prompt-reduce.md` -- the two
  system prompts, both opening with an untrusted-input threat-model block
  (excerpts are mined from other agents' sessions -- data, never
  instructions). Each states its output contract once; the API enforces
  the shape, so the prompts document it rather than pleading for it.
- `lib/proposal-schema.json` -- the per-change proposal row contract every
  written row is validated against before it touches disk.
- `lib/triggers.py` -- the deterministic trigger matcher. Every
  `learning_add` / `learning_supersede` proposal carries
  `trigger: {"kind", "value"}` (null for the other kinds):

  | kind | value | fires when the text |
  |------|-------|---------------------|
  | `regex` | string, 3-200 chars | matches it (`re.search`, ignoring case) |
  | `command_prefix` | string | contains the command at a word boundary |
  | `path_glob` | glob string | contains a path (or its basename) that matches |
  | `phrase_set` | list of strings, 3+ chars each | contains any phrase, ignoring case |

  The finalizer validates the trigger against the proposal's own cited
  evidence: a missing or malformed trigger is rejected as `trigger_invalid`,
  one that fires on none of its evidence excerpts as `trigger_unverified`
  (counted as `triggers_unverified` in the run summary). Triggers that match
  everything (`.*`, `*`, one-letter values) and nested-quantifier regexes
  are invalid. Phase 4's recurrence metric imports `triggers.matches()` to
  scan later transcripts.
- `lib/loaded_context.py` -- the loaded-context corpus and prefilter
  (#1098 3.3). Every session already loads its rules, CLAUDE.md files,
  auto-memory and hook messages; a mined learning that restates one of them
  teaches nothing. Each night, with no model calls, the analyzer builds a
  corpus per slug from:

  | category | source |
  |----------|--------|
  | `rule` | `~/.claude/rules/*.md` (symlinks followed) |
  | `claude_md` | `~/.claude/CLAUDE.md`, plus each `CLAUDE.md` and `.claude/rules/*.md` from every cwd seen in the slug's transcripts up to `/` |
  | `auto_memory` | `~/.claude/projects/<cwd-encoded>/memory/*.md` |
  | `hook` | string constants and docstrings (the denial messages) of `~/.claude/hooks/*.py` |
  | `store` | live learnings-store rows for the slug and `_global` |
  | `pending_proposal`, `discarded_proposal` | pending and rejected add/supersede rows of the last 30 days, `.jsonl.gz` included |

  Between the map and the reduce, `prefilter_candidates()` drops a candidate
  when its best match in a non-store category scores at or above
  `prefilter_threshold` (reason `already_encoded`, with the matching source
  path), or when all of its evidence is friction that autoheal already
  records (reason `routed_to_autoheal`, below). Dropped candidates never
  reach the reduce prompt. A candidate that restates a live `store` row is kept so the
  reduce can `learning_verify` it. The score is the cosine of the two token
  sets with each token weighted by inverse document frequency in the corpus;
  plain Jaccard peaked at 0.36 on real learnings because they are longer
  elaborations of the rule text, so the default threshold is 0.35, and a
  value above 1 turns the prefilter off. Survivors carry their top three
  corpus snippets to the reduce, which emits `already_encoded: <source>` (the
  proposal is dropped and counted) or a one-line `novelty` for every add and
  supersede. The reduce also receives up to `reduce_pending_max` (100)
  pending proposals in compact form. The run summary records
  `routed_to_autoheal` (#1098 3.2) keeps tool and hook friction out of
  memory. Autoheal's `failure-logger.py` already records every tool failure
  and hook denial first-hand, in real time, so dreaming forwards nothing;
  forwarding would count each failure twice. A candidate is dropped when
  every evidence excerpt is friction (it matches a friction-cluster exemplar
  in the night's bundle and no signal from the redirection, struggle_arc,
  conclusion, abandoned_work or rediscovery extractors) and either (a) each
  excerpt is a hook error from an installed hook (this folds in the earlier
  `installed_hook_friction` reason; the drop record's source is the hook
  file), or (b) the candidate's content scores at or above
  `friction_threshold` (default 0.35, the same score as the prefilter)
  against the error excerpts, meaning the content restates the error. At 0.35
  every drop in this machine's backlog restated its error text; at 0.25 the
  extra drops were multi-line worktree and git failures whose content added
  project facts. One cited signal keeps the candidate, tool errors or not,
  and excerpts the bundle cannot place are never treated as friction. A value
  above 1 turns rule (b) off. The digest prints "N friction-only candidates
  left to autoheal" when N is above zero.

  The run summary records
  `candidates_mapped`, `prefilter_dropped` (by reason), `prefilter_drops`
  (reason, source path, category, score), and `reduce_already_encoded`;
  `proposals_deduped` counts fingerprint hits plus candidates dropped for
  restating a prior proposal. Roots are overridable: `CCGM_DREAMING_CLAUDE_HOME`
  moves the whole `~/.claude` tree, `CCGM_DREAMING_RULES_DIR` and
  `CCGM_DREAMING_HOOKS_DIR` move one directory.

  Add and supersede fingerprints key on `(target_id, sorted evidence session
  ids, key terms shared by content and excerpts)`, not on the reduce
  model's wording, so a re-run over the same evidence collides.
- `bin/dream-digest.sh` -- renders `~/.claude/dreaming/digests/{date}.md`:
  proposals grouped by project/kind with evidence, prevalence, and
  confidence; a durable canary banner for schema-drift/reduce-failure
  incidents that stays visible across days until acknowledged; yesterday's
  applied/rejected tally (forward-compatible with a later apply path).
- `bin/dream-scorecard.sh` / `lib/scorecard.py` -- read-only weekly
  observability scorecard (`/dream-scorecard`) rendered to
  `~/.claude/dreaming/scorecards/{date}.md`: captured / injected / reused /
  applied counts plus store health, aggregated from the learnings store,
  injection telemetry, and proposals. Never writes to the store.

Every proposal starts `status: "pending"`. `dream_analyze.py` never writes to
the learnings store -- it only *reads* it (to build the projection reduce
compares candidates against) and *proposes*. The optimistic engine (opt-in,
default off) applies; see "No human queue" below for how every proposal ends.

## What's implemented so far (Epic 2)

The **deterministic transcript miner** -- pure Python stdlib, no network
calls, no LLM calls, no scheduling:

- `discover(slugs, cursors=...)` -- enumerate transcript files under
  `~/.claude/projects/*/`, including each session's subagent transcripts
  (`<session-id>/subagents/agent-*.jsonl`; where most failures, struggles
  and stated findings happen -- the `.meta.json` siblings and
  `tool-results/` are not transcripts). A subagent file resolves its slug
  from its own `cwd`; a `cwd` under `<repo>/.claude/worktrees/` resolves
  from the repo, so a torn-down worktree still maps to the repo's slug
  instead of `agent-<hash>`. `mine()` reports `parent_session_id` for them,
  and no user turn in a subagent transcript is ever a human turn (it is the
  dispatcher). Cursors are per file, so the watermark-to-cursor migration
  seeds subagent files like any other, and an unseeded file stays inside
  the `lookback_days` mtime window. Only files whose owning learnings-store
  slug (re-derived from each transcript's own `cwd` field) is in the
  wanted set and that hold bytes past their per-file cursor are returned (`state/mining-cursors.json`, byte
  offsets). A timestamp-less append (`file-history-snapshot`) is not new
  content, and a file shorter than its cursor is re-read from 0. Slugs
  dreamed before cursors existed are seeded once from `last-dreamed.json`.
- `mine(path, start_offset=0)` -- extract friction events (tool errors, hook errors,
  prevented-continuation), user-correction sequences, PR links, token
  totals + cache-read ratio, session identity, and the five **signals**
  below, from one transcript.
- **Signals** -- five deterministic extractors for knowledge the agent does
  not already carry (hook friction goes to friction clusters, not here):
  `redirection` (a human-typed turn that corrects or redirects, with or
  without a nearby tool error; the excerpt is the human's text and
  `context` is the assistant turn before it), `struggle_arc` (three or
  more consecutive failures on one file path, test name or three-word
  command prefix, then a success; the excerpt is the assistant's
  conclusion, preferring "root cause" / "the fix" / "turns out" /
  "because" sentences), `conclusion` (a sentence of assistant prose, text
  blocks only, that states a finding -- markers: "root cause", "turns out",
  "the fix is/was", "the problem is/was", "the actual", "the reason",
  "because", "doesn't support", "only works when", "so ... requires/needs/
  must" -- within 8 turns after a friction event or a human redirection;
  sentences under 40 characters, ones that restate a friction excerpt (60%
  token overlap), and near-duplicates are dropped; at most 6 per session;
  the excerpt is the sentence plus one neighbour as a contiguous span and
  `context` is the friction or redirection that opened the window),
  `abandoned_work` (a clean `git revert` or
  `git reset --hard` that is not a sync to `origin/`, or a human asking to
  undo or revert), and `rediscovery` (the same Read/Grep/Glob target in two
  or more sessions of one slug in the mining window; built in
  `mine_to_evidence_bundle()`). Only genuinely human turns count: the
  existing `human_origin` gate, minus `<system-reminder>` blocks, harness
  wrappers, `isMeta` lines, anything over 800 characters, and the session's
  opening prompt. Every excerpt goes through `make_excerpt()`. Signals
  take token budget before friction clusters (at most 80% of it; the
  lowest-priority kinds drop first and `signals_dropped` counts them).
  Priority: redirection, struggle_arc, conclusion, abandoned_work,
  rediscovery.
- `cluster(events)` -- group events by `(event_kind, tool_name,
  command_prefix)`.
- `budget(clusters, max_input_tokens)` -- trim to a token cap without ever
  dropping a friction cluster entirely.
- `schema_canary(mined_sessions)` -- validates a field-level structural
  contract via `validate_structure()` (friction, token-economics,
  turn-structure); fails loud (raises `SchemaDriftError`, naming the
  broken field + extraction) only on real structural drift, and passes a
  benign Claude Code version bump silently -- no version allowlist to
  maintain.

The map-reduce analyzer that turns evidence into proposals landed in Epic 3
(see above). The apply path / slash commands / scheduler, the eval harness,
and the auto-memory reconciliation report all landed in later durable-memory
Epics 4-8 and are built today (`/dream-apply`, `bin/dream-daily.sh`,
`bin/dream-eval.sh`, `lib/reconcile_automemory.py`); the opt-in optimistic
auto-integration engine on top of all of it is covered in its own section
above.

## The gate and the breaker

From 2026-07-09 to the redesign (#1098 Phase 2) nothing integrated: the gate
demanded a `high_value` row no live eval produced (#1037), any in-session
learning made the eval stale, and the breaker could only resume after a gate
that never opened. Both now work as follows.

**Gate** (`dream-eval.sh --gate`, `memory_eval.gate_check()`). Prints
`{"gate", "code", "reason", "since"}`.

| State | Exit | When | Codes |
|---|---|---|---|
| `open` | 0 | no supported regression | `ok` |
| `closed` | 1 | a supported regression, or the live dreamed task's noise-only corpus yielded a proposal | `regression`, `noise_contamination` |
| `paused` | 3 | nothing usable was measured | `harness_broken`, `budget_abort`, `no_results`, `results_stale`, `stale_own_writes`, `results_empty`, `unmeasured_rows` |

- A **supported regression**: on a canary task, or a task whose seed learning
  changed since the previous run (`seed_fingerprint`; a row without one counts
  as changed), the baseline passes a check in at least 2 of 3 runs and the
  treatment fails it in at least 2 of 3, with at least 3 scored runs per arm.
- No `high_value` row and no live dreamed row are required; the buckets are
  reporting only.
- **Fresh** while both bounds hold: the newest results are at most
  `eval_freshness_days` old (default 7, so a weekly smoke keeps them fresh),
  and dreaming has made at most `max_unevaluated_writes` (default 15) of its
  own `auto: true` writes since them. Past either bound the gate pauses
  (`results_stale` or `stale_own_writes`). Writes below the bound are checked
  by the next weekly eval, and in between by the nightly recurrence metric.
  An agent's in-session `ccgm-learnings-log` write never counts.
- A checked row with a failed launch or judge error pauses the gate unless it
  still shows a regression, so a harness flake never opens it.
- `since` on a closed gate is the time of the results file before the newest
  one, the last run that could have been green.
- `dream-eval.sh --offline` (a plumbing smoke with canned scores) never writes
  the live `~/.claude/dreaming`: with no `CCGM_DREAMING_DIR`, or one that
  points at the live dir, it writes to a fresh temp dir and says so.
  `--allow-real-dir` is the explicit opt-in. An offline run once overwrote a
  paid live eval's results, and offline results there would make the gate
  read a fresh file.

**Breaker** (`state/optimistic.json`, `lib/breaker.py`). Every anomaly has a class.

| Class | Reasons | Effect |
|---|---|---|
| infra | `eval_gate_paused`, `harness_failure`, `analyze_failed`, `timeout`, `dirty_learnings_tree`, `eval_regression_unattributed` | no integration that night; never counts toward a trip |
| content | `eval_regression` (a batch integrated since `since` explains it), `batch_eviction_concentration`, `session_citation_concentration`, `rolling_add_rate_exceeded`, `recurrence_spike` | the batch it names is reverted at once with `ccgm-learnings-sync revert <sha>` and audited `batch_auto_reverted`; it also counts toward suspension (`circuit_breaker_max_anomalies`, default 2, in `circuit_breaker_window_nights`, default 7). `batch_eviction_concentration` names no batch: its rows are withheld before apply |

- **Resume** runs first in every nightly chain (`apply_dream_proposal.py
  breaker-check`), before analyze and independent of the gate: after
  `circuit_breaker_auto_resume_nights` (default 7) with no content anomaly
  since the suspension, it resumes and clears the content anomalies only.
  Integration still needs that night's gate to be open.
- `optimistic-resume` stays as the manual override.
- `recurrence_spike` is the seam for the Phase 4 recurrence metric:
  `apply_dream_proposal.py record-anomaly --reason recurrence_spike
  --batch-id <optbatch_id>`.

**Existing history.** Before #1098, `anomaly_log` held bare timestamps, and
the 89 `red_eval_gate` audit rows were nights the gate did not open. Nothing
is migrated on disk: `_read_optimistic_state()` re-classifies on every read.
A bare timestamp with an `anomaly_recorded` audit row for an infra reason
within 2 seconds after it is infra; any other bare timestamp may have been a
batch anomaly and stays content. On the 2026-07-09 suspension every entry is
infra, so the first `breaker-check` resumes it.

## No human queue (#1098 2.3, 2.4)

The operator does not review memories, so nothing waits for him. With
`optimistic_integration.enabled: true` every proposal ends in one of two
states, written on the row and as an apply-audit record:

| State | Status | Reason (`discard_reason`, audit `reason`) |
|---|---|---|
| integrated | `auto_applied` | dwell 24h, then live, behind the caps, corroboration and rollback |
| discarded | `discarded` | `low_confidence`, `low_prevalence`, `failed_corroboration`, `low_composite_score`, `cap_exceeded`, `batch_anomaly`, `compaction_guard_failed`, `global_manual_only`, `unsupported_kind`, `target_gone`, `invalid`, `promotion_failed`, `malformed`, `expired` |

- The engine decides tonight's rows and the still-pending rows of yesterday's
  file. A suspended breaker, a mid-batch timeout or an infra error leaves a row
  pending for the next night.
- `apply_dream_proposal.py expire-pending` runs every active night, whatever the
  gate said, and discards anything pending longer than
  `pending_max_age_hours` (48) as `expired`, `.jsonl.gz` included.
- Retention deletes a proposals file only through `retention-check`: in active
  mode its pending rows are audited `expired` first.
- A `_global` add promotes automatically when its transcript-verified evidence
  spans `promotion_min_sessions` (3) sessions over `promotion_min_slugs` (2)
  slugs. Otherwise it is rescoped to the slug its evidence comes from
  (`rescoped_from: "_global"`), or discarded `failed_corroboration` when no
  cited session verifies. Ops on existing `_global` rows stay manual.
- Corroboration reads a session's subagent transcripts
  (`<session>/subagents/agent-*.jsonl`) as well as the parent.
- `/dream-apply` is a manual override; `/dream-review` is for vetoes.

**Off means hold.** With integration `off` or `shadow`, nothing is discarded:
the engine does not run (shadow writes nothing), the expiry sweep and
`retention-check` hold, and retention keeps every proposals file that still has
a pending row. Both read the on-disk flag the way `dream-daily.sh` does, so a
legacy `auto_apply_counters: true` alone never starts discarding.

**The daily notice.** `health.json` carries `recent_changes`, the engine's
integrations and retirements from the last 7 days. The first session of each
day prints one line when anything changed since the last notice, for example
`dreaming: integrated 2 learnings last night (devtrainer: "…"; _global: "…") · retired 1 · /dream-review to veto`,
as `systemMessage` for the user and `additionalContext` for the model. The
sentinel is `state/notice.json`. Later sessions, and days with nothing new,
print nothing. A red health notice takes precedence. Nothing asks a question.

**Backlog close (one-off).** `bin/dream-close-backlog.sh` replays every pending
proposal, `.jsonl.gz` included, through the current filters: the loaded-context
prefilter (`already_encoded`), hook-error routing (`routed_to_autoheal`) and
trigger validation (`trigger_invalid`, `trigger_unverified`, only for rows that
carry a trigger). Everything else is discarded `expired` with detail
`pre-redesign`. It prints the plan by default and writes nothing; `--apply`
writes the statuses and the audit records. Run it once, by hand:

```bash
bash ~/.claude/bin/dream-close-backlog.sh            # dry run: plan + counts by reason
bash ~/.claude/bin/dream-close-backlog.sh --apply    # pending count goes to 0
```

## A broken pipeline announces itself (health)

Dreaming once sat broken for 87 days with every signal in a file nobody opens.
Now each chain run ends by recomputing `~/.claude/dreaming/state/health.json`
from scratch (`lib/health.py`, called from an EXIT trap in `bin/dream-daily.sh`,
so a crash still writes it). Nothing in it is sticky: fix the cause and the next
run reads green.

The `dreaming-health.py` SessionStart hook reads that file (no network, no
subprocess) and, when status is red or the last success is older than 36h,
injects `<dreaming-health status="red">` with the top two reasons and a fix
command each. After 3 red nights running it also tells the agent to mention the
problem once. Green and yellow inject nothing. With dreaming enabled but no
`health.json`, it says the pipeline has never run. The statusline shows
`dream:red` or `dream:yellow` from the same file.

Shared top-level shape (autoheal's `health.json` uses the same four keys):
`status`, `generated_at`, `last_success_at`, `reasons[{code, message, fix}]`.
Dreaming adds `analyze_rc`, `gate`, `breaker`, `pending_count`,
`oldest_pending`, `expired_last_night`, `discarded_last_night`,
`recent_changes`, `nights_since_last_integration`, `spend_7d`, `spend_30d`,
`budget_30d`, `eval_last_run`, `eval_last_cost`, `eval_budget_abort` and
`consecutive_red_nights` (counted from `state/health-history.jsonl`, one status
per date).

| Code | Red | Yellow |
|------|-----|--------|
| `no_recent_success` / `success_aging` | no good run in 36h, or ever | last good run 26 to 36h ago |
| `analyze_failed` | analyze step exited non-zero this run | |
| `breaker_suspended` | suspended 3+ nights | suspended 0 to 2 nights. The fix says what clears it (7 nights with no content anomaly) and the date that falls on |
| `gate_closed` | closed (a supported regression) 3+ nights in a row | closed 1 to 2 nights |
| `gate_paused` | | the gate is paused; the fix names the cause, e.g. "no fresh eval: eval-refresh is disabled until the Phase 4 smoke test lands" |
| `no_terminal_outcomes` / `pending_backlog` | oldest pending 7+ nights, nothing integrated or discarded in 7 nights | oldest pending 3+ nights |
| `spend_near_budget` | 30-day spend over 80% of budget (below 100%) | over 60% |
| `budget_paused` | | 30-day spend at or above budget (from `cost.log`). Replaces `spend_near_budget`; the message gives the resume date. It hides nothing by itself |
| `daily_cap_reached` | | `state/last-run.json` says the analyzer stopped at its daily cap; clears tomorrow |

`dream_analyze.py` writes `state/last-run.json` (`date`, `rc`, `outcome`, `spent_30d`, `budget`) with outcome `ok`, `budget_refused`, `daily_cap_refused` or `failed`. Exit code 2 is shared by both refusals and by real failures, so health never infers a refusal from it. Only a recorded `budget_refused` for today's date suppresses `no_recent_success`, `success_aging` and `analyze_failed`; a missing file or outcome `failed` stays red, even during a budget pause.
| `eval_budget_abort` | an eval budget-abort in the last 7 days with no later results | |

Gate, breaker and backlog rules apply only when `optimistic_integration` is
`shadow` or `active`. `remine_ratio` is not written: the mining cursors store
byte offsets and `cost.log` stores token totals, so neither records which input
repeated. `python3 ~/.claude/lib/health.py` rewrites the file on demand.

The chain also runs the weekly scorecard on Sundays (`scorecards/<date>.md`),
and `bin/dream-reconcile.sh` writes its report to `digests/<date>.reconcile.md`
with one pointer line in the digest, so the digest stays small.

**Bring-up:** installing the module copies the hook, but a new SessionStart hook
must be registered in the live `~/.claude/settings.json` (re-run
`./start.sh --add dreaming`, which merges `settings.partial.json`). Open a new
session to load it.

## The eval harness fails loud

`bin/dream-eval.sh` runs `eval/memory_eval.py`, whose `--gate` mode is the
regression gate the optimistic engine must pass nightly. Between 2026-07-15
and 2026-09-02 every nightly run scored `format_error_rate: 1.0` on all 54
rows and the gate read that as a memory failure. Neither memory nor the API
was at fault: the LaunchAgent exports a fixed PATH
(`/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`), Claude Code's native
installer puts the CLI in `~/.local/bin`, and every arm subprocess died with
`FileNotFoundError` before it ran. Runs an operator started from a login
shell worked, which is why the breakage looked intermittent.

Two rules keep that shut:

- **The `claude` binary is resolved to an absolute path before any task
  runs.** `resolve_claude_bin()` tries the ambient PATH, then the known
  install directories (`~/.local/bin`, `~/.claude/local`,
  `/opt/homebrew/bin`, `/usr/local/bin`), and raises -- naming everything it
  searched and pointing at `--claude-bin` / `CCGM_EVAL_CLAUDE_BIN` -- rather
  than starting a run that cannot work.
- **A whole-run format-error rate of 1.0 aborts.** One failed arm run stays
  non-fatal; a run where every arm failed is not a measurement, so the
  harness prints the first failure's raw output to stderr, exits non-zero,
  writes no results file (dropping any partial file it wrote this run), and
  records `evals/<date>.harness-broken`. The marker is load-bearing: `evals/`
  always holds prior runs, so an abort that wrote nothing would otherwise
  leave `--gate` reading the previous file and reporting `open` on a broken
  harness. While a marker is newer than the newest results file, `--gate`
  reports `harness broken: every agent run failed to execute on <date>`;
  the next run that produces results clears it.

**A launch failure may only move a row toward a closed gate, never toward
an open one.** A run that never executed is not sent to the judge (nothing
to grade, and on a broken harness that would be a whole task's judge calls
spent before the abort fires) and is excluded from every mean the classifier
reads -- flooring it to zero instead pulls the arm's mean down, and two
failed launches in a five-run baseline arm are enough to classify a row
`high_value`. Cost is the exception: a run stopped against
`--max-budget-usd` spent real money, and spend is not a quality metric. A
row is only as good as its worst arm, so any arm holding a failed run
downgrades the row to `error` (a `regression` keeps its label;
`downgrade_bucket_for_launch_failures()` decides). The gate itself reads pass
rates: a checked row with a failed launch shows its regression or pauses the
gate, never opens it.

The judge call is one Messages API request per run: no sampling parameters
(every judge model from Opus 4.7 / Sonnet 5 on returns 400 for one),
`thinking: {"type": "disabled"}` so a model bump cannot spend the output cap
on thinking, and `output_config.format` pinning the `{pass, score}` schema so
the verdict is valid by construction.

## Slug identity (read this before touching project-identity code)

Every transcript's owning learnings-store slug is re-derived from the
transcript's own `cwd` field via `learnings_store.detect_project_slug()` --
**never** via `session-history`'s `repo_detect.py`. Those two functions
compute *different* strings for the same repo (verified live on the
development machine: `repo_detect.py` returns the bare repo-directory
name, while `detect_project_slug()` returns the canonical `owner-repo`
form derived from the git remote). Using the wrong one silently mines
into an orphaned namespace no read path ever queries. `session-history`'s
`discover-sessions.sh` / `repo_detect.py` exist only to locate transcript
*files* by directory-name heuristic; this module
never imports or consults them for identity.

## Evidence bundle format

`mine_to_evidence_bundle(paths, max_input_tokens=...)` is the function that
wires `mine()` + `schema_canary()` + `cluster()` + `budget()` together into
the **evidence bundle** -- the frozen contract Epic 3's analyzer consumes.
The shape is pinned in `lib/evidence-bundle-schema.json` (a real JSON
Schema, validated by both this module's `--self-check` and, in Epic 3,
`dream_analyze.py` on load, via the same stdlib-only
`transcript_miner.validate_against_schema()`). At a glance:

```json
{
  "generated_at": "<ISO 8601 UTC>",
  "slugs": ["<learnings-store slug>", "..."],
  "session_count": 4,
  "sessions": [
    {
      "session_id": "<uuid or null>",
      "slug": "<learnings-store slug>",
      "git_branch": "<str or null>",
      "started_at": "<ISO or null>",
      "ended_at": "<ISO or null>",
      "token_totals": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
      "cache_read_ratio": 0.0,
      "user_corrections": [{"excerpt": "...", "timestamp": "...", "session_id": "...", "line": 5, "turns_after_failure": 2, "friction_line": 3}],
      "pr_links": [{"pr_number": 9001, "pr_repository": "org/repo", "pr_url": "https://..."}],
      "malformed_line_count": 0,
      "tool_use_count": 1,
      "friction_field_presence": 4
    }
  ],
  "signals": [
    {
      "kind": "redirection",
      "session_id": "<uuid>",
      "timestamp": "<ISO or null>",
      "line": 7,
      "excerpt": "<what the human typed; redacted, <=400 chars>",
      "context": "<the assistant turn before it; redacted, <=240 chars>"
    }
  ],
  "signals_dropped": 0,
  "clusters": [
    {
      "event_kind": "tool_error",
      "tool_name": "Bash",
      "command_prefix": "./deploy.sh --env prod",
      "count": 1,
      "is_friction": true,
      "sample_session_ids": ["<uuid>"],
      "exemplars": [{"session_id": "<uuid>", "excerpt": "<redacted, <=400 chars>", "timestamp": "..."}]
    }
  ],
  "friction_cluster_count": 4,
  "routine_cluster_count": 0,
  "token_estimate": 1234,
  "max_input_tokens": 200000,
  "over_budget": false,
  "malformed_line_total": 0,
  "canary": {"observed_versions": {"2.1.198": 4}}
}
```

Every `excerpt` field has already been through `redact_secrets()` (17 secret
token shapes, `hooks` module) and `redact_pii()` (email/phone/address, this
module's own addition -- `hook_utils` has no PII coverage) and truncated to
400 chars, redaction always applied *before* truncation so a boundary can
never lop a redaction marker in half.

## Redaction: two layers

- `hook_utils.redact_secrets()` -- 17 vendor secret-token shapes (API keys,
  GitHub tokens, etc.), shared with `autoheal`.
- `redact_pii()` (this module) -- email, phone, and street-address shapes.
  Transcripts are prose and routinely carry the operator's own PII;
  `redact_secrets()` alone does not cover that class.

Both run on every excerpt before it is stored anywhere or would leave the
machine (Epic 3's API calls).

## Schema drift canary

The transcript JSONL is an undocumented, internal Claude Code format that
has already drifted once (a `queue-operation` line type absent from earlier
research). `schema_canary()` validates a field-level structural contract via
the pure `validate_structure()` -- three hard invariants, each gated on a
corroborating "should-be-present" signal so a genuinely quiet week never
trips a finding:

- **friction** -- gated on `tool_use_count > 0`; violated when zero
  recognized friction-bearing fields (`is_error`/`toolUseResult`/
  `hookErrors`/`preventedContinuation`) were found anywhere in the batch.
- **token-economics** -- gated on `assistant_turn_count > 0`; violated when
  zero recognized token/cache usage fields were found anywhere.
- **turn-structure** -- gated on `parsed_line_count > 0`; violated when zero
  recognized user/assistant turns were found anywhere (this is what catches
  an envelope-`type` rename, which would otherwise silently zero
  `tool_use_count` too and slip past the friction invariant).

A violation raises `SchemaDriftError` naming the specific broken extraction
and field. `dream_analyze.py` catches it and records it as the one loud,
durable alarm (`state/canary.json`'s `active_incidents`, rendered by the
digest banner) rather than silently returning a thin evidence bundle. A
benign Claude Code version bump with every field intact passes silently --
there is no version allowlist to maintain, and the observed `version`
distribution (`canary.observed_versions`) is recorded for information only
and never gates the raise. PR-link field drift is a documented, accepted
residual the canary does not detect (PR links are optional evidence, not
integrity-critical).

## Quick checks

```bash
# Run the miner's own test suite (offline, fixture-only).
python3 -m pytest modules/dreaming/tests/test_transcript_miner.py -q

# End-to-end fixture pipeline + schema validation + JSON summary.
python3 modules/dreaming/lib/transcript_miner.py --self-check

# Analyzer unit tests (offline, fixture-only -- no network, no API key).
python3 -m pytest modules/dreaming/tests/test_dream_analyze.py -q

# Full offline pipeline: real transcript fixtures -> real miner -> --offline
# analyzer (canned map/reduce responses, no network) -> proposals -> digest.
# Builds its own throwaway ~/.claude/projects/-shaped temp directory --
# see the script for the exact layout dream-analyze.sh expects.
bash modules/dreaming/tests/test-dream-pipeline.sh
```

## When NOT to invoke this module's internals directly

- The miner and analyzer never write to the learnings store themselves --
  they only read it (for the reduce-phase projection) and propose.
  The opt-in `optimistic_integration` engine (default off) applies or
  discards every proposal; `/dream-apply` is the manual override --
  see `modules/dreaming/skills/dreaming/SKILL.md` for the full contract. Do not
  hand-edit `~/.claude/dreaming/proposals/*.jsonl` expecting either path to
  respect the edit.
- Do not call `mine()`/`discover()` against real transcripts expecting a
  file the analyzer has not consumed; run `dream-analyze.sh` (which mines
  internally) rather than wiring the miner up by hand.

## Manual installation (development clone)

```bash
# From a CCGM development clone (not the canonical):
bash start.sh --add dreaming
```

## Cross-references

- Plan (mining/apply/eval/scheduler foundation): `~/code/plans/ccgm-durable-memory-system/plan.md`
  (§5 Epics 1-8; §3.3 for the runtime-dir and config-key contract later
  epics build on).
- Plan (optimistic auto-integration): `~/code/plans/ccgm-optimistic-memory/plan.md`
  (§3 dwell-window architecture / per-op-kind posture / blast-radius caps /
  circuit breaker; §5 Epics 1-8).
- Decision log: `~/code/plans/ccgm-durable-memory-system/decisions.md`.
- `modules/self-improving/` -- the learnings store this module proposes
  changes into and (opt-in) auto-integrates into. `/dream-apply` and the
  optimistic engine are the only two writers.
- `modules/autoheal/` -- the capture-analyze-propose pipeline this module
  mirrors (not imports) -- curl invocation shape, daily cost cap, and
  cost.log bookkeeping are deliberately duplicated, not shared, per
  decisions.md bizlogic-006.
