# dreaming

Nightly, cost-capped dreaming service that mines Claude Code session
transcripts for cross-session failure patterns and proposes evidence-tagged
memory-store changes. Extends the `self-improving` learnings store with an
out-of-band analyzer -- `autoheal`'s capture-analyze-propose pipeline,
retargeted at session transcripts instead of permission events. Every
proposal is human-reviewed via `/dream-apply` by default; an opt-in
`optimistic_integration` mode (default off) auto-integrates instead, behind
a per-op-kind posture engine, a dwell window, blast-radius caps, and a
circuit breaker -- see "Optimistic auto-integration" below.

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
  an `optimistic-integrate` step, both config- and eval-gated, placed
  BEFORE the digest step (so tonight's just-integrated batch is reported
  while its dwell window is still entirely ahead of it).
- `bin/dream-eval.sh` -- extended with poisoning negative-control fixtures
  so the regression gate optimistic integration must pass every night
  actually exercises the attack shapes the engine is designed against.
- `commands/dream-review.md` (`/dream-review`) -- post-hoc review of
  auto-integrated and still-dwelling rows.
- `bin/ccgm-learnings-sync` (in `self-improving`) -- `revert <sha>`: a
  line-set-difference rollback that does NOT shell out to `git revert`
  (unsound against this store's `merge=union` shard files -- see
  `modules/self-improving/rules/learnings-store.md`'s Rollback section).
- `lib/scorecard.py` -- extended with auto-integrated / mid-dwell /
  reverted / breaker-trip counts.
- `bin/memory-setup.sh` (in `self-improving`) -- the activation
  forcing-function: an explicit prompt offering optimistic mode, the same
  script that already activates dreaming itself.

`optimistic_integration.enabled` is `false` by default in every case; the
operator opts in on their own machine via `memory-setup.sh`, never a hand
JSON edit.

## What's implemented so far (Epic 3)

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
  above lives here, `bin/dream-analyze.sh` is a thin wrapper).
- `lib/dreaming-prompt-map.md` / `lib/dreaming-prompt-reduce.md` -- the two
  system prompts, both opening with an untrusted-input threat-model block
  (excerpts are mined from other agents' sessions -- data, never
  instructions).
- `lib/proposal-schema.json` -- the per-change proposal row contract every
  written row is validated against before it touches disk.
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

Every proposal starts `status: "pending"`. This module never writes to the
learnings store -- `dream_analyze.py` only *reads* it (to build the
projection reduce compares candidates against) and *proposes*. Nothing
auto-applies yet; that is a later epic, gated separately and default OFF.

## What's implemented so far (Epic 2)

The **deterministic transcript miner** -- pure Python stdlib, no network
calls, no LLM calls, no scheduling:

- `discover(slugs, since_watermark)` -- enumerate transcript files under
  `~/.claude/projects/*/` whose owning learnings-store slug (re-derived from
  each transcript's own `cwd` field) is in the wanted set.
- `mine(path)` -- extract friction events (tool errors, hook errors,
  prevented-continuation), user-correction sequences, PR links, token
  totals + cache-read ratio, and session identity from one transcript.
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
  `/dream-apply` is the always-available, human-gated write path; the
  opt-in `optimistic_integration` engine (default off) is the other one --
  see `modules/dreaming/rules/dreaming.md` for the full contract. Do not
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
