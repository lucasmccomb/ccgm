---
description: Deep multi-query research using parallel Exa MCP tool calls
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion
argument-hint: <topic> [--depth full|standard|lite] [--output <path>] [--plan-dir <path>] [--extend <prior-research-path>]
---

# /deepresearch - Deep Multi-Query Research (Exa MCP)

Generate diverse search queries from a topic, run them in parallel via the Exa MCP server, and synthesize the results (with full page contents, not snippets) into a structured `research.md`.

**Can be used:**
- Standalone: `/deepresearch "dark mode browser extensions"` writes to `~/code/docs/research/`
- From `/xplan` Phase 1
- From any skill that needs deep research

**Prerequisites:**
- Exa MCP server registered in `mcp.json`. The expected entry is:
  ```json
  "exa": {
    "command": "npx",
    "args": ["-y", "exa-mcp-server"],
    "env": { "EXA_API_KEY": "${EXA_API_KEY}" }
  }
  ```
- `EXA_API_KEY` set in the shell environment (https://exa.ai - free tier covers 1000 searches/mo).
- After adding the entry, restart Claude Code so the MCP server loads.

If the Exa MCP tools (`web_search_exa` etc.) are not available in this session, stop immediately and tell the user how to set them up. Do not fall back to `/research` or `WebSearch` silently.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments

Extract from `$ARGUMENTS`:
- **Topic** (required): the research subject
- **`--depth <preset>`**: `lite` (3 queries), `standard` (5 queries, default), or `full` (7 queries)
- **`--output <path>`**: custom output path for `research.md` (must end in `.md`)
- **`--plan-dir <path>`**: when called from `/xplan`, the plan directory; `research.md` is written there
- **`--extend <path>`**: accepted for compatibility, gracefully ignored

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
| Standard (recommended) | 5 | ~30s-1m | Most research tasks |
| Full | 7 | ~1-2m | New domains, comparative research |
| Lite | 3 | ~20s | Quick scoping |

---

## Phase 2: Generate Diverse Queries

Generate `N` diverse queries directly (where `N` is the depth count). Mix angles:
- A broad overview query
- A technical / how-it-works query
- A competitive / comparison query
- A practical / tutorial query
- A risk / pitfall query (`standard` and above)
- A pricing / business-model query (when commercial context matters)
- An academic / paper query (technical/research topics, `full` only)

Each query should be a self-contained sentence or noun phrase. Avoid overlong compound queries (>120 chars) - tighter queries return better results from Exa.

Hold these queries; pass each to the MCP search tool in the next phase.

---

## Phase 3: Run Parallel Exa MCP Searches

Issue **all `N` Exa MCP tool calls in a single assistant message** so they run concurrently. The expected tool name is `web_search_exa` (the default exposed by `exa-mcp-server`). Use `numResults: 5` per query.

For topic types where Exa exposes specialized tools, route accordingly:

| Topic shape | Tool to use | Notes |
|-------------|-------------|-------|
| General research | `web_search_exa` | Default for most queries |
| Academic / scientific | `research_paper_search_exa` | If `full` depth on a research-heavy topic, route 1-2 of the queries here |
| Open-source / dev tooling | `github_search_exa` | Optional supplement; do not replace `web_search_exa` |
| Specific company / product | `company_research_exa` | When the topic is a single named company |
| Encyclopedic background | `wikipedia_search_exa` | Optional - Exa already indexes Wikipedia; only use when you specifically need Wikipedia framing |

**If the Exa MCP tools are unavailable** in this session (the tools do not appear in the available tool list), STOP and tell the user the MCP server is not loaded. Reference the prerequisites above. Do not silently fall back.

For each result that comes back, you have:
- `url`, `title`, `text` (full page content), `publishedDate`, `score`

Aggregate the results in memory across queries.

---

## Phase 4: Synthesize research.md

Cross-reference claims across queries. Note contradictions. Weight by source quality (official docs > peer-reviewed > industry > blogs). Call out high-confidence findings explicitly.

Write the file at the resolved `output_path` using this exact structure:

```markdown
# Research: {topic}

## Executive Summary
{2-3 paragraphs synthesizing the key findings. Lead with the most important insight.
Note overall confidence based on source quality and corroboration.}

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
{Bulleted list of all source URLs deduplicated across queries. Group by credibility:
Official/Academic first, then Industry/News, then Blogs/Community.}
```

---

## Phase 5: Report

After writing `research.md`, report to the user:
- Output path
- Executive Summary (2-3 sentences)
- Key Insights list (numbered)
- Number of unique sources collected
- Approximate elapsed time

If standalone (not called from `/xplan`), suggest:
- "Run `/xplan` with this research to plan an implementation"
