# /autoheal - Self-Healing Observability Loop Overview

Inspect autoheal status and learn the slash command surface. Read-only:
this command modifies no files. Use the listed subcommands for stateful
actions. The one exception is `/autoheal doctor`, which can run a launchd
repair after you approve it.

## Usage

```
/autoheal
/autoheal doctor
```

## What it shows

1. The set of autoheal slash commands and a one-line description of each.
2. The current config flags (`realtime_alerts_enabled`, `auto_apply_mode`,
   `email_enabled`, `digest_enabled`, `webhook_url`) read from
   `~/.claude/autoheal/config.json`.
3. Today's local digest path (whether it exists yet) and the last analyzer
   run timestamp from `~/.claude/autoheal/last-analyzed` if present.
4. The count of fixes waiting for a decision (`python3 ~/.claude/lib/ledger.py
   ready`, the whole ledger `~/.claude/autoheal/proposals.jsonl`, any age)
   and the path to today's event log under `~/.claude/autoheal/events/`.
5. Auto-apply and outcomes, from `python3 ~/.claude/lib/autoheal_mode.py stats
   ~/.claude/autoheal/config.json` (JSON). Show:
   - `mode` (off, shadow or active), plus `promoted_at` or `demoted_at` and
     `demoted_reason` when set;
   - agreement: `agreed` of `decided` shadow decisions (`agreement` as a
     percent), `pending`, and `harmful` (would-apply fixes later measured
     harmful or reverted);
   - whether the promotion bar is met (`ready_for_active`), else each entry
     of `reasons`;
   - measured outcomes: `outcomes.effective`, `outcomes.ineffective`,
     `outcomes.harmful`, `outcomes.unmeasurable`, plus `reverts_30d` (3 demote
     active to shadow) and `auto_applied`;
   - the `targets` allowlist, or "empty: nothing can qualify" when it is empty.

## How it works

This command is a thin Claude reader, not a shell script. The agent:

1. Reads `~/.claude/autoheal/config.json` (treating missing keys as
   defaults from the rule file `modules/autoheal/skills/autoheal-reference/SKILL.md`).
2. Counts the ready rows in `~/.claude/autoheal/proposals.jsonl` and lists
   files under `~/.claude/autoheal/events/`, `~/.claude/autoheal/digests/`, and
   `~/.claude/autoheal/sent/` to summarize state.
3. Prints the rendered status table and the command surface.

## `/autoheal doctor`

Diagnose the daily job. When the argument is `doctor`, skip the overview
and do this:

1. Run the checks. They are a script, not your arithmetic:

   ```bash
   python3 ~/.claude/bin/autoheal-doctor.py
   ```

   (From a CCGM checkout: `python3 modules/autoheal/bin/autoheal-doctor.py`.)
   It prints the loaded launchd plist path, whether the job's script exists
   under the real `$HOME`, the last exit code, heartbeat status and age, whether
   `ANTHROPIC_API_KEY` is set in `~/.claude/autoheal/.env` (never the value),
   and the last `cost.log` row. Exit 0 means healthy.
2. Exit 0: report the output and stop.
3. Exit 1: the output ends with `problems:` and a `repair (run in order):`
   block (`launchctl bootout` then `launchctl bootstrap` of the real plist).
   Ask with AskUserQuestion before running it. The question payload must
   stand alone (ask-context rules): put the evidence from the doctor output in
   the question text (the loaded path or "not loaded", the missing file, the
   last exit code, the heartbeat status and age) and the exact commands in
   each option's description. Options:
   - Run the repair: runs the printed bootout and bootstrap commands, then
     re-runs the doctor and reports its output.
   - Show only: print the commands and change nothing.
4. If the doctor says the real plist does not exist, there is no bootstrap
   to offer; the repair is `bash modules/autoheal/bin/autoheal-install.sh`.

Never run `launchctl bootout`, `bootstrap` or `kickstart` without the user
picking the repair option. The `problems:` line may also name a missing API
key or a stale heartbeat; those have no launchctl fix, so report them.

## Command surface

| Command | Purpose |
|---|---|
| `/autoheal` | This overview. |
| `/autoheal doctor` | Diagnose the launchd job, heartbeat and API key; offer the repair. |
| `/autoheal-review [id]` | Accept, edit, reject or snooze each ready fix. Apply opens and merges a PR. `revert <id>` undoes a merged fix; `redraft <id>` asks for a new draft of a measured one. |
| `/autoheal-digest [date]` | Render today's or a specific date's digest (an archive). |
| `/autoheal-toggle [pause\|resume\|status\|realtime\|autoapply\|webhook] [on\|off\|shadow\|active\|status\|url <URL>]` | Flip config flags. `autoapply active` is refused below the promotion bar. |
| `/autoheal-snooze <id> [days]` | Snooze a proposal for N days (default 30). |
| `/autoheal-apply [id\|list]` | Alias for `/autoheal-review`. |
| `/permission-fix [event-id\|latest]` | In-session root-cause sub-agent (Epic 4). |
| `/permission-audit` | Static audit of installed hooks + settings (Epic 5). |

## Config flags

See the autoheal rule (`~/.claude/skills/autoheal-reference/SKILL.md`) for the full config
schema. Defaults: `realtime_alerts_enabled: "off"`, `auto_apply_mode:
"off"` (each takes `off|shadow|active`), `auto_apply_targets: []`,
`email_enabled: false`, `digest_enabled: true`, `webhook_url: null`.

## When NOT to invoke

- This is a status read-out, not a fix path. To loosen a specific friction
  point, use `/permission-fix latest`, or `/autoheal-review` for a fix
  autoheal already drafted.
- For audit alignment between hooks and settings, use `/permission-audit`.

## Cross-references

- Rule: `~/.claude/skills/autoheal-reference/SKILL.md`
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §5 Epic 7
