# startup-dashboard

Plain-text dashboard rendered by `/startup`. Surfaces the state an agent needs at the start of a session without writing any markdown logs.

## What This Module Does

- **`/startup` command**: Runs the gather pipeline and emits a formatted dashboard straight from Bash — no model tokens for formatting.
- **Gather pipeline**: Collects git state, open PRs, `tracking.csv` claims, live Claude Code sessions, sibling branches, orphan processes, release info, and recent session activity in parallel.
- **Recent Activity**: Unified 7-day view of session transcripts across every clone of the current repo, powered by the `session-history` module's `/recall`.

The module used to be called `session-logging` and wrote markdown logs to `~/code/lem-agent-logs/`. That was retired once Claude Code's native JSONL transcripts + `/recall` covered the same ground deterministically. See `docs/session-memory.md` for the full story.

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/startup.md` | command | `/startup` invokes the dashboard script |
| `lib/startup-gather.sh` | lib | Parallel data gather, emits `=== SECTION ===` blocks |
| `lib/startup-dashboard.sh` | lib | Formats gather output into a plain-text dashboard |

## Dependencies

- `session-history` — supplies `~/.claude/scripts/recall.py`, which powers the Recent Activity block.

## Running the Dashboard

```
/startup
```

Or directly:

```
bash ~/.claude/lib/startup-dashboard.sh
```

## Customizing

`startup-gather.sh` emits structured sections. `startup-dashboard.sh` parses them and renders the layout. To change what shows up, edit the parser and/or add new sections to the gather script.

## Configuration

None. The dashboard uses data already available from git, the tracking system, and Claude Code's session transcripts.
