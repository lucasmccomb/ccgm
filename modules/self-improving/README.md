# self-improving

Meta-learning system that triggers reflection at key moments and captures reusable patterns to a structured, schema-validated, queryable learnings store.

## What It Does

Combines rules, commands, hooks, and a JSONL learnings store to create an active self-improvement loop:

### Rules (Always Active)

The reflection loop methodology with prescriptive trigger points:

1. **Extract Experience** - After each task, identify what worked, what failed, and what surprised you
2. **Identify Patterns** - Distill specific experiences into general reusable rules
3. **Update Memory** - Log confirmed patterns to `~/.claude/learnings/{project-slug}/learnings.jsonl` via `ccgm-learnings-log`
4. **Consolidate** - Periodically dedup, retire stale anchors, and reconcile with the legacy MEMORY.md

Includes a reflection checklist, mandatory trigger points, type vocabulary, and confidence tracking.

### Learnings Store

- **JSONL per project** at `~/.claude/learnings/{project-slug}/learnings.jsonl`. Append-only; schema-validated; sanitizer neutralizes instruction-like patterns on write.
- **Confidence decay**: effective confidence = `base * 0.5^(age_days / half_life_days)`, with `uses` boosting and `contradictions` cutting. Default half-life 90 days.
- **Staleness**: `last_verified` older than 180 days is excluded by default; `files[]` anchors enable filesystem-aware staleness checks.
- **Injection filter**: search results are ranked and capped by token budget (default ~2000 tokens) before going into a preamble.
- **Cross-project search**: opt-in via `ccgm-learnings-log config cross-project on`.

Full schema and model: `rules/learnings-store.md`.

### Commands

| Command | Description |
|---------|-------------|
| `/reflect` | Run the reflection checklist inline; dual-writes learnings to JSONL and MEMORY.md index |
| `/consolidate` | Review the JSONL store and legacy MEMORY.md; dedup, deprecate stale, reconcile |
| `/retro` | Generate a retrospective from git history over a time window (default 7d); supports `/retro global` across all repos |

### Bin

| Tool | Description |
|------|-------------|
| `ccgm-learnings-log` | Append a learning, reinforce (`verify`), record contradictions, deprecate, or configure |
| `ccgm-learnings-search` | Rank + filter + token-cap learnings (formats: preamble, markdown, jsonl) |

### Hooks

| Hook | Event | Trigger |
|------|-------|---------|
| `reflection-trigger.py` | PostToolUse:Bash | Injects reflection reminder after `gh pr merge` or `gh issue close` |
| `precompact-reflection.py` | PreCompact | Reminds agent to capture patterns before context compaction |

## Migration from MEMORY.md

The learnings store runs in parallel with the legacy `~/.claude/projects/*/memory/MEMORY.md` flow. `/reflect` dual-writes: structured entries to the JSONL (source of truth), pointer lines to MEMORY.md (rendered index). No automatic import of legacy entries - port manually via `ccgm-learnings-log --from-json ...` if worth keeping.

The JSONL wins any disagreement. MEMORY.md is treated as a derived view that can be regenerated.

## Cross-Module Integration

This module works best alongside:

- **session-logging** - Mandatory trigger #8 prompts post-merge reflection
- **systematic-debugging** - Three-strike rule triggers debugging pattern capture
- **common-mistakes** - Living document that self-improving feeds new entries into
- **compound-knowledge** (team-shared) - personal JSONL vs team `docs/solutions/`; related but non-overlapping

These are soft references, not hard dependencies. The self-improving module works standalone; the cross-module triggers add automation.

## Manual Installation

```bash
# Rules
cp rules/self-improving.md ~/.claude/rules/self-improving.md
cp rules/learnings-store.md ~/.claude/rules/learnings-store.md

# Commands
cp commands/reflect.md ~/.claude/commands/reflect.md
cp commands/consolidate.md ~/.claude/commands/consolidate.md
cp commands/retro.md ~/.claude/commands/retro.md

# Bin (executable)
mkdir -p ~/.claude/bin
cp bin/ccgm-learnings-log ~/.claude/bin/ccgm-learnings-log
cp bin/ccgm-learnings-search ~/.claude/bin/ccgm-learnings-search
chmod +x ~/.claude/bin/ccgm-learnings-log ~/.claude/bin/ccgm-learnings-search

# Lib (imported by bin scripts)
mkdir -p ~/.claude/lib
cp lib/learnings_store.py ~/.claude/lib/learnings_store.py

# Hooks
cp hooks/reflection-trigger.py ~/.claude/hooks/reflection-trigger.py
cp hooks/precompact-reflection.py ~/.claude/hooks/precompact-reflection.py

# Settings (merge into existing settings.json)
# Use jq or manually add the hook entries from settings.partial.json

# Optional: add ~/.claude/bin to PATH
export PATH="$HOME/.claude/bin:$PATH"
```

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/self-improving.md` | rule | Reflection loop, trigger points, checklist, learnings store usage, confidence tracking |
| `rules/learnings-store.md` | rule | Full schema, type vocabulary, decay formula, sanitizer, migration notes |
| `commands/reflect.md` | command | Inline structured reflection workflow; dual-writes JSONL + MEMORY.md |
| `commands/consolidate.md` | command | Learnings maintenance via subagent (dedup, deprecate, reconcile) |
| `commands/retro.md` | command | Windowed git-history retrospective; surfaces candidates for /reflect |
| `bin/ccgm-learnings-log` | script | CLI to append, verify, contradict, deprecate, configure learnings |
| `bin/ccgm-learnings-search` | script | CLI to search, rank, filter, and inject learnings |
| `lib/learnings_store.py` | lib | Shared library (schema, decay math, sanitizer, search) |
| `hooks/reflection-trigger.py` | hook | PostToolUse detection for PR merge and issue close |
| `hooks/precompact-reflection.py` | hook | PreCompact reminder to capture patterns |
| `settings.partial.json` | config | Hook registration (PostToolUse:Bash, PreCompact) |
| `tests/test_learnings_store.py` | test | Unit tests for store (schema, sanitizer, decay, search, updates) |

## Running Tests

```bash
python3 modules/self-improving/tests/test_learnings_store.py
```

Tests run in isolation (tempdir via `CCGM_LEARNINGS_DIR` env var) and never touch the real store.
