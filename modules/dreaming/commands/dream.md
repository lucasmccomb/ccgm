# /dream - Dreaming Status Overview

Inspect dreaming status and learn the slash command surface. Read-only: this
command modifies no files. Use the listed subcommands for stateful actions.

## Usage

```
/dream
```

## What it shows

1. The set of dreaming slash commands and a one-line description of each.
2. The current config flags (`enabled`, `auto_apply_counters`, `map_model`,
   `reduce_model`, `daily_cost_cap_usd`, `promotion_min_sessions`,
   `promotion_min_agents`) read from `~/.claude/dreaming/config.json`.
3. The watermark (`~/.claude/dreaming/state/last-dreamed.json`) — last mined
   transcript timestamp per project slug.
4. Today's digest path and whether it exists yet
   (`~/.claude/dreaming/digests/{today}.md`).
5. The count of `pending` proposals across the retained window (walk
   `~/.claude/dreaming/proposals/*.jsonl`, filter `status == "pending"`) and,
   separately, counts of `accepted` / `auto_applied` / `rejected` for today.
6. Any active canary incident (`~/.claude/dreaming/state/canary.json`) —
   render it as a loud banner if present, matching the digest's own
   treatment (adrev-014: this must stay visible even if a human skipped the
   day it first appeared).
7. Whether the LaunchAgent is loaded: `launchctl list | grep ccgm.dreaming`.
8. **Optimistic auto-integration state** (optimistic-memory plan.md §3.5,
   Epic 6): a one-line summary —
   - `enabled` — `config.json`'s `optimistic_integration.enabled` (a
     DIFFERENT, more specific flag than the top-level `enabled` in item 2,
     which gates the mining/analyze pipeline, not auto-integration).
   - `suspended` — `~/.claude/dreaming/state/optimistic.json`'s
     `suspended` field (the windowed circuit breaker). Absent file means
     `false` (never tripped).
   - **N dwelling** — count of rows currently inside their `dwell_until`
     window, summed across every project slug. Use the SAME recipe
     `/dream-review` documents (`{e for e in load_all(slug) if
     is_dwelling(e)}` per slug, via `learnings_store.list_project_slugs()`
     for the slug list) — never `search(include_dwelling=True)`, which
     token/max-results-caps its output and would under-count.
   - **N auto-applied last night** — the same today's `auto_applied` count
     item 5 already computes, restated here as the headline figure.

## How it works

This command is a thin Claude reader, not a shell script. The agent:

1. Reads `~/.claude/dreaming/config.json` (treating missing keys as the
   defaults documented in `modules/dreaming/lib/dream_analyze.py`'s
   `DEFAULT_CONFIG`).
2. Reads `~/.claude/dreaming/state/last-dreamed.json` and
   `~/.claude/dreaming/state/canary.json` if present.
3. Lists files under `~/.claude/dreaming/proposals/`,
   `~/.claude/dreaming/digests/`, and `~/.claude/dreaming/evals/` to
   summarize state. For the pending count, either shell out to
   `python3 modules/dreaming/lib/apply_dream_proposal.py list` (JSON array,
   deterministic) or read the JSONL files directly — prefer the CLI, since
   it already applies the correct 8-day review window and pending filter.
4. Runs `launchctl list | grep ccgm.dreaming` to check LaunchAgent load
   state (non-zero grep exit just means "not loaded" — not an error).
5. Reads `optimistic_integration` out of the same `config.json` (item 2)
   for `enabled`, and `~/.claude/dreaming/state/optimistic.json` for
   `suspended` (treat a missing file as `suspended: false`, matching
   `apply_dream_proposal._default_optimistic_state()`). Computes the
   dwelling count via `learnings_store.list_project_slugs()` +
   `load_all(slug)` + `is_dwelling(e)` per slug (never `search()` — see
   item 8 and `/dream-review`'s own docstring for why).
6. Prints the rendered status table and the command surface.

## Command surface

| Command | Purpose |
|---|---|
| `/dream` | This overview. |
| `/dream-digest [date]` | Render today's or a specific date's digest. |
| `/dream-review [veto\|revert]` | Review auto-integrated + dwelling rows; veto a row or revert a batch. |
| `/dream-apply [id\|list]` | Back-compat: list pending proposals, or apply/reject one by id (the `gated`/`_global` path). |

## Config flags

See `modules/dreaming/lib/dream_analyze.py`'s `DEFAULT_CONFIG` for the full
schema. Defaults: `enabled: true`, `auto_apply_counters: false`,
`map_model: "claude-sonnet-5"`, `reduce_model: "claude-opus-4-8"`,
`daily_cost_cap_usd: 10.00`, `promotion_min_sessions: 3`,
`promotion_min_agents: 2`.

`auto_apply_counters` is the **legacy** verify-only flag, kept only for
backward compatibility — it is not the flag to set on a fresh config.
`dream_analyze.load_config()` migrates a config that still has it set `true`
to `optimistic_integration.enabled = true` (with the conservative defaults),
in memory on read, so a prior opt-in survives the rename.

`optimistic_integration.enabled` (a nested, more specific flag — see item 8
above) is SEPARATELY `false` by default (`DEFAULT_OPTIMISTIC_INTEGRATION`
in `dream_analyze.py`). The activation prompt that offers it ships in
`memory-setup.sh` (PR #824) — turning it on is a `y` at that prompt, never a
hand-edit of `~/.claude/dreaming/config.json`, per
`modules/dreaming/rules/dreaming.md`'s do-not-hand-edit rule.

`optimistic_integration.eligibility.enabled` is a further, independent opt-in
*beneath* the flag above (governs `learning_add`/`learning_supersede`
admission only), also `false` by default. `memory-setup.sh` offers it as a
separate prompt, only once optimistic integration itself is on. See
`modules/dreaming/rules/dreaming.md` > "Eligibility composite" for the gate's
full contract.

## When NOT to invoke

- This is a status read-out, not an apply path. To act on a specific
  auto-integrated or dwelling row, use `/dream-review`. To act on an
  older-style pending (`gated`/`_global`) proposal, use `/dream-apply <id>`.
- To read a rendered digest body, use `/dream-digest [date]`.

## Cross-references

- `/dream-review [veto|revert]` — the optimistic model's post-hoc review
  and rollback surface (Epic 6).
- Rule: `modules/dreaming/rules/dreaming.md` — the full dreaming +
  optimistic-integration contract, including the "Eligibility composite"
  subsection and the do-not-hand-edit rule for
  `~/.claude/dreaming/config.json`. Store side:
  `modules/self-improving/rules/learnings-store.md`.
- Plan: `~/code/plans/ccgm-optimistic-memory/plan.md` §5 Epic 6 (this
  command's own update); `~/code/plans/ccgm-durable-memory-system/plan.md`
  §5 Epic 6 (the original `/dream`/`/dream-apply` this command predates).
