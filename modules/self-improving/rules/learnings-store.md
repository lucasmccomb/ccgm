# Learnings Store

Structured, schema-validated, append-only JSONL store for personal, cross-project learnings. Replaces the narrative-only `MEMORY.md` flow with a queryable store that supports confidence decay, staleness detection, and token-budgeted injection into command context.

This is the **personal** counterpart to `compound-knowledge` (which is team-shared per-repo under `docs/solutions/`). Do not conflate the two. Compound-knowledge entries are committed and code-reviewed; learnings stay under `~/.claude/learnings/` and never leave your machine unless you explicitly opt-in.

---

## Why JSONL, Not Markdown

Narrative markdown decays silently. A bullet from 2023 looks the same as a bullet from last week, but one of them is probably wrong now. The JSONL store fixes four problems:

1. **Confidence is explicit.** Every entry has a 1-10 confidence score. Read-time decay makes old entries weaker automatically.
2. **Staleness is detectable.** `last_verified` + referenced files let us flag entries whose anchor disappeared.
3. **Injection is safe.** The write path sanitizes instruction-like patterns so pasted prompts cannot be replayed as instructions later.
4. **Search is ranked.** Keyword + tag + type + confidence rank results; a token budget caps what gets injected into each command.

MEMORY.md still exists as an index and human-readable rendered view, but the JSONL is the source of truth.

---

## Storage Layout

`~/.claude/learnings/` is a git repository (see "Versioning & Sync" below):

```
~/.claude/learnings/
    config.json                     # Cross-project opt-in + tunables
    .gitattributes                  # *.jsonl merge=union
    {project-slug}/
        learnings.jsonl             # Legacy pre-shard file -- read-only from
                                     # the current write path's perspective;
                                     # still folded on every read for
                                     # backward compatibility, but no new
                                     # writes land here
        agents/
            {agent_id}.jsonl        # Per-agent shard -- ALL new writes
                                     # (add/verify/contradict/supersede/
                                     # deprecate) land in the writer's own
                                     # shard, never learnings.jsonl
    _global/
        agents/
            {agent_id}.jsonl        # Promotion-only -- see "_global promotion"
```

The project slug is auto-derived from the git remote (`{owner}_{repo}` sanitized). Override via `CCGM_LEARNINGS_PROJECT` or `--project`. `agent_id` resolves via `CCGM_AGENT_ID` env → `AGENT_ID` in `.env.clone` → `solo`.

---

## Schema

