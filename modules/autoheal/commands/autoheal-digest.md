# /autoheal-digest - Render an Autoheal Digest

Print the markdown digest for today (default) or a specific past date.

The digest is an archive. To act on ready fixes, run `/autoheal-review`: it
shows each fix with its evidence and diff and merges the one you accept.

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
   - If `~/.claude/autoheal/proposals.jsonl` has rows for that date with at least
     one record: run `bash ~/.claude/bin/autoheal-digest.sh` with the
     env override `CCGM_AUTOHEAL_TODAY={date}` to materialize the digest,
     then print it.
   - If the ledger has no rows for that date: print "no digest available
     for {date}" plus the path that was checked.

## Shadow rollout section

When `auto_apply_enabled` or `realtime_alerts_enabled` has run in `shadow`,
the digest ends with a "Shadow rollout" section: decisions logged, agreed,
disagreed (false positives and false negatives), pending, false positives on
`check`-surface proposals, and whether the promotion bar is met (20 decided
decisions, 90% agreement, zero `check` false positives). See the README's
"Rollout: off, shadow, active".

## When to invoke

- The daily launchd job has not yet fired and you want to see what is
  ready right now.
- A past day's digest scrolled past you and you want to re-read it.
- You suspect the analyzer crashed on a given day and want to confirm
  no proposals landed.

## When NOT to invoke

- To apply a specific proposal — use `/autoheal-review <id>` or
  `/permission-fix apply <id>` (Epic 4) instead.
- To toggle config flags — use `/autoheal-toggle`.
- For dates older than the retention window (default: gzipped at 30 days,
  deleted at 60 days). Older digests have been swept by
  `autoheal-retention.sh` and are not recoverable from this command.

## How it interacts with state

This command is read-mostly. The one write path is re-running
`autoheal-digest.sh` when the ledger has rows for the date but the digest does not.
That call writes only to `~/.claude/autoheal/digests/{date}.md` and never
modifies the ledger or events files.

## Cross-references

- Generator: `~/.claude/bin/autoheal-digest.sh`
- Rule: `~/.claude/skills/autoheal-reference/SKILL.md`
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7
