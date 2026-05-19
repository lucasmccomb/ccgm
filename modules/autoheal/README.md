# autoheal

Self-healing observability loop for Claude Code. Captures permission events, tool failures, and user-correction signals; runs a daily analyzer via direct Anthropic API call; surfaces a digest with proposed configuration changes. Optional real-time security alerts and confidence-gated auto-apply, both default off.

## What this module installs

- **5 event-capture hooks** on `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, and `Stop`.
- **2 response hooks**: `permission-request-suppress.py` (contextual auto-allow) and `realtime-security-scanner.py` (opt-in mid-session alerts).
- **7 slash commands**: `/permission-fix`, `/permission-audit`, `/autoheal`, `/autoheal-digest`, `/autoheal-toggle`, `/autoheal-snooze`, `/autoheal-apply`.
- **Daily LaunchAgent** (macOS) calling `bin/autoheal-daily.sh` at 08:00 local. Linux scheduling is an architectural seam, not built in v1.

## Default posture

- **Real-time security alerts: OFF.** Enable with `/autoheal-toggle realtime on` (or `realtime_alerts_enabled: true` in config).
- **Auto-apply: OFF.** Enable with `/autoheal-toggle autoapply on` (or `auto_apply_enabled: true` in config).
- **Email digest: OFF.** Local digest is always-on; opt into Resend with `digest_email` and `email_enabled: true` + `RESEND_API_KEY` in `~/.claude/autoheal/.env` (NOT shell rc — see "API keys" below).
- **Webhook publisher: OFF.** Set `webhook_url` in config to enable.

## Config

User-global config lives at `~/.claude/autoheal/config.json`. Per-repo overrides live in `.autoheal/config.json` at the repo root.

See `rules/autoheal.md` for the full config-key table and merge rules.

## API keys

Autoheal reads `ANTHROPIC_API_KEY` (analyzer) and `RESEND_API_KEY` (email) from `~/.claude/autoheal/.env` (mode 0600). The daily LaunchAgent's entrypoint sources this file; it never sources your shell rc.

**Do not export `ANTHROPIC_API_KEY` from `~/.zshrc`.** Anthropic SDK clients (anthropic-python, the `claude` CLI, custom scripts) auto-detect it from env and would bill against the API key instead of your Claude Max subscription. The scoped `.env` keeps it invisible to interactive shells.

`autoheal-install.sh` creates an empty `.env` template on first run with usage notes inline.

## Cross-references

- Rule file: `rules/autoheal.md` (the contract autoheal expects Claude Code to follow).
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
