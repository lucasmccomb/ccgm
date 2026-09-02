# Memory System

CCGM's durable, cross-session memory: a store that learns from your work and surfaces what it knows at the start of each new session. This is the comprehensive technical reference. For the visual overview, see [`memory-system.html`](./memory-system.html); for the concise pitch, see the [Memory System](../README.md#memory-system) section of the README.

---

## Overview

The memory system splits into two halves that share one store:

- **Read path** — the [`self-improving`](../modules/self-improving/rules/self-improving.md) learnings store plus a `SessionStart` hook that surfaces the current project's top-ranked learnings at the start of each new session. **Local and free — no network calls.**
- **Write path** — the [`dreaming`](../modules/dreaming/rules/dreaming.md) module: a nightly analyzer that mines your session transcripts into evidence-tagged *proposals* for new learnings, behind a human gate. **Opt-in; spends Anthropic API tokens.**

The read path is the valuable, always-safe half and is complete on its own. The write path is an optional layer that automates capture — you never need it to benefit from memory.

| Half | Module | Storage | Cost | Network |
|------|--------|---------|------|---------|
| Read path | `self-improving` | `~/.claude/learnings/` (local git repo) | free | none |
| Write path | `dreaming` | `~/.claude/dreaming/` | Anthropic API tokens | analyzer only, opt-in |

### The end-to-end loop

**Read path (capture → reuse):**

1. **Capture** — `/reflect`, `/consolidate`, `/retro`, or a direct `ccgm-learnings-log` call write a learning (a pattern, pitfall, preference, architecture fact, tool gotcha, or ops fact).
2. **Store** — it appends to a per-agent JSONL shard, projected at read time into a ranked view with confidence decay and staleness detection.
3. **Inject** — at the *next* fresh session start, the injection hook surfaces the project's top-ranked learnings into context.
4. **Reuse** — when a learning proves useful again, a `verify` op reinforces it, raising its effective confidence and refreshing its freshness.

**Write path (dreaming, automated capture):**

Nightly, the analyzer mines the day's transcripts into a redacted evidence bundle → proposes per-change deltas against the same store → writes them `pending` to `~/.claude/dreaming/proposals/{date}.jsonl`. From there, one of two things happens:

- **Human-gated (default)** — you review the digest and accept/reject with `/dream-apply`. Nothing reaches the store until you do.
- **Optimistic auto-integration (opt-in)** — a per-op-kind engine writes the change immediately, holds it behind a dwell window before it can reach agent context, and reports it for a post-hoc veto or one-command rollback.

Either way, an applied change feeds the same read path above once it's live.

### Architecture at a glance

| Component | Where | Role |
|-----------|-------|------|
| Learnings store | `~/.claude/learnings/` (git repo) | Append-only, per-agent-sharded JSONL op-events; confidence decay, staleness, supersede chains, injection sanitization, read-time quarantine |
| Store library | `modules/self-improving/lib/learnings_store.py` | The projection, ranking, validation, and write functions all three CLIs and the hook call into |
| Store CLI | `ccgm-learnings-log` / `-search` / `-sync` | Write/verify/supersede/deprecate; query + inject; git init/commit/pull/push/revert |
| Reflection | `/reflect`, `/consolidate`, `/retro` | Capture and maintain learnings |
| Injection hook | `learnings-inject.py` (`SessionStart`) | Gated on `CCGM_LEARNINGS_INJECT` **and** `source == "startup"`; emits one `<ccgm-learnings-injection>` block of top-ranked learnings |
| Reflection triggers | `reflection-trigger.py` (`PostToolUse`), `precompact-reflection.py` (`PreCompact`) | Nudge a reflection pass after merges/issue-closes and before context compaction |
| Nightly analyzer | `dreaming` LaunchAgent → `dream_analyze.py` | Mines transcripts → evidence → proposals via direct Anthropic API (no nested agent) |
| Digest / apply | `/dream-digest`, `/dream-apply` | Render the day's proposals; the always-available human-gated write path |
| Optimistic engine | `apply_dream_proposal.py` (opt-in) | Per-op-kind posture engine: dwell window, per-slug caps, batch-anomaly check, circuit breaker |
| Post-hoc review | `/dream-review`, `ccgm-learnings-sync revert <sha>` | Veto a still-dwelling row; roll back a bad batch |
| Eval gate | `dream-eval.sh --gate` | With/without-memory A/B regression gate optimistic integration must pass nightly |
| Scorecard | `/dream-scorecard` | Weekly, read-only observability of captured / injected / reused / applied + store health |

The read path uses only the first six rows. The rest ship with `dreaming`.

---

# Part 1 — The read path (`self-improving`)

## The data model: op-events and the projected view

The store is an **append-only op-event log**, not a mutable record store. Every write appends exactly one JSON line describing a *change*; the current state of any learning is *reconstructed* by folding its op-events at read time. Nothing on disk is ever mutated in place — this is what makes the store safe to sync with a union merge (see Part 3).