Every line on disk is an **op-event** (`add`/`verify`/`contradict`/`supersede`/`deprecate`); the table below is the **projected, read-time view** returned by `load_all()`/`search()` — the shape callers actually consume, not the physical write format. Writing a raw line by hand is unsupported; always go through `ccgm-learnings-log` (or the store's Python API), which emits the correct op-event and lets the projection derive `uses`/`contradictions`/`deprecated`/`superseded_by` from the op chain.

Each returned entry is a JSON object:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | 12-char uuid4 fragment |
| `timestamp` | ISO 8601 UTC | yes | write time |
| `type` | enum | yes | `pattern`, `pitfall`, `preference`, `architecture`, `tool`, `operational` |
| `source` | enum | no | `observed` (default), `user-stated`, `inferred`, `cross-model` |
| `content` | string | yes | Sanitized single-paragraph prose, max 2000 chars |
| `confidence` | 1-10 | no | Default 5 |
| `tags` | string[] | no | Lowercase kebab-case |
| `files` | string[] | no | Repo-relative paths; used for staleness |
| `project` | string | no | Slug (auto-detected if omitted) |
| `key` | string | no | Dedup key; derived from content hash if omitted |
| `last_verified` | ISO 8601 UTC | yes | Updated on successful reuse |
| `uses` | integer | no | Increments on verify |
| `contradictions` | integer | no | Increments on contradict |
| `deprecated` | bool | no | Hard-excluded from reads when true |
| `supersedes` | string | no | Id of the entry this one replaces (set on the new entry) |
| `superseded_by` | string | no | Id of the entry that replaced this one (set on the old entry) |
| `supersede_reason` | string | no | Free-form note on why the replacement happened |
| `dwell_until` | ISO 8601 UTC | no | Optimistic-integration only (see "Dwell Window" below); absent = immediately live |

### Type vocabulary

- **`pattern`** — reusable approach that worked (e.g., "prefer `git rev-parse --show-toplevel` over shelling out to pwd").
- **`pitfall`** — known-bad trap (e.g., "don't use `git stash` with untracked files across branch switches").
- **`preference`** — user or project taste call (e.g., "Lucas prefers squash merges, not rebase-merge").
- **`architecture`** — codebase fact (e.g., "auth middleware runs before rate limiting in this repo").
- **`tool`** — tool/framework gotcha (e.g., "Tailwind v4 omits cursor:pointer on buttons").
- **`operational`** — ops fact (e.g., "Cloudflare Pages deploys take 2-3 minutes; do not test immediately").

---

## Confidence Decay

Effective confidence is computed at read time:

```
base = clamp(confidence + min(uses * 0.25, 2.0) - contradictions * 1.5, 0, 10)
effective = base * 0.5 ^ (age_days / half_life_days)
```

- Half-life default: 90 days (configurable).
- Uses boost capped so a single learning cannot accumulate unlimited authority through repetition.
- Contradictions cut hard (1.5 points each) to prevent "one person said this is wrong" from silently persisting.
- `deprecated: true` zeros effective confidence unconditionally.

Entries whose effective confidence falls below the deprecate threshold (default 2.0) are skipped at read time without being deleted from the JSONL. This keeps the audit trail intact.

**Read-time decay vs gate-time eligibility — different clocks, non-duplicative.** The `dreaming` module's opt-in composite-eligibility gate (see `modules/dreaming/rules/dreaming.md` → "Eligibility composite") scores an *evidence recency* signal at **admission** time — how old the mined transcript evidence is when a `learning_add`/`learning_supersede` is auto-integrated, on a short (default 30-day) half-life. The confidence decay above is a separate, later clock: it ages an *already-admitted* entry by its own `timestamp` on the store's 90-day half-life, every time the entry is read. One is a write-gate on evidence freshness; the other is a read-time weakening of stored rows. They never double-count — a row that clears the gate then begins decaying independently — so neither is a substitute for the other.

---

## Supersede Chains

When a learning needs to be explicitly replaced (same topic, updated guidance), use `supersede` instead of `deprecate` + new entry. Supersede is atomic and bidirectional:

- The **new** entry gets `supersedes: <old_id>` and a `supersede_reason`.
- The **old** entry gets `superseded_by: <new_id>`.
- `search()` hides the old entry by default. Pass `include_superseded=True` (CLI: `--include-superseded`) to walk the chain.

Unlike `deprecate`, which tells the reader "this is wrong," supersede says "this was replaced by X." The chain is the audit trail: reading old → follow `superseded_by` → reach current state.

Missing `type_`, `confidence`, `tags`, or `files` are inherited from the old entry — the common "refine the wording" case is `supersede <old_id> --content "..."` with no other flags.

Supersede is the right tool when:
- A pattern evolved (old version still worked, new version is better).
- A preference changed (user now prefers X over Y).
- An architecture fact was refined (was "runs at 5s", is now "runs at 2s").
- A `/consolidate` pass needs to fix a stale `files[]` anchor or duplicate while keeping the chain (same content, corrected metadata — see "Delta-First Consolidation" below).

Use `deprecate` (not supersede) when:
- The learning is outright wrong and has no replacement.
- The pattern was abandoned; there is no "new version."

---

## Compaction Guard

When a compaction pass (e.g., `/consolidate`) rewrites a learning's content to reduce tokens, call `compact_preserves_facts(old, new, threshold=0.05)` before committing the rewrite. The guard extracts fact-bearing tokens from both texts — identifiers (`foo_bar`, `Foo.Bar`), proper nouns, quoted strings, dates, version numbers, acronyms — and rejects the rewrite if more than `threshold` (default 5%) of unique old tokens go missing.

Intent: model-driven compaction can silently drop facts. The guard is a cheap regex-based backstop that catches the common "rewrote the prose but lost the `users` table name" failure mode. It is not semantic; false positives are fine (they fail safe), false negatives are possible (the guard can only see tokens it recognizes).

```python
from learnings_store import compact_preserves_facts
ok, dropped = compact_preserves_facts(old_content, new_content)
if not ok:
    # Flag for human review; do not overwrite the original.
    log_unsafe_rewrite(old_id, dropped)
```

---

## Delta-First Consolidation (ACE)

`/consolidate` maintains the store via **incremental delta operations, not whole-entry rewrites.** This follows Agentic Context Engineering (ACE, arXiv:2510.04618): context curated through small, append-only deltas preserves far more detail than periodic monolithic rewrites, which collapse hard-won specifics and cause "context drift." A whole-entry rewrite also discards the entry's `uses`, `contradictions`, and `last_verified` history and severs the supersede audit chain.

When maintaining an entry, pick the **least destructive** operation that resolves the issue, in this strict order:

1. **Counter delta** (`verify` / `contradict`) — mutates only counters; content untouched. Use whenever the question is "is this still right?"
2. **Supersede** — the default for *any content change* (refined wording, corrected `files` anchors, evolved pattern, changed preference). Atomic, bidirectional, audit-preserving; inherits unspecified fields from the old entry.
3. **Deprecate** — only when the learning is outright wrong with no replacement, or genuinely obsolete.
4. **Whole-entry content rewrite** — last resort, only when supersede does not fit, and **only after `compact_preserves_facts` passes**. If the guard rejects, abort and flag for human review.

This is why both primitives above exist: supersede provides the audit-preserving delta, and the compaction guard backstops the rare in-place rewrite. A healthy consolidation pass is supersede- and verify-heavy and deprecate-light; a deprecate-and-re-log-heavy pass is the whole-entry-rewrite anti-pattern in disguise.

---

## Staleness

An entry is stale if its `last_verified` is older than `stale_days` (default 180). Stale entries are excluded from search by default; pass `--include-stale` to see them. Staleness is a separate dimension from confidence decay; an entry can be high-confidence AND stale (e.g., a once-important pattern for a codebase that has been refactored).

When the entry lists `files`, the search path can optionally verify those files still exist. Missing anchors are a strong signal the learning no longer applies.

---

## Dwell Window

`dwell_until` (optimistic-memory plan.md §3.2) marks a row **written but not yet live** — the mechanism behind `dreaming`'s opt-in optimistic auto-integration (see `modules/dreaming/rules/dreaming.md`). A row with a `dwell_until` in the future is excluded from `search()` — and therefore from SessionStart injection and the mining reduce projection — until that timestamp passes, exactly mirroring how `include_stale`/`include_superseded` work above:

- `is_dwelling(entry, now=...)` returns true iff `dwell_until` parses to a time strictly after `now`. Absent or malformed `dwell_until` fails open to `False` ("live") — a parse bug must never trap a row in permanent dwell.
- `search()` takes a matching `include_dwelling: bool = False` kwarg; `ccgm-learnings-search` exposes it as `--include-dwelling`, so a human reviewing the store (or `/dream-review`) can see a still-dwelling row while agent context cannot.
- A dwelling row is still resolvable by id — `load_all()`, `update_entry_by_id()`, `supersede_entry()`, and the CAS liveness check all go through the *unfiltered* projection, not `search()`. Only the ranked, injectable result set hides it.
- **The dwell can only get longer, never shorter.** `dwell_until` is folded with `max(old, new)` whenever a head is rebuilt (a fresh `add`, a `supersede` targeting an existing row, or a counter-op) — so a `supersede` can never shorten a target's existing dwell window. This closes the "chain a cheap op to release a poisoned row early" attack against a row still dwelling (or a row a human has manually quarantined with a long dwell).
- `dwell_hours` is a config knob read by `dreaming`'s optimistic engine, not by this store — the engine computes the dwell and passes it to `ccgm-learnings-log add`/`supersede`/`contradict`/`deprecate` as `--dwell-hours <n>`; the store only ever applies the max-with-existing rule above.

---

## Injection Filter

Search results are ranked by `effective_confidence * (0.5 + relevance)`, then trimmed to:
1. Max-result cap (default 8).
2. Token budget (default 2000 tokens; approximated as chars/4).

This is the critical difference from MEMORY.md: you cannot accidentally load 50 stale learnings into a command preamble. The budget is enforced on the read path.

### Prompt-Injection Sanitizer

On write, `content` is passed through a pattern filter that neutralizes common LLM-instruction shapes:

- `System:` / `Assistant:` / `User:` role prefixes
- `Ignore all previous instructions` / `Disregard ...`
- `You are now ...`
- `<system>` / `<instructions>` / `<prompt>` tags
- ```` ```system ``` ```` fence openers

Matches are wrapped with `[neutralized]...[/neutralized]` rather than stripped so the content stays readable. This is a best-effort filter; the point is to stop accidental prompt replay, not to defeat determined attackers. Untrusted content should not be logged as a learning at all.

---

## CLI Surface

### Log a learning

```bash
ccgm-learnings-log \
  --type pattern \
  --content "Always quote PostgreSQL reserved keywords like \"position\", \"order\" in migrations" \
  --tag supabase --tag migrations \
  --confidence 8
```

### Search / inject

```bash
# Preamble block for injection into a skill
ccgm-learnings-search --query supabase --max 5 --format preamble

# Raw JSONL for pipelines
ccgm-learnings-search --query auth --format jsonl

# Cross-project (opt-in via config)
ccgm-learnings-search --tag tailwind --cross-project
```

### Reinforce / contradict / retire

```bash
ccgm-learnings-log verify <id>       # Bumps uses + last_verified
ccgm-learnings-log contradict <id>   # Bumps contradictions counter
ccgm-learnings-log deprecate <id>    # Hard-excludes from reads
```

### Supersede (atomic replace)

```bash
# Refine the wording, keep type/tags/files from the old entry
ccgm-learnings-log supersede <old_id> \
  --content "Updated guidance..." \
  --reason "clarified based on 2026-04-22 incident"

# Change tags as well
ccgm-learnings-log supersede <old_id> \
  --content "..." \
  --tag workflow --tag git \
  --reason "broader scope"
```

Old entry's `superseded_by` is set atomically; both rows persist in the JSONL. Default search hides the old row; `ccgm-learnings-search --include-superseded` surfaces the chain.

### Config

```bash
ccgm-learnings-log config cross-project on
```

Other tunables live in `~/.claude/learnings/config.json`:

```json
{
  "cross_project_search": false,
  "half_life_days": 90,
  "deprecate_threshold": 2.0,
  "stale_days": 180,
  "token_budget": 2000,
  "max_results": 8
}
```

---

## When to Log

Log a learning when all three hold:

1. **Observed in THIS session** or explicitly confirmed by the user. No speculative entries.
2. **Likely to recur** across future sessions or projects. One-off ticket details do not qualify.
3. **Not already written.** Run `ccgm-learnings-search --query "<topic>"` first; if the pattern exists, `verify` it instead of logging a duplicate.

### Quality bar

- **One idea per entry.** If the content has more than one sentence and the second sentence changes topic, split into two entries.
- **Actionable phrasing.** "Prefer X over Y because Z" not "We talked about X."
- **Anchors where possible.** If the learning is tied to specific files, include them in `files[]` so staleness detection can flag drift.

---

## Versioning & Sync

`~/.claude/learnings/` (or `$CCGM_LEARNINGS_DIR`) is its own git repository, managed exclusively through `ccgm-learnings-sync` — never with raw `git pull`/`git rebase` against this repo (see "Raw git is unsupported" below).

### Init

```bash
ccgm-learnings-sync init
```

Idempotent — safe to run repeatedly, and safe to run against a repo that already has a `.git` directory and a commit history from before this tool existed (e.g. a manual `git init` + baseline commit made during initial bring-up). `init`:

- `git init` only if `.git` is missing.
- Writes `.gitattributes` (`*.jsonl merge=union`) if the line isn't already present.
- Writes `.gitignore` covering per-machine, never-synced state: `.env*`, `*.quarantine.jsonl`, `config.json`. The read-time snapshot cache (`snapshot.jsonl` + its watermark) needs **no** gitignore entry — it already lives outside this repo entirely, in a sibling `learnings-cache/` directory (`LEARNINGS_CACHE_ROOT` in `learnings_store.py`), so it is structurally never a sync participant.
- Commits whatever that leaves dirty. Running `init` twice produces no second commit.

### Commit cadence

```bash
ccgm-learnings-sync commit [-m "message"]
```

Stages everything and commits iff the tree is actually dirty; a clean tree is a no-op, not an error. Default message is `learnings: {ISO timestamp} on {agent_id}`.

**Autocommit.** Set `CCGM_LEARNINGS_AUTOCOMMIT=true` and every successful mutating write (`add`/`verify`/`contradict`/`supersede`/`deprecate`/`promote_to_global`) fires a detached `ccgm-learnings-sync commit` after the write completes — it never blocks the write path, and its failure (or stand-down) is invisible to the caller. This is opt-in; unset by default.

### Pull is merge-only — never rebase

```bash
ccgm-learnings-sync pull
```

`pull` is `git fetch` + `git merge --no-edit`, and **only** that — it never rebases and never runs `git merge --abort` / `git rebase --abort` on a stopped merge. This was tightened after an empirical finding (git 2.50.1, scratch repos): a rebase-based `pull` design's conflict fallback required `git rebase --abort` to recover, and that abort **silently wiped a concurrently-appended learning from the working tree** — no commit, no reflog entry, unrecoverable. The union merge driver itself was verified to work correctly under both rebase and plain merge; the defect was specifically in the abort-on-conflict recovery path. Removing rebase (and the abort it requires) from the picture removes the defect.

If `pull` hits a real conflict (rare — union-attributed `*.jsonl` shards auto-resolve; a conflict means two machines edited the same *other* tracked file, e.g. `.gitattributes` itself), it leaves the repo exactly where a human would find it: `MERGE_HEAD` present, conflict markers in the offending file, nothing aborted. Resolve it with plain git (`git add <file> && git commit`) and move on. `ccgm-learnings-sync status` reports an in-progress merge loudly rather than staying silent about it.

`pull` refuses outright (exit 1, no git operations attempted) when:
- the working tree is dirty — commit first;
- no remote is configured (see "Optional remote (H2)" below).

**Sync lock.** `pull`/`commit`/`push`/`revert` all take a store-wide lock file (`~/.claude/learnings/.git/ccgm-sync.lock`, never tracked) so they serialize against each other — a `pull` in flight and a `commit` cannot interleave. `commit` (and therefore autocommit, since it always routes through `commit`) additionally stands down as a **provable no-op** whenever `.git/MERGE_HEAD` or a rebase-state marker is present, rather than committing over an unresolved merge.

**Known residual — not closed by this lock.** Ordinary learnings writes (`ccgm-learnings-log add`/`verify`/`supersede`/...) do **not** themselves take the sync lock; only the sync verbs do. Two sync verbs rewrite shard files in place: `pull` (its `git merge`) and `revert` (its line-set-difference rewrite). A write that lands in the brief window while `pull`'s `git merge` is actively rewriting that same shard file is not structurally protected against the merge's own file write — **that is the residual.** In practice this window is short (a clean union merge completes in well under a second) and the write survives on disk in the overwhelmingly common case (git's checkout of merged content is a write, not a byte-level race, under normal filesystem semantics) — but it is not a proven-safe guarantee the way the lock-protected sync verbs are. `revert` does **not** share this residual: its per-shard read-through-write critical section takes an exclusive `fcntl.flock` on the same shard file `file_locked_append` locks (`_shard_flock` in `ccgm-learnings-sync`), so a concurrent append serializes against revert's rewrite instead of being lost between revert's read and its write. Closing `pull`'s equivalent window would require extending the lock into the store's own write path — touching `learnings_store.py`'s write functions, which is deliberately out of scope for the sync layer (see "Autocommit lives outside the store" below).

### Post-merge validation and quarantine

`git merge=union` operates on raw text — it has no idea what `validate_entry()`, the write-time sanitizer, or CAS mean. A shard line arriving via merge from another machine (or a hand-edited file, or a compromised/buggy peer) is therefore **not** re-validated by git itself. Two layers close this gap:

- **Eager, at merge time.** After every clean `ccgm-learnings-sync pull` merge, `pull` re-checks every line that is new since before the merge — content-bearing rows (legacy v1 snapshots, and any `add`/`supersede` op-event) run through `learnings_store.validate_entry()`; counter-ops (`verify`/`contradict`/`deprecate`) carry no free-text `content` by design, so they get a lighter structural check instead (a recognized op naming a real target) — applying the content schema check to counter-ops would falsely quarantine every legitimate one ever merged. This pass exists to give an immediate, loud report (`{"quarantined": N}`) and to pre-populate the quarantine index below; it is an optimization, not the load-bearing safety property.
- **Load-bearing, at every projection.** `learnings_store.py`'s projection (`project_slug()`, which backs both `load_all()` and `search()` — the fold that produces the current heads for a slug) independently re-runs `validate_entry()` on every head, and additionally checks every model-influenceable free-text field (`content`, `supersede_reason`) for unneutralized injection-shaped content via `contains_unneutralized_injection()` — a detection-only check that recognizes text sanitize_content() already wrapped in `[neutralized]...[/neutralized]` and passes it, while catching the same INJECTION_PATTERNS shapes anywhere they survive unwrapped (never re-running the sanitizer itself, which is not idempotent). This is what actually makes quarantine an **exclusion mechanism**: a head that fails either check is dropped from the heads returned to the caller on the spot, and its id is recorded in `<slug>/.quarantine.jsonl` if it isn't there already. Because this runs inside the projection itself, it catches every ingestion path — `ccgm-learnings-sync pull`, a hand-edited shard file, or a raw `git pull`/`git rebase`/`revert` that bypassed `ccgm-learnings-sync` entirely — not just the one command that happens to have an eager check.

A line that fails validation is **never removed or rewritten** in its original shard file — mutating another writer's line breaks the append-only invariant that union-merge safety depends on (a locally "fixed" line diverges from the still-unfixed original elsewhere, and a later sync reintroduces the original alongside it). Instead, its id is recorded in that project's `<slug>/.quarantine.jsonl` (gitignored, local, per-machine, shared by both layers above — same path, same `line_id`-keyed envelope shape). The projection consults this index (plus its own fresh validation) on every read and **excludes** matching ids from the heads it returns: isolation is real and enforced at read time, not just an audit trail nobody consults.

`ccgm-learnings-sync status` surfaces the total quarantined-line count so it doesn't sit silently in a file nobody looks at.

**Raw git skips the loud report, not the safety check.** The eager, immediate `{"quarantined": N}` report and quarantine-index pre-population only run inside `ccgm-learnings-sync pull`. A raw `git pull`, `git rebase`, or `git -C ~/.claude/learnings revert <sha>` (see Rollback, below) still applies `merge=union` via `.gitattributes` and skips that eager pass — but the very next `load_all()`/`search()` call independently re-validates and excludes whatever bad content the raw git operation landed, at projection time. Always prefer `ccgm-learnings-sync pull` for the immediate feedback and the pre-populated index; raw git is discouraged, not unsafe.

### Optional remote (H2)

v1 works entirely local-only; nothing requires a remote. To add one:

```bash
gh repo create <you>/ccgm-learnings --private --description "CCGM learnings store (personal memory -- private)"
git -C ~/.claude/learnings remote add origin git@github.com:<you>/ccgm-learnings.git
ccgm-learnings-sync commit && ccgm-learnings-sync push
```

This repo holds personal memory — keep it **private**; never point it at the public `ccgm` repo. `push` refuses cleanly (exit 1) with this same pointer if no remote is configured yet.

**Cross-machine ordering assumes roughly NTP-sane clocks.** The projection's fold order is `(timestamp, id)`; timestamps are each writer's local wall clock. A single machine protects itself with per-writer monotonic stamps, but two *different* machines racing the same shard (both resolve `agent_id()` to `solo` unless `.env.clone`/`CCGM_AGENT_ID` disambiguate them) can still have their ops ordered by whichever clock is more skewed. This is a documented, accepted residual, not a bug to chase: badly-ordered ops still fold deterministically and safely (an op whose target hasn't materialized yet is deferred, then surfaced as `orphan_ops` if it never resolves — never silently dropped), it just means the *causal* order across machines isn't guaranteed under significant clock drift. Keep machines on NTP.

### Rollback

```bash
git -C ~/.claude/learnings log --oneline
ccgm-learnings-sync revert <sha>
```

`ccgm-learnings-sync revert <sha>` is the only sound way to undo a commit here — it deliberately does **not** shell out to `git revert`. A plain `git revert` is unsound against this store's shard files specifically because of the `*.jsonl merge=union` gitattribute every shard carries (the same attribute that makes `pull` safe): once a shard has had even one write since the reverted commit (the realistic case — a `/dream-review` target from days ago has almost certainly had later nights or human accepts touch the same file), `git revert` invokes the union merge driver for that path's 3-way merge, and the driver's whole job is "never let a line disappear" — it silently re-adds the very content the revert was trying to remove and reports "nothing to commit, working tree clean," having made no change at all.

Instead, `revert` computes the exact set of lines commit `<sha>` **added** (`git diff --unified=0 <sha>~1 <sha>`) and removes that exact multiset from each touched file's current content directly — a plain content transformation that never invokes git's merge/attribute machinery, so the union driver never gets a vote. This is sound *because of* (not despite) the store's own append-only invariant (every write is a new appended line; existing lines are never rewritten in place): reverting a commit always reduces to "remove the lines it added," regardless of what else has been appended to the same file since, in what order, or whether the commit created the file fresh. If any file in the commit's diff also shows removed or modified lines — this store's own write path never produces that shape; a hand-edited shard or an unrelated manual commit could — the whole revert is refused before any file is touched: nothing mutated, resolve manually.

`revert` is guarded by the same store-wide sync lock as `commit`/`pull`/`push`, and refuses outright (not attempted) on a dirty working tree or an already in-progress git operation. Two caveats:

- **Revert stops future reads, not the current session's.** A row that was already read, ranked, and injected into a live session's frozen SessionStart context (see "Injection Filter" above) stays in that session's prompt — the frozen prefix cannot be un-injected mid-session. `ccgm-learnings-sync revert` removes the row from every projection computed *after* the revert; an already-running session that picked it up must be restarted to actually drop it. This is also the honest limit on `dreaming`'s optimistic-integration dwell window (see `modules/dreaming/rules/dreaming.md`): the dwell shrinks the *pre-exposure* blind spot to zero, but reverting an already-exposed row still only stops *future* sessions, not the one that already read it.
- Pre-`init` mutations (writes made before this repo existed) have no commit to revert; use `ccgm-learnings-log deprecate <id>` instead.

### Autocommit lives outside the store

`learnings_store.py`'s write path carries exactly one small hook: after a successful mutating op, if `~/.claude/learnings/.git` exists and `CCGM_LEARNINGS_AUTOCOMMIT=true`, it spawns a detached `ccgm-learnings-sync commit` and returns immediately. Everything else — the sync lock, standing down mid-merge, the actual `git add`/`git commit` — lives inside `ccgm-learnings-sync`, not the store. This keeps the store's write path (a cross-epic-frozen file) storage-only; sync orchestration is `ccgm-learnings-sync`'s job alone, whether it was triggered by a human or by the autocommit hook.

---

## Migration from MEMORY.md

The legacy flow wrote narrative markdown to `~/.claude/projects/*/memory/MEMORY.md`. The new flow:

- **Dual-write during transition.** `/reflect` writes to the JSONL AND appends a pointer line to MEMORY.md for human browsing. Over time, MEMORY.md becomes a thin index rather than a content store.
- **JSONL is truth.** If the two disagree, the JSONL wins. MEMORY.md is treated as a rendered view that can be regenerated.
- **No automatic import.** Old MEMORY.md entries stay where they are; import them manually (via `ccgm-learnings-log --from-json ...`) only for the ones you actually want to keep.
- **`/consolidate` reads both.** The consolidation pass dedupes across the JSONL and flags stale MEMORY.md entries for retirement.

See `self-improving.md` for the reflection loop that feeds the store.
