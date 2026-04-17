---
name: compound
description: >
  After solving a non-trivial problem, extract a durable learning to docs/solutions/ in the current repo. Two modes - Full (parallel research subagents, strict schema, overlap check) and Lightweight (single-pass, direct from current conversation). Writes team-shared knowledge that /xplan and /review later re-inject as grounding. Runs a Discoverability Check so every repo's AGENTS.md or CLAUDE.md points at docs/solutions/.
  Triggers: compound, capture learning, write solution doc, post-mortem, retro, log this lesson, save this finding.
disable-model-invocation: true
---

# /compound - Compound Team Knowledge

Capture a learning from the current task into `docs/solutions/{category}/{slug}.md` in the repo being worked on. The file is committed with the rest of the codebase, greppable by teammates and agents, and re-injected as grounding context on future `/xplan` and `/review` runs via the `learnings-researcher` agent.

This is the team-shared counterpart to the personal `~/.claude/projects/.../memory/MEMORY.md` that the `self-improving` module writes. Both exist; neither replaces the other. Use personal memory for cross-repo patterns about your own working style. Use `docs/solutions/` for durable, per-repo facts that a teammate or a fresh agent session would want on hand.

## When to Run

Run `/compound` after:

- Shipping a fix for a non-trivial bug
- Resolving a tricky three-strike debugging session
- Confirming a non-obvious pattern, convention, or constraint that future work will need to respect
- Landing a decision that a future agent might accidentally unmake without knowing the prior context

Do NOT run for:

- Typo fixes, version bumps, or purely mechanical changes
- Speculative conclusions from a single observation (wait for the second occurrence)
- Anything already well-covered in the repo's AGENTS.md, CLAUDE.md, or existing `docs/solutions/` files

## Mode Selection

On invocation, parse `$ARGUMENTS` for a mode token:

- `mode:full` (or no mode token) - Full run with parallel research subagents
- `mode:light` - Lightweight single-pass, direct from current conversation

Full mode is the default. Use light mode when:

- The session already contains all the evidence needed (the bug and fix just shipped in this conversation)
- No prior `docs/solutions/` docs exist that plausibly overlap
- Speed matters more than completeness

If the user runs `/compound` with no arguments and the session is short or still has ambient context about the problem, prefer Full mode - the research passes often surface overlaps and related docs the agent has forgotten.

## Phase 1: Research (Full Mode)

Dispatch four subagents in parallel with the pass-paths-not-contents pattern (see `modules/subagent-patterns/rules/subagent-patterns.md`). Each returns a short structured report; the orchestrator merges them.

### Context Analyzer

Objective: Restate the problem in one paragraph and identify what would make this learning retrievable.

Inputs: the current conversation summary, the most recent diff (`git diff origin/main...HEAD`), and any linked issue or PR.

Deliverable:

- `problem`: one paragraph describing what went wrong or what was learned
- `trigger`: the specific reproduction steps or the conditions under which the pattern applies
- `surface_area`: which files, modules, or subsystems are implicated
- `tags_candidate`: 3-8 searchable tags, biased toward tags that already appear in other `docs/solutions/` docs in this repo

### Solution Extractor

Objective: Extract the fix (for bugs) or the durable rule (for knowledge) as something another agent could execute without the current conversation in context.

Inputs: the recent diff, the conversation trail that led to the fix.

Deliverable:

- `solution`: the fix or rule in imperative voice, 3-8 sentences max
- `why_it_works`: one paragraph on the mechanism, not just "because it passed tests"
- `prevention`: how to avoid hitting the same issue again (if bug) or when to apply the pattern (if knowledge)
- `anti_patterns`: common wrong turns to explicitly reject

### Related Docs Finder

Objective: Find existing `docs/solutions/` docs in this repo that plausibly overlap with the new learning.

Inputs: `tags_candidate`, `surface_area`, the one-paragraph problem.

Method: Use the native file-search tool (e.g., Glob) for `docs/solutions/**/*.md`. Use the native content-search tool (e.g., Grep) to search their frontmatter for matching `tags`, `module`, `component`, or `category`. Read the ones that match.

Deliverable:

- `overlap_candidates`: list of existing doc paths that might duplicate or relate to the new learning
- For each, a two-line justification

