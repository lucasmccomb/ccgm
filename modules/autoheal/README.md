# autoheal

Self-healing observability loop for Claude Code. Captures permission events, tool failures, and user-correction signals; runs a daily analyzer via direct Anthropic API call; surfaces a digest with proposed configuration changes. Optional real-time security alerts and confidence-gated auto-apply, both default off.

## What this module installs

- **5 hooks** across `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, and `UserPromptSubmit`:
  - **3 event-capture hooks**: `permission-event-logger.py` (PermissionRequest rows; PostToolUse / PostToolUseFailure bump the daily per-tool counter `counts/{date}.json`), `failure-logger.py` (PostToolUseFailure: the only writer of failure rows, with `error`, `error_class`, `cmd_head`), `user-correction-detector.py` (UserPromptSubmit: a short prompt after a failure or interrupt).
  - **2 response hooks**: `permission-request-suppress.py` (PermissionRequest contextual auto-allow) and `realtime-security-scanner.py` (PostToolUse opt-in mid-session alerts).
- **Signature aggregator**: `bin/autoheal-aggregate.py [--date D]` counts recurring failures over a 14-day window with no model call and writes `signatures/{date}.json`, ranked by count x sessions. A signature qualifies at 5 or more occurrences across 2 or more sessions and 2 or more days (override under `aggregation` in `config.json`). It is not yet scheduled; a later unit wires it into the daily run.
- **7 slash commands**: `/permission-fix`, `/permission-audit`, `/autoheal`, `/autoheal-digest`, `/autoheal-toggle`, `/autoheal-snooze`, `/autoheal-apply`.
- **Daily LaunchAgent** (macOS) calling `bin/autoheal-daily.sh` at 08:00 local. Linux scheduling is an architectural seam, not built in v1.

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
