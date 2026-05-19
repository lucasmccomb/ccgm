# /autoheal-digest - Render an Autoheal Digest

Print the markdown digest for today (default) or a specific past date.

## Usage

```
/autoheal-digest             # today
/autoheal-digest 2026-05-15  # a specific date
```

## What it does

1. Resolve the target date. With no argument, use today (the agent reads
   `date +%Y-%m-%d`). With an argument, validate the `YYYY-MM-DD` shape.
2. Check whether `~/.claude/autoheal/digests/{date}.md` exists.
3. If it does, print the file body verbatim.
4. If it does not, fall through to one of the following:
   - If `~/.claude/autoheal/proposals/{date}.jsonl` exists with at least
     one record: run `bash ~/.claude/bin/autoheal-digest.sh` with the
     env override `CCGM_AUTOHEAL_TODAY={date}` to materialize the digest,
     then print it.
   - If no proposals file exists for that date: print "no digest available
     for {date}" plus the path that was checked.

## When to invoke

- The daily launchd job has not yet fired and you want to see what is
  ready right now.
- A past day's digest scrolled past you and you want to re-read it.
- You suspect the analyzer crashed on a given day and want to confirm
  no proposals landed.

## When NOT to invoke

- To apply a specific proposal — use `/autoheal-apply <id>` (Epic 11) or
  `/permission-fix apply <id>` (Epic 4) instead.
- To toggle config flags — use `/autoheal-toggle`.
- For dates older than the retention window (default: gzipped at 30 days,
  deleted at 60 days). Older digests have been swept by
  `autoheal-retention.sh` and are not recoverable from this command.

## How it interacts with state

This command is read-mostly. The one write path is re-running
`autoheal-digest.sh` when a proposals file exists but the digest does not.
That call writes only to `~/.claude/autoheal/digests/{date}.md` and never
modifies the proposals or events files.

## Cross-references

- Generator: `~/.claude/bin/autoheal-digest.sh`
- Rule: `~/.claude/rules/autoheal.md`
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7