There are five op kinds:

| Op | Written by | Effect on the target |
|----|-----------|----------------------|
| `add` | `ccgm-learnings-log` (default subcommand) | Creates a new learning with zeroed counters |
| `verify` | `ccgm-learnings-log verify <id>` | `uses += 1`; refreshes `last_verified` (unless `--auto`) |
| `contradict` | `ccgm-learnings-log contradict <id>` | `contradictions += 1` |
| `deprecate` | `ccgm-learnings-log deprecate <id> --expected-sha …` | `deprecated = True` |
| `supersede` | `ccgm-learnings-log supersede <old_id> --content … --expected-sha …` | Retires the old head, seeds a replacement, links both directions |

An **on-disk op row** (`_build_op_row`) carries these keys, `json.dumps` with sorted keys: `id`, `op`, `target_id`, `timestamp`, `type`, `source`, `content`, `confidence`, `tags`, `files`, `project`, `key`, `content_sha256`, `writer`, `source_session`, `expected_sha256`, `supersede_reason`, `last_verified`, `deprecated`. Optional keys appear only when relevant: `auto: true` for engine-written ops, `dwell_until` when the row is held back, `evidence_sessions` for adds, and `reviewed_by` + `evidence_sessions` for global promotions.

The **projected read-time entry** — the shape every caller actually consumes — is the fold of those ops:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | 12-char uuid4 fragment |
| `timestamp` | ISO 8601 UTC | write time of the `add` |
| `type` | enum | `pattern`, `pitfall`, `preference`, `architecture`, `tool`, `operational` |
| `source` | enum | `observed` (default), `user-stated`, `inferred`, `cross-model` |
| `content` | string | sanitized single paragraph, ≤2000 chars |
| `confidence` | 1–10 | default 5 |
| `tags`, `files` | string[] | `files` are repo-relative; used for staleness |
| `key` | string | dedup key; content-hash-derived if omitted |
| `last_verified` | ISO 8601 UTC | bumped by non-`--auto` `verify` |
| `uses` | int | derived — count of `verify` ops |
| `contradictions` | int | derived — count of `contradict` ops |
| `deprecated` | bool | hard-excludes from reads |
| `supersedes` / `superseded_by` | string | supersede-chain links |
| `dwell_until` | ISO 8601 UTC | optimistic-integration only; absent = live |

Writing a raw line by hand is unsupported. Always go through `ccgm-learnings-log`, which emits the correct op-event; the derived counters (`uses`, `contradictions`, `superseded_by`, …) come only from the fold, never from a hand-edited field.

## Storage layout and sharding

```
~/.claude/learnings/                     ← LEARNINGS_ROOT (env: CCGM_LEARNINGS_DIR)
  config.json                            ← tunables (see below)
  .gitattributes                         ← "*.jsonl merge=union"
  {project-slug}/
    learnings.jsonl                      ← legacy v1 rows: read-only, still folded
    agents/{agent-id}.jsonl              ← v2: ALL new writes append here
    .quarantine.jsonl                    ← gitignored, per-machine (see Part 2)
  _global/
    agents/{agent-id}.jsonl              ← promotion-only (see Part 4)
```

Sharding is **per agent**: every writer appends only to its own `agents/{agent-id}.jsonl`, so two clones (or two machines) never write the same file and a union merge is conflict-free by construction. The legacy pre-shard `learnings.jsonl` is still folded on every read for backward compatibility, but no new writes land there.

**Agent id** resolves in precedence order: `CCGM_AGENT_ID` env → `AGENT_ID=` in the cwd's `.env.clone` → `"solo"`. This id is a *display / shard label only* — it is never trusted for provenance. Privileged operations (global promotion, tier-raising supersede) derive the trusted `writer` from the *transcript's own recorded `cwd`*, never from `CCGM_AGENT_ID`.

**Project slug** (`detect_project_slug`) resolves in precedence order: `CCGM_LEARNINGS_PROJECT` env → the git `remote.origin.url` slugified to `{owner}_{repo}` → the basename of the repo toplevel → the basename of cwd. Because the slug keys on the git remote, every clone of a repo shares one store even though each clone's session transcripts live under a different `~/.claude/projects/` directory.

**config.json** (read by `load_config`, defaults merged under any file values):

| Key | Default | Meaning |
|-----|---------|---------|
| `cross_project_search` | `false` | Allow `--cross-project` reads |
| `half_life_days` | `90` | Confidence decay half-life |
| `deprecate_threshold` | `2.0` | Effective-confidence floor below which entries are hidden |
| `stale_days` | `180` | `last_verified` age past which entries are hidden by default |
| `token_budget` | `2000` | Injection budget (≈ chars/4) |
| `max_results` | `8` | Injection result cap |

## The projection: how a read is computed

`project_slug()` is the canonical entry point; `load_all()` and `search()` both call it. The fold (`_project_lines` → `_fold`) is deterministic:

