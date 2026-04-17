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

```
~/.claude/learnings/
    config.json                 # Cross-project opt-in + tunables
    {project-slug}/
        learnings.jsonl         # Append-only per project
    _global/
        learnings.jsonl         # Learnings that apply across projects
```

The project slug is auto-derived from the git remote (`{owner}_{repo}` sanitized). Override via `CCGM_LEARNINGS_PROJECT` or `--project`.

---

## Schema

Each line is a JSON object:

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

---

## Staleness

An entry is stale if its `last_verified` is older than `stale_days` (default 180). Stale entries are excluded from search by default; pass `--include-stale` to see them. Staleness is a separate dimension from confidence decay; an entry can be high-confidence AND stale (e.g., a once-important pattern for a codebase that has been refactored).

When the entry lists `files`, the search path can optionally verify those files still exist. Missing anchors are a strong signal the learning no longer applies.

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

## Migration from MEMORY.md

The legacy flow wrote narrative markdown to `~/.claude/projects/*/memory/MEMORY.md`. The new flow:

- **Dual-write during transition.** `/reflect` writes to the JSONL AND appends a pointer line to MEMORY.md for human browsing. Over time, MEMORY.md becomes a thin index rather than a content store.
- **JSONL is truth.** If the two disagree, the JSONL wins. MEMORY.md is treated as a rendered view that can be regenerated.
- **No automatic import.** Old MEMORY.md entries stay where they are; import them manually (via `ccgm-learnings-log --from-json ...`) only for the ones you actually want to keep.
- **`/consolidate` reads both.** The consolidation pass dedupes across the JSONL and flags stale MEMORY.md entries for retirement.

See `self-improving.md` for the reflection loop that feeds the store.
