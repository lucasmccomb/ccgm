# autoheal

Self-healing observability loop for Claude Code. Captures permission events, tool failures, and user-correction signals; counts recurring failures with plain code; drafts a small rule for each recurring failure through a direct Anthropic API call; surfaces a digest with the proposals. Optional real-time security alerts and earned auto-apply, both default off. Applied fixes are measured 14 days after merge.

## What this module installs

- **6 hooks** across `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, and `SessionStart`:
  - **3 event-capture hooks**: `permission-event-logger.py` (PermissionRequest rows; PostToolUse / PostToolUseFailure bump the daily per-tool counter `counts/{date}.json`), `failure-logger.py` (PostToolUseFailure: the only writer of failure rows, with `error`, `error_class`, `cmd_head`), `user-correction-detector.py` (UserPromptSubmit: a short prompt after a failure or interrupt).
  - **2 response hooks**: `permission-request-suppress.py` (PermissionRequest contextual auto-allow) and `realtime-security-scanner.py` (PostToolUse opt-in mid-session alerts).
  - **1 notice hook**: `autoheal-session-notice.py` (SessionStart). See "Session notice" below.
- **Signature aggregator**: `bin/autoheal-aggregate.py [--date D]` counts recurring failures over a 14-day window with no model call and writes `signatures/{date}.json`, ranked by count x sessions. A signature qualifies at 5 or more occurrences across 2 or more sessions and 2 or more days (override under `aggregation` in `config.json`). `bin/autoheal-analyze.sh` runs it first.
- **8 slash commands**: `/permission-fix`, `/permission-audit`, `/autoheal`, `/autoheal-review`, `/autoheal-digest`, `/autoheal-toggle`, `/autoheal-snooze`, `/autoheal-apply`. `/autoheal-review` is where a fix is accepted; `/autoheal-apply` and `/autoheal-snooze` are aliases into it (apply forwards; snooze sets a ledger row to `snoozed`) and `/autoheal-digest` is an archive. `/autoheal` shows status and the success metrics.
- **Heartbeat**: every run of `bin/autoheal-daily.sh` writes `~/.claude/autoheal/health.json` from an EXIT trap (`status` ok/partial/failed/paused, per-step exit codes, calls, cost, `reasons[{code,message,fix}]`; same top level as dreaming's health file). The wrapper exits 1 when the analyze step fails. A paused run writes `paused` and counts as a success. The analyzer records how each run ended in `last-run.json` (`outcome` ok, `daily_cap_refused` or `failed`); a daily-cap stop is a non-failure only through that record, and exit code 2 alone is a failure.
- **`/autoheal doctor`**: `bin/autoheal-doctor.py` reports the loaded launchd path, whether the job's script exists under the real home, last exit code, heartbeat age, whether the `.env` API key is set, the last cost row, and whether every `module.json` file target of this module exists under the real home's `.claude`, then prints the repair: bootout and bootstrap for the job, or a one-line `ccgm_sync_install.install_new_files` call that links the missing files (link-mode installs; a copy install needs `./start.sh` again). It never runs a repair itself, and it skips the install check when it cannot find `module.json`. A non-zero launchd exit code counts as stale, not a problem, when a good heartbeat is newer than the job's stderr file (launchd keeps the code until the next fire).
- **Daily LaunchAgent** (macOS) calling `bin/autoheal-daily.sh` at 08:00 local. Linux scheduling is an architectural seam, not built in v1.

## How the analyzer drafts a fix

`bin/autoheal-analyze.sh` is the daily analyzer. Code counts and checks; the model only writes the rule text.

1. **Aggregate.** It runs `bin/autoheal-aggregate.py --date <day>` and takes at most 3 qualifying signatures from `signatures/<day>.json`. With none, it makes no API call, logs that, and exits 0.
2. **Route.**
   - A hook-denial signature (`hook_denial_*`) never goes to the model. Code writes an `issue` proposal (title, body and evidence drafted locally, naming the denying hook's module). Nothing is filed on GitHub; filing waits for Apply in a later unit.
   - Any other signature gets a request of about 6 to 12k tokens: the signature record, the module index, the full text of at most 2 candidate rule files, and at most one redacted excerpt of 1,500 characters or less. `lib/signature-module-map.json` picks the candidates (command head such as `git`, then error class such as `zsh_not_found`); keyword matching against the index is the fallback.
3. **Measure.** Before each call it measures the input with the Anthropic `count_tokens` endpoint (free). Input over 15,000 tokens is refused unsent and counted as a failed call.
4. **Ask.** The model answers through structured outputs (`lib/proposal-schema.json`) with a `rule_insert` (`target_path` limited to the supplied candidates, `anchor_heading`, `insert_markdown` of 8 lines or fewer) or a `skip`. It returns no diff, id or fingerprint. The request uses `claude-sonnet-5` (or `default_model` from `config.json`), thinking off, `max_tokens` 2000. The prompt and module index form a cached prefix.
5. **Build.** `lib/draft_proposals.py` checks that the path is a candidate and the anchor heading exists in the real file, then generates the unified diff. The id is the aggregator's `signature_id` (`sha256(signature)[:12]`). A failed check drops the answer with a counted reason (`anchor_missing`, `path_not_candidate`, `insert_too_long`, ...) in `runs/{today}.json` and the rejection log.
6. **Validate.** `validate(proposal)` in `lib/apply-proposal.py` gates every `rule_insert` before it is stored as `ready`; `/autoheal-review` runs the same function before it branches. It works on a throwaway copy of the source repo's `origin/main` (`git archive` into a temp dir), so the repo's working tree, index, refs and worktree list are only read, never changed. Checks run cheapest first, each capped by `validation_timeout_seconds` (default 120):

   | Check | Drop reason |
   |---|---|
   | `target` is a `modules/*/rules/*.md` file in `origin/main` | `path_not_candidate` |
   | The anchor heading is in that file | `anchor_missing` |
   | Lines added to always-loaded rules (`rules/*.md` with no `paths:` frontmatter), counted with every ready or applied proposal of the last 7 days, stay within `rule_budget_lines_per_week` (default 20) | `rule_budget` |
   | The diff applies to the copy | `apply_conflict` |
   | `tests/test-no-personal-data.sh` passes with the diff applied | `personal_data` |
   | `tests/test-modules.sh` passes with the diff applied | `module_tests` |
   | The source repo cannot be resolved, `origin/main` is missing, or a check timed out | `validation_unavailable` |

   A failing row is stored with `state: dropped` and a `drop_reason`, counted in `runs/{today}.json`, and never shown. The checks read the local `origin/main` ref and call no API; the gate does not fetch.

   Every dropped draft is stored, including answers the build step rejects (`anchor_missing`, `path_not_candidate`, `insert_too_long`, ...). The aggregator turns a dropped row into a cooldown so a draft that cannot pass is not paid for again every night (`excluded: "cooldown"` with `cooldown_until` in `signatures/{date}.json`):

   | Last drop | Signature is covered for |
   |---|---|
   | Content reason (anything but `validation_unavailable`) | `aggregation.redraft_cooldown_days` (default 14) from the drop date; each further content drop doubles it, capped at 90 days |
   | `validation_unavailable` | 1 day; three in a row start the 14-day cooldown |
   | Model `skip` (state `skipped`) | No expiry |

   Rows dropped as `validation_unavailable` carry `consecutive_unavailable`; at three, the row also carries `health_reason`, for the health writer to surface.
7. **Write.** Rows go to the ledger (`proposals.jsonl`, see below) with `signature_id`, `kind`, `target`, `anchor`, `insert_markdown`, `diff` and `evidence` (count, sessions, sample errors). `state` is `ready`, or `skipped` when the model declined; a skipped signature counts as covered, so it is not sent again. The digest, the session notice and `/autoheal-review` read these rows.

## The proposal ledger

Every proposal lives in one file, `~/.claude/autoheal/proposals.jsonl` (`lib/ledger.py`), one row per proposal. Lookup by id (`/autoheal-review <id>`) searches the whole file, so a proposal stays applicable until someone decides it.

| State | Meaning |
|---|---|
| `ready` | Waiting for a decision |
| `applied` | `/autoheal-review` landed it (merged PR or filed issue) |
| `rejected` | The user said no; the signature is suppressed until `suppressed_until` (90 days) |
| `snoozed` | Deferred until `snoozed_until` (14 days from `/autoheal-review`) |
| `dropped` | Failed the validation gate; feeds the redraft cooldown |
| `skipped` | The model declined to draft; the signature stays covered |
| `measured` | Applied, and its +14 day outcome is recorded |
| `reverted` | Applied, then undone |
| `legacy` | Written before the redesign; never shown |

Retention (`bin/autoheal-retention.sh`) never deletes a `ready` row. It prunes only `dropped` rows older than 120 days, past the 90-day cooldown cap; applied, rejected and skipped rows keep their signature covered.

**Migration.** Per-day files from before the ledger (`proposals/{date}.jsonl`) move in with `bin/autoheal-ledger-migrate.py`. It plans by default (`--dry-run`) and writes only with `--apply`. Rows without a `signature_id` become `legacy`; the script renames `proposals/` to `proposals.migrated/` afterwards and skips rows already in the ledger, so a second `--apply` adds nothing. Nothing runs it on install.

## Reviewing fixes: `/autoheal-review`

`/autoheal-review` takes up to 5 `ready` rows, oldest first, and asks one AskUserQuestion for each. The question text holds the signature (tool, command head, error class), the count, sessions and date range, two redacted sample errors, the target rule file and the anchor heading; the Apply option's preview is the exact diff; each option's description says what it will do. All computation is in `bin/autoheal-review.py` (`list`, `apply`, `reject`, `snooze`); the command only asks.

| Answer | Result |
|---|---|
| Apply | `rule_insert`: re-runs `validate()`, then in a temporary worktree of the CCGM source repo (`ccgm_repo_path` or the rules symlinks) on `autoheal/<id>` from `origin/main`: applies the diff, commits `#auto: apply autoheal proposal <id>` with trailers `Autoheal-Id` and `Autoheal-Signature`, pushes, opens a PR, waits for checks and squash-merges it. Never `--admin`. The repo's own working tree is never touched, and the worktree is removed in a `finally`. The row becomes `applied` with `pr_url`, `merge_sha`, `merged_at` and `baseline_rate` (failures per 100 calls of the tool over the 14 days before the merge). `issue` (hook denials): files a GitHub issue on the source repo, no labels, and marks the row `applied` with `issue_url`. |
| Edit then apply | The user types replacement lines (8 at most) under Other. They are rebuilt into a diff against `origin/main` and re-validated; a bad edit changes nothing. |
| Reject | Records the reason; the aggregator skips the signature for 90 days. |
| Snooze 14d | The signature is skipped and the row leaves the list for 14 days. |

If checks fail or the merge is refused, the PR stays open, the row goes back to `ready` with an `apply_error`, and the next Apply merges that PR instead of opening another. A proposal that no longer fits `origin/main` (`anchor_missing`, `apply_conflict`, `personal_data`, `module_tests`, `path_not_candidate`) becomes `dropped` with its reason, so the aggregator redrafts it after the cooldown. The commit subject uses the `#auto:` convention of `lib/apply-proposal.py` because a drafted fix has no issue number. `apply_checks_timeout_seconds` in `config.json` (default 1800) caps the wait for checks. After a successful merge the script deletes `autoheal/<id>` from origin with `git push origin --delete` (a failure is logged, never fails the apply; the checkout is untouched); a branch whose PR is still open stays. A stale `autoheal/<id>` branch from an earlier apply is replaced with `--force-with-lease` pinned to its current tip.

## Session notice

`hooks/autoheal-session-notice.py` runs at SessionStart and prints one line, at most once per UTC day per machine (sentinel `notice-sentinel`), only in a real session (not a subagent worktree). It stays silent when there is nothing to say.

- Ready fixes: `autoheal: 2 fixes ready (zsh quoting in Bash, cp -i alias) — run /autoheal-review`
- Stale or failed run, from `health.json`: `autoheal: last good run 3d ago (<reason>) — /autoheal doctor`. A `paused` status says nothing.
- A launchd job that runs a missing file, from `launchctl print` (once a day, cached in `notice-launchd.json`; skipped when `launchctl` is absent): `autoheal: scheduled job runs <path>, which does not exist — /autoheal doctor`
  A path that exists but resolves (`realpath`) outside the real home gets its own line: `autoheal: job points outside your home: <path> — /autoheal doctor`. This is the foreign-HOME case, before the temp dir is cleaned up.

The hook reads files only, never calls the network, never asks a question, and always exits 0.

A failed call is logged and counted, never retried in the run and never held for a later one. There is no day watermark and no give-up counter; `last-analyzed` only records the date of the last finished run.

### Finding the CCGM source repo

The module index and the candidate files come from the CCGM source repo, never from guesses. `lib/module-index.py` resolves it in this order:

1. `ccgm_repo_path` in `config.json`, when set. It overrides everything; if it does not point at a CCGM repo (a directory holding `start.sh` and `modules/`), resolution fails rather than falling back.
2. The `~/.claude/rules/*.md` symlinks. CCGM installs each rule file as a symlink into the repo. The first one that resolves, walked up to the directory holding `start.sh` and `modules/`, names the repo.
3. Neither resolves (a copy install): drafting is skipped with a logged `no_source_repo` reason. Paths are never invented. Hook-denial `issue` proposals still work, since they need no repo.

Run `python3 lib/module-index.py` to see what resolves and the index text.

## Default posture

- **Real-time security alerts: OFF.** Enable with `/autoheal-toggle realtime on` (or `realtime_alerts_enabled: "active"` in config). Try `/autoheal-toggle realtime shadow` first.
- **Auto-apply: OFF.** Try `/autoheal-toggle autoapply shadow` first. `active` has to be earned; see "Earned auto-apply".
- **Email digest: OFF.** Local digest is always-on; opt into Resend with `digest_email` and `email_enabled: true` + `RESEND_API_KEY` in `~/.claude/autoheal/.env` (NOT shell rc — see "API keys" below).
- **Webhook publisher: OFF.** Set `webhook_url` in config to enable; unset it to stop.

Email and the webhook are kept, opt-in features. Both read the ledger: the digest and email render today's `ready` rows (`lib/ledger.py day`), and the publisher posts today's ledger rows as `proposal` records, plus the day's events and digest. Neither runs in the nightly chain unless its key is set.

## Rollout: off, shadow, active

`realtime_alerts_enabled` and `auto_apply_mode` each take `"off"`, `"shadow"` or `"active"`. A persisted realtime boolean reads as `active` (`true`) or `off` (`false`). Every reader goes through `lib/autoheal_mode.py`.

- **shadow** computes the decision and logs it. Nothing else happens.
- Realtime alerts in shadow evaluate the patterns and append `{ts, session_id, pattern, severity, would_alert}` to `~/.claude/autoheal/shadow/realtime.jsonl` (never the command). No `<autoheal-security-alert>` block, no event, exit 0. Alerts have no recorded human outcome, so the digest counts them but they stay pending.

## Earned auto-apply

The nightly `bin/autoheal-auto-apply.sh` (logic in `lib/auto_apply.py`) can apply a fix without asking, but only after shadow mode shows it agrees with your own `/autoheal-review` decisions.

| Mode | What runs | How you get there |
|---|---|---|
| `off` (default) | Nothing. Fixes wait for `/autoheal-review`. | Default, or `/autoheal-toggle autoapply off` |
| `shadow` | Each ready `rule_insert` row gets a decision `{ts, proposal_id, generated_at, signature_id, would_apply, reason, mode}` in `~/.claude/autoheal/shadow/auto-apply.jsonl`. No git, gh or ledger change. | `/autoheal-toggle autoapply shadow`, or automatic demotion |
| `active` | Fixes measured harmful are reverted, then rows that pass the gate are applied through `/autoheal-review`'s path (PR, checks, squash-merge, `Autoheal-Id` and `Autoheal-Signature` trailers) and marked `applied_by: auto`. The next session's notice names each one with its undo command. | `/autoheal-toggle autoapply active`, refused below the promotion bar |

- **Gate.** All of: kind `rule_insert`; `validate()` passes against `origin/main`; at least 10 occurrences across at least 3 sessions; target matches a glob in `auto_apply_targets` (key absent: the default `["modules/*/rules/*.md"]`, every rule file, which is the set the drafter targets and `validate()` accepts; a narrower list of globs restricts it; an explicit `[]` lets nothing qualify).
- **Agreement.** Each decision is matched to its ledger row by id and `generated_at`. Applied by you (applied, measured or reverted, not `applied_by: auto`) is accepted; rejected is rejected. Would-apply and accepted, or would-skip and rejected, agree; the rest disagree; rows still ready are pending. A proposal decided on several nights counts once, by its latest decision.
- **Promotion bar.** `active` is refused, with exit 3 and the reasons, until there are at least 10 decided decisions at 90% agreement or better and no would-apply decision whose fix was later measured harmful or reverted. A successful switch records `auto_apply_promoted_at`; an `active` value without it (a hand edit) runs as shadow.
- **Demotion.** 3 reverts within 30 days set the mode back to `shadow` and record `auto_apply_demoted_at` and `auto_apply_demoted_reason`. Only decisions logged after the demotion count toward the next promotion.
- **Legacy flag.** `auto_apply_enabled` is retired. When `auto_apply_mode` is absent it is migrated on read: off/false stays off, and any other value (true, `"shadow"`, `"active"`) reads as `shadow`, never active, because active must be earned. The toggle writes `auto_apply_mode` and deletes the old key.
- The constants are in `lib/autoheal_mode.py` (`PROMOTION_MIN_DECIDED`, `PROMOTION_MIN_AGREEMENT`, `PROMOTION_MAX_HARMFUL`, `DEMOTION_REVERTS`, `DEMOTION_WINDOW_DAYS`) and `lib/auto_apply.py` (`MIN_OCCURRENCES`, `MIN_SESSIONS`). `/autoheal` and the digest show the mode, the agreement and the verdict.

## Outcome measurement

Every night the aggregator (`bin/autoheal-aggregate.py`, no API call) measures each `applied` rule fix once its 14-day post-merge window has ended (merge day + 15). It compares the failure rate of the fix's signature over the 14 days after the merge with the `baseline_rate` recorded at merge (the 14 days before), and moves the row to `measured`:

| Outcome | Rule | What happens |
|---|---|---|
| effective | post rate at most 50% of baseline | Counted in `/autoheal` |
| ineffective | above 50%, at most 100% | The notice offers `/autoheal-review revert <id>` or `/autoheal-review redraft <id>` |
| harmful | above baseline, or a new signature (same tool and command head, another error class, 2+ failures after and none before) appeared | `active`: a revert PR is opened and merged automatically and the row becomes `reverted`. `off`/`shadow`: flagged in the notice only |
| unmeasurable | no baseline to compare against | Counted in `/autoheal` |

When a window has no counted tool calls, failure counts over the two equal windows are compared instead of rates. A failed automatic revert records `revert_error` and is not retried every night; `/autoheal-review revert <id>` retries it. `redraft` keeps the merged rule and lets the next run draft the signature again from newer samples.

## Success metrics

`/autoheal` prints the metrics of the redesign (`lib/autoheal_metrics.py`, JSON). Four are computed from files the module already keeps; three are marked not computable yet.

| Metric | Target | Source |
|---|---|---|
| Run health, last 30 days | at least 95% of days `ok` | `health-history.jsonl`, one row per daily run (paused days and days before the first run are left out) |
| Acceptance rate | at least 40% | ledger: accepted (applied, measured, reverted, not `applied_by: auto`) over accepted plus rejected |
| Applied fixes effective at +14 days | at least 60% | ledger `outcome`: effective over effective, ineffective and harmful |
| API spend, last 30 days | under $3 | `cost.log` |
| Time to detect a dead job | one SessionStart | not computable yet: the notice keeps no log |
| Friction rate | down 20% in 60 days | not computable yet: needs 60 days of counts after the first applied fix |
| Cost per accepted fix | under $1 | not computable yet: `cost.log` records no per-fix cost |

## Config

User-global config lives at `~/.claude/autoheal/config.json`. Per-repo overrides live in `.autoheal/config.json` at the repo root; the merge rule is "missing keys fall through to global" (`hook_utils.load_repo_config()`; the daily wrapper reads `paused` from it). The installer writes the defaults below on first run and never overwrites an existing file.

| Key | Type | Default | Notes |
|---|---|---|---|
| `paused` | bool | `false` | Off switch. Only `true` pauses: the daily wrapper logs "paused", runs no step, makes no API call and writes `health.json` with status `paused`. A per-repo `.autoheal/config.json` that sets it wins. `/autoheal-toggle pause` and `resume` flip it |
| `realtime_alerts_enabled` | `off\|shadow\|active` | `off` | Mid-session `<autoheal-security-alert>` blocks; shadow logs would-alert only (a persisted boolean reads as active/off) |
| `auto_apply_mode` | `off\|shadow\|active` | `off` | Earned auto-apply of `rule_insert` fixes; shadow logs would-apply only; `active` only through `/autoheal-toggle` past the promotion bar. Replaces `auto_apply_enabled`, which is migrated on read (off stays off; any other value reads as shadow) and deleted on the next toggle |
| `auto_apply_targets` | glob list | `["modules/*/rules/*.md"]` | Rule files auto-apply may change. Key absent: every `modules/*/rules/*.md`, the set `validate()` accepts. Narrow it with globs such as `modules/git-workflow/rules/*.md`; an explicit `[]` lets nothing qualify |
| `auto_apply_promoted_at`, `auto_apply_demoted_at`, `auto_apply_demoted_reason` | written by autoheal | absent | Promotion and demotion record; do not hand-edit |
| `aggregation.window_days` | int | `14` | Days of events the aggregator counts |
| `aggregation.min_occurrences` | int | `5` | Failures a signature needs to qualify |
| `aggregation.min_sessions` | int | `2` | Distinct sessions it must span |
| `aggregation.min_days` | int | `2` | Distinct days it must span |
| `aggregation.redraft_cooldown_days` | int | `14` | Days a signature stays covered after a draft is dropped for a content reason; each further drop doubles it, capped at 90. Infrastructure drops (`validation_unavailable`) wait 1 day |
| `rule_budget_lines_per_week` | int | `20` | Most lines `validate()` lets fixes add to always-loaded rules (no `paths:` frontmatter) in 7 days, counting every ready or applied fix |
| `validation_timeout_seconds` | int | `120` | Cap for each `validate()` check |
| `apply_checks_timeout_seconds` | int | `1800` | How long `/autoheal-review` waits for PR checks before leaving the PR open |
| `ccgm_repo_path` | string | unset | CCGM source repo the drafter reads rule files from and `/autoheal-review` opens PRs against. Overrides the `~/.claude/rules/*.md` symlink lookup; must hold `start.sh` and `modules/` |
| `default_model` | string | `claude-sonnet-5` | Model for the drafting call; it must support structured outputs and have a `cost_pricing` entry. `model` is read when `default_model` is absent |
| `cost_pricing` | object | seeded by the installer | Per-model `input_per_million` and `output_per_million` dollar rates used for `cost.log` |
| `daily_cost_cap_usd` | number | `10.00` | The analyzer refuses to start a call once today's spend reaches it |
| `digest_enabled` | bool | `true` | Set `false` to skip rendering the local digest |
| `email_enabled` | bool | `false` | Opt-in to Resend digest delivery (needs `digest_email` and `RESEND_API_KEY`) |
| `digest_email` | string or string list | `null` | Recipient(s) for the email digest |
| `webhook_url` | string | `null` | When set, the daily run POSTs to `${webhook_url}/v1/ingest`. This one key is the on/off switch |
| `webhook_token` | string | generated at install | 32-character Bearer token sent with each webhook POST |
| `webhook_kinds` | string list | `["proposal", "event", "digest"]` | Streams the publisher sends |
| `webhook_max_per_run` | int | `100` | Most records one run sends |
| `retention_gzip_days` | int | `30` | Gzip events and digests older than N days. The ledger is never gzipped, and retention never deletes a `ready` row |
| `retention_delete_days` | int | `60` | Delete gzipped artifacts older than N days |

Cost stays low because the model is called only for a qualifying signature, with an input under 15,000 tokens (measured, not estimated) and thinking off. The 15,000-token limit is fixed.

## API keys

Autoheal reads `ANTHROPIC_API_KEY` (analyzer) and `RESEND_API_KEY` (email) from `~/.claude/autoheal/.env` (mode 0600). The daily LaunchAgent's entrypoint sources this file; it never sources your shell rc.

**Do not export `ANTHROPIC_API_KEY` from `~/.zshrc`.** Anthropic SDK clients (anthropic-python, the `claude` CLI, custom scripts) auto-detect it from env and would bill against the API key instead of your Claude Max subscription. The scoped `.env` keeps it invisible to interactive shells.

`autoheal-install.sh` creates an empty `.env` template on first run with usage notes inline.

## Cross-references

- Rule file: `skills/autoheal-reference/SKILL.md` (the contract autoheal expects Claude Code to follow).
- Plan: `~/code/plans/ccgm-autoheal/plan.md`.
- Bring-up runbook: `plan.md §9.1`.

## Manual installation (development clone)

```bash
# From a CCGM development clone (not the canonical):
bash start.sh --add autoheal
```

This installs the hooks, commands, rules, and shell scripts. Run `autoheal-install.sh` (Epic 6) afterwards to register the LaunchAgent.

## Tests

```bash
bash modules/autoheal/tests/run-all.sh                 # every autoheal suite
bash modules/autoheal/tests/test-doctor.sh             # one suite
```

Each test sets `CCGM_AUTOHEAL_DIR` to a temp directory; nothing pollutes the real `~/.claude/autoheal/`.