### Session Historian

Objective: Surface any prior conversation or agent log on this exact problem so the new doc can cite "we tried X before and it failed because Y".

Inputs: the repo name, the one-paragraph problem, any session-history module outputs if available.

Method: If the `session-history` module is installed, invoke its `session-historian` agent. Otherwise, grep the local agent log repo (`~/code/{log-repo-name}/{repo-name}/`) for entries mentioning the implicated files or error strings.

Deliverable:

- `prior_sessions`: list of prior session IDs or log entries touching this problem, with a one-line summary of what each concluded

## Phase 2: Classification and Scoring

Classify `problem_type`:

- `bug` - The learning is about a specific failure with a reproducible trigger. Example: "Supabase db push fails with circuit breaker after second retry."
- `knowledge` - The learning is a durable rule, convention, or constraint. Example: "Always quote PostgreSQL reserved words in migrations."

Both types use the same schema (see `references/schema.yaml`); the tag matters for retrieval - `learnings-researcher` can prefer bug docs when investigating a new failure, or knowledge docs when planning new work.

### Overlap Scoring

For each candidate in `overlap_candidates`, score across 5 dimensions. Each dimension is 0, 1, or 2:

| Dimension | 0 | 1 | 2 |
|-----------|---|---|---|
| **Problem** | Different problem | Related problem | Same underlying problem |
| **Root cause** | Different mechanism | Adjacent mechanism | Same root cause |
| **Solution** | Different fix | Partially overlapping fix | Same fix |
| **Files** | No shared files | Some shared files | Majority of files overlap |
| **Prevention** | Different preventive rule | Partially overlapping rule | Same preventive rule |

Total: 0-10. Decision:

- **8-10** - Update the existing doc in place. Do not create a new file.
- **5-7** - Create a new doc but set `related: [path-to-overlap]` in frontmatter, and add a one-line "See also" to the existing doc pointing at the new one.
- **0-4** - Create a new independent doc.

### Category Selection

Select the `category` from the standard list in `references/schema.yaml`. If the repo has already established repo-specific categories (look in `docs/solutions/README.md`), prefer those. Only add a new category when no standard category fits - and when you add one, update `docs/solutions/README.md` at the same time.

## Phase 3: Write or Update

### Path and Slug

Derive the slug from the learning title:

```
slug = kebab-case(title, max 60 chars)
path = docs/solutions/{category}/{slug}.md
```

Always use `.md`. Always lowercase, hyphen-separated slug. No date suffix in the filename - the `date` frontmatter field is the canonical source.

If the slug collides with an existing file, append `-2`, `-3`, etc. Do not overwrite silently.

### Frontmatter

Write frontmatter matching `references/schema.yaml`. Required fields: `title`, `date`, `problem_type`, `category`, `root_cause`, `tags`, `severity`. Optional fields: `module`, `component`, `files`, `related`.

### Body Structure

```markdown
---
{frontmatter}
---

# {title}

## Problem
{one paragraph; include reproduction steps for bugs}

## Root Cause
{one or two paragraphs; the "why it works" mechanism}

## Solution
{imperative-voice fix or rule, 3-8 sentences}

## Prevention
{how to avoid hitting this again, or when to apply this pattern}

## Anti-Patterns
{wrong turns the next agent might take; enumerate as bullets}

## References
{commit SHAs, PR links, issue numbers, related solution docs}
```

Keep each section short. If any section wants to grow past a page, the learning is probably two learnings - split it.

### Update vs Create

If overlap score was 8-10, update the existing doc:

- Merge new evidence into `Problem`, `Root Cause`, and `References`
- Bump `date` to today
- Append to `tags` without removing existing tags
- Do not rewrite the whole doc

Otherwise create a new doc.

## Phase 4: Discoverability Check

After writing, verify the learning is reachable:

1. Check `docs/solutions/README.md` exists. If not, create it with a short index pointing at the category directories. Use the bootstrap template below.

