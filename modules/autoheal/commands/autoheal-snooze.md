# /autoheal-snooze - Snooze a Proposal

Suppress a specific autoheal proposal for N days. The proposal will not
be re-rendered in the digest until the snooze expires, even if it
re-occurs as a daily recommendation.

## Usage

```
/autoheal-snooze <proposal-id>              # 30-day default
/autoheal-snooze <proposal-id> 7            # 7 days
/autoheal-snooze <proposal-id> 0            # remove an existing snooze
/autoheal-snooze list                       # list active snoozes
```

## What it does

1. Resolve `proposal-id` against today's
   `~/.claude/autoheal/proposals/{today}.jsonl` (and the previous 7
   days if not found in today's file) to extract the proposal's
   `fingerprint`. Snoozes are keyed by fingerprint, not by id, so that
   the next analyzer run cannot re-issue the same proposal under a new
   id and bypass the snooze.
2. Compute the expiry timestamp:
   `now + N days`, ISO 8601 UTC. With `N = 0`, the existing snooze for
   this fingerprint is removed.
3. Read `~/.claude/autoheal/snoozed.json` (or `{}` if absent), add the
   entry `{fingerprint: snoozed_until_iso}`, and write back atomically
   (tempfile + `mv`).
4. Print a confirmation: `snoozed prop_XYZ (fingerprint sha256-...) until
   YYYY-MM-DD`.

## Storage format

```json
{
  "sha256-of-proposal-fingerprint-1": "2026-06-17T00:00:00Z",
  "sha256-of-proposal-fingerprint-2": "2026-06-25T00:00:00Z"
}
```

Entries whose timestamp is in the past are not strictly removed by this
command; the digest renderer ignores them and the next analyzer run
treats them as eligible again. `/autoheal-snooze list` prints the active
entries (those whose timestamp is in the future) in human-readable form.

## When to invoke

- The digest keeps suggesting a proposal you have already decided not to
  apply (e.g., the recommended allow rule conflicts with a policy you
  enforce manually).
- A proposal is suspect and you want to defer judgment for a few days
  without losing the underlying event evidence.

## When NOT to invoke

- To reject a proposal permanently — set `auto_apply_blocked: true` in
  the proposal record instead (a future epic exposes this via a flag).
- To delete the underlying event log — the events drive proposal
  generation, not the snoozed set. Editing events directly is forbidden
  (see the autoheal rule).
- To pause autoheal globally — use `/autoheal-toggle pause`.

## Examples

```
/autoheal-snooze prop_01HW3FQQX7         # snooze 30 days (default)
/autoheal-snooze prop_01HW3FQQX7 7       # snooze 1 week
/autoheal-snooze prop_01HW3FQQX7 0       # un-snooze
/autoheal-snooze list                    # print active snoozes
```

## How it works

This command is implemented as a small bash transform driven by the
agent. The agent:

1. Locates the proposal by id by scanning back through 7 days of
   `~/.claude/autoheal/proposals/*.jsonl`.
2. Reads its `fingerprint` field.
3. Computes the expiry timestamp via `date -u` or a small Python
   snippet (Python is portable across BSD and GNU date).
4. Reads / writes `~/.claude/autoheal/snoozed.json` atomically.

## Cross-references

- Storage: `~/.claude/autoheal/snoozed.json`
- Rule: `~/.claude/rules/autoheal.md`
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7