1. **Dedupe by op `id`**, first occurrence wins — *not* by content `key`, so counter-ops (which carry no key) don't collide.
2. **Total order** every op by `(parsed_timestamp, id)`. The `id` tiebreaker keeps the order stable when two ops share a timestamp.
3. **Two-phase fold.** *Phase A* seeds a head for each `add` (empty counters) and each legacy v1 row (projected verbatim — its counters already *are* state). *Phase B* applies `verify` / `contradict` / `deprecate` / `supersede` onto their target heads. An op whose target hasn't been seeded yet is deferred and retried each pass until a fixpoint; any op that never resolves is surfaced as an **orphan op**, never silently dropped.

**Conflict handling.** If two `supersede` ops target the same live head (two machines refined the same entry independently), the fold does *not* pick a last-writer winner. It marks `conflict: True` on the old head and on both competing replacements and records a `conflicting_superseded_by` list. Conflicted rows are surfaced to the CLI (flagged) but **suppressed from session injection** — they aren't settled truth. `/consolidate` resolves them.

`load_all()` returns all heads (including superseded/deprecated). `search()` layers filtering, ranking, and budgeting on top.

## Confidence, decay, and staleness

Confidence is explicit and ages automatically. `effective_confidence()` computes, at read time:

```
base      = clamp(confidence + min(uses * 0.25, 2.0) − contradictions * 1.5, 0, 10)
effective = base * 0.5 ^ (age_days / half_life_days)
```

- **Reuse boosts, but caps.** Each `verify` adds 0.25, capped at +2.0 total, so a learning can't accumulate unbounded authority by being verified over and over.
- **Contradiction cuts hard.** Each `contradict` subtracts 1.5, so "one session found this wrong" meaningfully weakens it.
- **Age halves it.** Decay is anchored on `last_verified` (falling back to `timestamp`), with a 90-day half-life by default. A learning nobody has re-verified in a quarter is worth half its base.
- `deprecated: true` zeroes effective confidence unconditionally.

Entries whose effective confidence falls below `deprecate_threshold` (2.0) are skipped at read time but never deleted — the audit trail stays intact. **Staleness** is a separate axis: an entry is stale if `last_verified` is older than `stale_days` (180). Stale entries are hidden by default (`--include-stale` to see them). An entry can be high-confidence *and* stale.

`search()` ranks surviving entries by `effective_confidence * (0.5 + relevance)`, dedupes by `(key, type)` keeping the latest, then trims to `max_results` (8) within a token budget of `token_budget * 4` chars.

## Supersede chains

`supersede` is the audit-preserving way to *replace* a learning (refined wording, evolved pattern, corrected `files[]` anchor, changed preference). It is atomic and bidirectional: the new head gets `supersedes: <old_id>`, the old head gets `superseded_by: <new_id>` and a `supersede_reason`. Omitted fields (`type`, `confidence`, `tags`, `files`) are inherited from the old entry, so the common "refine the wording" case is a one-flag call. Both rows persist; `search()` hides the old one unless `--include-superseded` walks the chain.

Supersede requires a **CAS check** (`--expected-sha`) so a replacement written against a stale view is rejected rather than silently clobbering a concurrent edit. A *tier-raising* supersede (e.g. bumping `source` from `inferred` to `user-stated`) additionally derives its trusted `writer` from the transcript cwd — you can't forge a more-trusted origin.

Prefer supersede over "deprecate + re-add": `deprecate` says *this is wrong, with no replacement*; supersede says *this was replaced by X*, and the chain is the record of how the entry evolved. `/consolidate` is deliberately supersede- and verify-heavy and deprecate-light.

## The dwell window

`dwell_until` marks a row **written but not yet live**. It is the mechanism behind dreaming's optimistic auto-integration (Part 4). A row whose `dwell_until` is in the future is excluded from `search()` — and therefore from session injection and the mining reduce projection — until the timestamp passes.

- `is_dwelling()` returns true iff `dwell_until` parses to a time strictly after now. Absent or malformed → false ("live"): a parse bug can never trap a row in permanent dwell.
- **Dwell only extends, never shortens.** Whenever a head is rebuilt, `dwell_until` is folded with `max(old, new)`, so a cheap follow-up op can't be chained to release a poisoned row early or shorten a human-set quarantine.
- Only the *ranked, injectable* result set (`search()`) hides a dwelling row. It stays resolvable by id — `load_all()`, `update_entry_by_id()`, `supersede_entry()` all see it — so it can still be reviewed, superseded, or reverted.

---

# Part 2 — Store integrity

A memory system that grows itself is a poisoning surface: a wrong or malicious "learning" injected into every future session. Three independent layers defend the store.

## The prompt-injection sanitizer

On **write**, `content` (and `supersede_reason`) pass through `sanitize_content()`, which neutralizes eight instruction-shaped patterns (all line-anchored, case-insensitive):

