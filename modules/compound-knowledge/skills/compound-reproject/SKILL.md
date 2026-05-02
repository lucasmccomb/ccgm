---
name: compound-reproject
description: >
  Generate derived markdown artifacts from existing docs/solutions/ entries without mutating the source. Four projection types: qa (Q&A pairs), contradictions (disagreeing entries made explicit), summary (restructured alternative summary), outline (synthesized narrative outline). Output goes to docs/solutions/_reprojections/{type}-{timestamp}.md with traceable source IDs.
  Triggers: compound reproject, reproject learnings, synthesize solutions, generate qa from solutions, find contradictions in solutions.
disable-model-invocation: true
---

# /compound-reproject - Re-Project Team Knowledge

Read existing `docs/solutions/` entries and generate one derived markdown artifact. Re-projection turns a passive store into a thinking surface: the same facts, looked at from a different angle, reveal structure that accumulates invisibly in any large learning corpus.

Inspired by the observation that a knowledge base becomes most useful when you generate synthetic views over fixed data — not just accumulate and deduplicate.

## When to Run

Run `/compound-reproject` when:

- The `docs/solutions/` directory has grown large enough that no single agent can hold all entries in context at once (rough threshold: 20+ docs)
- You want Q&A study pairs to prepare for a complex feature area
- Two recent incidents feel related but no doc links them — contradictions mode surfaces the tension
- You are onboarding a new teammate or agent and want a narrative overview of a subsystem
- A periodic review (`/compound-refresh`) found no staleness but the corpus still feels hard to navigate

Do NOT run for:

- A corpus with fewer than five entries in the filter set — re-projection on too little data produces noise
- Generating new learnings from scratch — use `/compound` for that
- Writing back the output as new `docs/solutions/` entries — v1 is read-only; `--ingest` is future work

## Arguments

Parse `$ARGUMENTS` for the following tokens. All are optional except the `type` token, which must be provided.

### Required

`type:{value}` — The projection type. One of:

- `type:qa` — Q&A pairs
- `type:contradictions` — pairs of entries that disagree, made explicit
- `type:summary` — restructured alternative summary of the same facts
- `type:outline` — synthesized narrative outline tying entries together

### Optional

`tag:{value}` — Filter source entries to those whose frontmatter `tags` list includes this value. Repeat for multiple tags (any-match semantics). If omitted, all entries in `docs/solutions/` are candidates.

`n:{value}` — Maximum number of source entries to read. Default is 50. If the filtered set is smaller than N, use all of them.

`topic:{value}` — Free-text topic hint. When set, the skill uses this to bias entry selection toward entries whose title, tags, or body are most relevant to the topic. Applied after the `tag:` filter.

### Examples

```
/compound-reproject type:qa tag:supabase
/compound-reproject type:contradictions n:30
/compound-reproject type:outline topic:authentication
/compound-reproject type:summary tag:migrations tag:postgres
```

## Phase 1: Collect Source Entries

1. Use Glob to find all `docs/solutions/**/*.md`. Exclude `_reprojections/` subdirectory.
2. If `tag:` tokens are present, read each file's frontmatter and keep only entries whose `tags` list includes at least one of the specified values.
3. If `topic:` is set, rank the filtered set by relevance to the topic (title keyword match first, then body keyword match) and take the top N.
4. Otherwise, take up to N entries in filesystem order.
5. Record the `id` or derivable identifier for each source entry. If the frontmatter has no `id` field, use the repo-relative file path as the identifier.

Emit a source list before proceeding:

```
Source entries ({count} files):
- docs/solutions/{category}/{slug}.md
- ...
```

Stop if fewer than 2 entries remain after filtering. Inform the user and exit cleanly.

## Phase 2: Generate Re-Projection

Apply the generation procedure for the specified type. Read the full body of each source entry before generating — do not rely on frontmatter alone.

### type:qa

Produce a list of Q&A pairs grounded in the source entries. Each pair must:

- Phrase the question as a developer would ask it ("Why does X fail?", "When should I use Y?", "What is the rule for Z?")
- Answer in 2-5 sentences using only facts present in the source entries
- Cite the source entry path or slug in parentheses after the answer

Target: 3-5 Q&A pairs per source entry, deduplicated. Merge pairs whose questions are semantically identical.

Format:

```markdown
**Q: {question}**

A: {answer} *(source: {slug-or-path})*
```

### type:contradictions

Identify pairs of entries that make claims that conflict with each other. A contradiction is:

- Two entries that prescribe opposite actions for the same condition
- Two entries that diagnose the same symptom with different root causes
- One entry that marks something as safe or recommended and another that marks it as dangerous or discouraged

For each contradiction:

- State the tension in one sentence
- Quote the conflicting claims verbatim (one line each, with source)
- Note the likely resolution (newer entry wins, or both apply in different contexts, or genuine ambiguity)

If no contradictions are found, say so explicitly. Do not fabricate tensions.

Format:

```markdown
### Contradiction: {short label}

**Tension:** {one sentence}

- "{claim A}" — *{source-A}*
- "{claim B}" — *{source-B}*

**Likely resolution:** {one sentence}
```

