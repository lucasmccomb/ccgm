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
5. Prints the rendered status table and the command surface.

## Command surface

| Command | Purpose |
|---|---|
| `/dream` | This overview. |
| `/dream-digest [date]` | Render today's or a specific date's digest. |
| `/dream-apply [id\|list]` | List pending proposals, or apply/reject one by id. |

## Config flags

See `modules/dreaming/lib/dream_analyze.py`'s `DEFAULT_CONFIG` for the full
schema. Defaults: `enabled: true`, `auto_apply_counters: false`,
`map_model: "claude-sonnet-5"`, `reduce_model: "claude-opus-4-8"`,
`daily_cost_cap_usd: 10.00`, `promotion_min_sessions: 3`,
`promotion_min_agents: 2`.

`auto_apply_counters` stays `false` until a human deliberately edits
`~/.claude/dreaming/config.json` — there is no toggle command for it yet
(unlike autoheal's `/autoheal-toggle`); flipping it is a manual config edit,
by design, so it is never accidentally enabled.

## When NOT to invoke

- This is a status read-out, not an apply path. To act on a specific
  proposal, use `/dream-apply <id>` after reading it via `/dream-apply list`.
- To read a rendered digest body, use `/dream-digest [date]`.

## Cross-references

- Rule: `modules/dreaming/rules/dreaming.md` (Epic 8; not yet present in
  this branch — see `modules/self-improving/rules/learnings-store.md` for
  the store side of this system in the meantime).
- Plan: `~/code/plans/ccgm-durable-memory-system/plan.md` §5 Epic 6.
