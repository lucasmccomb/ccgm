# statusline

A compact, dependency-free Claude Code statusline rendered as a single line.

## What It Does

Consumes the statusline JSON Claude Code pipes to the script on stdin and renders these sections, separated by ` | `:

| Section | Source | Notes |
|---------|--------|-------|
| **Model + effort** | `.model.display_name`, `.effort.level` | `🧠 O-4.8 Max`, `🐢 S-4.6`, `⚠️ H-4.5`. Family/version parsed generically — new model versions need no edits. |
| **Clone identity** | `.env.clone` in cwd | `⛓ agent-2` when the working dir is a multi-clone checkout (reads `AGENT_ID`). Omitted otherwise. |
| **Dir + branch** | `.cwd`, git | Immediate directory name plus the current git branch. |
| **Context used** | `.context_window.total_input_tokens` ÷ auto-compact budget | `ctx:42%` (green/yellow/red by usage), measured against the compaction budget — `min(context_window_size, 500000)` — not the full window, so it reaches 100% as auto-compaction fires. Falls back to `.context_window.remaining_percentage` on older Claude Code. |
| **Compaction warning** | derived | `⚠ COMPACT SOON` appears at ≥90% of the auto-compact budget, so you can `/compact` before an auto-compaction truncates the session. Override the budget via `CCGM_CTX_COMPACT_BUDGET` if you changed it with `/autocompact`. |
| **Session cost** | `.cost.total_cost_usd` | `$1.23` for the current session. Omitted when Claude Code does not supply it. |
| **Rate limits** | `.rate_limits.five_hour`, `.rate_limits.seven_day` | `5h:30% █░░░░ 2h14m` and `7d:…` bars with reset countdowns. |

Every field is optional: a missing JSON key simply drops its section, so the bar degrades gracefully on older Claude Code versions.

## Relationship to `lib/statusline.sh` and `commands-utility`

CCGM has long shipped a statusline script inside the `commands-utility` module (mirrored as `lib/statusline.sh`), but it was never wired to the `statusLine` setting — installing it left the user to configure `settings.json` by hand, and it did not surface clone identity, session cost, or an explicit compaction warning.

This module packages the statusline as a **first-class, installable unit**: it ships the script *and* a `settings.partial.json` that registers the `statusLine` setting, so `start.sh --add statusline` produces a working statusline with zero manual configuration. It is a superset of the `commands-utility` script (adds `⛓ clone`, `$cost`, and `⚠ COMPACT SOON`).

## Manual Installation

```bash
mkdir -p ~/.claude
cp statusline.sh ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash $HOME/.claude/statusline.sh"
  }
}
```

## Files

| File | Description |
|------|-------------|
| `statusline.sh` | The statusline renderer (bash + jq, portable to bash 3.2 / BSD + GNU). |
| `settings.partial.json` | Merged into `settings.json` to register the `statusLine` command. |

## Dependencies

`jq` only (already required by every CCGM tool). No external packages, no TUI library.