- `System:` / `Assistant:` / `User:` role prefixes
- `ignore (all|previous|prior) (instructions|prompts)`
- `you are (now|a|an) …`
- `disregard … (rules|instructions|guidelines)`
- `<system>` / `<instructions>` / `<prompt>` tags
- ` ```system ` fence openers

Matches are **wrapped** with `[neutralized]…[/neutralized]` rather than stripped, so the text stays readable while losing its instruction shape. Content is then whitespace-collapsed and capped at 2000 chars. The sanitizer is intentionally *not idempotent* (re-running would double-nest), so it is applied only on write.

## Read-time validation and quarantine

`git merge=union` operates on raw text — it never re-runs `validate_entry()`. So a row arriving via merge from another machine, a hand-edited shard, or a raw `git pull` that bypassed the sync tool is **not** re-validated by git. The projection closes that gap and is the load-bearing safety property:

On **every** projection, `_suppress_quarantined_heads()` re-runs `validate_entry()` (schema check) and `contains_unneutralized_injection()` (detection-only — it recognizes text already wrapped in `[neutralized]…` and passes it, but catches the same injection shapes surviving unwrapped) against each head's `content` and `supersede_reason`. A head that fails either check is:

- **dropped** from the heads returned to the caller on the spot, and
- recorded by id in `{slug}/.quarantine.jsonl` (gitignored, per-machine).

The offending line is **never removed or rewritten** in its shard — mutating another writer's line would break the append-only invariant union-merge safety depends on. Quarantine is an *exclusion at read time*, enforced inside the projection itself, so it catches every ingestion path, not just the one command that happened to run an eager check. `ccgm-learnings-sync pull` additionally runs an *eager* post-merge pass (new-since-merge lines only) for an immediate `{"quarantined": N}` report and to pre-populate the index; that's an optimization, not the guarantee.

## The compaction guard

When `/consolidate` rewrites an entry's content to save tokens, `compact_preserves_facts(old, new, threshold=0.05)` guards the rewrite. It extracts fact-bearing tokens from both texts — identifiers (`foo_bar`, `Foo.Bar`), proper-noun phrases, quoted strings, dates, version numbers, acronyms — and **rejects** the rewrite if more than 5% of unique old tokens went missing. It's a cheap regex backstop against the "rewrote the prose but lost the `users` table name" failure; false positives fail safe (flag for human review), false negatives are possible (it only sees tokens it recognizes). This is why consolidation prefers supersede (a delta) over whole-entry rewrite (which also discards `uses`/`contradictions` history and severs the audit chain).

---

# Part 3 — Versioning and cross-machine sync

`~/.claude/learnings/` is its own git repository, managed exclusively through `ccgm-learnings-sync` — never with raw `git pull`/`git rebase` against it. Every shard carries the `*.jsonl merge=union` gitattribute, so two machines appending to the same shard merge line-union-wise with no conflict.

**`init`** — idempotent. `git init` only if `.git` is missing; ensures the union gitattribute and a `.gitignore` covering per-machine state (`.env*`, `*.quarantine.jsonl`, `config.json`); commits whatever that leaves dirty. The read-time snapshot cache lives in a sibling `-cache/` directory *outside* the repo, so it's structurally never a sync participant.

**`commit`** — takes a store-wide lock, stands down as a provable no-op if a merge/rebase/cherry-pick is in progress (never commits over an unresolved merge), and commits only when the tree is actually dirty. `CCGM_LEARNINGS_AUTOCOMMIT=true` makes every mutating write spawn a detached `commit` afterward — best-effort, never blocking the write.

**`pull` is merge-only — never rebase.** It is `git fetch` + `git merge --no-edit`, and only that. This was tightened after an empirical finding (git 2.50.1): a rebase-based pull's conflict fallback required `git rebase --abort`, and that abort **silently wiped a concurrently-appended learning** — no commit, no reflog, unrecoverable. Removing rebase (and the abort it needs) removes the defect. On a real conflict (rare — only non-shard files like `.gitattributes` conflict), `pull` leaves the repo exactly as a human would: `MERGE_HEAD` present, markers in place, nothing aborted.

**`revert <sha>` is a line-set-difference, not `git revert`.** A plain `git revert` is *unsound* here: once a shard has had any write since the reverted commit, `git revert` invokes the union merge driver, whose whole job is "never let a line disappear" — it silently re-adds the very content the revert was trying to remove and reports "nothing to commit." Instead, `revert` computes the exact set of lines the commit *added* (`git diff --unified=0`) and removes that multiset directly from each touched shard's current content — a plain text transform git's merge machinery never sees. This is sound *because of* the append-only invariant: reverting always reduces to "remove the lines it added," regardless of what else was appended since. If any file in the commit shows *removed* or *modified* lines (which this store's write path never produces), the whole revert is refused before touching anything.

`pull` / `commit` / `push` / `revert` all serialize on a store-wide lock (`.git/ccgm-sync.lock`). **Cross-machine ordering** assumes roughly NTP-sane clocks: the fold orders by `(timestamp, id)` using each writer's local wall clock, so two machines racing the same shard under significant clock drift may order ops by the more-skewed clock. Badly-ordered ops still fold deterministically and safely (an op ahead of its target is deferred, then surfaced as an orphan if unresolved) — only the *causal* cross-machine order isn't guaranteed. Keep machines on NTP.

> **Rollback caveat.** `revert` stops *future* reads of a row, not the current session's. A row already read into a live session's frozen `SessionStart` prefix stays in that session until it restarts. This is also the honest limit of dreaming's dwell window (Part 4).

---

# Part 4 — The write path (`dreaming`)

Dreaming is a nightly, cost-capped, out-of-band pipeline that mines session transcripts into evidence-tagged *proposals* against the learnings store, behind a human gate. It never runs inside a Claude Code agent runtime — every model call is a direct `curl` to the Anthropic Messages API, which removes the nested-agent exec-escape surface. It runs headless under `launchd`.

## Stage 1 — deterministic mining (no model)

`transcript_miner.py` is pure stdlib. Its pipeline is `discover() → mine() → cluster() → budget()`:

- **`discover()`** enumerates the session-transcript JSONLs under `~/.claude/projects/*/`. Crucially, it re-derives each transcript's owning learnings slug by *peeking the transcript's own recorded `cwd`* and running `detect_project_slug()` — never from the `~/.claude/projects/` directory name, which is keyed by encoded cwd path (one per clone) and does *not* agree with the git-remote slug. A per-slug watermark (epoch-compared, fcntl-locked, forward-only) skips already-mined transcripts; slugs with no watermark fall back to a 7-day lookback.
- **`mine()`** extracts, in one deterministic forward pass: **friction events** (`tool_error` from `is_error`/non-zero Bash exit, `hook_error`, `prevented_continuation`), **user-correction events** (a human-origin user turn containing one of 22 negation phrases within 2 turns *after* a friction event), **PR links**, and **token economics** (per-session input/output/cache token sums + cache-read ratio). Every excerpt is redacted (secrets *then* PII) and truncated to 400 chars before storage.
- **`cluster()`** groups events by `(kind, tool, normalized-command-prefix)`, friction-first. Friction clusters keep ≤3 exemplars; routine clusters carry none.
- **`budget()`** trims to a token cap (default 200k) by round-robin down-sampling exemplars — but **never drops a friction cluster entirely** (each keeps ≥1 mandatory exemplar).
- **`schema_canary()`** validates three field-level structural invariants (`friction_events`, `token_economics`, `turn_structure`), each gated on a corroborating signal so a genuinely quiet window doesn't false-trip. On real drift it **raises `SchemaDriftError`** naming the broken extraction, field, and observed versions, and the run records a durable canary incident and excludes that slug — rather than silently mining nothing. Benign version bumps pass silently (no allowlist to maintain).

## Stage 2 — map-reduce analysis

`dream_analyze.py` runs a map-reduce over the mined slugs:

- **Map** — one call per due slug (default model `claude-sonnet-5`): the redacted evidence bundle → candidate learnings, each schema-validated. Runs with thinking disabled at `effort: low` — this is classification-shaped extraction, and Sonnet 5 thinks by default unless told otherwise.
- **Reduce** — one call across every planned slug's candidates plus a current-store projection (default model `claude-opus-4-8`): candidates → per-change proposals. Runs with thinking disabled and the model's default effort. A reduce that returns no usable proposal array fails the reduce, records an incident, and advances no watermark.

Both calls send `output_config.format` with a JSON schema, so the response shape is enforced by the API rather than requested in prose. `max_tokens` is a backstop at 16000, not a tuning knob, paired with a 300s curl timeout so the cap is reachable. A map call that stops at the cap is a failed extraction: that slug's watermark is held so its evidence is re-mined next run, a durable incident lands in the canary banner, and the count reaches the run summary the digest renders. The preflight prices a call at a separate planning figure, so raising the backstop does not shrink the plan.

A preflight cost plan walks due slugs *least-recently-dreamed first*, accumulating estimated map+reduce cost and stopping before it would exceed a `$10/day` cap (configurable). `--offline <dir>` replaces every `curl` with canned fixtures for deterministic, no-network testing. `load_config()` auto-migrates a legacy `auto_apply_counters: true` flag to `optimistic_integration.enabled: true` **in memory** (never rewriting disk) so a prior opt-in survives the rename.

## The proposal / evidence / gate contract

Every proposal (`~/.claude/dreaming/proposals/{date}.jsonl`) is a **per-change delta** against the store — `learning_add | verify | contradict | supersede | deprecate` — never a whole-store swap. Each carries: the evidence sessions that support it (redacted, ≤400-char excerpts), a prevalence count, a confidence score, and a justification. Proposals are fingerprinted (`sha256(kind:project:key_basis)`) and deduped against all prior proposal files. Nothing is applied silently: a proposal starts `pending` and stays there until a human `/dream-apply` accepts it — or the opt-in optimistic engine acts on it under its own gates.

**Two-layer redaction** runs before anything leaves the machine: every evidence excerpt passes through secret-token redaction *and* PII redaction (email / phone / address), then is truncated to ≤400 chars — redaction always *before* truncation so a boundary can't split a redaction marker. Untrusted proposal text, excerpts, and justifications are sanitized before they ever reach a digest a human reads or an agent session.

## Apply path A — human-gated (`/dream-apply`)

Always available, no opt-in required. `/dream-apply list` shows pending proposals; `/dream-apply <id>` accepts or rejects one. `apply_proposal()` is the single write entry point for both human and engine applies: it holds an exclusive lock across read → not-pending-check → dispatch → status-rewrite (so a proposal is applied at most once), maps the kind to a `ccgm-learnings-log` op (with CAS retry for supersede/deprecate), and always writes an audit record. This is the **only** path a `_global` proposal can ever be promoted through: `promote_to_global()` is invoked only after a recorded human accept, verifies every cited evidence session resolves to a real transcript, and derives the writer from that transcript's cwd.

## Apply path B — optimistic auto-integration (opt-in, default OFF)

`optimistic_integration.enabled` is `false` in the shipped module — a public module must not silently auto-write on install. Turning it on is a deliberate choice made through `memory-setup.sh` (see Part 6), never a buried JSON edit. When on, every pending proposal is resolved to a **posture** (the single source of truth every gate reads):

| Op-kind | Posture | Dwell? | Confidence floor | Per-run cap |
|---|---|---|---|---|
| `learning_verify` | `optimistic-immediate` | no | 7 | none |
| `learning_add` | `optimistic-dwell` | yes | 8 (or composite gate) | `max_add_supersede_per_run` (10) |
| `learning_supersede` | `optimistic-dwell` | yes | 8 (or composite gate) | shared with add |
| `learning_contradict` | `dwell-quarantine` | yes | 8 | `min(max_eviction_absolute, fraction × live heads)` |
| `learning_deprecate` | `dwell-quarantine` | yes | 8 | shared with contradict |
| any → `_global` | `gated` | n/a | n/a | human accept stays required |

`learning_verify` integrates immediately because it's purely additive (bounded `+0.25/use`) and reversible by a later contradict — nothing to hold back. Everything else is written to the store *immediately* but carries a `dwell_until` (default 24h) that excludes it from every read path until the window elapses. Anything that misses its floor/cap, targets `_global`, or arrives on an anomalous/tripped run falls back to `pending` — never silently dropped.

### The composite eligibility gate (add/supersede only, default OFF)

A *second*, independent opt-in beneath the engine. While off, add/supersede keep flat floors (conf ≥ 8, and prevalence ≥ 2 verified sessions for add) — bit-for-bit today's behavior. When on, those two op-kinds pass a deterministic, no-LLM waterfall (no model anywhere in the write decision):

1. **Static floor** — `confidence < static_floor` (default 5, never below the hard-coded `MIN_STATIC_FLOOR = 4`) → skip.
2. **Legacy escape** — a conf ≥ 8 add with ≥ 2 verified sessions (or conf ≥ 8 supersede) still admits, so enabling only *widens* what admits.
3. **Origin gate** (non-compensatory) — admit only if evidence tier is `user-corrected` OR ≥ 2 transcript-verified sessions. No soft signal rescues a weak origin.
4. **Composite score** — `S = Σ wᵢ·signalᵢ ≥ θ` (θ default 0.58) over four signals: `confidence` (.40, the only model-assigned input), `prevalence` (.30, distinct verified sessions, capped), `recency` (.20, 30-day half-life on evidence age), `novelty` (.10). Every signal is re-derived from the transcripts and live store *at apply time*, never trusted from the proposal row.

The point is admitting the useful conf-5–7 memories the flat floor held back (user-corrected or seen across sessions) while making each newly-admitted class *harder to forge* than confidence inflation. Evictions and `verify` are untouched. Every scored row writes its full per-signal breakdown to the audit trail.

### Blast-radius controls and the circuit breaker

All caps are scoped **per project slug** (a legitimate focused night on one project is topically narrow by nature):

- **Per-run caps** — `max_add_supersede_per_run` (10) on adds+supersedes; the smaller of `max_eviction_absolute` (3) or `max_eviction_fraction_per_run` (0.20 × the slug's live head count) on contradicts+deprecates. Live head count is computed once, before any write, so same-run adds can't inflate it.
- **Batch-anomaly check** — keys on *eviction concentration* (contradict/deprecate piling onto one row or tag ≥ 0.6 of the batch), never on add-tag overlap, so an all-one-tag night of adds never false-trips it.
- **Cross-night accumulation** — counts `auto:true` add/supersede volume per slug over a rolling 14-night window (threshold 40), the one control that looks across nights. It bounds the "patient attacker drips one plausible add per night" case that stays under every per-run cap.
- **Windowed self-healing circuit breaker** — trips when anomalies (a batch-anomaly fire, a red eval gate, a dirty tree, a timeout, session-citation concentration, or rolling-rate exceeded) reach 2 within a trailing 7 nights (not strictly consecutive). A trip is surfaced loudly and **auto-resumes** after 7 quiet nights; `optimistic-resume` forces an immediate manual re-enable. It fails *closed* on a corrupt state file.

### The eval gate

Before optimistic integration may act **at all**, `dream-eval.sh --gate` must pass. It runs a three-arm A/B (`baseline`, `treatment` = with mined memory, `full_context` = the whole transcript dumped in) over a seed task suite, classifying each into four buckets (`regression > high_value > redundant > gap > inconclusive`). `gate_check()` fails **closed** on any of nine conditions — no results, stale results, results predating the last content-shaping store mutation, any regression row, no high-value row, no *live* (non-offline) dreamed high-value row, a nonzero judge-error rate, or a noise-only control that produced a high-value proposal. Missing or red ⇒ no integration that night, and a red gate is itself recorded as a breaker anomaly.

> **Today the gate stays deliberately closed** for capable models: the harness has not yet demonstrated that mined memory beats a full-context dump on outcome *or* clears the efficiency path on realistic agentic tasks (the injected facts block is a minority of each turn's input, dominated by Claude Code's own re-read system context). So `/dream-apply` (human review) remains the real write path; optimistic auto-integration is wired, gated, and off.

## Poisoning defenses (why "promote what's prevalent" is safe here)

- **Origin binding is transcript-verified, not caller-supplied.** A proposal's evidence must resolve to real transcript files; `writer` is derived from the transcript's recorded `cwd`, never from an exportable env var. A supersede can never *raise* an entry's source tier without an independently-verified new session.
- **`_global` is promotion-only, through exactly one path** — `promote_to_global()`, invoked only after a recorded human accept. No automated `_global` add exists anywhere.
- **Breadth is informational, not a bypass.** Under-prevalence `_global` proposals are labeled `needs_manual_promotion` in the digest — never dropped, never silently applied. (For a solo/single-clone user the "≥2 agents" breadth condition is realistically unsatisfiable, so treat fleet-wide auto-promotion as a latent multi-agent capability, not a solo-user outcome.)

## The nightly scheduler chain

A `launchd` LaunchAgent (`com.$USER.ccgm.dreaming.daily`, default 03:30) runs `dream-daily.sh`, an exit-tolerant chain — one step's failure never kills the rest or trips a launchd cooldown:

```
analyze → eval-refresh → optimistic-integrate → digest → reconcile → retention
```

`digest` runs *after* `optimistic-integrate` so tonight's just-integrated batch is reported while its dwell window is still entirely ahead of it. `optimistic-integrate` is both config-gated (raw on-disk `enabled` read) and eval-gated (a missing eval script fails *closed*), and runs under a 600s timeout. `retention` gzips artifacts older than 30 days and deletes gzipped ones older than 60, scoped to `proposals/`, `digests/`, and `state/runs/` (never the perpetual state files).

## Reconciliation (read-only)

`reconcile_automemory.py` compares Claude Code's own harness auto-memory (`~/.claude/projects/*/memory/`) against the learnings store and appends a `## Reconciliation` section to the day's digest: **import candidates** (auto-memory facts absent from the store) and **contradictions** (store rows that dispute a topic auto-memory still presents as current, flagged for `/consolidate`). It **never writes** to `~/.claude/projects/` — the harness's own consolidator owns that file, and colliding writers on it is exactly the failure class this whole system exists to prevent.

