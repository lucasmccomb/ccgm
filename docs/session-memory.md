# Session Memory

How CCGM handles session continuity, cross-session retrieval, and the curated knowledge base.

## The layers

Claude Code already captures every session as JSONL. CCGM adds two small layers on top: a query tool that unifies the transcripts across clones, and a curated memory file that persists the deliberate conclusions.

| Layer | What it is | Who writes it | Who reads it |
|-------|------------|---------------|--------------|
| Raw transcripts | `~/.claude/projects/{normalized-cwd}/sessions/{session-id}.jsonl` | Claude Code (automatic) | `/recall`, you via `grep` |
| Per-repo unified history | `/recall` command | no one — it is a query | agents at session start, you on demand |
| Curated memory | `CLAUDE.md` (repo) and `MEMORY.md` + auto-memory files (per-project) | `/reflect`, `/consolidate`, you | every session, automatically |

Nothing in this chain depends on agent discipline to write markdown logs. The JSONL is written whether or not the agent remembered to.

## `/recall`

`/recall` surfaces recent session activity for the current repo across every clone on the machine. Defaults: last 7 days, all clones, summary view.

```
/recall                         # last 7 days, summary
/recall startup dashboard       # filter turns containing the phrase
/recall --days 30               # longer window
/recall --repo voxter           # different repo by canonical name
/recall --session <id>          # dump one session as readable text
```

Claude Code normally treats `ccgm-0`, `ccgm-1`, and `ccgm-workspaces/...` as separate projects. `/recall` merges them by detecting the canonical repo name from the git remote.

The `/startup` dashboard calls `/recall --summary --limit 3 --days 7` to render its **Recent Activity** block.

## Curated memory

`/reflect` and `/consolidate` (from the `self-improving` module) write distilled patterns to `MEMORY.md` and topic-specific memory files. These are the deliberate takeaways — "don't mock the database in integration tests", "this user prefers single bundled PRs for refactors" — that you want every future session to see.

Raw transcripts are the search target; `MEMORY.md` is the instruction set.

## `AGENTS.md`

Repos that opt in keep an `AGENTS.md` symlink pointing to `CLAUDE.md` so that non-Claude agentic tools (Cursor, Aider, etc.) read the same project instructions. Run once:

```
bash ~/.claude/scripts/add-agents-md-symlinks.sh
```

The script targets a curated list of active repos and skips any where `AGENTS.md` already exists as a regular file.

## The retired agent-log-repo

Before this redesign, CCGM relied on agents writing markdown logs at specific triggers (after commit, after PR create, after merge, etc.) to a private git repo at `~/code/lem-agent-logs/`. That system had two problems:

1. **Agent discipline**: when an agent was deep in a task, logs frequently went unwritten.
2. **Duplication**: Claude Code already captured the same information deterministically as JSONL.

The agent-log-repo is preserved read-only as historical archive. The `tracking.csv` that lives inside it remains the source of truth for multi-agent coordination; its hooks (claim / pr-created / merged / closed) still work because `/recall` does not touch that file.

If you ever want to search the archive:

```bash
grep -r "your search term" ~/code/lem-agent-logs/
```

A future "deep recall" tier may unify the archive with the live JSONL via SQLite FTS5. Not built, not planned for v1.
