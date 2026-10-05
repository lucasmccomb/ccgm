# /autoheal-snooze - Snooze a Proposal

Alias for the Snooze answer in `/autoheal-review`. It snoozes one ledger row
without opening the review questions. The row leaves the review list and the
SessionStart count until the snooze ends, then comes back as a ready fix.

## Usage

```
/autoheal-snooze <proposal-id>        # 14 days
/autoheal-snooze <proposal-id> 7      # 7 days
/autoheal-snooze <proposal-id> 0      # wake it now
```

## Steps

Run `python3 ~/.claude/bin/autoheal-review.py snooze <proposal-id> --days <N>`
(omit `--days` for the 14-day default). It prints one JSON object. Report
`snoozed <id> until <date>` from `snoozed_until`, or the `error` verbatim
(for example "proposal X is applied, not ready").

The script sets the row's state to `snoozed` and `snoozed_until` to now plus N
days, in `~/.claude/autoheal/proposals.jsonl`. Only a `ready` or `snoozed` row
can be snoozed. While the row exists the aggregator treats its signature as
covered, so the nightly run does not draft it again.

## When to invoke

- A fix is right but not for now, and you do not want it in the review list.

## When NOT to invoke

- To reject a fix: use Reject in `/autoheal-review`, which records the reason
  and suppresses the signature for 90 days.
- To pause autoheal globally: use `/autoheal-toggle pause`.

## Cross-references

- Storage: the `snoozed` state in `~/.claude/autoheal/proposals.jsonl`
- Review: `/autoheal-review`
- Reference: `~/.claude/skills/autoheal-reference/SKILL.md`