---

# Part 5 — Observability

## The weekly scorecard

`/dream-scorecard` renders a deterministic, read-only weekly report to `~/.claude/dreaming/scorecards/{date}.md` — every number is a count of something already on disk; it never touches the store. Metrics, over a half-open 7-day window:

- **Captured** — new `add` events, by type and project.
- **Injected** — sessions that received memory, from the per-machine injection telemetry (IDs + counts only, never content).
- **Reused** — `verify` events. **This is the key signal**: a reuse means a stored learning actually helped in a later session, which is the whole point.
- **Applied** — proposals applied (keyed strictly on `outcome == "applied"`), by kind.
- **Optimistic integration** — auto-integrated / mid-dwell / reverted-after-review / circuit-breaker trips.
- **Store health** — active count and effective-confidence bands, plus deprecated/superseded tallies.

## Injection telemetry

Each surfacing appends one record to `~/.claude/dreaming/injection-log/{date}.jsonl`: `timestamp`, `session_id`, `source`, `project_slug`, `injected_count`, `injected_ids`, and an `approx_tokens` estimate — **memory IDs + counts + a token estimate only, never the memory content** (so it never becomes a second PII surface). It's per-machine, lives *outside* the synced learnings store, and is best-effort: any failure is swallowed and never blocks or alters the injected block. Because the read-path hook writes it, telemetry accrues even without `dreaming` installed; the `/dream-scorecard` command that renders it ships with `dreaming`.

