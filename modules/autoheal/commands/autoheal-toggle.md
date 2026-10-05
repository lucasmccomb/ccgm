# /autoheal-toggle - Flip Autoheal Config Flags

Edit `~/.claude/autoheal/config.json` to enable, disable, or inspect
autoheal feature flags.

## Usage

```
/autoheal-toggle                                    # equivalent to status
/autoheal-toggle status
/autoheal-toggle pause                              # paused: true
/autoheal-toggle resume                             # paused: false

/autoheal-toggle realtime on|off|shadow|status      # realtime_alerts_enabled
/autoheal-toggle autoapply off|shadow|active|status # auto_apply_mode (active must be earned)
/autoheal-toggle email on|off|status                # email_enabled
/autoheal-toggle digest on|off|status               # digest_enabled

/autoheal-toggle webhook on|off|status              # webhook_enabled
/autoheal-toggle webhook url <URL>                  # webhook_url
/autoheal-toggle webhook url clear                  # webhook_url -> null
```

## What it does

For every subcommand:

1. Read `~/.claude/autoheal/config.json` (or `{}` if missing).
2. Mutate exactly one key based on the subcommand:
   - `pause` / `resume` set `paused: true|false`. When `paused: true`,
     the daily wrapper exits early before any sub-step (the bash script
     respects this flag in its preflight).
   - `realtime on|off|shadow` sets `realtime_alerts_enabled` (Epic 10) to
     `active`, `off` or `shadow`. `active` is also accepted.
   - `autoapply off|shadow|active` sets `auto_apply_mode` (#1099 Phase 4.2).
     Shadow logs what auto-apply would do and changes nothing. `active` (or
     `on`) is refused, with exit 3 and the reasons, until the shadow record
     shows at least 10 decided decisions at 90% agreement or better with no
     would-apply fix later measured harmful or reverted; a successful switch
     records `auto_apply_promoted_at`. Report a refusal to the user verbatim.
     Writing this key also deletes the retired `auto_apply_enabled` flag.
     The rule-file allowlist `auto_apply_targets` defaults to every
     `modules/*/rules/*.md`; narrow it with globs such as
     `modules/git-workflow/rules/*.md`, or set `[]` to let nothing qualify.
     See the README's "Earned auto-apply".

   These two run through `lib/autoheal_mode.py`, which validates the value,
   keeps every other key, writes atomically, and prints the confirmation:
   `python3 ~/.claude/lib/autoheal_mode.py set ~/.claude/autoheal/config.json autoapply shadow`
   (`status` prints `{key} = {mode}`; a persisted realtime boolean reads as
   active/off). Do not hand-edit these two keys with `jq`.
   - `email on|off` flips `email_enabled` (Epic 7 sender gate).
   - `digest on|off` flips `digest_enabled` (Epic 7 renderer gate).
   - `webhook on|off` flips `webhook_enabled` (Epic 12 publisher gate).
     `webhook url <URL>` writes the URL to `webhook_url`. `webhook url
     clear` sets `webhook_url` to `null`.
3. Write the file back via `jq` so the on-disk JSON stays well-formed.
   For `status` queries, print the current value and exit without
   writing.
4. Print a one-line confirmation: `set {key} = {value}`.

## Subcommand reference

| Subcommand | Key it flips | Default |
|---|---|---|
| `pause` | `paused` | `false` |
| `resume` | `paused` | (sets to `false`) |
| `realtime` | `realtime_alerts_enabled` | `off` |
| `autoapply` | `auto_apply_mode` | `off` |
| `email` | `email_enabled` | `false` |
| `digest` | `digest_enabled` | `true` |
| `webhook` (`on`/`off`) | `webhook_enabled` | `false` |
| `webhook url <URL>` | `webhook_url` | `null` |

`status` (or no second argument) on any of the above prints the current
value without changing anything.

## Examples

```
# Pause autoheal entirely for a day or a session
/autoheal-toggle pause

# Re-enable
/autoheal-toggle resume

# Turn on real-time security alerts
/autoheal-toggle realtime on

# Log what auto-apply would do, without doing it
/autoheal-toggle autoapply shadow

# Check current auto-apply state
/autoheal-toggle autoapply status

# Wire up dev.lem.work webhook (Epic 12 / Human-Epic 2)
/autoheal-toggle webhook url https://dev.lem.work/v1/ingest
/autoheal-toggle webhook on

# Clear the webhook (revert to no-op)
/autoheal-toggle webhook url clear
```

## How it works

This command is implemented as a small bash transform driven by the
agent. The agent:

1. Resolves the target key from the subcommand.
2. Reads the existing config via `jq`.
3. Builds an updated object with `jq '. + {key: value}'`.
4. Writes the result atomically (write to a tempfile, then `mv` over the
   original) so a crash mid-write cannot leave a half-written config.

## When NOT to invoke

- To apply a single proposal — use `/autoheal-apply <id>`.
- To suppress a single proposal — use `/autoheal-snooze <id> [days]`.
- For per-repo overrides — edit `.autoheal/config.json` in the repo root
  directly. This command edits only the global config.

## Cross-references

- Rule: `~/.claude/skills/autoheal-reference/SKILL.md` (config keys table)
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7, §5 Epic 10
  (realtime), §5 Epic 12 (webhook); `ccgm-learning-loops/autoheal-rca.md`
  §3.5 (earned auto-apply).