### type:summary

Produce an alternative summary of the source entries, restructured by theme rather than chronological order. Group related entries under synthesized headings. Each group should:

- Open with a one-sentence synthesis of the theme
- Bullet the key facts from member entries
- Note dissent or nuance where entries within the group partially disagree

The goal is a document a new agent could read in place of the individual entries and arrive at the same working understanding.

Format:

```markdown
## {Synthesized Theme Heading}

{One-sentence synthesis.}

- {Key fact 1} *(source: {slug})*
- {Key fact 2} *(source: {slug})*
```

### type:outline

Produce a narrative outline that ties the source entries into a coherent story. Identify the arc: what class of problems does this corpus address, what sequence of understanding did the team build, what is the current state of knowledge, and what questions remain open?

Structure:

```markdown
## Overview

{2-3 sentence framing of what this set of learnings covers and why it exists.}

## How the Problem Space Developed

{Narrative paragraphs tracing key discoveries in roughly chronological order.}

## Current Consensus

{Bullet list of the firmest conclusions drawn from the corpus.}

## Open Questions

{Bullet list of unresolved tensions, known unknowns, or areas where the corpus is thin.}

## Source Entries

{Flat list of all source paths.}
```

## Phase 3: Write Output File

Derive the output path:

```
docs/solutions/_reprojections/{type}-{YYYYMMDD-HHMMSS}.md
```

Create `docs/solutions/_reprojections/` if it does not exist.

Write the output file with this header:

```markdown
---
reprojection_type: {type}
generated: {ISO 8601 UTC timestamp}
source_count: {N}
source_ids:
  - {path-or-id-1}
  - {path-or-id-2}
  ...
filter_tags: [{tags if any}]
filter_topic: "{topic if set}"
---

# {Type-title}: {Short description of the filter/topic}

{Body generated in Phase 2}
```

The `source_ids` frontmatter field is the traceable source citation required by the spec. Every re-projection is self-documenting.

## Phase 4: Report

Print a short summary:

```
Wrote: docs/solutions/_reprojections/{type}-{timestamp}.md
Type: {type}
Source entries: {count}
Filter: {tags/topic description, or "none"}
```

Do NOT suggest committing the re-projection to the repo unless the user asks. Re-projections are ephemeral work artifacts; whether to commit them is the user's call.

## Constraints

- **No mutation of source entries.** The skill reads `docs/solutions/` but never writes to it. Re-projections go only to `_reprojections/`.
- **No write-back as new entries in v1.** The `--ingest` flag (which would write the re-projection back as new `docs/solutions/` entries with `source: reprojection`) is not implemented in this version.
- **Single project only.** Cross-project re-projection (spanning multiple repos) is out of scope for v1.
- **Grounded output.** Every claim in the re-projection must trace to a specific source entry. Do not synthesize conclusions that no source entry supports.

## Anti-Patterns

- **Inventing claims.** If no source entry says X, the re-projection may not say X. Ground every assertion.
- **Re-projecting too few entries.** Fewer than 5 entries rarely produces a useful artifact. Check the source count before generating.
- **Generating without filtering when the corpus is large.** A 200-doc corpus without a tag or topic filter will produce an incoherent summary. Encourage the user to narrow the scope.
- **Treating the output as authoritative.** Re-projections are derived views, not new learnings. If a Q&A pair reveals a gap, the right follow-up is `/compound` to write a new entry — not to treat the re-projection itself as the learning.
- **Committing re-projections without user intent.** They are working artifacts. Some warrant committing; most do not. Never commit silently.

## Example Output Shapes

The following illustrates the shape of each type on a small corpus. These are not real entries.

### qa example

```markdown
---
reprojection_type: qa
generated: 2026-05-02T14:00:00Z
source_count: 4
source_ids:
  - docs/solutions/data-migrations/quote-reserved-words.md
  - docs/solutions/data-migrations/idempotent-migrations.md
  - docs/solutions/tooling/supabase-circuit-breaker.md
  - docs/solutions/testing/migration-validation.md
filter_tags: [supabase, migrations]
filter_topic: ""
---

# Q&A: supabase, migrations

**Q: Why do Supabase migrations fail on keywords like "position" or "order"?**

A: PostgreSQL reserves these identifiers. Using them unquoted in a column definition triggers a syntax error at parse time, before the migration runs. Always double-quote reserved words: `"position" integer`. *(source: quote-reserved-words)*

**Q: How do I make a migration safe to re-run?**

A: Use idempotent DDL patterns: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. For triggers, use `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`. *(source: idempotent-migrations)*

**Q: What happens if I retry a failing `db push` more than once?**

A: The Supabase connection pooler circuit breaker trips after repeated auth failures. Once tripped, all CLI database operations fail for a 5-30 minute cooldown. Re-authenticate with `npx supabase login` and wait before retrying once. *(source: supabase-circuit-breaker)*
```

### contradictions example

