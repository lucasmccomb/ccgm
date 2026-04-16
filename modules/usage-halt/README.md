# usage-halt

Halts every Claude Code session on the machine when the active 5-hour usage block approaches its limit.

## What it does

1. A launchd agent polls `ccusage blocks --active --json --token-limit max` every 60 seconds.
2. When `tokenLimitStatus.percentUsed` crosses the threshold (default 99%), the monitor writes `~/.claude/halt.flag` with the block's reset timestamp and fires a macOS notification.
3. A universal `PreToolUse` hook (`halt-gate.py`) checks the flag on every tool call. While the flag is live, the hook denies the call with a message showing when the block resets.
4. When the block resets, the monitor clears the flag and sends a resume notification. The next tool call succeeds normally.

The hook denies tools rather than killing processes, so agents drain cleanly — their current response finishes and the next tool call is blocked. Override a live halt with `rm ~/.claude/halt.flag`.

## Files

| Path | Purpose |
|------|---------|
| `hooks/halt-gate.py` | PreToolUse hook, universal matcher. Reads halt.flag; denies tool calls while flag's reset_iso is in the future; auto-clears stale flags. |
| `hooks/usage-monitor.sh` | Polls ccusage, writes/clears halt.flag, sends macOS notifications via osascript. |
| `postInstall.sh` | Writes `~/Library/LaunchAgents/com.lem.claude-usage-monitor.plist` and loads it with `launchctl`. Also installs `ccusage` globally if npm is available. |
| `settings.partial.json` | Merges a PreToolUse entry (matcher `""`) into `~/.claude/settings.json` to run `halt-gate.py` on every tool call. |

## Flag format

`~/.claude/halt.flag` (key=value, one per line):

```
reset_iso=2026-04-16T19:00:00.000Z
percent=99.5
triggered_at=2026-04-16T18:47:00Z
```

## Configuration

Threshold is set via the `HALT_THRESHOLD` environment variable in the launchd plist (written by `postInstall.sh`). To change it after install, edit `~/Library/LaunchAgents/com.lem.claude-usage-monitor.plist`, then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.lem.claude-usage-monitor.plist
launchctl load -w ~/Library/LaunchAgents/com.lem.claude-usage-monitor.plist
```

## Limitations

- Only covers the 5-hour session block, not the 7-day rolling subscription cap. `ccusage` doesn't expose the weekly cap against an Anthropic subscription tier.
- `ccusage blocks --token-limit max` uses the highest token count ever observed in history as the limit benchmark. If you've never hit 100% of your actual subscription cap, this is an underestimate of the real ceiling.
- macOS only. The launchd plist and `osascript` notification paths are Darwin-specific.

## Dependencies

- `ccusage` (npm package, auto-installed by postInstall if npm is present)
- `jq` (used by `usage-monitor.sh` to parse ccusage JSON)
- `launchctl`, `osascript` (macOS built-ins)
