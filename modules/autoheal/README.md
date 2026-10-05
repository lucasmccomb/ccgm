# autoheal

Self-healing observability loop for Claude Code. Captures permission events, tool failures, and user-correction signals; counts recurring failures with plain code; drafts a small rule for each recurring failure through a direct Anthropic API call; surfaces a digest with the proposals. Optional real-time security alerts and confidence-gated auto-apply, both default off.

## What this module installs

- **6 hooks** across `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, and `SessionStart`:
  - **3 event-capture hooks**: `permission-event-logger.py` (PermissionRequest rows; PostToolUse / PostToolUseFailure bump the daily per-tool counter `counts/{date}.json`), `failure-logger.py` (PostToolUseFailure: the only writer of failure rows, with `error`, `error_class`, `cmd_head`), `user-correction-detector.py` (UserPromptSubmit: a short prompt after a failure or interrupt).
  - **2 response hooks**: `permission-request-suppress.py` (PermissionRequest contextual auto-allow) and `realtime-security-scanner.py` (PostToolUse opt-in mid-session alerts).
  - **1 notice hook**: `autoheal-session-notice.py` (SessionStart). See "Session notice" below.
- **Signature aggregator**: `bin/autoheal-aggregate.py [--date D]` counts recurring failures over a 14-day window with no model call and writes `signatures/{date}.json`, ranked by count x sessions. A signature qualifies at 5 or more occurrences across 2 or more sessions and 2 or more days (override under `aggregation` in `config.json`). `bin/autoheal-analyze.sh` runs it first.
- **8 slash commands**: `/permission-fix`, `/permission-audit`, `/autoheal`, `/autoheal-review`, `/autoheal-digest`, `/autoheal-toggle`, `/autoheal-snooze`, `/autoheal-apply`. `/autoheal-review` is where a fix is accepted; `/autoheal-apply` is an alias for it and `/autoheal-digest` is an archive.
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
7. **Write.** Rows go to `proposals/{today}.jsonl` with `signature_id`, `kind`, `target`, `anchor`, `insert_markdown`, `diff` and `evidence` (count, sessions, sample errors). `state` is `ready`, or `skipped` when the model declined; a skipped signature counts as covered, so it is not sent again. The digest, the session notice and `/autoheal-review` read these rows.

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

If checks fail or the merge is refused, the PR stays open, the row goes back to `ready` with an `apply_error`, and the next Apply merges that PR instead of opening another. A proposal that no longer fits `origin/main` (`anchor_missing`, `apply_conflict`, `personal_data`, `module_tests`, `path_not_candidate`) becomes `dropped` with its reason, so the aggregator redrafts it after the cooldown. The commit subject uses the `#auto:` convention of `lib/apply-proposal.py` because a drafted fix has no issue number. `apply_checks_timeout_seconds` in `config.json` (default 1800) caps the wait for checks. Remote branches are not deleted (the repo's "delete branch on merge" setting does that), and a stale `autoheal/<id>` branch from an earlier apply is replaced with `--force-with-lease` pinned to its current tip.

## Session notice

`hooks/autoheal-session-notice.py` runs at SessionStart and prints one line, at most once per UTC day per machine (sentinel `notice-sentinel`), only in a real session (not a subagent worktree). It stays silent when there is nothing to say.

- Ready fixes: `autoheal: 2 fixes ready (zsh quoting in Bash, cp -i alias) — run /autoheal-review`
- Stale or failed run, from `health.json`: `autoheal: last good run 3d ago (<reason>) — /autoheal doctor`. A `paused` status says nothing.
- A launchd job that runs a missing file, from `launchctl print` (once a day, cached in `notice-launchd.json`; skipped when `launchctl` is absent): `autoheal: scheduled job runs <path>, which does not exist — /autoheal doctor`
  A path that exists but resolves (`realpath`) outside the real home gets its own line: `autoheal: job points outside your home: <path> — /autoheal doctor`. This is the foreign-HOME case, before the temp dir is cleaned up.

The hook reads files only, never calls the network, never asks a question, and always exits 0.