---

# Part 6 — Operating the system

## Enabling it

Run the activation script (idempotent — re-running reports current state and changes nothing already set):

```bash
bash ~/.claude/bin/memory-setup.sh
```

It confirms before every write and walks three prompts in order:

1. **Read path** — on your yes, it jq-deep-merges `env.CCGM_LEARNINGS_INJECT = "true"` into `~/.claude/settings.json` (preserving your existing keys, read-back verified) and runs `ccgm-learnings-sync init` so the store is a versioned git repo. Local, free, no network.
2. **Write path** — if `dreaming` is installed, it offers to activate it: this costs Anthropic API tokens and installs the nightly LaunchAgent. It prompts for your API key with hidden input, writes it to `~/.claude/dreaming/.env` (mode `0600`, never echoed), and runs `dream-install.sh`. If `dreaming` isn't installed, it prints `bash start.sh --add dreaming`.
3. **Optimistic mode** — if `dreaming` is installed, it asks directly: "enable auto-integration with a 24h dwell window + daily report?" On yes it sets `optimistic_integration.enabled = true` in `~/.claude/dreaming/config.json` — the only way this ever turns on. A nested follow-up offers the composite eligibility gate; enabling it forces the outer flag on in the same write, so eligibility can never land with the engine off.

The read path alone is a complete, useful configuration. Add `dreaming` only when you want automated nightly capture and accept the token cost; add optimistic mode only when you want that capture to reach the store without running `/dream-apply` yourself.

