# Compound Knowledge

Team-shared learnings in `docs/solutions/`. After solving a non-trivial problem, `/compound` writes a structured markdown doc that later `/xplan` and `/review` runs re-inject as grounding context via the `learnings-researcher` agent.

## Team-Shared vs Personal Memory

CCGM ships two reflection stores; they are complementary, not competing.

| | `self-improving` (personal) | `compound-knowledge` (team) |
|---|---|---|
| **Location** | `~/.claude/projects/.../memory/MEMORY.md` | `docs/solutions/` in the working repo |
| **Committed to git** | No | Yes |
| **Scope** | Cross-repo, per-user | Per-repo, shared |
| **What to capture** | User preferences, cross-repo gotchas, working style | Repo-specific bugs, patterns, conventions |
| **Retrieval** | Auto-loaded at session start | Pulled by `learnings-researcher` on demand |

Use personal memory for things like "user prefers single bundled PRs" or "Tailwind v4 drops `cursor: pointer` - remember this across projects." Use team knowledge for things like "Supabase migrations in this repo quote all reserved words by convention" or "the Vite build in `apps/web` requires a CSS import in this specific order."

A learning can plausibly go in either store. When in doubt, ask: "would a teammate who never worked with this agent want to find this?" If yes, write it to `docs/solutions/`. If it is really about your own working style, write it to personal memory.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/compound/SKILL.md` | `skills/compound/SKILL.md` | `/compound` - capture a new learning |
| `skills/compound/references/schema.yaml` | `skills/compound/references/schema.yaml` | YAML schema for doc frontmatter |
| `skills/compound-refresh/SKILL.md` | `skills/compound-refresh/SKILL.md` | `/compound-refresh` - maintenance pass |
| `agents/learnings-researcher.md` | `agents/learnings-researcher.md` | Retrieval agent for `/xplan`, `/review` |

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/skills/compound/references
mkdir -p ~/.claude/skills/compound-refresh
mkdir -p ~/.claude/agents

cp modules/compound-knowledge/skills/compound/SKILL.md \
   ~/.claude/skills/compound/SKILL.md

cp modules/compound-knowledge/skills/compound/references/schema.yaml \
   ~/.claude/skills/compound/references/schema.yaml

cp modules/compound-knowledge/skills/compound-refresh/SKILL.md \
   ~/.claude/skills/compound-refresh/SKILL.md

cp modules/compound-knowledge/agents/learnings-researcher.md \
   ~/.claude/agents/learnings-researcher.md
```

## Per-Repo Bootstrap

`compound-knowledge` writes to the repo being worked on, not to CCGM or to `~/.claude/`. Each consuming repo needs two small things before the loop is fully discoverable:

1. `docs/solutions/README.md` - an index describing categories and how to add a learning. The `/compound` skill offers to write this automatically on first use.

2. A pointer block in the repo's `AGENTS.md` or `CLAUDE.md`. Example:

   ```markdown
   ## Prior Learnings

   Team-shared learnings live in `docs/solutions/`. Before planning a new
   feature or debugging an unfamiliar problem, check for relevant priors.
   The `learnings-researcher` agent surfaces them automatically at the
   start of /xplan and /review.
   ```

The `/compound` skill runs a Discoverability Check on every invocation and offers to add this pointer if missing. You do not need to pre-seed either file - the skill self-bootstraps on first use. Pre-seeding is only worth it when onboarding a new repo or running a large `/xplan` before the first compound.

## Usage

### Capture a learning

```
/compound
/compound mode:light
```

Run after shipping a non-trivial fix or confirming a durable pattern. The skill interviews the session, classifies the problem, scores overlap with existing docs, and writes or updates the corresponding file.

Full mode (default) dispatches four parallel research subagents (Context Analyzer, Solution Extractor, Related Docs Finder, Session Historian). Lightweight mode skips the fan-out and writes directly from the current conversation.

### Maintain the store

```
/compound-refresh
/compound-refresh mode:autofix
/compound-refresh mode:report-only
```

Monthly or after a major refactor. Classifies each existing doc as Keep / Update / Consolidate / Replace / Delete based on file mtime, referenced-code existence, and overlap with newer docs.

### Retrieve priors

The `learnings-researcher` agent is a drop-in, invoked by other skills. It is not wired into `/xplan` or `/review` by this PR - those integrations are tracked separately (see CCGM issues #268 and #277). To use it manually from any skill or command:

```
Dispatch the learnings-researcher agent with:
- task_summary: <one paragraph>
- files_hint: [<paths>]
- tags_hint: [<tags>]
```

The agent returns structured blocks listing matching priors with excerpts.

## Dependencies

- `skill-authoring` - compound and compound-refresh follow the skill-authoring discipline (reference files via backticks, imperative voice, one command per Bash call, etc.)

No runtime dependencies beyond the module system.

## Non-Goals

This module does **not**:

- Replace `self-improving`. Personal memory and team knowledge are complementary. `self-improving` stays installed alongside this module.
- Auto-wire itself into `/xplan` or `/review`. Those integrations ship as follow-up PRs (#268 for two-stage review prompt templates; #277 for the unified review orchestrator).
- Install `docs/solutions/` in any repo. The skill bootstraps per-repo on first use - CCGM itself does not touch consuming repos.

## Source

Ported from EveryInc/compound-engineering-plugin. The original ships `ce-compound`, `ce-compound-refresh`, and `agents/research/learnings-researcher.md` as part of a larger compound-engineering loop. CCGM adopts the keystone piece - the learnings loop - while leaving the rest of that plugin's surface for separate evaluation.

Adaptations from the source:

- Mode token names match the CCGM skill-authoring convention (`mode:full`, `mode:light`, `mode:autofix`, `mode:report-only`)
- Frontmatter schema is extracted to `references/schema.yaml` so the skill body does not carry it in every invocation
- The pass-paths-not-contents subagent dispatch pattern is applied to the four Phase-1 research subagents
- The `learnings-researcher` agent lives under `agents/` (per the `agents/` directory convention added in CCGM #273) rather than inside a skill directory
