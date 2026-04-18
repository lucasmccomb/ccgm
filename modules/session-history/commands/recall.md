# /recall - Search session history across all clones of a repo

Run `recall.py` and display its output verbatim:

```bash
python3 ~/.claude/scripts/recall.py $ARGUMENTS
```

## What It Does

`/recall` reads Claude Code's native JSONL transcripts at `~/.claude/projects/**/*.jsonl` and surfaces session history for the current repo, unified across all of its clones (flat-clone and workspace models).

It does NOT maintain a separate index or database — transcripts are the source of truth, read on demand.

## Usage

| Invocation | Behavior |
|-----------|----------|
| `/recall` | Last 7 days, current repo (auto-detected), all clones, summary view |
| `/recall <query>` | Last 7 days, filtered to turns matching `<query>` (case-insensitive regex) |
| `/recall --days N` | Custom time window |
| `/recall --days N <query>` | Custom window + query filter |
| `/recall --repo <name>` | Different repo. Pass the canonical name (e.g. `ccgm`, `habitpro-ai`) as returned by `git remote get-url origin` — substring matching is NOT supported |
| `/recall --summary` | Force summary mode even when a query is given |
| `/recall --full <query>` | Do not truncate matched turn content |
| `/recall --limit N` | Maximum sessions/results to display (default 50) |
| `/recall --session <id>` | Dump a specific session's transcript as readable text. Accepts full session id or a unique prefix |

## Examples

```
/recall                       # What have I been doing in this repo this week?
/recall migration             # What did I try with that migration?
/recall --days 30 auth        # Broader lookback on auth work
/recall --repo voxter         # Switch to voxter sessions
/recall --session 65b57a04    # Read a specific session
```

## Design

- Reads JSONL directly (no SQLite, no pre-built index). Fast enough for ~4,000-session corpora.
- Unifies across clones by matching `~/.claude/projects/*` dirs whose encoded path ends with the canonical repo name plus a known clone-suffix pattern (`-N`, `-wN`, `-wN-cM`).
- Skips tool_result-only user turns and `<system-reminder>`-wrapped messages from summary extraction.
- Exits 0 when no repo is detected (so dashboard wrappers can gracefully skip the Recent Activity block).
