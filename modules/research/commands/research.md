---
description: Multi-channel research using parallel agents with WebSearch, WebFetch, GitHub, and Reddit. No external dependencies.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, WebSearch, WebFetch, AskUserQuestion
argument-hint: <topic> [--depth full|technical|market|lite|custom] [--output <path>] [--repo <path>] [--plan-dir <path>] [--extend <prior-research-path>]
---

# /research - Multi-Channel Research

A research skill that spawns parallel agents to research a topic across the web using WebSearch, WebFetch, GitHub CLI, and Reddit JSON API. Produces a comprehensive research.md. No external dependencies required.

**Can be used:**
- Standalone: `/research "dark mode browser extensions"`
- From xplan: xplan Phase 1 can delegate to this skill
- From any skill that needs research

For deeper, higher-quality research with a local pipeline, install `/deepresearch` from the lem-deepresearch repo (see the research module README for details).

## Sub-Agent Model Optimization

When spawning research agents (Domain, Technical, Competitive, Adjacent, UX, Data, Monetization, Codebase), set model to **sonnet** in the Agent/Task tool call. Research synthesis and web queries work well on Sonnet. The orchestrator remains on the current model for final synthesis and verification.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments

Extract from arguments:
- **Topic**: The research subject (required)
- **`--depth <preset>`**: Research depth preset (optional, triggers interactive selection if omitted)
- **`--output <path>`**: Custom output path for research.md (optional)
- **`--repo <path>`**: Existing repo to analyze alongside topic research (optional)
- **`--plan-dir <path>`**: When called from xplan, the plan directory to write research.md into (optional)
- **`--extend <path>`**: Path to prior research.md to build on (optional, enables cross-session continuity)

If no topic is provided, use AskUserQuestion to ask what to research.

### Cross-Session Continuity (--extend)

If `--extend` is provided, read the prior research.md and use it as context:
1. Read the prior research file and extract: key insights, gaps identified in "Risks & Unknowns", sources already consulted
2. Pass prior findings to each research agent with the instruction: "Prior research exists. Focus on gaps, contradictions with prior findings, and new developments. Do NOT re-research what is already well-covered."
3. In synthesis, merge new findings with prior research rather than starting from scratch
4. In the output, note which findings are new vs. confirmed from prior research

### Determine Output Path

```
if --plan-dir provided:
  output = {plan-dir}/research.md          # xplan mode
elif --output provided:
  output = {output}/research.md            # custom path
else:
  slug = kebab-case(topic)
  mkdir -p ~/code/docs/research/{slug}
  output = ~/code/docs/research/{slug}/research.md  # standalone default
```

---

## Phase 1: Research Configuration

### If `--depth` was provided (e.g., from xplan delegation)

Skip the interactive question. Use the provided depth preset directly.

### If `--depth` was NOT provided

Ask the user what level of research they want using AskUserQuestion:

> "What level of research should I run?"

| Option | Agents Spawned | Channel Intensity | Best For |
|--------|---------------|-------------------|----------|
| **Full (Recommended)** | All 7 agents | 5-10 web requests per agent | New products, unfamiliar domains |
| **Technical Only** | Technical Architecture + Data & Infrastructure | Heavy GitHub code search | Adding features, technical spikes |
| **Market & Product** | Domain + Competitive + Monetization | Heavy WebSearch/Reddit | Validating a product idea, market analysis |
| **Lite** | Domain + Technical Architecture | 2-3 web requests per agent | Quick research, well-understood domains |
| **Custom** | User picks individual agents | Varies | Full control |

If the user selects **Custom**, follow up with a multi-select AskUserQuestion:

> "Which research agents should I spawn?"

