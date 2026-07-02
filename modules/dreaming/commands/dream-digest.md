# /dream-digest - Render a Dreaming Digest

Print the markdown digest for today (default) or a specific past date.

## Usage

```
/dream-digest             # today
/dream-digest 2026-05-15  # a specific date
```

## What it does

1. Resolve the target date. With no argument, use today (the agent reads
   `date -u +%Y-%m-%d`). With an argument, validate the `YYYY-MM-DD` shape.
2. Check whether `~/.claude/dreaming/digests/{date}.md` exists.
3. If it does, print the file body verbatim.
4. If it does not, fall through to one of the following:
   - If `~/.claude/dreaming/proposals/{date}.jsonl` exists (with any number
     of records, including zero — unlike autoheal's digest, dream-digest.sh
     never skips an empty day, since the canary banner must be checkable on
     any date): run `bash ~/.claude/bin/dream-digest.sh {date}` to
     materialize the digest, then print it.
   - If no proposals file exists for that date either: print "no digest
     available for {date}" plus the path that was checked, and separately
     check `~/.claude/dreaming/state/canary.json` — if it names an active
     incident, surface that regardless of whether a digest exists for this
     specific date (the canary is durable, not day-scoped).

## When to invoke

- The daily launchd job (03:30 local) has not yet fired and you want to see
  what is ready right now.
- A past day's digest scrolled past you and you want to re-read it.
- You suspect the analyzer or mining canary fired on a given day and want
  to confirm what happened (the digest surfaces a loud canary banner when
  `state/canary.json` names an active incident — this is independent of
  which date you pass, adrev-014).

## When NOT to invoke

- To apply or reject a specific proposal — use `/dream-apply <id>`.
- To toggle config flags — edit `~/.claude/dreaming/config.json` directly
  (no `/dream-toggle` command exists yet).
- For dates older than the retention window (gzipped at 30 days, deleted at
  60 days by `dream-daily.sh`'s retention step). Older digests have been
  swept and are not recoverable from this command.

## How it interacts with state

This command is read-mostly. The one write path is re-running
`dream-digest.sh` when a proposals file exists but the digest does not.
That call writes only to `~/.claude/dreaming/digests/{date}.md` and never
modifies the proposals, state, or learnings-store files.

## Cross-references

- Generator: `~/.claude/bin/dream-digest.sh`
- `/dream-apply [id|list]` — the write path for the proposals this digest
  summarizes.
- Plan: `~/code/plans/ccgm-durable-memory-system/plan.md` §5 Epic 3 (digest
  renderer), §5 Epic 6 (apply path this digest points at).
