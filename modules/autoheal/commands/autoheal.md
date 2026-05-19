# /autoheal - Self-Healing Observability Loop Overview

Inspect autoheal status and learn the slash command surface. Read-only:
this command modifies no files. Use the listed subcommands for stateful
actions.

## Usage

```
/autoheal
```

## What it shows

1. The set of autoheal slash commands and a one-line description of each.
2. The current config flags (`realtime_alerts_enabled`, `auto_apply_enabled`,
   `email_enabled`, `digest_enabled`, `webhook_url`) read from
   `~/.claude/autoheal/config.json`.
3. Today's local digest path (whether it exists yet) and the last analyzer
   run timestamp from `~/.claude/autoheal/last-analyzed` if present.
4. The count of unread proposals in
   `~/.claude/autoheal/proposals/{today}.jsonl` and the path to today's
   event log under `~/.claude/autoheal/events/`.

## How it works

This command is a thin Claude reader, not a shell script. The agent:

1. Reads `~/.claude/autoheal/config.json` (treating missing keys as
   defaults from the rule file `modules/autoheal/rules/autoheal.md`).
2. Lists files under `~/.claude/autoheal/proposals/`,
   `~/.claude/autoheal/events/`, `~/.claude/autoheal/digests/`, and
   `~/.claude/autoheal/sent/` to summarize state.
3. Prints the rendered status table and the command surface.

## Command surface

| Command | Purpose |
|---|---|
| `/autoheal` | This overview. |
| `/autoheal-digest [date]` | Render today's or a specific date's digest. |
| `/autoheal-toggle [pause\|resume\|status\|realtime\|autoapply\|webhook] [on\|off\|status\|url <URL>]` | Flip config flags. |
| `/autoheal-snooze <id> [days]` | Snooze a proposal for N days (default 30). |
| `/autoheal-apply [id\|list]` | Apply a proposal via the formal apply path (Epic 11). |
| `/permission-fix [event-id\|latest]` | In-session root-cause sub-agent (Epic 4). |
| `/permission-audit` | Static audit of installed hooks + settings (Epic 5). |

## Config flags

See the autoheal rule (`~/.claude/rules/autoheal.md`) for the full config
schema. Defaults: `realtime_alerts_enabled: false`, `auto_apply_enabled:
false`, `email_enabled: false`, `digest_enabled: true`, `webhook_url:
null`.

## When NOT to invoke

- This is a status read-out, not a fix path. To loosen a specific friction
  point, use `/permission-fix latest` or `/autoheal-apply <id>` after
  reading the proposal.
- For audit alignment between hooks and settings, use `/permission-audit`.

## Cross-references

- Rule: `~/.claude/rules/autoheal.md`
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7