Options (multiSelect: true):
1. **Domain & Problem Space** - Core problem domain, users, pain points, existing solutions, market gaps
2. **Technical Architecture** - Best technical approaches, scalability, data modeling, performance
3. **Competitive Landscape** - Existing products, feature matrices, pricing, user complaints, differentiation
4. **Adjacent Domains** - Related fields, lessons from adjacent industries, integrations, regulatory/compliance
5. **UX/Design Patterns** - UI/UX conventions, innovative interaction patterns
6. **Data & Infrastructure** - Storage patterns, API design, infrastructure requirements
7. **Monetization & Business** - Pricing strategies, conversion funnels, business models

**Note**: If `--repo` was provided, the **Codebase Analysis Agent** is always included regardless of selection.

---

## Phase 1.5: Query Decomposition

Before spawning agents, decompose the research topic into 5-10 atomic sub-questions. This yields dramatically better results than giving agents a broad topic (800%+ improvement on multi-hop questions in IR research).

1. Break the topic into specific, answerable sub-questions
2. Tag each sub-question with the agent type best suited to answer it
3. Group sub-questions by agent so each agent gets targeted questions, not the broad topic

Example:
```
Topic: "dark mode browser extensions"
Sub-questions:
  [Domain] What user pain points drive dark mode adoption?
  [Domain] What accessibility benefits does dark mode provide?
  [Technical] How do browser extensions inject CSS? What APIs are used?
  [Technical] How do extensions handle dynamic content and shadow DOM?
  [Competitive] What dark mode extensions exist? Stars, users, pricing?
  [Competitive] What do user reviews say about existing solutions?
  [Adjacent] What design system patterns exist for dark/light theming?
  [Monetization] How do browser extensions monetize? What do users pay?
```

Pass these targeted sub-questions to each agent instead of (or alongside) the broad topic. Agents answer specific questions more effectively than open-ended research prompts.

---

## Phase 2: Spawn Research Agents

Launch the selected research agents in **parallel** using the Task tool. Each agent gets:
1. The topic/concept to research
2. Its targeted sub-questions from Phase 1.5
3. The Internet Research Tools reference (below)
4. Output size rules
5. Depth-appropriate channel intensity guidance
6. Prior research context (if `--extend` was provided)

### Internet Research Tools Reference

Include this reference block in EVERY research agent's Task prompt:

```
## Internet Research Tools

You have access to real internet research tools. USE THEM. Do not rely solely on your training data.

### Search Channels

**General Web Search (WebSearch) - primary research tool**
WebSearch: "QUERY"
Best for: broad discovery, current events, product pages, general knowledge, finding specific content

**Read Any Web Page (WebFetch)**
WebFetch: URL
Best for: reading specific URLs, article content, documentation pages

**Reddit (community sentiment, user discussions)**
curl -s "https://www.reddit.com/search.json?q=QUERY&limit=5" -H "User-Agent: research-agent/1.0" | jq '.data.children[].data | {title, selftext: .selftext[:500], url, score, num_comments}'
curl -s "https://www.reddit.com/r/SUBREDDIT/hot.json?limit=5" -H "User-Agent: research-agent/1.0" | jq '.data.children[].data | {title, selftext: .selftext[:500], url, score}'
Fallback: WebSearch "site:reddit.com QUERY"

**GitHub (code, repos, issues)**
gh search repos "QUERY" --sort stars --limit 10
gh search code "QUERY" --language LANG --limit 10
gh repo view OWNER/REPO
Fallback: WebSearch "site:github.com QUERY"

**YouTube (find talks and tutorials)**
WebSearch "site:youtube.com QUERY"
Best for: finding relevant video content, conference talks, tutorials
Read video descriptions with WebFetch on the video page

### Source Credibility (weight findings accordingly)
- **Highest**: Academic papers (.edu), government (.gov), official documentation
- **High**: Established news outlets, peer-reviewed journals, official project repos
- **Medium**: Industry blogs, conference talks, Stack Overflow answers
- **Lower**: Personal blogs, social media, forum posts
- When sources conflict, prefer higher-credibility sources. Note the conflict in your output.

### Iterative Research Strategy
Do NOT do a single pass. Use descending parallelism:
- **Round 1** (broad): Run 3+ searches across different channels. Cast a wide net.
- **Round 2** (focused): Based on Round 1 findings, run 1-2 targeted follow-up searches to fill gaps or verify surprising claims.
- **Round 3** (validation): If a key finding relies on a single source, search for corroboration. If you cannot find a second source, flag the finding as "single-source."
Accumulate learnings across rounds. Each round should build on prior findings, not repeat them.

### Output Rules (MANDATORY)
- Cap your returned output at 10-15KB of relevant, synthesized text
- NEVER return raw JSON from any channel - always filter/extract relevant fields
- Filter Reddit JSON to title, selftext (500 chars max), url, score
- Summarize long web pages rather than returning raw content
- Include source URLs for ALL findings (populate the Sources section)
- For each key finding, note source count: "(3 sources)" or "(single source - unverified)"
- If a channel returns no useful data after trying its fallback, note: "[No data from {channel}. Findings based on LLM knowledge.]"
```