A failed call is logged and counted, never retried in the run and never held for a later one. There is no day watermark, no give-up counter and no calibration mode; `last-analyzed` only records the date of the last finished run.

### Finding the CCGM source repo

The module index and the candidate files come from the CCGM source repo, never from guesses. `lib/module-index.py` resolves it in this order:

1. `ccgm_repo_path` in `config.json`, when set. It overrides everything; if it does not point at a CCGM repo (a directory holding `start.sh` and `modules/`), resolution fails rather than falling back.
2. The `~/.claude/rules/*.md` symlinks. CCGM installs each rule file as a symlink into the repo. The first one that resolves, walked up to the directory holding `start.sh` and `modules/`, names the repo.
3. Neither resolves (a copy install): drafting is skipped with a logged `no_source_repo` reason. Paths are never invented. Hook-denial `issue` proposals still work, since they need no repo.

Run `python3 lib/module-index.py` to see what resolves and the index text.

## Default posture

- **Real-time security alerts: OFF.** Enable with `/autoheal-toggle realtime on` (or `realtime_alerts_enabled: "active"` in config). Try `/autoheal-toggle realtime shadow` first.
- **Auto-apply: OFF.** Enable with `/autoheal-toggle autoapply on` (or `auto_apply_enabled: "active"` in config). Try `/autoheal-toggle autoapply shadow` first.
- **Email digest: OFF.** Local digest is always-on; opt into Resend with `digest_email` and `email_enabled: true` + `RESEND_API_KEY` in `~/.claude/autoheal/.env` (NOT shell rc — see "API keys" below).
- **Webhook publisher: OFF.** Set `webhook_url` in config to enable.

## Rollout: off, shadow, active

`realtime_alerts_enabled` and `auto_apply_enabled` each take `"off"`, `"shadow"` or `"active"`. Configs written before shadow mode hold a boolean; `lib/autoheal_mode.py` reads `true` as `active` and `false` as `off` and never rewrites the file. Every reader goes through its `resolve_mode`.

- **shadow** computes the decision and logs it. Nothing else happens.
  - Auto-apply runs the same eligibility logic as active (confidence, breadth, kind, target, snooze, block, the `check`-surface rule, the eval gate) and appends `{ts, proposal_id, would_apply, reason, fingerprint, fix_surface}` to `~/.claude/autoheal/shadow/auto-apply.jsonl`. It creates no branch and no applied record.
  - Realtime alerts evaluate the patterns and append `{ts, session_id, pattern, severity, would_alert}` to `~/.claude/autoheal/shadow/realtime.jsonl` (never the command). No `<autoheal-security-alert>` block, no event, exit 0.
- **Agreement.** The digest's "Shadow rollout" section compares each auto-apply decision with what you did next: an applied record (`/autoheal-apply`, `/permission-fix`) means accepted, a snoozed fingerprint means rejected. Would-apply and accepted, or would-skip and rejected, is agreed; would-apply and rejected is a false positive; would-skip and accepted is a false negative; neither yet is pending. Alerts have no recorded human outcome, so they are counted but stay pending.
- **Promotion bar.** Move a flag to `active` only when the digest shows at least 20 decided (non-pending) decisions, at 90% agreement or better, with zero false positives on `check`-surface proposals. The numbers are `PROMOTION_MIN_DECIDED`, `PROMOTION_MIN_AGREEMENT` and `PROMOTION_MAX_GUARDED_FALSE_POSITIVES` in `lib/autoheal_mode.py`; the digest computes the verdict from them.

## Config

User-global config lives at `~/.claude/autoheal/config.json`. Per-repo overrides live in `.autoheal/config.json` at the repo root.

See `skills/autoheal-reference/SKILL.md` for the full config-key table and merge rules.

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
bash modules/autoheal/tests/test-event-logging.sh
bash modules/autoheal/tests/test-permission-suppress.sh
bash modules/autoheal/tests/test-correction-detection.sh
bash modules/autoheal/tests/test-redaction-coverage.sh
```

Each test sets `CCGM_AUTOHEAL_DIR` to a temp directory; nothing pollutes the real `~/.claude/autoheal/`.
