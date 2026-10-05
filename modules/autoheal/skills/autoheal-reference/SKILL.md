---
name: autoheal-reference
description: >
  Reference for CCGM's autoheal loop: event-capture hooks, the daily analyzer, digest, apply path, config keys, and the opt-in alerts and auto-apply. Load when working on modules/autoheal, ~/.claude/autoheal, or the /autoheal commands.
---

# Autoheal: Self-Healing Observability Loop

Autoheal is a CCGM module that observes how you and your agents interact with Claude Code, then proposes concrete configuration improvements once a day. It captures permission events, tool failures, and user-correction signals as a local JSONL log, runs a daily analyzer against the log via a direct Anthropic API call, and surfaces a digest of proposed changes. Real-time security alerts and earned auto-apply (off, shadow, then active once shadow agrees with your reviews) are opt-in.

## What autoheal does

1. **Event capture** (hooks). Hooks on `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, and `UserPromptSubmit` write append-only JSONL rows to `~/.claude/autoheal/events/{YYYY-MM-DD}.jsonl`: failures (`error`, `error_class`, `cmd_head`), interrupts, permission requests, and corrections. Routine successful calls write no row; they bump a per-tool counter in `~/.claude/autoheal/counts/{YYYY-MM-DD}.json`. Every record is redacted via `hook_utils.redact_secrets()` before truncation and every append goes through `hook_utils.file_locked_append()` so multiple clones cannot tear writes.
2. **Contextual auto-allow** (`permission-request-suppress.py`). In bypass mode, a `PermissionRequest` for a (tool, command-verb) signature that has been approved at least 3 times across at least 2 sessions is auto-allowed. This is conservative on purpose — one rogue session cannot establish a precedent.
3. **Daily analyzer** (Epic 6, redesigned in #1099). A launchd job runs `bin/autoheal-daily.sh` at 08:00 local (UTC-keyed; see #525), which runs `bin/autoheal-analyze.sh`. The analyzer first runs `bin/autoheal-aggregate.py --date <day>` (a 14-day window, no model call) and takes at most 3 qualifying signatures from `signatures/<day>.json`; with none it makes no API call and exits 0. A hook-denial signature never reaches the model: code writes an `issue` proposal with locally drafted evidence and files nothing on GitHub. Any other signature becomes one request of about 6 to 12k tokens: the signature record, the module index (`lib/module-index.py`: every `modules/*/rules/*.md` path with its H1 and H2 headings), the full text of at most 2 candidate rule files picked by `lib/signature-module-map.json` (command head, then error class, then keyword match against the index), and at most one redacted excerpt of 1,500 characters or less. The CCGM source repo comes from `ccgm_repo_path` in config.json, else from the `~/.claude/rules/*.md` symlinks; a copy install skips drafting with a logged reason and never invents paths. Before each call the input is measured with the Anthropic `count_tokens` endpoint (free) and anything over 15,000 tokens is refused unsent. The model (`default_model` in config.json, else `claude-sonnet-5`; thinking off, `max_tokens` 2000, the prompt and module index cached) answers through structured outputs (`lib/proposal-schema.json`) with a `rule_insert` (`target_path` enum-constrained to the candidates, `anchor_heading`, at most 8 lines of `insert_markdown`) or a `skip`. It returns no diff, id or fingerprint: `lib/draft_proposals.py` uses the aggregator's `signature_id` (`sha256(signature)[:12]`) as the id, checks the path and anchor against the real file, builds the unified diff, and drops a failed answer with a counted reason (`anchor_missing`, `path_not_candidate`, ...). Rows go to the ledger `~/.claude/autoheal/proposals.jsonl` with `state` `ready` (or `skipped`, which counts as covered so the signature is not sent again). A configured model that does not support structured outputs stops the run before any call, naming the model and listing the ones it can use; that list and the `cost_pricing` tables are one contract, so a model is accepted only if it both supports structured outputs and has a published rate (`claude-sonnet-4-6` and `claude-opus-4-7` stay priced but ungated). Cost lines include cache-write (1.25x) and cache-read (0.1x) tokens. **A failed call is logged and counted in `runs/{date}.json`, never retried in the run and never held for a later one**: a non-200, a transport failure, a `stop_reason` other than `end_turn`, an empty response and an over-limit input all count as failed calls, and the digest renders the count. There is no per-SHA give-up counter, rejected-day hold or chars/4 size estimate. `--date YYYY-MM-DD` sets the aggregation window end. The only cap in config is `daily_cost_cap_usd`; the 15,000-token input limit is fixed.
4. **Digest** (Epic 7). `bin/autoheal-digest.sh` renders today's rows of the proposal ledger (`~/.claude/autoheal/proposals.jsonl`) as Markdown to `~/.claude/autoheal/digests/{YYYY-MM-DD}.md`. The local digest is always-on; optional Resend email is multi-recipient with per-recipient idempotency keys.
5. **Apply path** (Epic 4 + 11, #1099 Phase 3.2). `/autoheal-review` (`bin/autoheal-review.py`) re-runs `validate()`, applies a `rule_insert` in a temporary worktree of the CCGM source repo on `autoheal/<id>`, commits with `Autoheal-Id` and `Autoheal-Signature` trailers, pushes, opens a PR and squash-merges it once checks pass (never `--admin`); an `issue` proposal files a GitHub issue. `revert <id>` undoes a merged fix the same way (a `git revert` PR of the `Autoheal-Id` commit, `Autoheal-Revert` trailer, row `reverted`); `redraft <id>` lets a measured fix's signature be drafted again. `/permission-fix` still uses `lib/apply-proposal.py` (local branch, no push, user reviews).
6. **Real-time security alerts** (Epic 10, OPT-IN). When `realtime_alerts_enabled` is `active` (or `shadow`, which only logs `would_alert` to `shadow/realtime.jsonl`), `realtime-security-scanner.py` runs on `PostToolUse` with `asyncRewake: true`. A match on a high-confidence pattern (`ghp_` in a commit, `rm -rf /`, force-push to main without `ALLOW_MAIN_COMMIT`, etc.) wakes Claude mid-session with `<autoheal-security-alert>`. Default off.
7. **Earned auto-apply** (#1099 Phase 4.2, OPT-IN). `auto_apply_mode` is `off` (default), `shadow` or `active`. The nightly `bin/autoheal-auto-apply.sh` (`lib/auto_apply.py`) gates each ready row on kind `rule_insert`, `validate()`, at least 10 occurrences across at least 3 sessions, and a target matching `auto_apply_targets`. Shadow logs each decision to `shadow/auto-apply.jsonl` and changes nothing; agreement is measured against `/autoheal-review` outcomes. `active` is refused until 10 decided decisions at 90% agreement with none later harmful, and runs through `/autoheal-review`'s PR path (`applied_by: auto`). 3 reverts in 30 days demote it to shadow. The legacy `auto_apply_enabled` flag migrates to off or shadow, never active.
8. **Outcome measurement** (#1099 Phase 4.1). The aggregator measures each applied rule fix 14 days after merge against its `baseline_rate`: effective (≤50%), ineffective (50 to 100%), harmful (above baseline, or a new signature on the same command head), or unmeasurable; the row becomes `measured`. In `active` mode a harmful fix gets an automatic revert PR; otherwise the SessionStart notice flags it.
9. **Email and webhook publisher** (OPT-IN, off by default). Email (`email_enabled`, `digest_email`, `RESEND_API_KEY`) sends the rendered digest. When `webhook_url` is set, `bin/autoheal-publish.sh` POSTs today's ledger rows, events and digest to the endpoint with a Bearer token; null is a no-op. Both read the ledger.
10. **Success metrics and doctor.** `/autoheal` shows run health over 30 days, acceptance rate, applied-effective rate and 30-day spend (`lib/autoheal_metrics.py`), and marks the rest not computable yet. `/autoheal doctor` (`bin/autoheal-doctor.py`) also checks that every `module.json` file target exists under `~/.claude`.

## Config keys (`~/.claude/autoheal/config.json`)

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

Per-repo overrides live in `.autoheal/config.json` at the repo root. The merge rule is "missing keys fall through to global"; see `hook_utils.load_repo_config()`.

## API keys: `~/.claude/autoheal/.env` (NOT shell rc)

Autoheal reads `ANTHROPIC_API_KEY` (analyzer) and `RESEND_API_KEY` (email) from a **scoped env file**, not from `~/.zshrc` / `~/.bash_profile`. The file lives at `~/.claude/autoheal/.env` with mode 0600. The daily LaunchAgent's entrypoint sources it just before running the chain — its environment never reaches your interactive shells.

**Do not put `ANTHROPIC_API_KEY` in your shell rc.** Every Anthropic SDK client running in any interactive shell (`anthropic-python`, the `claude` CLI, custom scripts) auto-picks it up from env, which bills against the API key instead of your Claude Max subscription. The scoped `.env` keeps the key visible to autoheal only.

To enable the analyzer: add `ANTHROPIC_API_KEY=sk-ant-...` to `~/.claude/autoheal/.env`. To enable the email digest: also add `RESEND_API_KEY=re_...` and flip `/autoheal-toggle email on`. An empty `.env` is fine — the analyzer logs `ANTHROPIC_API_KEY not set; skipping` and the rest of the chain proceeds normally.

## Slash commands

- `/permission-fix [event-id|latest]` — in-session root-cause sub-agent. Proposes a fix; can apply via `lib/apply-proposal.py`.
- `/permission-audit` — static audit of installed hooks + settings against the explicit classification table.
- `/autoheal` — help + status.
- `/autoheal-review [id]` — the one place a fix is accepted: one AskUserQuestion per ready fix (evidence, exact diff), then Apply (PR opened and squash-merged), Edit then apply, Reject (90-day suppression) or Snooze 14d. `revert <id>` and `redraft <id>` act on merged fixes. Code is `bin/autoheal-review.py`.
- `/autoheal-digest [date]` — render today's (or a specific date's) digest. An archive, not the interface.
- `/autoheal-toggle [pause|resume|status|realtime|autoapply|webhook]` — flip config flags.
- `/autoheal-snooze <id> [days]` — alias for the Snooze answer: sets the ledger row to `snoozed` for N days (default 14; 0 wakes it).
- `/autoheal-apply [id|list]` — alias for `/autoheal-review`; also documents the local apply path for `check` proposals.

## When NOT to invoke

- **Do not edit `~/.claude/autoheal/events/*.jsonl` by hand.** The file is append-only by contract; the analyzer assumes monotonic ordering and idempotent reads. Use `/autoheal-review` (Reject or Snooze) to suppress proposals; never delete events to "clean up" the log.
- **Do not bypass the apply path.** Auto-apply gates exist to keep the agent honest. Manually committing an autoheal proposal without `/autoheal-review` skips `validate()`, the `Autoheal-Id` trailer the revert path looks for, and the baseline the outcome check needs.
- **Do not hand-set `auto_apply_mode: "active"`.** Without `auto_apply_promoted_at` it runs as shadow; use `/autoheal-toggle autoapply active`, which checks the promotion bar.
- **Do not enable `realtime_alerts_enabled` in a session that runs against production data without `ALLOW_MAIN_COMMIT=1` already set.** Real-time alerts will fire on legitimate production operations and may interrupt time-sensitive work. Use the opt-in only when you want mid-session friction for security signals.
- **Do not point `webhook_url` at an untrusted endpoint.** The webhook publisher streams redacted events, but redaction is best-effort. Treat the webhook receiver as a trusted system.

## Quick checks

```bash
# Verify the hooks are installed and the log is being written.
ls ~/.claude/hooks/permission-event-logger.py
ls ~/.claude/autoheal/events/

# Verify the schemas are valid JSON.
python3 -c "import json; json.load(open('modules/autoheal/lib/event-schema.json'))"
python3 -c "import json; json.load(open('modules/autoheal/lib/proposal-schema.json'))"

# Run the module's test suites.
bash modules/autoheal/tests/run-all.sh
```

## Cross-references

- Plan: `~/code/plans/ccgm-autoheal/plan.md` (Section 1 vision; Section 3 architecture; Section 5 Epic 3 spec).
- Hook helper: `modules/hooks/lib/hook_utils.py` — `read_hook_input`, `redact_secrets`, `file_locked_append`, `is_bypass_mode`, `emit_decision`, `hard_block`, `load_repo_config`.
- Bring-up runbook: `plan.md §9.1`.
