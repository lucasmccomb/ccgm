# Autoheal: Self-Healing Observability Loop

Autoheal is a CCGM module that observes how you and your agents interact with Claude Code, then proposes concrete configuration improvements once a day. It captures permission events, tool failures, and user-correction signals as a local JSONL log, runs a daily analyzer against the log via a direct Anthropic API call, and surfaces a digest of proposed changes. Real-time security alerts and confidence-gated auto-apply are opt-in.

## What autoheal does

1. **Event capture** (hooks). Five hooks register on `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, and `Stop` to write append-only JSONL records to `~/.claude/autoheal/events/{YYYY-MM-DD}.jsonl`. Every record is redacted via `hook_utils.redact_secrets()` before truncation and every append goes through `hook_utils.file_locked_append()` so multiple clones cannot tear writes.
2. **Contextual auto-allow** (`permission-request-suppress.py`). In bypass mode, a `PermissionRequest` for a (tool, command-verb) signature that has been approved at least 3 times across at least 2 sessions is auto-allowed. This is conservative on purpose — one rogue session cannot establish a precedent.
3. **Daily analyzer** (Epic 6). A launchd job runs `bin/autoheal-daily.sh` at 08:00 local (UTC-keyed; see #525). The analyzer reads unanalyzed events, clusters routine successes by `(tool, command-prefix)` so heavy days fit under the input cap, keeps friction records (deny/ask permission_decisions, non-zero exits, corrections) as full records, and adapts the transcript excerpt window (3 → 1 → 0 turns) before rejecting on size. It calls the Anthropic API directly (no agent runtime — eliminates exec-escape attack surface) and writes proposals to `~/.claude/autoheal/proposals/{YYYY-MM-DD}.jsonl`. Size rejections accumulate in `~/.claude/autoheal/rejected-days.jsonl`; after 7 rejections of the same day under the same analyzer version the day is skipped past. `--force-day YYYY-MM-DD` re-processes a single day without bumping `last-analyzed`. Caps are config-driven (`max_input_tokens`, `daily_cost_cap_usd`).
4. **Digest** (Epic 7). `bin/autoheal-digest.sh` renders today's proposals as Markdown to `~/.claude/autoheal/digests/{YYYY-MM-DD}.md`. The local digest is always-on; optional Resend email is multi-recipient with per-recipient idempotency keys.
5. **Apply path** (Epic 4 + 11). `/permission-fix` and `/autoheal-apply` share `lib/apply-proposal.py`: detect canonical clone, create feature branch, apply diff, run validation tests, commit, print `git diff`, write audit. Never auto-pushes; user reviews PR.
6. **Real-time security alerts** (Epic 10, OPT-IN). When `realtime_alerts_enabled: true`, `realtime-security-scanner.py` runs on `PostToolUse` with `asyncRewake: true`. A match on a high-confidence pattern (`ghp_` in a commit, `rm -rf /`, force-push to main without `ALLOW_MAIN_COMMIT`, etc.) wakes Claude mid-session with `<autoheal-security-alert>`. Default off.
7. **Confidence-gated auto-apply** (Epic 11, OPT-IN). When `auto_apply_enabled: true` AND a proposal has confidence ≥ 9, breadth ≤ 1, kind `settings_allow_add`, and target under `modules/settings/`, the daily run creates a feature branch and commits — but never pushes. Default off.
8. **Webhook publisher** (Epic 12, OPT-IN). When `webhook_url` is set, `bin/autoheal-publish.sh` POSTs daily proposals/events/digests to the configured endpoint with a Bearer token. Default null → no-op.

## Config keys (`~/.claude/autoheal/config.json`)

| Key | Type | Default | Notes |
|---|---|---|---|
| `realtime_alerts_enabled` | bool | `false` | Opt-in to mid-session `<autoheal-security-alert>` blocks |
| `auto_apply_enabled` | bool | `false` | Opt-in to confidence-gated auto-apply (feature branches only; never pushes) |
| `email_enabled` | bool | `false` | Opt-in to Resend digest delivery |
| `digest_email` | string OR string list | `null` | Recipient(s) for the optional email digest |
| `webhook_url` | string | `null` | When set, daily run POSTs to `${webhook_url}/v1/ingest` |
| `webhook_token` | string | generated at install time | 32-char Bearer token for the webhook |
| `retention_gzip_days` | int | `30` | Gzip events/proposals/digests older than N days |
| `retention_delete_days` | int | `60` | Delete gzipped artifacts older than N days |
| `calibration_days` | int | `7` | Relaxed thresholds during the first N days after install |

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
