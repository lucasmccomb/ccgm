---
name: autoheal-reference
description: >
  Reference for CCGM's autoheal loop: event-capture hooks, the daily analyzer, digest, apply path, config keys, and the opt-in alerts and auto-apply. Load when working on modules/autoheal, ~/.claude/autoheal, or the /autoheal commands.
---

# Autoheal: Self-Healing Observability Loop

Autoheal is a CCGM module that observes how you and your agents interact with Claude Code, then proposes concrete configuration improvements once a day. It captures permission events, tool failures, and user-correction signals as a local JSONL log, runs a daily analyzer against the log via a direct Anthropic API call, and surfaces a digest of proposed changes. Real-time security alerts and confidence-gated auto-apply are opt-in.

## What autoheal does

1. **Event capture** (hooks). Hooks on `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, and `UserPromptSubmit` write append-only JSONL rows to `~/.claude/autoheal/events/{YYYY-MM-DD}.jsonl`: failures (`error`, `error_class`, `cmd_head`), interrupts, permission requests, and corrections. Routine successful calls write no row; they bump a per-tool counter in `~/.claude/autoheal/counts/{YYYY-MM-DD}.json`. Every record is redacted via `hook_utils.redact_secrets()` before truncation and every append goes through `hook_utils.file_locked_append()` so multiple clones cannot tear writes.
2. **Contextual auto-allow** (`permission-request-suppress.py`). In bypass mode, a `PermissionRequest` for a (tool, command-verb) signature that has been approved at least 3 times across at least 2 sessions is auto-allowed. This is conservative on purpose — one rogue session cannot establish a precedent.
3. **Daily analyzer** (Epic 6, redesigned in #1099). A launchd job runs `bin/autoheal-daily.sh` at 08:00 local (UTC-keyed; see #525), which runs `bin/autoheal-analyze.sh`. The analyzer first runs `bin/autoheal-aggregate.py --date <day>` (a 14-day window, no model call) and takes at most 3 qualifying signatures from `signatures/<day>.json`; with none it makes no API call and exits 0. A hook-denial signature never reaches the model: code writes an `issue` proposal with locally drafted evidence and files nothing on GitHub. Any other signature becomes one request of about 6 to 12k tokens: the signature record, the module index (`lib/module-index.py`: every `modules/*/rules/*.md` path with its H1 and H2 headings), the full text of at most 2 candidate rule files picked by `lib/signature-module-map.json` (command head, then error class, then keyword match against the index), and at most one redacted excerpt of 1,500 characters or less. The CCGM source repo comes from `ccgm_repo_path` in config.json, else from the `~/.claude/rules/*.md` symlinks; a copy install skips drafting with a logged reason and never invents paths. Before each call the input is measured with the Anthropic `count_tokens` endpoint (free) and anything over 15,000 tokens is refused unsent. The model (`default_model` in config.json, else `claude-sonnet-5`; thinking off, `max_tokens` 2000, the prompt and module index cached) answers through structured outputs (`lib/proposal-schema.json`) with a `rule_insert` (`target_path` enum-constrained to the candidates, `anchor_heading`, at most 8 lines of `insert_markdown`) or a `skip`. It returns no diff, id or fingerprint: `lib/draft_proposals.py` uses the aggregator's `signature_id` (`sha256(signature)[:12]`) as the id, checks the path and anchor against the real file, builds the unified diff, and drops a failed answer with a counted reason (`anchor_missing`, `path_not_candidate`, ...). Rows go to `~/.claude/autoheal/proposals/{YYYY-MM-DD}.jsonl` with `state` `ready` (or `skipped`, which counts as covered so the signature is not sent again). A configured model that does not support structured outputs stops the run before any call, naming the model and listing the ones it can use; that list and the `cost_pricing` tables are one contract, so a model is accepted only if it both supports structured outputs and has a published rate (`claude-sonnet-4-6` and `claude-opus-4-7` stay priced but ungated). Cost lines include cache-write (1.25x) and cache-read (0.1x) tokens. **A failed call is logged and counted in `runs/{date}.json`, never retried in the run and never held for a later one**: a non-200, a transport failure, a `stop_reason` other than `end_turn`, an empty response and an over-limit input all count as failed calls, and the digest renders the count. There is no calibration mode, per-SHA give-up counter, rejected-day hold or chars/4 size estimate. `--date YYYY-MM-DD` sets the aggregation window end. The only cap in config is `daily_cost_cap_usd`; the 15,000-token input limit is fixed.
4. **Digest** (Epic 7). `bin/autoheal-digest.sh` renders today's proposals as Markdown to `~/.claude/autoheal/digests/{YYYY-MM-DD}.md`. The local digest is always-on; optional Resend email is multi-recipient with per-recipient idempotency keys.
5. **Apply path** (Epic 4 + 11). `/permission-fix` and `/autoheal-apply` share `lib/apply-proposal.py`: detect canonical clone, create feature branch, apply diff, run validation tests, commit, print `git diff`, write audit. Never auto-pushes; user reviews PR.
6. **Real-time security alerts** (Epic 10, OPT-IN). When `realtime_alerts_enabled` is `active` (or `shadow`, which only logs `would_alert` to `shadow/realtime.jsonl`), `realtime-security-scanner.py` runs on `PostToolUse` with `asyncRewake: true`. A match on a high-confidence pattern (`ghp_` in a commit, `rm -rf /`, force-push to main without `ALLOW_MAIN_COMMIT`, etc.) wakes Claude mid-session with `<autoheal-security-alert>`. Default off.
7. **Confidence-gated auto-apply** (Epic 11, OPT-IN). When `auto_apply_enabled` is `active` (or `shadow`, which only logs `would_apply` to `shadow/auto-apply.jsonl`) AND a proposal has confidence ≥ 9, breadth ≤ 1, kind `settings_allow_add`, and target under `modules/settings/`, the daily run creates a feature branch and commits — but never pushes. Default off. A proposal must ALSO clear the eval/regression gate (#9 below) before it is applied.
8. **Eval/regression gate** (Epic #659, OPT-IN promotion precondition). Before any proposal is auto-applied, `bin/autoheal-auto-apply.sh` runs `lib/proposal-eval.py` against a fixed fixture set (`tests/fixtures/eval-scenarios.json`). The proposal's added allow-rules are replayed against representative permission scenarios; the proposal passes only if it resolves ≥ 1 friction scenario (an `allow`-expected case) with **zero regressions** (no `prompt`- or `deny`-expected scenario silently auto-allowed). The scoring is fully deterministic — same proposal + fixtures always yield the same verdict. The gate fails closed: a missing/erroring evaluator blocks promotion rather than allowing un-evaluated changes. This layers on top of the structural gate; it never relaxes it, and auto-apply stays default OFF.
9. **Webhook publisher** (Epic 12, OPT-IN). When `webhook_url` is set, `bin/autoheal-publish.sh` POSTs daily proposals/events/digests to the configured endpoint with a Bearer token. Default null → no-op.

## Config keys (`~/.claude/autoheal/config.json`)

| Key | Type | Default | Notes |
|---|---|---|---|
| `realtime_alerts_enabled` | `off\|shadow\|active` | `off` | Mid-session `<autoheal-security-alert>` blocks; shadow logs would-alert only (a persisted boolean reads as active/off) |
| `auto_apply_enabled` | `off\|shadow\|active` | `off` | Confidence-gated auto-apply (feature branches only; never pushes); shadow logs would-apply only (a persisted boolean reads as active/off) |
| `email_enabled` | bool | `false` | Opt-in to Resend digest delivery |
| `digest_email` | string OR string list | `null` | Recipient(s) for the optional email digest |
| `webhook_url` | string | `null` | When set, daily run POSTs to `${webhook_url}/v1/ingest` |
| `webhook_token` | string | generated at install time | 32-char Bearer token for the webhook |
| `aggregation` | object | `{window_days: 14, min_occurrences: 5, min_sessions: 2, min_days: 2}` | Window and qualifying bar for `bin/autoheal-aggregate.py` |
| `retention_gzip_days` | int | `30` | Gzip events/proposals/digests older than N days |
| `retention_delete_days` | int | `60` | Delete gzipped artifacts older than N days |
| `ccgm_repo_path` | string | unset | CCGM source repo the analyzer reads rule files from. Overrides the `~/.claude/rules/*.md` symlink lookup; must hold `start.sh` and `modules/` |
| `calibration_days` | int | `7` | Inert. Calibration mode was removed in #1099; the key is still accepted in per-repo configs |

Per-repo overrides live in `.autoheal/config.json` at the repo root. The merge rule is "missing keys fall through to global"; see `hook_utils.load_repo_config()`.

## API keys: `~/.claude/autoheal/.env` (NOT shell rc)

Autoheal reads `ANTHROPIC_API_KEY` (analyzer) and `RESEND_API_KEY` (email) from a **scoped env file**, not from `~/.zshrc` / `~/.bash_profile`. The file lives at `~/.claude/autoheal/.env` with mode 0600. The daily LaunchAgent's entrypoint sources it just before running the chain — its environment never reaches your interactive shells.

**Do not put `ANTHROPIC_API_KEY` in your shell rc.** Every Anthropic SDK client running in any interactive shell (`anthropic-python`, the `claude` CLI, custom scripts) auto-picks it up from env, which bills against the API key instead of your Claude Max subscription. The scoped `.env` keeps the key visible to autoheal only.

To enable the analyzer: add `ANTHROPIC_API_KEY=sk-ant-...` to `~/.claude/autoheal/.env`. To enable the email digest: also add `RESEND_API_KEY=re_...` and flip `/autoheal-toggle email on`. An empty `.env` is fine — the analyzer logs `ANTHROPIC_API_KEY not set; skipping` and the rest of the chain proceeds normally.

## Slash commands

- `/permission-fix [event-id|latest]` — in-session root-cause sub-agent. Proposes a fix; can apply via `lib/apply-proposal.py`.
- `/permission-audit` — static audit of installed hooks + settings against the explicit classification table.
- `/autoheal` — help + status.
- `/autoheal-digest [date]` — render today's (or a specific date's) digest.
- `/autoheal-toggle [pause|resume|status|realtime|autoapply|webhook]` — flip config flags.
- `/autoheal-snooze <id> [days]` — snooze a proposal for N days (default 30).
- `/autoheal-apply [id|list]` — formal apply path; same shape as `/permission-fix apply`.

## When NOT to invoke

- **Do not edit `~/.claude/autoheal/events/*.jsonl` by hand.** The file is append-only by contract; the analyzer assumes monotonic ordering and idempotent reads. Use `/autoheal-snooze` to suppress proposals; never delete events to "clean up" the log.
- **Do not bypass the apply path.** Auto-apply gates exist to keep the agent honest. Manually committing an autoheal proposal without running `apply-proposal.py` skips the validation tests and audit log.
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

# Run the Epic-3 test suite.
bash modules/autoheal/tests/test-event-logging.sh
bash modules/autoheal/tests/test-permission-suppress.sh
bash modules/autoheal/tests/test-correction-detection.sh
bash modules/autoheal/tests/test-redaction-coverage.sh
```

## Cross-references

- Plan: `~/code/plans/ccgm-autoheal/plan.md` (Section 1 vision; Section 3 architecture; Section 5 Epic 3 spec).
- Hook helper: `modules/hooks/lib/hook_utils.py` — `read_hook_input`, `redact_secrets`, `file_locked_append`, `is_bypass_mode`, `emit_decision`, `hard_block`, `load_repo_config`.
- Bring-up runbook: `plan.md §9.1`.