## Injection applies to new sessions only

The injection hook fires on `SessionStart` **only when `source == "startup"`** — never on resume or compact. The injected block is frozen into the session's prompt prefix at start (this prefix-cache safety is deliberate; re-injecting per turn is the exact anti-pattern the hook avoids). Consequences:

- An **already-open session will not gain** newly-logged learnings. Start a *fresh* session to pick them up.
- A learning you log **during** a session is not visible to that same session's injected block — it appears at the next fresh start.

## Troubleshooting

**Injection isn't firing.** Check, in order:

1. **The flag.** `CCGM_LEARNINGS_INJECT` must be truthy (`true` / `1` / `yes`) in the environment the session starts with — under `env` in `~/.claude/settings.json` (what `memory-setup.sh` sets). With the flag unset the hook is a strict no-op.
2. **A fresh session.** The hook only runs on `source == "startup"`. Resuming or continuing won't inject; open a new session.
3. **Learnings for this project.** Injection surfaces the *current project's* store. A brand-new project with nothing logged has nothing to inject — confirm with `ccgm-learnings-search --query <topic>`.
4. **Conflicted rows are suppressed.** A conflicted learning (two competing edits racing the same entry) is withheld from injection because it isn't settled truth — run `/consolidate` to resolve it.

## Privacy