### Research Agent Definitions

**1. Domain & Problem Space Agent**

Research the core problem domain for "{TOPIC}".

Questions to answer:
- What does this space look like? Who are the users?
- What are their pain points and jobs-to-be-done?
- What existing solutions exist? What do they get right and wrong?
- What market gaps exist?

Channels to prioritize:
- WebSearch for broad discovery
- Reddit for user pain points and community discussions (search relevant subreddits)
- WebFetch for reading key articles found via search

---

**2. Technical Architecture Agent**

Research the best technical approaches for building solutions in the "{TOPIC}" space.

Questions to answer:
- What architectures work best for this type of system?
- What are the scalability concerns and data modeling challenges?
- What are the performance considerations?
- What specific technical challenges are unique to this domain?
- What open-source projects or libraries exist in this space?

Channels to prioritize:
- GitHub code search and repo search for real implementations
- WebSearch for architectural blog posts and documentation
- WebFetch for reading technical docs and READMEs

---

**3. Competitive Landscape Agent**

Deep dive on existing products, apps, and tools in the "{TOPIC}" space.

Questions to answer:
- What products exist? Feature matrices? Pricing models?
- What do user reviews and complaints say?
- What is missing from the market?
- What would make a new product stand out?

Channels to prioritize:
- WebSearch for product pages, review sites, comparison articles
- Reddit for user reviews and complaints (search r/SaaS, relevant subreddits)
- GitHub for open-source alternatives (stars, activity, issues)

---

**4. Adjacent Domains Agent**

Research related fields, technologies, and concepts that should inform "{TOPIC}".

Questions to answer:
- What lessons from adjacent industries apply?
- What integrations would users expect?
- What regulatory or compliance considerations exist?
- What emerging trends could impact this space?

Channels to prioritize:
- WebSearch for cross-domain research
- Reddit for discussions in adjacent subreddits

---

**5. UX/Design Patterns Agent**

Research UI/UX patterns for applications in the "{TOPIC}" space.

Questions to answer:
- What conventions do users expect?
- What innovative interaction patterns exist?
- What are the best-in-class design examples?
- What accessibility considerations apply?

Channels to prioritize:
- WebSearch for design pattern libraries and UX case studies
- Reddit (r/webdev, r/userexperience, r/UI_Design) for design discussions

---

**6. Data & Infrastructure Agent**

Research data storage patterns, API design, and infrastructure for "{TOPIC}".

Questions to answer:
- What data storage patterns work best?
- What API design approaches suit this domain?
- What infrastructure requirements exist?
- What scaling patterns are needed?

Channels to prioritize:
- GitHub for real infrastructure implementations
- WebSearch for infrastructure comparison articles

---

**7. Monetization & Business Model Agent**

Research pricing strategies, conversion funnels, and business models for "{TOPIC}".

Questions to answer:
- What pricing strategies work in this space?
- What conversion funnels do successful products use?
- What business models generate sustainable revenue?
- What are users willing to pay for?

Channels to prioritize:
- WebSearch for pricing pages and business model articles
- Reddit (r/SaaS, r/startups, r/Entrepreneur) for pricing discussions