```markdown
---
reprojection_type: contradictions
generated: 2026-05-02T14:05:00Z
source_count: 8
source_ids:
  - docs/solutions/deployment/wrangler-pages-deploy.md
  - docs/solutions/deployment/cloudflare-git-integration.md
  ...
filter_tags: [cloudflare, deployment]
filter_topic: ""
---

# Contradictions: cloudflare, deployment

### Contradiction: wrangler pages deploy vs. git integration

**Tension:** One entry recommends using `wrangler pages deploy` to ship quickly; another marks it as creating an unrecoverable direct-upload project.

- "Use `wrangler pages deploy <name>` to get the site live immediately." — *wrangler-pages-deploy*
- "Never run `wrangler pages deploy <new-project-name>` for a project that should auto-deploy; it creates a direct-upload project Cloudflare cannot convert to Git integration." — *cloudflare-git-integration*

**Likely resolution:** The newer entry (*cloudflare-git-integration*, dated 2026-04-20) supersedes the older. The older entry predates the discovery that Git integration cannot be retrofitted.
```

### summary example

```markdown
---
reprojection_type: summary
generated: 2026-05-02T14:10:00Z
source_count: 6
source_ids:
  - docs/solutions/data-migrations/quote-reserved-words.md
  - docs/solutions/data-migrations/idempotent-migrations.md
  - docs/solutions/data-migrations/on-conflict-requires-unique.md
  - docs/solutions/tooling/supabase-circuit-breaker.md
  - docs/solutions/testing/migration-validation.md
  - docs/solutions/testing/local-migration-test.md
filter_tags: [supabase, migrations]
filter_topic: ""
---

# Summary: supabase, migrations

## DDL Safety Rules

PostgreSQL has reserved identifiers that cause parse-time errors if used unquoted.

- Always double-quote reserved words (`"position"`, `"order"`, `"user"`) in column definitions. *(source: quote-reserved-words)*
- Use idempotent DDL variants (`IF NOT EXISTS`, `CREATE OR REPLACE`) so migrations can be re-run without failure. *(source: idempotent-migrations)*
- `ON CONFLICT` requires a unique constraint on the conflict column; adding one mid-migration is a separate step. *(source: on-conflict-requires-unique)*

## CLI Safety Rules

The Supabase connection pooler has a circuit breaker that trips on repeated auth failures.

- Never retry a failing `db push` more than once without re-authenticating. *(source: supabase-circuit-breaker)*
- Use `supabase migration up` (incremental) over `db reset` (destructive) during development. *(source: local-migration-test)*
```

### outline example

```markdown
---
reprojection_type: outline
generated: 2026-05-02T14:15:00Z
source_count: 6
source_ids:
  - docs/solutions/data-migrations/quote-reserved-words.md
  - docs/solutions/data-migrations/idempotent-migrations.md
  - docs/solutions/data-migrations/on-conflict-requires-unique.md
  - docs/solutions/tooling/supabase-circuit-breaker.md
  - docs/solutions/testing/migration-validation.md
  - docs/solutions/testing/local-migration-test.md
filter_tags: [supabase, migrations]
filter_topic: ""
---

# Outline: supabase, migrations

## Overview

This corpus covers hard-won knowledge about running Supabase/PostgreSQL migrations safely. The six entries span DDL correctness, CLI safety, and local validation workflow. They accumulated over roughly three months of incident-driven learning.

## How the Problem Space Developed

The earliest entry (*quote-reserved-words*, 2026-01-10) captures the first incident: a migration failed because `position` is a PostgreSQL reserved word. This triggered a broader audit of identifiers in existing schemas.

The idempotency and ON CONFLICT entries followed as the team ran migrations in CI where partial failures and retries are common. The circuit breaker entry was the costliest: a developer retried a failing `db push` six times, tripped the pooler, and blocked the team from running any migration for forty minutes.

The two testing entries represent the team's response — a local validation checklist that catches DDL errors before they reach the pooler.

## Current Consensus

- Quote all PostgreSQL reserved words in column definitions.
- Use idempotent DDL patterns everywhere; treat non-idempotent migrations as a code smell.
- Never retry a failing CLI migration command without re-authenticating first.
- Validate migrations locally with `supabase migration up` before pushing.

## Open Questions

- No entry yet covers rollback procedures for destructive migrations (DROP COLUMN, DROP TABLE).
- The circuit breaker cooldown time (5-30 minutes) is stated as a range; the exact duration is unknown.

## Source Entries

- docs/solutions/data-migrations/quote-reserved-words.md
- docs/solutions/data-migrations/idempotent-migrations.md
- docs/solutions/data-migrations/on-conflict-requires-unique.md
- docs/solutions/tooling/supabase-circuit-breaker.md
- docs/solutions/testing/migration-validation.md
- docs/solutions/testing/local-migration-test.md
```

## Source

Added in CCGM #439. Inspired by Karpathy on LLM knowledge bases (Sequoia interview, 2026-04-29): "I always like feel like I gain insight... it's really just a lot of prompts for me to do synthetic data generation kind of over fixed data." Re-projection is the CCGM implementation of that move: the same docs, looked at from a different angle.