2. Check `AGENTS.md` or `CLAUDE.md` at the repo root for a pointer to `docs/solutions/`. Look for the phrase "docs/solutions" or the string "compound knowledge" or "prior learnings". If not found, offer to add one. Example pointer block:

   ```
   ## Prior Learnings

   Team-shared learnings live in `docs/solutions/`. Before planning a new
   feature or debugging an unfamiliar problem, check for a relevant prior
   with `rg <keyword> docs/solutions/` or let the `learnings-researcher`
   agent fan out at the start of /xplan or /review.
   ```

   Ask the user before writing this pointer. If they accept, inject the block into the file's most appropriate section (usually right after the top-level intro).

3. If the repo has a session log file for today (`~/code/{log-repo-name}/{repo}/YYYYMMDD/{agent-id}.md`), append a one-line entry noting the new learning and its path.

## Phase 5: Lightweight Mode

When invoked with `mode:light`, skip Phases 1 and 2 and write directly from the current conversation. Still:

- Apply the same frontmatter schema
- Select a `category` from the standard list
- Run the Discoverability Check at the end

Skip:

- The four-subagent fan-out
- The overlap scoring
- The related-docs merge

Use lightweight mode when the cost of a full research pass outweighs the value of catching overlaps. A single-repo agent fresh off fixing a 20-line bug usually knows the context well enough that full-mode research returns the same conclusions.

## Output

On completion, print:

```
Wrote: docs/solutions/{category}/{slug}.md
Mode: {full|light}
Problem type: {bug|knowledge}
Overlap: {none|related: <path>|updated: <path>}
Discoverability: {ok|pointer-added|pointer-offered}
```

If the user has an open PR or branch, suggest committing the new doc alongside the fix so the learning ships with the change that inspired it.

## Anti-Patterns

- **Speculative learnings.** One observation is not a pattern. Wait for the second hit, or write the doc and mark severity P3 with a clear "observed once" note.
- **Copy-paste from the conversation.** Extract the rule; do not paste the dialogue. If the next agent has to re-read a whole conversation to use the doc, the doc failed.
- **Skipping the overlap check in Full mode.** Duplicated learnings poison retrieval - two docs on the same problem make the agent see "this has been handled before" twice and dilute the signal.
- **Writing to a generic category.** `tooling` is not a category; `vite-build-config` is. Be specific; teammates grep by category name.
- **Second-person voice.** The doc is a spec for the next agent to execute. Use imperative voice: "Quote the identifier." Not: "You should quote the identifier."
- **Skipping Discoverability.** A doc no agent can find is indistinguishable from no doc.

## Bootstrap Template: docs/solutions/README.md

If the repo has no `docs/solutions/README.md`, write one with this shape:

```markdown
# Solutions

Team-shared learnings for this repo. Each subdirectory groups docs by
category. Every doc starts with YAML frontmatter matching the schema at
`modules/compound-knowledge/skills/compound/references/schema.yaml` in CCGM.

## Categories

- `build-errors/` - Build pipeline failures and their fixes
- `runtime-errors/` - Application-layer errors encountered in dev or prod
- `performance-issues/` - Profiling finds, slow queries, render bottlenecks
- `security-issues/` - Vulnerabilities, mis-configurations, secret handling
- `data-migrations/` - Schema changes, migration gotchas, rollback patterns
- `testing/` - Test infrastructure patterns and flake fixes
- `tooling/` - CI, linters, package managers, local dev environment
- `skill-design/` - Patterns for writing agent skills and commands
- `architecture/` - Boundaries, coupling, dependency direction choices
- `api-contracts/` - Public interface decisions and their rationale
- `deployment/` - Release, deploy, and rollback procedures
- `dev-environment/` - Local setup, editor config, tooling quirks

Add a new category only when no existing category fits, and update this
README in the same commit.

## Adding a Learning

Run `/compound` from Claude Code. It writes a frontmatter-tagged doc to
the right category and updates related prior docs as needed.

## Reading Learnings

At the start of `/xplan` and `/review`, the `learnings-researcher` agent
greps this directory by frontmatter tags and surfaces relevant priors as
planning or review context. Teammates without agents can grep directly -
tags and categories are designed for human browsing first.
```

## Source

Ported from EveryInc/compound-engineering-plugin's `ce-compound` skill. Adapted to CCGM voice, schema-first frontmatter, and the pass-paths-not-contents subagent pattern. Kept verbatim: the two-mode choice, the 5-dimension overlap scoring, the Discoverability Check.