- Learnings stay **on your machine**. `~/.claude/learnings/` is a local git repo with no remote by default — nothing leaves the machine.
- **Cross-machine sync is opt-in.** Add a *private* git remote and `ccgm-learnings-sync push`. This repo holds personal memory — keep it private; never point it at a public repo.

  ```bash
  git -C ~/.claude/learnings remote add origin git@github.com:<you>/ccgm-learnings.git
  ccgm-learnings-sync commit && ccgm-learnings-sync push
  ```

- Injection telemetry records IDs + counts only, never content, and is never committed to the synced store.
- When you opt into `dreaming`, the analyzer sends **redacted** transcript evidence to the Anthropic API using your own API key (stored in `~/.claude/dreaming/.env`). The read path makes no network calls of its own.

---

## Reference

### CLI surface

```bash
# Capture / maintain
ccgm-learnings-log --type pattern --content "…" --tag git --confidence 8
ccgm-learnings-log verify <id>            # reinforce (uses += 1, refresh freshness)
ccgm-learnings-log contradict <id>        # weaken (contradictions += 1)
ccgm-learnings-log supersede <old_id> --content "…" --expected-sha <sha> --reason "…"
ccgm-learnings-log deprecate <id> --expected-sha <sha>
ccgm-learnings-log config cross-project on

# Query / inject
ccgm-learnings-search --query <topic> --max 5 --format preamble
ccgm-learnings-search --tag tailwind --cross-project
ccgm-learnings-search --query auth --format jsonl --include-superseded --include-stale

# Sync
ccgm-learnings-sync init | commit [-m …] | pull | push | revert <sha> | status
```

### Source (the authoritative, agent-facing specs this guide distills)

- [`self-improving.md`](../modules/self-improving/rules/self-improving.md) — the reflection loop and capture triggers
- [`learnings-store.md`](../modules/self-improving/rules/learnings-store.md) — store schema, confidence decay, supersede chains, the dwell window, git sync, and rollback
- [`dreaming.md`](../modules/dreaming/rules/dreaming.md) — the nightly pipeline, the proposal / evidence / gate contract, and the optimistic auto-integration engine
- Store library: `modules/self-improving/lib/learnings_store.py` · hooks: `modules/self-improving/hooks/` · dreaming pipeline: `modules/dreaming/lib/`