---

**Codebase Analysis Agent (only if --repo provided)**

Analyze the existing repo at `{REPO_PATH}`. Deep dive into:
- Architecture and patterns used
- Tech stack and dependencies
- Code quality and tech debt
- Test coverage and testing patterns
- Current state (open issues, recent PRs, active branches)

This agent does NOT use internet channels. It uses: Read, Glob, Grep, Bash (for git commands, gh CLI).

---

## Phase 3: Synthesize Research

Once ALL research agents return:

1. **Synthesize findings** into a contextual model - a mental framework for how to think about this problem and its solution
2. **Identify key insights** that should drive decisions (numbered list)
3. **Assess confidence** for each key finding based on: number of corroborating sources, source credibility tier, and whether sources agree or conflict
4. **Flag risks, unknowns**, and areas needing further investigation
5. **Compile sources** from all agents into a unified sources list
6. **Write research.md** to the determined output path

## Phase 3.5: Verification (for Full depth only)

When depth is **Full**, run a verification pass after synthesis. Skip this for Lite/Technical/Market presets to keep them fast.

1. **Identify high-stakes claims**: Extract the 5-10 most important findings from the synthesis (claims that would drive major decisions)
2. **Cross-reference**: For each high-stakes claim, check if multiple independent sources support it. If a claim relies on a single source, attempt one targeted search to find corroboration.
3. **Flag contradictions**: If sources conflict on a claim, note the conflict explicitly rather than silently picking one side
4. **Mark confidence levels**:
   - **High confidence**: 3+ independent sources agree, from credible domains
   - **Medium confidence**: 2 sources, or sources from mixed credibility tiers
   - **Low confidence**: Single source, or only from low-credibility sources
   - **Unverified**: Claim from LLM knowledge only, no source found
5. **Update the synthesis** with confidence markers before writing the final output

### research.md Template

```markdown
# Research: {Topic}

## Table of Contents

## Executive Summary
[2-3 paragraph synthesis. Lead with the "so what" - what should the reader do with this information?]
[Overall confidence: "Strong evidence from N sources" or "Mixed evidence, key gaps remain"]

## Contextual Model
[The mental framework for thinking about this problem and solution]
[Key principles that should guide every decision]

## Problem Space
[Domain analysis, user pain points, jobs-to-be-done]

## Competitive Landscape
[Existing solutions, feature gaps, differentiation opportunities]

## Technical Landscape
[Architecture patterns, technology options, scalability considerations]

## Adjacent Domains & Integrations
[Related fields, expected integrations, compliance/regulatory]

## UX & Design Patterns
[User expectations, UI conventions, innovative approaches]

## Key Insights
[Numbered list of the most important findings. For each insight, include:]
[1. **Finding title** - description (Confidence: High/Medium/Low, N sources)]
[2. **Finding title** - description (Confidence: High/Medium/Low, N sources)]
[Flag any findings where sources conflict rather than silently picking a side]

## Risks & Unknowns
[Identified risks with severity and mitigation strategies]
[Include findings marked "Low confidence" or "Unverified" as explicit unknowns]

## Sources
[URLs and references from all research agents - MUST be populated with real links]
[Group by credibility tier: Academic/Official, Industry/News, Blogs/Social]
```

### Standalone Mode Addition

If NOT called from xplan (no `--plan-dir`), append after Sources:

```markdown
## Recommendations
[Concrete, prioritized recommendations for next steps]
[Each recommendation should reference the finding(s) that support it]
[Flag recommendations that depend on low-confidence findings]
```

---

## Phase 4: Report Results

After writing research.md:

1. Print the output path
2. Summarize key insights (top 3-5) with their confidence levels
3. Note any channels that failed or returned no data
4. Flag any high-stakes findings that are low-confidence or unverified
5. If standalone, suggest next steps:
   - "Run `/research --extend {output-path}` to go deeper on specific areas"
   - "Run `/xplan` with this research to plan an implementation"
