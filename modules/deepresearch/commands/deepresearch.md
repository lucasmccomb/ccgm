---
description: Deep multi-channel research using Exa neural search across many sources
allowed-tools: Bash, Read, Write, Glob, Grep, AskUserQuestion
argument-hint: <topic> [--depth full|standard|lite] [--output <path>] [--plan-dir <path>] [--extend <prior-research-path>]
---

# /deepresearch - Deep Multi-Query Research (Exa)

Generates diverse search queries from a topic, fans them out in parallel through Exa's neural search API, and synthesizes the results (with full page contents, not snippets) into a structured `research.md`.

**Can be used:**
- Standalone: `/deepresearch "dark mode browser extensions"` writes to `~/code/docs/research/`
- From `/xplan` Phase 1
- From any skill that needs deep research

**Prerequisites:**
- `EXA_API_KEY` set in the shell environment. Sign up at https://exa.ai (free tier: 1000 searches/mo).
- Python 3 with `httpx`. The CLI prefers `~/.research-tools-venv/bin/python` if present, otherwise system `python3`.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments

Extract from arguments:
- **Topic** (required): the research subject
- **`--depth <preset>`**: `lite` (3 queries), `standard` (5 queries, default), or `full` (7 queries)
- **`--output <path>`**: custom output path for `research.md` (must end in `.md`)
- **`--plan-dir <path>`**: when called from `/xplan`, the plan directory; `research.md` is written there
- **`--extend <path>`**: accepted for compat, gracefully ignored

If no topic is provided, use `AskUserQuestion` to ask what to research.

### Determine output path

```
if --plan-dir:    output = {plan-dir}/research.md
elif --output:    output = {output}
else:             slug = kebab-case(topic); mkdir -p ~/code/docs/research/{slug}; output = ~/code/docs/research/{slug}/research.md
```

---

## Phase 1: Determine Depth

If `--depth` was passed (e.g., from xplan), use it directly.

Otherwise, ask the user with `AskUserQuestion`:

> "What level of research should I run?"

| Option | Queries | Time | Best for |
|--------|---------|------|----------|
| Standard (recommended) | 5 | ~1-2 min | Most research tasks |
| Full | 7 | ~2-3 min | New domains, comparative research |
| Lite | 3 | ~1 min | Quick scoping |

---

## Phase 2: Generate Diverse Search Queries

You generate the queries directly. Do NOT call a separate model for this. Write `N` diverse queries (where `N` is the depth count) that approach the topic from different angles. Mix:
- A broad overview query
- A technical / how-it-works query
- A competitive / comparison query
- A practical / tutorial query
- A risk / pitfall query (for `standard` and above)
- A pricing / business-model query (for topics where commercial context matters)
- An academic / paper query (for technical / research topics, in `full` only)

Each query should be a self-contained sentence or noun phrase that a search engine would handle well. Avoid overlong compound queries (>120 chars) — Exa handles natural language but tighter queries return better results.

Example for topic "browser-based presentation apps":
```
1. browser-based presentation apps comparison
2. how SPA presentation apps handle slide rendering and export to PDF
3. Reveal.js vs Slidev vs Spectacle technical tradeoffs
4. building a presentation editor with React and PDF export
5. accessibility issues in browser-based slide tools
```

Hold these in memory. Pass each as a `--query` flag in the next phase.

---

## Phase 3: Run the Exa Pipeline

Run the CLI with each generated query as a `--query` argument. Use a Bash timeout of 120000ms (2 minutes); Exa is fast.

The CLI prefers `~/.research-tools-venv/bin/python` if it exists; otherwise use system `python3`.

**Standalone mode:**

```bash
PYTHON=~/.research-tools-venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3
"$PYTHON" ~/.claude/bin/deepresearch-cli.py \
  --topic "TOPIC" \
  --output "OUTPUT_PATH" \
  --depth DEPTH \
  --query "Q1" \
  --query "Q2" \
  --query "Q3"
```

**xplan mode (with `--plan-dir`):**

```bash
"$PYTHON" ~/.claude/bin/deepresearch-cli.py \
  --topic "TOPIC" \
  --output "OUTPUT_PATH" \
  --plan-dir "PLAN_DIR" \
  --depth DEPTH \
  --query "Q1" \
  --query "Q2" ...
```

**Bash tool configuration:**
- `timeout: 120000` (2 minutes)
- If exit code is non-zero, surface the stderr to the user verbatim. Common failures are listed below.

**Expected stderr (informational):**
```
[start] deepresearch-cli.py (Exa)
[start] Topic:  ...
[start] Depth:  standard (5 queries)
[search] Running 5 parallel Exa queries...
[search] Retrieved 25 results across 5 queries.
[done] Pipeline complete in 3.4s (5 queries, 25 results, 23 sources)
```

**Failure modes:**
- `ERROR: EXA_API_KEY not set` — tell the user to set it in their shell rc per `~/.claude/commands/deepresearch.md` setup. Do not retry.
- `ERROR: Exa rejected the API key (401)` — key invalid or revoked. Tell the user to regenerate at https://exa.ai/dashboard. Do not retry.
- `WARN: Exa HTTP 429 ...` — rate limited. The CLI continues with partial results. Tell the user.
- `WARN: Exa timed out ...` — the CLI returns partial results. Surface the warning but continue with synthesis.

**Expected stdout: a JSON envelope** with these fields:
- `topic` — the research topic
- `queries` — the list of queries that were run
- `batches` — list of `{query, results: [{url, title, text, score, ...}], error}` per query
- `sources` — deduplicated list of `- title - url` entries
- `depth` — depth preset
- `total_results` — count of valid results across all queries
- `output_path` — resolved path where `research.md` should be written
- `plan_dir` — resolved plan directory or null
- `elapsed_seconds` — pipeline duration
- `engine` — `"exa"`

---

## Phase 4: Synthesize research.md

Parse the JSON from stdout. For each batch, the `results[].text` field contains up to 6000 characters of clean, full page content (not a 200-char snippet). Synthesize aggressively across batches: cross-reference claims, note contradictions, weight by source quality, and call out high-confidence findings.

Write the file at `output_path` using this exact structure:

```markdown
# Research: {topic}

## Executive Summary
{2-3 paragraphs synthesizing the key findings. Lead with the most important insight.
Note overall confidence based on source quality and corroboration across batches.}

## Contextual Model
{The mental framework for thinking about this problem. Key principles that should guide decisions.}

## Problem Space
{Domain analysis, user pain points, jobs-to-be-done. What does this space look like?}

## Technical Landscape
{Architecture patterns, technology options, scalability considerations, relevant tools/libraries.}

## Competitive Landscape
{Existing solutions, feature gaps, differentiation opportunities, pricing patterns when relevant.}

## Key Insights
{Numbered list of the 5-10 most important findings:
1. **Finding title** - description. (Confidence: High/Medium/Low based on source count and quality)}

## Risk Register
| Risk | Severity | Mitigation |
|------|----------|------------|
{At least 3 rows covering technical, market, and execution risks}

## Sources
{Bulleted list of all source URLs from the JSON `sources` array. Group by credibility:
Official/Academic first, then Industry/News, then Blogs/Community.}
```

---

## Phase 5: Report

After writing `research.md`, report to the user:
- Output path
- Executive Summary (2-3 sentences)
- Key Insights list (numbered)
- Number of sources collected
- Pipeline time (`elapsed_seconds`)

If standalone (not called from xplan), suggest:
- "Run `/xplan` with this research to plan an implementation"
