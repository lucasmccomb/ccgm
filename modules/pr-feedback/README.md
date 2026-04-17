# PR Feedback Resolver

Structured resolver for PR review comments. `/resolve-pr-feedback` fetches unresolved review threads via GraphQL, triages new vs already-handled, and - when 3+ new comments land - runs cluster analysis across 11 fixed concern categories before dispatching parallel resolver subagents.

## Why Cluster

A PR with ten review comments usually encodes two or three real concerns. Dispatching ten one-off fixes churns files, produces ten tiny commits, and still leaves the systemic concern un-addressed. Clustering by concern category + spatial proximity surfaces the systemic view before any code is touched.

The cluster-gate only activates at 3+ new threads. Below that, overhead of categorization is not justified - the skill dispatches per-thread.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/resolve-pr-feedback/SKILL.md` | `skills/resolve-pr-feedback/SKILL.md` | `/resolve-pr-feedback` - orchestrator |
| `skills/resolve-pr-feedback/references/cluster-categories.md` | `skills/resolve-pr-feedback/references/cluster-categories.md` | 11 fixed categories + proximity + autofix routing |
| `scripts/get-pr-comments` | `scripts/get-pr-comments` | GraphQL fetcher for unresolved threads |
| `agents/pr-comment-resolver.md` | `agents/pr-comment-resolver.md` | Fan-out subagent that implements one cluster |

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/skills/resolve-pr-feedback/references
mkdir -p ~/.claude/scripts
mkdir -p ~/.claude/agents

cp modules/pr-feedback/skills/resolve-pr-feedback/SKILL.md \
   ~/.claude/skills/resolve-pr-feedback/SKILL.md

cp modules/pr-feedback/skills/resolve-pr-feedback/references/cluster-categories.md \
   ~/.claude/skills/resolve-pr-feedback/references/cluster-categories.md

cp modules/pr-feedback/scripts/get-pr-comments \
   ~/.claude/scripts/get-pr-comments
chmod +x ~/.claude/scripts/get-pr-comments

cp modules/pr-feedback/agents/pr-comment-resolver.md \
   ~/.claude/agents/pr-comment-resolver.md
```

## Requirements

- `gh` CLI, authenticated (`gh auth login`)
- `jq` on the PATH
- Bash 4+

## Usage

### Standard run

```
/resolve-pr-feedback pr:123
```

Fetches unresolved threads for PR 123 in the current repo, triages, clusters if 3+ new threads, and dispatches resolver subagents in parallel after confirmation.

### Modes

```
/resolve-pr-feedback pr:123 mode:autofix       # no prompts; write run artifact
/resolve-pr-feedback pr:123 mode:report-only   # fetch + triage + cluster, no dispatch
/resolve-pr-feedback pr:123 mode:headless      # skill-to-skill composition
```

### Filters

```
/resolve-pr-feedback pr:123 cluster:force      # cluster even for 1-2 threads
/resolve-pr-feedback pr:123 cluster:skip       # per-thread dispatch even for 3+
/resolve-pr-feedback pr:123 only:1,3,5         # only listed thread indices
/resolve-pr-feedback pr:123 repo:owner/name    # override repo
```

### Fetcher standalone

The fetcher script is useful on its own when you want to inspect thread state:

```bash
# JSON (machine-consumable)
bash modules/pr-feedback/scripts/get-pr-comments 123 --state unresolved

# Markdown (human-readable)
bash modules/pr-feedback/scripts/get-pr-comments 123 --format markdown
```

## Cluster Categories

The 11 fixed categories are:

`error-handling`, `validation`, `type-safety`, `testing`, `naming`, `style-consistency`, `architecture`, `performance`, `security`, `documentation`, `other`.

Each has a definition, sample reviewer phrases, and an autofix-class mapping (`safe_auto` / `gated_auto` / `manual` / `advisory`). See `skills/resolve-pr-feedback/references/cluster-categories.md`.

Clusters group threads by category and spatial proximity: same file, shared subtree (e.g., `src/auth/` but not the repo root), or cross-cutting across 3+ files. A cross-cutting cluster is a systemic finding, not N one-off fixes.

## Dependencies

- `skill-authoring` - skills follow the authoring discipline (reference files via backticks, imperative voice, one command per Bash call)
- `subagent-patterns` - cluster fan-out uses pass-paths-not-contents; completion statuses use the four-state protocol

## Non-Goals

This module does **not**:

- Replace human taste on architectural comments. `manual` clusters are batched for explicit human decision, not auto-applied.
- Auto-dispatch `security`-category fixes. Security always requires at least one human-in-the-loop confirmation.
- Resolve threads with no code change on record. Replies are cheap; closing a thread without a fix is dishonest.
- Manage PR workflow beyond reviews. For creating PRs, see `/pr` and `/cpm` in `commands-core`. For review orchestration beyond comments, see the `ce-review` module.

## Source

Ported from EveryInc/compound-engineering-plugin's `skills/resolve-pr-feedback/SKILL.md` and `scripts/get-pr-comments`. Adaptations:

- Bundled as a standalone CCGM module rather than part of a larger compound-engineering plugin
- Mode token names match CCGM's skill-authoring convention (`mode:interactive`, `mode:autofix`, `mode:report-only`, `mode:headless`)
- Cluster categories and autofix routing extracted to `references/cluster-categories.md` so the skill body does not carry them in every invocation
- Resolver agent lives under `agents/` per CCGM's agents-directory convention
- Four-state completion protocol (`DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`) for subagent returns
