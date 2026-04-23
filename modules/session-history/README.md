# Session History

Cross-platform session historian agent. Searches prior **Claude Code** and **Codex** session transcripts for related work, failed approaches, and decisions from earlier sessions on the same repo - context that a fresh session cannot see.

Agent logs and `project-story.md` capture what *shipped*. This module answers a different question: *"when I was debugging this last week, what did I try?"*

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/session-historian.md` | `agents/session-historian.md` | Retrieval agent, invoked by other skills for deep synthesis |
| `commands/recall.md` | `commands/recall.md` | `/recall` slash command (lightweight, user-facing) |
| `scripts/discover-sessions.sh` | `scripts/discover-sessions.sh` | Enumerate session files across platforms |
| `scripts/extract-metadata.py` | `scripts/extract-metadata.py` | Batch-extract session metadata (branch, cwd, timestamps) |
| `scripts/recall.py` | `scripts/recall.py` | `/recall` implementation — unified session view across clones |
| `scripts/repo_detect.py` | `scripts/repo_detect.py` | Canonical repo-name detection + multi-clone project-dir matching |
| `scripts/add-agents-md-symlinks.sh` | `scripts/add-agents-md-symlinks.sh` | Sets up AGENTS.md symlinks so Codex transcripts share the same rule surface as Claude Code |

Two consumption patterns:

1. **`/recall` slash command** — fast, deterministic summary / query over the last N days of sessions for the current repo (unified across all clones). Default 7 days. No agent dispatch, no LLM calls.
2. **`session-historian` agent** — heavier synthesis via Task tool dispatch when you need "what was tried, what failed, what was decided" analysis across platforms (Claude Code + Codex).

Use `/recall` for quick lookups. Use the agent when you need the history interpreted, not just listed.

## Supported Platforms

| Platform | Session path | Correlation signal |
|----------|--------------|--------------------|
| Claude Code | `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` | Git branch + encoded CWD in directory name |
| Codex | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` (and `~/.agents/sessions/YYYY/MM/DD/`) | `cwd` field in `session_meta` |

Cursor is intentionally out of scope for this module (different transcript format, different correlation signals, and not part of the typical CCGM workflow). If Cursor support is needed later, add a third platform branch to `discover-sessions.sh` and a detector to `extract-metadata.py`.

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/agents
mkdir -p ~/.claude/scripts

cp modules/session-history/agents/session-historian.md \
   ~/.claude/agents/session-historian.md

cp modules/session-history/scripts/discover-sessions.sh \
   ~/.claude/scripts/discover-sessions.sh
chmod +x ~/.claude/scripts/discover-sessions.sh

cp modules/session-history/scripts/extract-metadata.py \
   ~/.claude/scripts/extract-metadata.py
chmod +x ~/.claude/scripts/extract-metadata.py

cp modules/session-history/scripts/add-agents-md-symlinks.sh \
   ~/.claude/scripts/add-agents-md-symlinks.sh
chmod +x ~/.claude/scripts/add-agents-md-symlinks.sh
```

## Usage

### `/recall` slash command

```
/recall                     # Last 7 days, current repo, all clones, summary
/recall migration           # Last 7 days, filter turns by "migration"
/recall --days 30 auth      # Custom window + filter
/recall --repo voxter       # Different repo (canonical name required)
/recall --session 65b57a04  # Dump a specific session
/recall --summary --limit 3 # Top 3 most recent sessions, compact format
```

`--repo` takes the canonical repo name as returned by `git remote get-url origin` — substring matching is NOT supported to avoid false positives (e.g., `ccgm` matching `ccgm-agent-learning`).

### From another skill or command

Dispatch the agent via the Task tool. Pass:

- A one-paragraph `task_summary` describing the current problem.
- An optional `time_range` hint (`today`, `this week`, `last month`, ...).
- Any platform restriction (`claude` or `codex`) if relevant; otherwise the agent searches both.

The agent returns text findings - usually a short header ("Sessions searched: N...") followed by a synthesis of what was tried, what failed, and what was decided in those prior sessions.

### Ad-hoc

Ask directly in a session:

```
Dispatch the session-historian agent. Find out what I tried when I
debugged the Vite CSS preflight issue in habitpro-ai this past week.
```

### Scripts directly

The discovery and metadata scripts are usable on their own if you want to inspect session metadata without a full agent dispatch:

```bash
# List Claude Code + Codex sessions for this repo from the last 7 days
bash ~/.claude/scripts/discover-sessions.sh habitpro-ai 7

# Get metadata for all of them in one pipeline
bash ~/.claude/scripts/discover-sessions.sh habitpro-ai 7 \
  | tr '\n' '\0' \
  | xargs -0 python3 ~/.claude/scripts/extract-metadata.py --cwd-filter habitpro-ai
```

Output is one JSON object per session plus a final `_meta` line with `files_processed` and `parse_errors` counts.

## Guardrails

The agent enforces these rules at all times:

- Never reads entire session files (they can be 1-7MB).
- Never extracts or reproduces tool call inputs/outputs verbatim.
- Never includes thinking or reasoning block content.
- Never analyzes the current session - its history is already available to the caller.
- Never writes files. Text findings only.
- Fails fast on permission errors rather than retrying with different tools.

Full guardrail list is in `agents/session-historian.md`.

## Dependencies

None. The agent depends only on `bash`, `find`, and `python3` (all present on macOS/Linux by default) plus the Claude Code / Codex transcript files the user has already been producing.

## Non-Goals

This module does **not**:

- Wire itself into `/xplan`, `/debug`, or `/compound`. Those integrations are follow-up work (see CCGM issue #276 for compound, and future integration PRs).
- Index or persist a summary of sessions. It retrieves and synthesizes on demand.
- Support Cursor (see "Supported Platforms" above).
- Cross-correlate sessions across different users or machines.

## Source

Ported from EveryInc/compound-engineering-plugin's `agents/research/session-historian.md` and companion `session-history-scripts/`. The CCGM port drops Cursor (Lucas does not use Cursor), folds skeleton/error extraction back into the agent itself (using native Read + Grep rather than additional Python scripts - keeping the surface minimal), and uses absolute `~/.claude/scripts/` paths matching CCGM's install convention rather than the plugin-relative paths the original assumes.
