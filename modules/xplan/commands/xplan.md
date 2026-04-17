---
description: Interactive deep research + planning + execution framework for new projects and features
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <project concept or idea> [--repo <existing-repo-path>] [--light] [--deepen [<plan-dir>]]
---

# xplan - Interactive Project Planning & Execution

A human-in-the-loop planning framework that interviews you upfront, deeply researches your concept, builds a contextual model, proposes tech stack and architecture for your sign-off, creates a parallelized execution plan, reviews it with specialized agents, and then autonomously executes using parallel agents.

**Flags:**
- `--repo <path>` - Analyze and plan work for an existing repo
- `--light` - Skip the interactive interview phases; uses minimal clarification + traditional walkthrough at the end (old xplan behavior)
- `--deepen [<plan-dir>]` - Skip fresh planning; load an existing plan and run targeted deepening passes on under-specified sections. See "Deepen Mode" below.

**Companion commands:**
- `/xplan-status` - Check progress on a running or completed plan
- `/xplan-resume` - Resume an interrupted plan execution

---

## Sub-Agent Model Optimization

Specify cheaper models when spawning sub-agents to conserve usage without sacrificing quality:

| Phase | Sub-Agent | Model |
|-------|-----------|-------|
| Phase 1 | Research agents (via /deepresearch) | sonnet |
| Phase 2 | Naming agent | sonnet |
| Phase 4 | Review agents (security, architecture, business) | sonnet |
| Phase 7 | Execution agents (epic implementation) | sonnet |

The orchestrator (this session) stays on the current model for all synthesis, architecture, and interactive decisions. Simple background tasks (file checks, directory setup, issue creation) can use haiku if spawned as Task agents.

---

## CRITICAL: Interactive Prompts Are Mandatory

**This skill REQUIRES user interaction to function.** xplan is an interactive framework - the user chose to run `/xplan` precisely because they want the guided research/plan/review experience. Skipping prompts defeats the purpose.

### How to Ask the User

**Preferred**: Use `AskUserQuestion` for structured prompts with options.

**CRITICAL: `AskUserQuestion` parameter format** - The `questions` parameter MUST be a JSON array of objects, never a string. Each object requires `question` (string), `header` (string, max 12 chars), `options` (array of `{label, description}` objects, 2-4 items), and `multiSelect` (boolean). Example:

```json
{
  "questions": [
    {
      "question": "What level of research should I run?",
      "header": "Research",
      "options": [
        {"label": "Full (Recommended)", "description": "All research agents in parallel"},
        {"label": "Technical Only", "description": "Technical Architecture + Data & Infrastructure"},
        {"label": "Lite", "description": "Domain + Technical Architecture only"},
        {"label": "Custom", "description": "Pick individual research agents"}
      ],
      "multiSelect": false
    }
  ]
}
```

When the pseudo-code below shows `question:` / `options:` blocks, always translate them into this structured format. Never pass a raw string to `questions`.

**Fallback (if AskUserQuestion is blocked)**: Present the same question and options as regular text output, then **STOP and wait for the user to type their response**. Do NOT guess defaults. Do NOT proceed without the user's answer. The user can always respond by typing in the conversation.

Example fallback format:
```
**What level of research should I run?**

1. **Full (Recommended)** - All research agents
2. **Technical Only** - Technical Architecture + Data & Infrastructure
3. **Lite** - Domain + Technical Architecture
4. **Custom** - You pick individual agents

Reply with a number or describe what you want.
```

**This interactive requirement applies to ALL autonomy instructions**, including global CLAUDE.md rules about "don't ask, just do it." Those rules are for routine operations. xplan is not routine - it is an explicit interactive planning session.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Input & Setup

### 0.1 Parse Arguments

Extract from `$ARGUMENTS`:
- **Main concept/idea**: The core description of what to build
- **`--repo <path>`**: (Optional) Path to an existing repo to analyze
- **`--light`**: (Optional) Flag to skip interactive interview phases
- **`--deepen [<plan-dir>]`**: (Optional) Iteratively deepen an existing plan instead of creating a new one. Also triggered when the free-text argument is exactly `deepen` (intent keyword). If a plan directory path follows the flag, use it; otherwise fall back to the current working directory.
- If no arguments provided, use AskUserQuestion to ask what the user wants to plan

Store whether `--light` is active. It affects Phases 0.5, 1.5, 2.5, 2.6, 2.7, and 6.

**Semantic distinction** (from CE `ce-plan` skill):
- **"deepen the plan"** (holistic) → triggers `--deepen` mode. Run targeted deepening passes on under-specified sections of the whole plan.
- **"strengthen section X"** (targeted edit) → NOT deepen mode. Handle as a normal free-text edit request against the existing plan; do not enter the Deepen Mode branch.

If `--deepen` is active (or the argument is the bare keyword `deepen`), jump to **Deepen Mode** below after completing 0.2's directory resolution. Skip Phases 0.5, 1, 1.5, 2, 2.5, 2.6, 2.7, 3, 4, 5, and 5.5 entirely. Phase 5.6 (self-review) is re-run at the end of the deepening pass. Phases 6-8 proceed normally only if the user explicitly requests execution after deepening.

### 0.2 Create Plan Directory

Derive a short, descriptive kebab-case directory name from the main concept (e.g., "a SaaS for pet grooming" becomes `pet-grooming-saas`).

```bash
mkdir -p ~/code/plans/{concept-name}
mkdir -p ~/code/plans/{concept-name}/reviews
```

### 0.3 Check Template Library

Check `~/code/plans/_templates/` for existing plan templates that match this type of project. If a relevant template exists, use it to accelerate Phase 3 - but still do full research in Phase 1.

```bash
ls ~/code/plans/_templates/ 2>/dev/null
```

### 0.4 Existing Repo Analysis (if --repo provided)

If an existing repo path was given:
1. Read its CLAUDE.md, README.md, package.json, and key config files
2. Map its architecture, tech stack, and current state
3. Check `gh issue list` and `gh pr list` for open work
4. Read recent agent logs from the log repo for the project
5. This context feeds into Phase 1 research and Phase 0.5 interview

---

## Deepen Mode (--deepen)

**Entry condition**: `--deepen` flag present, OR `$ARGUMENTS` is exactly the keyword `deepen`. Parsed in Phase 0.1.

**Goal**: Iteratively tighten an existing plan without re-running the full research + planning pipeline. Deepening fills confidence gaps in sections that are vague, under-specified, or resting on unverified assumptions - it does not re-do Phases 1-5.

**Announce at start**: "Entering Deepen Mode - loading existing plan and identifying under-specified sections. Skipping Phases 1-5."

### D.1 Resolve Plan Directory

Determine which plan to deepen:

1. If `--deepen <plan-dir>` was passed, use that path.
2. Else if the current working directory is under `~/code/plans/{concept-name}/` and contains `plan.md`, use that directory.
3. Else list `~/code/plans/*/plan.md` modified in the last 30 days and ask via AskUserQuestion which plan to deepen.
4. Else error out with `BLOCKED`: no plan to deepen.

Verify `plan.md` exists at the resolved path. If missing, stop and surface the problem - deepening requires a plan to operate on.

### D.2 Load Existing Context

Read every artifact already in the plan directory so the deepening pass operates with full context, not a fresh slate:

- `plan.md` (required)
- `research.md` (if it exists)
- `decisions.md` (if it exists)
- `naming.md` (if it exists)
- `progress.md` (if it exists)
- `reviews/*.md` (all review agent outputs, if any)

Do NOT ask the user to re-do the discovery interview. The plan already encodes those decisions.

### D.3 Identify Under-Specified Sections

Scan the loaded plan for confidence gaps. Categorize findings into four buckets (adapted from CE's "Confidence Check and Deepening"):

1. **Unclear patterns to follow** - sections that reference an approach or convention without a concrete example (e.g., "follow the repo's auth pattern" without citing a specific file or function).
2. **Missing test scenarios** - epics whose acceptance criteria do not include at least one testable scenario, or whose test list is labeled "etc." / "and more".
3. **Unverified technology assumptions** - framework versions, library capabilities, API shapes, or platform behaviors asserted without a source link or a pointer into research.md.
4. **Structural ambiguity** - sections where two reasonable interpretations exist and the plan does not disambiguate (e.g., "store the session" could mean cookie, localStorage, or server-side).

Produce a shortlist of 3-8 deepening candidates. Each candidate must cite:
- The section / heading in `plan.md` it targets
- The bucket (one of the four above)
- A one-sentence description of the gap
- A proposed research or clarification action

If zero gaps are found, report `DONE` for Deepen Mode - the plan is already tight enough to not benefit from this pass. Still run Phase 5.6 as a final check.

### D.4 User Selects Which Gaps to Close

Present the shortlist via AskUserQuestion (`multiSelect: true`) so the user picks which gaps to deepen. Include:
- "All of the above" as a convenience option
- "None - just re-run self-review" as an escape hatch

Wait for explicit selection. Do not auto-select.

### D.5 Dispatch Targeted Deepening Passes

For each selected candidate, spawn a focused Task agent (model: sonnet) whose entire job is to close that one gap. The agent's brief:

```
You are deepening one section of an existing plan.

Target section: {heading from plan.md}
Gap type: {pattern / test / tech-assumption / ambiguity}
Gap description: {one-sentence description}

Plan directory: ~/code/plans/{concept-name}/
Existing plan: ~/code/plans/{concept-name}/plan.md
Existing research: ~/code/plans/{concept-name}/research.md

Do:
- Research ONLY what is needed to close this specific gap (web search, repo grep, or doc read).
- Return a proposed replacement block for the target section, in diff-ready markdown.
- Cite every new claim with a source URL or repo file path.

Do NOT:
- Rewrite sections outside the target.
- Introduce new epics or restructure the plan.
- Re-run the discovery interview or naming phase.

Output:
- A "Findings" summary (3-8 bullet points)
- A "Proposed replacement" block containing the full rewritten section
- "Open questions" (any remaining unknowns the user still has to decide)
```

Run these agents in parallel when the targets are in different sections. Serialize them when two candidates touch the same section.

### D.6 User-Controlled Integration

For each returned deepening pass, present the user with the findings + proposed replacement via AskUserQuestion:

```
question: "Integrate these deepening findings for section {heading}?"
options:
  - "Yes - apply the full proposed replacement"
  - "Yes - apply with edits (I'll describe)"
  - "No - discard this deepening pass"
  - "Defer - keep the findings in decisions.md but don't touch plan.md yet"
```

Apply each accepted replacement by editing `plan.md` in place. Append a short deepening-log block to `decisions.md`:

```markdown
## Deepen Pass ({ISO date})
- Target: {heading}
- Gap: {bucket} - {description}
- Outcome: applied / edited-then-applied / discarded / deferred
- Sources added: {URLs or file paths}
```

### D.7 Re-run Phase 5.6 Self-Review

After all accepted deepening edits land, **re-run Phase 5.6 (Plan Quality Self-Review) against the updated plan.md, decisions.md, and naming.md**. This catches:
- New placeholders introduced by partial replacements
- Type / identifier drift introduced when a deepening agent picked a new name
- Granularity regressions (a deepened section that is now longer but still vague)

Loop until 5.6 reports clean, same as a fresh planning run. Do NOT modify Phase 5.6 - it is the same self-review used by the main flow.

### D.8 Exit Deepen Mode

After 5.6 passes:

1. Summarize the deepening pass for the user: which gaps were closed, which were deferred, which were discarded.
2. Ask via AskUserQuestion whether to proceed with execution (Phase 7) or stop here. Default is to stop - deepening is a planning activity, not an execution trigger.
3. If the user chooses to execute, resume at Phase 6 (Final Confirmation Gate). Otherwise end the command.

---

## Phase 0.5: Discovery Interview

**Skip this phase entirely if `--light` flag is active. Proceed to Phase 1.**

**Goal**: Reach 95%+ confidence about what the user wants to build before committing to research and planning. A wrong assumption at this stage cascades into hours of wasted work.

### 0.5.1 Confirm Core Understanding

Summarize what you understand from the initial input, then use AskUserQuestion:

```
question: "Here's what I understand you want to build: [1-2 sentence summary]. Does this capture what you have in mind?"
options:
  - "Yes, that's right - proceed"
  - "Close, but let me clarify..."
  - "Not quite - here's what I actually want..."
```

If the user selects a clarifying option, ask a focused follow-up free-text question, then re-confirm. Repeat until you hit 95% confidence. Do not proceed to 0.5.2 until confirmed.

### 0.5.2 Context Questions

Ask each of the following as a separate AskUserQuestion call with options. Do NOT dump them all as a numbered list - ask them one at a time as interactive prompts.

**Q1 - Codebase type:**
```
question: "Is this a new project from scratch or adding to an existing codebase?"
options:
  - "New project from scratch"
  - "Adding to an existing codebase"
```

**Q2 - Audience:**
```
question: "Who is this for?"
options:
  - "Personal use"
  - "Client project"
  - "Launch as a product"
```

**Q3 - V1 scope constraints:**
```
question: "Is anything explicitly out of scope for v1?"
options:
  - "Nothing specific - let the plan decide"
  - "Yes, I have specific exclusions (I'll describe)"
```

**Q4 - Technical constraints:**
```
question: "Any hard technical constraints or must-use services?"
options:
  - "No constraints - use best-fit choices"
  - "Yes, I have specific requirements (I'll describe)"
```

**Q5 - Success criteria (free text):**
```
question: "How will you know this is working? What does success look like at launch?"
```
(No options - this is open-ended. Wait for a typed response.)

**If Q2 was "Launch as a product", also ask:**

**Q6 - Revenue model:**
```
question: "What's the rough monetization approach?"
options:
  - "Subscription (monthly/annual)"
  - "One-time purchase"
  - "Freemium (free tier + paid)"
  - "Completely free / open source"
  - "Not sure yet - figure it out later"
```

**Q7 - Timeline:**
```
question: "Any deadline pressure or target timeline?"
options:
  - "No hard deadline"
  - "Soft target in mind (I'll specify)"
  - "Hard deadline (I'll specify)"
```

### 0.5.3 Research Level Preference

```
question: "What level of research should I run?"
options:
  - "Full (Recommended) - all 7 agents + internet search [best for new products / unfamiliar domains]"
  - "Technical Only - architecture + data infrastructure [best for adding features / technical spikes]"
  - "Market & Product - competitive landscape + monetization [best for validating an idea]"
  - "Lite - domain overview + technical architecture [quick planning / well-understood domains]"
  - "Custom - I'll pick individual agents"
```

Store the selection for Phase 1.1. Do not re-ask in Phase 1.0.

---

## Phase 1: Deep Research

**Goal**: Build a thorough contextual model of the problem space before planning anything. This is the foundation everything else builds on.

### 1.0 Research Configuration

**If `--light` flag is active**: Ask the research level question here using the same preset table as Phase 0.5.3.

**If not `--light`**: The research level was already confirmed in Phase 0.5.3. Skip this question entirely - do not double-prompt.

### 1.1 Delegate to /deepresearch

Spawn a single Task agent (model: sonnet) that executes the `/deepresearch` skill with the concept, depth selection, plan directory, and repo (if provided).

The Task agent's prompt should be:

```
Read the file ~/.claude/commands/deepresearch.md and follow its instructions exactly.

Topic: {concept from Phase 0}
Arguments: --depth {user's selection from 0.5.3 or 1.0} --plan-dir ~/code/plans/{concept-name} {--repo REPO_PATH if provided}

Execute the full /deepresearch workflow: parse arguments, run the research pipeline, and write research.md to the plan directory.
```

### 1.2 Verify Research Output

After the Task agent completes:

```bash
ls -la ~/code/plans/{concept-name}/research.md
```

If research.md does not exist, re-spawn the research agent or ask the user how to proceed.

Confirm research.md contains:
- Executive Summary
- Key Insights (with real data, not just LLM knowledge)
- Sources section with actual URLs

If the Sources section is empty, note this but proceed.

---

## Phase 1.5: Research Review & Idea Refinement

**Skip this phase entirely if `--light` flag is active. Proceed to Phase 2.**

**Goal**: Present research findings to the user and catch any concept changes before committing to planning. This is the "kill or refine" checkpoint.

### 1.5.1 Present Research Summary

Summarize the key findings from research.md into a digestible briefing:
- Executive summary (2-3 sentences)
- Top 3-5 insights that directly affect the plan
- Notable surprises or things that differed from the initial assumption
- Identified risks or unknowns worth flagging

### 1.5.2 Business Viability Assessment (New Products Only)

**Only run this if the project is being built as a product (not personal use or client work).**

Based on research findings, provide a frank business viability assessment:

**Competitive Landscape:**
- Who are the main competitors?
- What gaps or underserved niches exist?
- Is there a clear differentiator available for this concept?

**Opportunity Signal:**
- `Strong` - Identified gap, growing market, no dominant solution
- `Moderate` - Competitive but differentiation is viable
- `Weak` - Crowded market, strong incumbents, unclear differentiation
- `Unclear` - Insufficient data to assess

**Recommendation**: Give a direct recommendation - proceed as planned, adjust the concept to target a specific niche, or flag a pivot opportunity worth considering.

Then use AskUserQuestion:

```
question: "Based on these research findings, how do you want to proceed?"
options:
  - "Proceed as planned"
  - "Adjust the concept - let me describe what I'd change"
  - "Pivot to a different angle based on the gap you identified"
  - "Discuss further before deciding"
```

Update the plan direction based on the response. If the concept changes significantly, note what changed in decisions.md.

### 1.5.3 Idea Refinement Gate

After presenting findings (and business viability if applicable), use AskUserQuestion:

```
question: "Any changes to what we're building based on these findings?"
options:
  - "No changes - looks good, move into planning"
  - "Yes, I have changes (I'll describe)"
```

Wait for explicit confirmation before proceeding to Phase 2.

---

## Phase 2: Naming Ideation (Optional)

After research is confirmed, use AskUserQuestion:

```
question: "Before I start planning, would you like me to brainstorm project names and check domain availability?"
options:
  - "Yes - spin up a naming agent (.com/.io/.ai/.pro/.work checks)"
  - "No - skip naming, proceed to planning"
  - "I already have a name in mind (I'll provide it)"
```

If yes or "I already have a name":

### 2.1 Spawn Naming Agent

Launch a Task agent (model: sonnet) that:
1. Generates 15-25 name candidates based on research and concept
2. Considers: memorability, brandability, brevity, relevance, uniqueness
3. Checks for conflicts with existing apps/products (web search)
4. Checks domain availability across: `.com`, `.io`, `.ai`, `.pro`, `.work`
5. Checks npm package name availability (if relevant)
6. Checks GitHub org/repo name availability
7. Ranks names by overall viability

### 2.2 Write naming.md

Save results to `~/code/plans/{concept-name}/naming.md`:

```markdown
# Name Ideation: {Concept}

| Rank | Name | .com | .io | .ai | .pro | .work | Conflicts | Notes |
|------|------|------|-----|-----|------|-------|-----------|-------|
| 1    | ... | ... | ... | ... | ... | ... | ... | ... |
```

### 2.3 Present to User

Show the top 5 names and ask the user to pick one (or provide their own). The chosen name becomes the project name throughout the plan.

---

## Phase 2.5: Tech Stack Proposal & Sign-off

**Skip this phase entirely if `--light` flag is active. Tech stack is decided internally in Phase 3.1.**

**Goal**: Propose the full tech stack with justifications and get user sign-off before writing the plan.

### 2.5.1 Gather Existing Patterns

Scan active projects in ~/code to identify the established package ecosystem:

```bash
# Sample a few active projects for their dependency patterns
cat ~/code/provendoro-repos/provendoro-0/package.json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(list({**d.get('dependencies',{}), **d.get('devDependencies',{})}.keys()))" 2>/dev/null | head -5
ls ~/code/openslide-ai-repos/openslide-ai-0/packages/ 2>/dev/null
```

Use findings to identify the standard ecosystem (Drizzle, Hono, Better Auth, Zustand, TanStack Query, Vitest, zod, etc.) and apply appropriate defaults.

### 2.5.2 Propose Tech Stack

Present a full tech stack proposal with justifications. Apply these defaults unless research indicates a strong reason for alternatives:

**Hard defaults** (always use unless actively contradicted):
- **Hosting/Infra**: Cloudflare (Pages, Workers, D1/KV/R2, DNS)
- **Frontend**: React + Vite
- **Styling**: Tailwind v4 + shadcn/ui
- **Email**: Resend
- **Auth**: Google OAuth (architected to add providers later)
- **E2E Testing**: Playwright
- **CI/CD**: GitHub Actions
- **Language**: TypeScript throughout
- **Package manager**: pnpm

**Context-dependent** (choose based on what's being built):
- **Database**: CF D1 (SQLite/edge) or Supabase (managed Postgres)
- **ORM**: Drizzle (CF D1/SQLite) or Prisma (PostgreSQL)
- **API layer**: Hono (CF Workers) or tRPC (full-stack type safety)
- **Auth library**: Better Auth (if CF D1) or Supabase Auth (if Supabase)
- **State**: Zustand (client) + TanStack Query (server)
- **Validation**: zod
- **Monorepo**: pnpm workspaces (if multiple apps/packages)
- **AI integration**: Provider SDKs directly (`@anthropic-ai/sdk`, `openai`, `@google/generative-ai`)

**Banned** (never suggest, no exceptions):
- Anything from Vercel's ecosystem: `ai`, `@ai-sdk/*`, `next`, `@next/*`, `@vercel/*`, `v0`, `turbo`, `turborepo`, `swr`
- Next.js (use Vite + React Router, Remix, or Astro instead)

Present as a table:

```
## Proposed Tech Stack

| Layer | Choice | Justification |
|-------|--------|---------------|
| Hosting | Cloudflare Pages/Workers | ... |
| Frontend | React + Vite | ... |
| Styling | Tailwind v4 + shadcn/ui | ... |
| Database | CF D1 / Supabase | ... |
| ORM | Drizzle | ... |
| API | Hono | ... |
| Auth | Better Auth + Google OAuth | ... |
| Email | Resend | ... |
| State | Zustand + TanStack Query | ... |
| Testing | Vitest + Playwright | ... |
| CI/CD | GitHub Actions | ... |
```

Then use AskUserQuestion:

```
question: "Does this tech stack look right?"
options:
  - "Looks good - approved, proceed to planning"
  - "I have changes (I'll describe)"
```

### 2.5.3 Iterate Until Approved

If the user has changes, apply them. For each change, note the tradeoff briefly (e.g., "switching from D1 to Supabase adds managed Postgres but removes the CF-native advantage"). Re-present the updated table and re-confirm with the same AskUserQuestion options until "Looks good" is selected.

Record all stack decisions in `~/code/plans/{concept-name}/decisions.md`.

Once approved, store the approved stack - it is the canonical stack for Phase 3.

---

## Phase 2.6: High-Level Plan Proposal & Sign-off

**Skip this phase entirely if `--light` flag is active. Proceed to Phase 3.**

**Goal**: Propose the overall scope and rough epic structure before writing the full plan. Catch scope misalignment early, not after hours of detailed planning.

### 2.6.1 Propose Scope & Epic Structure

Present a high-level proposal:

**V1 Scope:**
- Core feature set (what's IN v1)
- Explicit non-goals (what's OUT of v1)
- Any scope decisions driven by research findings

**Rough Epic Structure** (names only, no full specs):
```
Wave 1 (Foundation):
- Epic 1: Project scaffold, CI/CD, shared config
- Epic 2: Database schema + migrations
- ...

Wave 2 (Core Features - Parallel):
- Epic 3: [Feature A]
- Epic 4: [Feature B]
- ...

Wave 3 (Integration + Polish):
- Epic N: [Integration work]

Human-Epics:
- [Service setups, API keys, DNS config]
```

Also indicate: "I'm planning [N] parallel agents across [N] waves. With the [workspace/clone] setup from Phase 2.7, up to [N] agents can run simultaneously."

### 2.6.2 Sign-off Gate

Use AskUserQuestion:

```
question: "Does this scope and epic breakdown feel right?"
options:
  - "Looks right - approved, write the full plan"
  - "Something's missing (I'll describe)"
  - "Something should be cut or moved to v2 (I'll describe)"
  - "I want to discuss before deciding"
```

Iterate until the user selects "Looks right". Update the plan direction accordingly before proceeding to Phase 3.

---

## Phase 2.7: Multi-Agent Setup

**Skip this phase entirely if `--light` flag is active. Use the default 4-clone flat model.**

**Goal**: Decide how parallel agent execution will be structured before creating the plan.

### 2.7.1 New Codebase

If this is a new project (no `--repo`), use AskUserQuestion:

```
question: "How do you want to set up parallel agent execution?"
options:
  - "Workspace model (recommended for large plans) - isolated workspaces, each with 3-4 clones"
  - "Flat clone model (simpler) - 4 sibling clones, best for ≤8 agent-epics"
  - "Single clone - no parallelism, best for small features or prototypes"
```

Use the answer to configure Phase 7.1.

### 2.7.2 Existing Codebase (if --repo provided)

First, check if the codebase already has a multi-clone or workspace setup:

```bash
ls ~/code/{project}-workspaces/ 2>/dev/null && echo "workspace model exists"
ls ~/code/{project}-repos/ 2>/dev/null && echo "flat clone model exists"
```

**If it already has a workspace/clone setup**: Ask which clone to use as the base, or whether to create new clones for this work.

**If no multi-clone setup exists**: Assess whether the planned scope warrants parallelism (yes if 4+ agent-epics). If yes, use AskUserQuestion:

```
question: "This codebase doesn't have a multi-clone setup yet. Given the scope ([N] agent-epics), it would benefit from parallel agents. How do you want to proceed?"
options:
  - "Set up flat clone model for this work (~/code/{project}-repos/)"
  - "Migrate to workspace model for full parallelism (~/code/{project}-workspaces/)"
  - "Work in the existing single clone (no parallelism)"
```

If "workspace model" is chosen, add workspace migration as a prerequisite step in the plan.

**If small scope (3 or fewer agent-epics)**: Skip parallelism and work in the existing clone.

---

## Phase 3: Plan Creation

**Goal**: Create a comprehensive, parallelized execution plan divided into agent-epics.

### 3.1 Tech Stack Documentation

**If interactive mode (not --light)**: The tech stack was already approved in Phase 2.5. Use the approved stack as the basis for architecture and epic design. Do not re-propose it.

**If --light mode**: Select the optimal tech stack based on research findings and the hard defaults defined in Phase 2.5.2. Document reasoning in decisions.md.

Hard constraints apply in both modes:
- **Cloudflare** for hosting/infra
- **Resend** for email
- **Google OAuth** for auth
- **Playwright** for E2E testing
- **GitHub Actions** for CI/CD
- **Never Vercel or Next.js**

### 3.2 Architecture Design

Design the system architecture:
- Component diagram (text/ASCII)
- Data model overview
- API design approach
- Authentication & authorization flow
- Deployment architecture (Cloudflare services map)
- Monitoring & observability approach

### 3.3 Define Agent-Epics

Break the plan into **agent-epics**: large, isolated chunks of work a single agent can complete autonomously.

**Sizing principle**: The constraint is **scope isolation**, not time. What matters:
- **Isolation** - Clear boundaries, minimal file overlap with concurrent epics
- **Testability** - Output can be independently verified; produces working, tested code
- **Merge safety** - Changes won't conflict with concurrent agents
- **Context coherence** - Focused enough that the agent won't lose critical context

Split when: spanning unrelated subsystems, context would be scattered, changes conflict with concurrent work, or mixing infrastructure with feature work.

Do NOT split just because work is large. A 3-hour focused epic is better than three 1-hour epics with artificial seams.

Rules:
- Each epic results in **working, tested code** (unit + integration tests included)
- Define clear **inputs** (what must exist) and **outputs** (what results)
- Identify **dependency order** - parallel vs. sequential
- Define **bring-up steps** - the concrete actions required to get the app (local and/or production) into a testable state once this epic merges: migrations to run, dev servers to restart, deploys to trigger, env vars/secrets to set, caches to invalidate, seed data to load. "Code merged" is not "change testable"; the plan must close that gap explicitly.

Epic categories:
- **Foundation epics**: Repo setup, CI/CD, shared types, config - run first
- **Parallel epics**: Independent feature work running simultaneously
- **Integration epics**: Connecting parallel streams - run after dependencies
- **Testing epics**: E2E test suites, load testing
- **Human-epics**: Work requiring human intervention

### 3.4 Define Human-Epics

For each human-epic:
- Exact step-by-step instructions
- When it needs to happen (what it blocks)
- Whether it can be done in parallel with agent execution
- Links to relevant dashboards/services

**Minimize human-epics.** For each, ask: "Can this be done via CLI/API instead?" Only create human-epics for things that genuinely require browser-based human action (OAuth app setup in Google Console, payment provider setup, etc.).

### 3.5 Define Prerequisites

Before execution begins:
- API keys and credentials the user must provide
- CLI tools that must be installed
- Services that must be signed up for
- DNS/domain configuration
- Multi-clone or workspace setup (from Phase 2.7)
- Any other blockers

### 3.6 Execution Strategy

Define:
- **Wave 1**: Foundation epics (sequential, must complete first)
- **Wave 2+**: Parallel epic groups with dependency constraints
- **Agent allocation**: How many agents per wave (based on Phase 2.7 decision)
- **Integration points**: Where parallel streams merge
- **Verification gates**: Checkpoints before proceeding
- **Post-wave bring-up**: Aggregate the bring-up steps from every epic in the wave into a single ordered runbook. Include: migrations (with correct order if multiple), which services to restart (local dev servers, workers, background jobs), which deploys to trigger and verify, env vars/secrets to set, and the smoke-test command(s) that prove all layers are live. This runbook executes between waves - agents do not advance to the next wave until the previous wave's app state is reactivated and verified working.

### 3.7 Create decisions.md

Create `~/code/plans/{concept-name}/decisions.md`:

```markdown
# Decision Log: {Project Name}

| # | Decision | Options Considered | Rationale | Date |
|---|----------|--------------------|-----------|------|
| 1 | ... | ... | ... | ... |
```

Include all stack decisions from Phase 2.5 and scope decisions from Phase 2.6.

---

## Phase 4: Plan Review

**MANDATORY**: Before finalizing the plan, run review agents.

### 4.0 Review Configuration

Use AskUserQuestion:

```
question: "What level of plan review should I run before writing the full plan?"
options:
  - "Full (Recommended) - Security + Architecture + Business Logic [new products / user-facing]"
  - "Technical Only - Security + Architecture [internal tools / technical features]"
  - "Architecture Only [small features / well-understood domains]"
  - "Security Only [quick security gut-check]"
  - "Skip Review - proceed directly to plan [iterating fast on a known pattern]"
  - "Custom - I'll pick individual reviewers"
```

If **Custom**, follow up with a multi-select AskUserQuestion:

```
question: "Which review agents should I spawn? (select all that apply)"
options:
  - "Security - auth vulnerabilities, data exposure, OWASP Top 10, RLS/access control"
  - "Architecture - scalability, tech stack optimization, data model, single points of failure"
  - "Business Logic - alignment with research, user needs, epic completeness, edge cases"
```

**Note**: If "Skip Review" is selected, Phases 4.1-4.4 are skipped entirely. Proceed directly to Phase 5.

### 4.1 Spawn Review Agents

Launch chosen review agents in parallel using the Task tool (model: sonnet).

1. **Security Review Agent** - Output: `~/code/plans/{concept-name}/reviews/security.md`
2. **Architecture Review Agent** - Output: `~/code/plans/{concept-name}/reviews/architecture.md`
3. **Business Logic Review Agent** - Output: `~/code/plans/{concept-name}/reviews/business-logic.md`

### 4.2 Wait for ALL Selected Review Agents to Complete

**HARD GATE**: All selected agents MUST be launched in **foreground** (not background). Do NOT proceed until every selected agent has returned.

If "Skip Review" was selected, skip to Phase 5.

### 4.3 Verify Reviews Exist

```bash
for f in {selected-reviews}; do
  if [ ! -f ~/code/plans/{concept-name}/reviews/$f ]; then
    echo "BLOCKED: $f missing"
  fi
done
```

If ANY selected file is missing, STOP. Do not proceed.

### 4.4 Incorporate Review Feedback

For each finding:
- **Critical issues**: Must be addressed before presenting plan
- **Recommendations**: Incorporate if they improve the plan without adding scope
- **Nice-to-haves**: Note for future consideration

Revise the plan based on critical and recommended findings.

---

## Phase 5: Write plan.md

**Prerequisite**: Phase 4 fully complete (or "Skip Review" selected).

Create `~/code/plans/{concept-name}/plan.md`:

```markdown
# {Project Name} - Execution Plan

## Table of Contents

## 1. Overview
### 1.1 Vision
### 1.2 Key Insights from Research
### 1.3 Scope (v1 in / v1 out)

## 2. Tech Stack
[Each choice with rationale - pull from approved stack in Phase 2.5]

## 3. Architecture
### 3.1 System Overview
### 3.2 Component Diagram
### 3.3 Data Model
### 3.4 API Design
### 3.5 Auth Flow
### 3.6 Deployment Architecture

## 4. Prerequisites
[CLI tools, API keys, service signups, DNS, clone setup]

## 5. Agent-Epics
### Epic 1: {Name}
- **Wave**: 1 / 2 / 3
- **Dependencies**: None / Epic N
- **Scope**: [What this epic covers]
- **Inputs**: [What must exist before starting]
- **Outputs**: [What exists when complete]
- **Tests**: [What tests are written]
- **Files created/modified**: [List]
- **Acceptance criteria**: [Checkboxes]
- **Bring-up steps**: [Concrete actions required to make this change testable once merged - migrations, server restarts, deploys, env vars, cache invalidation, seed data. "None" only if truly none (e.g., docs-only).]
- **Checkpoint notes**: [Key context to preserve if session compacts]

## 6. Human-Epics
### Human-Epic 1: {Name}
- **When**: Before Wave N / During Wave N / After Wave N
- **Blocks**: Epic N, Epic M
- **Instructions**: [Step-by-step]

## 7. Execution Strategy
### 7.1 Wave Breakdown
### 7.2 Parallel Agent Allocation
### 7.3 Dependency Graph (ASCII)
### 7.4 Integration Points
### 7.5 Verification Gates

## 8. Testing Strategy
### 8.1 Unit Tests (per epic)
### 8.2 Integration Tests
### 8.3 E2E Tests (Playwright)
### 8.4 Test Coverage Targets

## 9. Post-Implementation Integration

Getting the system from "code merged" to "app live and testable" is a first-class deliverable of this plan, not an afterthought. This section is the runbook for every transition.

### 9.1 Per-Wave Bring-Up Runbook

For each wave, a single ordered checklist that executes AFTER the wave's PRs merge and BEFORE the next wave begins:

```
Wave N Bring-Up:
1. Pull latest main in all active clones
2. Install new dependencies if package manifests changed: `{pnpm install | npm install}`
3. Run new DB migrations: `{exact commands, in order}`
4. Regenerate types if schema changed: `{exact command}`
5. Set new env vars/secrets: `{exact commands or file updates}`
6. Restart local dev servers: `{frontend, backend, workers, background jobs}`
7. Trigger/verify production deploys: `{commands or dashboard links}`
8. Invalidate caches if needed: `{exact commands}`
9. Load/update seed data if needed: `{exact commands}`
10. Smoke test: `{exact command or manual steps that prove all layers are live}`
```

Every step has an exact command or link. Vague instructions like "restart the server" do not belong here.

### 9.2 Local vs. Production Parity

Specify which bring-up steps apply to local vs. production vs. both. Production deploys often need extra steps (DNS propagation, CDN cache purge, health checks) that local doesn't.

### 9.3 Rollback Plan

For each wave's bring-up, specify the rollback: how to revert migrations, redeploy previous version, restore env vars. Rollback needs to be as well-defined as roll-forward.

### 9.4 Final Bring-Up (end of execution)

The last-wave bring-up runbook that takes the fully-merged project to a confirmed-live state. This is the single source of truth for "app is ready to test". Anything that was deferred or flagged during waves gets resolved here.

## 10. Review Findings
[Only sections for reviews selected in Phase 4.0]
### 10.1 Security Review Summary (if selected)
### 10.2 Architecture Review Summary (if selected)
### 10.3 Business Logic Review Summary (if selected)
### 10.4 Changes Made Based on Reviews

## 11. Risk Register
| Risk | Severity | Likelihood | Mitigation | Owner |
|------|----------|------------|------------|-------|

## 12. Scope Estimate
[See Phase 5.5 for generation details]

## 13. Post-Execution Verification Checklist
- [ ] All agent-epics completed and merged
- [ ] All tests passing (unit, integration, e2e)
- [ ] No open PRs (except human-blocked)
- [ ] No uncommitted changes in any clone
- [ ] No open issues (except human-agent/human-epic)
- [ ] CI/CD pipeline green
- [ ] **Final Bring-Up runbook (Section 9.4) executed end-to-end**
- [ ] **All app layers confirmed live: frontend loads, backend responds, DB reachable, migrations applied, deploys current**
- [ ] **Smoke test passes against the running system**
- [ ] All review findings addressed
- [ ] README.md generated and merged
```

### Phase 5.5: Scope Estimate

Add to plan.md Section 12:

```markdown
## 12. Scope Estimate

| Metric | Count |
|--------|-------|
| Total agent-epics | N |
| Total human-epics | N |
| Waves | N |
| Max parallel agents per wave | N |
| Total GitHub issues to create | N |
| Estimated PRs | N |
| Foundation (sequential) epics | N |
| Parallel epics | N |
| Integration epics | N |

### Agent Allocation by Wave
| Wave | Epics | Agents Needed | Clone Assignment |
|------|-------|---------------|------------------|
| 1 | ... | ... | ... |
| 2 | ... | ... | ... |

### Human Work Summary
| Human-Epic | Can Do During Execution? | Blocks |
|------------|--------------------------|--------|
```

---

### Phase 5.6: Plan Quality Self-Review (MANDATORY)

**Prerequisite**: plan.md and Section 12 (Scope Estimate) have been written.

**Goal**: Catch vague, placeholder, or internally inconsistent plan content before the user (or downstream execution agents) relies on it. Vague tasks and type-name drift are the two most common reasons parallel execution agents produce divergent implementations from the same plan.

**Announce at start**: "I'm running the Phase 5.6 plan-quality self-review - scanning for placeholders and type-consistency issues before the final gate."

This phase is a tight loop: scan, fix, rescan. Do not advance to Phase 6 while any check fails.

#### 5.6.1 Placeholder Scan

Scan the plan output for placeholder patterns. "Plan output" means ALL files written in this run:

- `~/code/plans/{concept-name}/plan.md`
- `~/code/plans/{concept-name}/decisions.md`
- `~/code/plans/{concept-name}/naming.md` (if Phase 2 ran)
- `~/code/plans/{concept-name}/progress.md` (if it exists yet)

Run a literal scan for forbidden patterns:

```bash
cd ~/code/plans/{concept-name}
grep -nE 'TBD|TODO|\[fill in\]|\[placeholder\]|similar to (Task|Epic) [0-9]|add appropriate (error handling|validation|tests)|write tests for the above|etc\.$|\.\.\.$|<insert|<fill' plan.md decisions.md naming.md progress.md 2>/dev/null
```

Also scan for soft placeholders that the grep won't catch - read the plan and look for:

- Epics with acceptance criteria like "works correctly" or "as appropriate" instead of concrete verifiable outcomes
- File lists that end in "etc." or "..." instead of being exhaustive
- Bring-up steps that say "restart the server" instead of the exact command
- "See above" or "same as Epic N" references that require the reader to reconstruct scope from another epic
- Code blocks labeled as snippets rather than complete, drop-in content

**Forbidden patterns (non-exhaustive)**:
- `TBD`, `TODO`, `[fill in]`, `[placeholder]`, `<insert ...>`, `<fill ...>`
- `similar to Task N`, `similar to Epic N`, `same as above`, `see above`
- `add appropriate error handling`, `add appropriate validation`, `add appropriate tests`
- `write tests for the above`
- Sentences that trail off with `etc.` or `...` where a concrete list belongs

**If any placeholder is found**: fix it in place by filling in the concrete content (exact file path, exact command, exact acceptance criterion, full code block). Do NOT delete the section - the section's presence means the information is needed. Re-run the scan after edits.

#### 5.6.2 Type & Identifier Consistency Scan

Plans frequently drift on the names of types, functions, database fields, env vars, and file paths across sections and across documents. Epic 3 calling a helper `clearLayers()` while Epic 7 calls the same helper `clearFullLayers()` will produce divergent implementations.

Extract the canonical identifier set from the plan and check for drift:

1. **Collect all proper-noun identifiers** referenced across plan.md, decisions.md, and naming.md. These include:
   - Type / interface / class names (e.g., `UserProfile`, `AgentEpic`)
   - Function / method names (e.g., `clearLayers`, `scheduleDraw`)
   - Database table and column names
   - Environment variable names (e.g., `CLOUDFLARE_API_TOKEN`)
   - File paths (e.g., `src/lib/agent-tracking.ts`)
   - Route / endpoint paths (e.g., `/api/users/:id`)
   - Package names and import aliases

2. **For each identifier**, grep across the plan output and verify it is spelled identically everywhere:

   ```bash
   cd ~/code/plans/{concept-name}
   grep -n 'IdentifierName' plan.md decisions.md naming.md progress.md 2>/dev/null
   ```

3. **Flag near-duplicates** - same concept, different names. Common patterns:
   - `clearLayers` vs `clearFullLayers` vs `resetLayers`
   - `userId` vs `user_id` vs `uid`
   - `VITE_SUPABASE_KEY` vs `VITE_SUPABASE_PUBLISHABLE_KEY`
   - `src/lib/foo.ts` vs `src/lib/Foo.ts` vs `apps/web/src/lib/foo.ts`
   - `AgentEpic` vs `Agent-Epic` vs `agent_epic`

4. **Cross-document consistency** - identifiers that appear in multiple plan docs (plan.md, decisions.md, naming.md, progress.md) MUST use the exact same spelling, casing, and path in all of them. A decisions.md entry that chose Drizzle cannot coexist with a plan.md that references Prisma.

**If any drift is found**: pick the canonical form (usually the one most consistent with the tech stack and naming conventions), update every occurrence, and re-run the scan. Record the canonical choice in decisions.md if the drift represented an actual choice between candidates.

#### 5.6.3 Granularity & Concreteness Check

Each agent-epic must be executable by a sub-agent without needing to ask the orchestrator for clarification. Check every Epic section in plan.md:

- **Exact file paths** - every file created or modified is listed by absolute-within-repo path, not by description ("the auth handler")
- **Complete code blocks** - any code shown in the plan is drop-in complete, not a snippet with "..." gaps
- **Verifiable acceptance criteria** - every acceptance checkbox describes something the agent can run a command or test to confirm (not "works correctly")
- **Explicit bring-up** - the Bring-up steps field lists exact commands, not descriptions
- **Named dependencies** - "Dependencies" lists specific epic names or "None", not "the previous work"

If any epic fails these checks, rewrite it until it passes. An epic that cannot be scoped concretely belongs in a different epic structure - consider splitting or merging.

#### 5.6.4 Loop Until Clean

Re-run 5.6.1, 5.6.2, and 5.6.3 after every round of fixes. Do not advance to Phase 6 until all three scans report zero findings. If three consecutive passes do not converge (new placeholders or drift keep appearing), stop and surface the specific section(s) to the user - the plan likely has a structural ambiguity that needs a human decision.

**Self-review output**: Append a short block to `decisions.md` recording that the self-review ran and what it found:

```markdown
## Plan Quality Self-Review (Phase 5.6)
- Placeholder scan: clean / fixed {N} instances
- Type-consistency scan: clean / fixed {N} instances (canonical forms: {list})
- Granularity check: clean / rewrote {N} epics
- Final pass: clean
```

---

## Phase 6: Final Confirmation Gate

### 6.0 Mode Split

**If `--light` flag is active**: Run the full interactive walkthrough (sections 6.1-6.4 below) before the final gate (6.5). This is the traditional pre-execution review.

**If interactive mode (not --light)**: The user has already reviewed research (Phase 1.5), approved the tech stack (Phase 2.5), approved the high-level scope (Phase 2.6), and confirmed the multi-agent setup (Phase 2.7). Skip sections 6.1-6.4. Go directly to 6.5.

---

### 6.1 Research Walkthrough (--light only)

Walk the user through `research.md`:
- Present the executive summary and contextual model
- Highlight key insights
- Discuss risks and unknowns
- Use AskUserQuestion to collect feedback before advancing
- Update research.md with any changes

### 6.2 Plan Walkthrough (--light only)

Walk through `plan.md` section by section:
- Present each section one at a time
- Use AskUserQuestion after EVERY section to get feedback or confirmation before advancing
- Update plan.md in real-time with any changes
- Pay special attention to: tech stack choices, epic breakdown, scope estimate, prerequisites, human-epics

### 6.3 Present Prerequisites (--light only)

Present everything needed before or during execution with walkthrough-style instructions for each item.

### 6.4 Confirm Naming (--light only)

If naming was done in Phase 2, confirm the chosen name. If not done, ask if they want to choose a name now.

---

### 6.5 Final Execution Gate (MANDATORY - both modes)

**HARD GATE - NON-BYPASSABLE - MANDATORY REGARDLESS OF PERMISSION MODE**

Before asking, re-verify:

```bash
ls -la ~/code/plans/{concept-name}/reviews/{selected-reviews} \
       ~/code/plans/{concept-name}/plan.md
```

If any selected review file is missing, STOP. Go back to Phase 4.

Use AskUserQuestion:

```
question: "Plan complete and reviewed. Ready to proceed?\n\nQuick summary:\n- [N] agent-epics across [N] waves\n- Up to [N] parallel agents\n- [N] human-epics (things you'll need to do)"
options:
  - "Proceed to execution"
  - "Revisit a section (I'll specify which)"
  - "Stop here - save plan, don't execute yet"
```

**This question is NON-NEGOTIABLE.** Do NOT proceed to Phase 7 without an explicit "Proceed to execution" from the user. No autonomy setting, permission bypass, or global instruction overrides this gate. If the user selects "Stop here", save the plan state and end gracefully.

---

## Phase 7: Execution

**PREREQUISITE**: Phase 6.5 must have completed with explicit "Proceed to execution". Do NOT proceed otherwise.

### 7.1 Pre-Execution Setup

1. **Create GitHub repo** (private):
   ```bash
   gh repo create {username}/{project-name} --private --description "{description}"
   ```

2. **Create local clones** based on Phase 2.7 decision:
   ```bash
   # Flat clone model:
   mkdir -p ~/code/{project-name}-repos
   for i in 0 1 2 3; do
     gh repo clone {username}/{project-name} ~/code/{project-name}-repos/{project-name}-$i
   done

   # Workspace model: use /workspace-setup {project-name} instead
   ```

3. **Create CLAUDE.md** in the repo with project-specific instructions

4. **Create GitHub labels**:
   ```bash
   gh label create "agent-epic" --color "5319E7"
   gh label create "human-epic" --color "B60205"
   gh label create "human-agent" --color "D93F0B"
   gh label create "epic" --color "3E4B9E"
   gh label create "blocked" --color "B60205"
   ```

5. **Initialize issue tracking**:
   ```bash
   python3 ~/.claude/lib/agent_tracking.py init {project-name}
   ```

6. **Create GitHub issues** for every epic and sub-task:
   - One issue per agent-epic with full scope description and acceptance criteria
   - One issue per human-epic with walkthrough instructions
   - Issues reference their wave and dependencies

7. **Initialize progress.md**:
   ```markdown
   # Execution Progress: {Project Name}

   ## Status: IN PROGRESS
   ## Started: {timestamp}
   ## Plan: ~/code/plans/{concept-name}/plan.md

   | Epic | Issue | Agent | Clone | Wave | Status | PR | Notes |
   |------|-------|-------|-------|------|--------|----|-------|

   ## Checkpoints
   ```

### 7.2 Inform User of Human-Epics

Before spinning up agents, list all human-epics with:
1. Instructions for each
2. Which can be done NOW (while agents work)
3. Which must wait until a specific wave completes

### 7.3 Execute Waves

For each wave:

#### 7.3.1 Spawn Agents

Spawn Task agents in parallel (model: sonnet), one per epic, assigned to different clones.

#### 7.3.2 Agent Work Loop

Each agent:
- Creates a feature branch (`git checkout -b {issue}-{desc} origin/main`) which auto-registers the claim in tracking.csv via the PostToolUse hook
- Implements the work with tests
- **Verifies the work actually functions** end-to-end (not just unit tests passing)
- Creates a PR
- Reports completion with verification evidence

#### 7.3.3 Monitor & Report

Monitor agent progress and report status updates to user.

#### 7.3.4 Wave Completion

When all wave agents complete:
- Verify all PRs are created and passing CI
- Verify all tests pass, no conflicts between PRs
- Merge all PRs for the wave
- **Execute the wave's Bring-Up Runbook (plan.md Section 9.1)**: run migrations in order, install new deps, regenerate types, set new env vars/secrets, restart local dev servers, trigger/verify deploys, invalidate caches, load seed data, run smoke tests. Do not declare the wave done until every step has run and passed.

#### 7.3.5 Checkpoint (MANDATORY after each wave)

Write to `progress.md`:

```markdown
## Checkpoint: Wave N Complete - {timestamp}
### Completed
- [epics with PR numbers]
### Merged to main
- [commit SHAs]
### Next wave
- Wave N+1: [epic names]
### Agent assignments
- agent-0 (clone-0): Epic X
- agent-1 (clone-1): Epic Y
### State
- All clones synced to main: yes/no
- CI status: green/red
- Bring-up runbook executed: yes/no
- All layers verified live (DB, backend, frontend, workers, deploy): yes/no
- Smoke test passed: yes/no
- Open blockers: none / [list]
### Resume context
[Key decisions, patterns established, and gotchas discovered so far]
```

This checkpoint enables `/xplan-resume` to pick up where execution left off.

#### 7.3.6 Update progress.md table and proceed to next wave.

### 7.4 Integration Verification

After each wave, AFTER the Bring-Up Runbook (7.3.4) has executed:
- Pull latest main into all clones
- Run full test suite
- **Verify every layer is live**:
  - Database: new migrations applied, no pending migrations, schema matches code
  - Backend: API responds to health check and a representative request, logs show no startup errors
  - Frontend: loads without console errors, hits the backend successfully
  - Workers/background jobs: running, processing queues, no crash loops
  - Deploy (if production-affecting): new version live at the canonical URL, old version retired
- **Run the wave's smoke test** against the running system (curl, browser automation, or explicit manual steps) - not just CI
- If any layer is broken or stale, fix it before proceeding. The next wave does NOT start against a degraded system.
- Record completion in progress.md: bring-up done, layers verified, smoke test passed

### 7.5 Continue Until Complete

**DO NOT STOP** until:
- All agent-epics completed and merged
- All tests pass
- All issues closed (except human-epic/human-agent)
- No uncommitted changes in any clone
- No open PRs
- CI is green
- Deployment working
- **Final Bring-Up (plan.md Section 9.4) executed** - all migrations applied, all services running current code, all layers confirmed live
- **End-to-end smoke test passes** against the running system - the user should be able to open the app and use it immediately

If blocked by a human-epic: create a P0 issue with exact instructions, notify the user, continue non-blocked work.

---

## Phase 8: Post-Execution Verification & Retrospective

### 8.1 Full Audit

```bash
gh issue list --state open --repo {username}/{project-name}
gh pr list --state open --repo {username}/{project-name}
for i in 0 1 2 3; do
  echo "=== Clone $i ==="
  git -C ~/code/{project-name}-repos/{project-name}-$i status
done
cd ~/code/{project-name}-repos/{project-name}-0
npm test && npm run build
```

### 8.2 Report

Present final status:
- Total epics completed / PRs merged / test results
- Any remaining human-epic issues with instructions
- Any verification issues found
- Deployment status

### 8.3 Retrospective

Generate `~/code/plans/{concept-name}/retro.md`:

```markdown
# Retrospective: {Project Name}

## Execution Summary
- **Started**: {timestamp}
- **Completed**: {timestamp}
- **Total epics**: N completed, N remaining (human-blocked)
- **Total PRs merged**: N
- **Waves executed**: N

## What Went Well
[Patterns that worked, well-scoped epics, smooth integrations]

## What Agents Struggled With
[Epics requiring rework, merge conflicts, unclear scoping, context loss]

## Scope Accuracy
| Metric | Estimated | Actual | Delta |
|--------|-----------|--------|-------|
| Agent-epics | N | N | +/-N |
| PRs | N | N | +/-N |
| Waves | N | N | +/-N |

## Key Decisions Made During Execution
[Decisions that deviated from the plan, with rationale]

## Gotchas & Lessons Learned
[Technical gotchas, tooling issues, patterns to remember for future plans]

## Recommendations for Similar Projects
[What to do differently for this type of project]
```

### 8.4 Save as Template (if applicable)

Ask:

> "This plan could serve as a template for future {type} projects. Want me to save a generalized version to the template library?"

If yes, create `~/code/plans/_templates/{project-type}.md` with generalized patterns stripped of project-specific details.

### 8.5 Generate README.md

**MANDATORY**: After all agent-epics are merged and the audit passes, generate a comprehensive `README.md` in the repo root. Read all source files, plan.md, research.md, and decisions.md - every claim must reflect the actual codebase.

Commit on a branch, create a PR, merge it.

README structure:
```markdown
# {Project Name}
{One-paragraph statement of purpose}

## Table of Contents
## Overview
## Tech Stack
## Architecture
## Getting Started
### Prerequisites
### Installation
### Environment Variables
## Development
## Testing
## Deployment
## Key Decisions
## Contributing
## License
```

### 8.6 Update Logs and Progress

Update agent log with full session summary. Mark progress.md as COMPLETE with final statistics and link to retro.md.

---

## Important Principles

### Human-in-the-Loop First

In interactive mode, the user is a partner in every major decision: concept clarity, research findings, tech stack, scope, and multi-agent setup. These gates happen BEFORE the expensive work, not after. The goal is to eliminate "I didn't want that" surprises.

### Token Efficiency

Use the right model for each job:
- Simple background tasks (file checks, directory setup): haiku
- Research, naming, review agents: sonnet
- Execution agents: sonnet
- Orchestrator (synthesis, architecture, interactive decisions): current session model

Keep sub-agent prompts focused and specific. Do not send more context than the agent needs.

### Parallelism is the Default

Maximize parallel agents based on the setup confirmed in Phase 2.7:
- Research happens in parallel
- Reviews happen in parallel
- Agent-epics within a wave execute in parallel
- Human-epics that can be done during agent execution should be

### Autonomy First

Do as much as possible without human intervention. Only create human-epics for things that genuinely require the user's browser session or credentials you don't have. CLI/API access replaces human actions wherever possible.

### Quality Over Speed

- Every piece of code has tests
- Every PR passes CI before merge
- **Every feature is verified to actually work** end-to-end - unit tests passing is the bare minimum, not the finish line. Mocked tests prove internal consistency; they say nothing about whether the real system functions. Use the real API, the real database, the real UI.
- Security, architecture, and business logic reviews are mandatory unless explicitly skipped

### Scope Over Time

Epic sizing is about isolation, testability, and merge safety - not clock time. A focused 3-hour epic is better than three 1-hour epics with artificial seams.

### Plans are Living Documents

- plan.md is updated during interactive phases based on user feedback
- progress.md is updated during execution with checkpoints after every wave
- decisions.md is updated whenever a significant decision is made

### Complete Execution

Plans execute until ALL completable work is done. No stopping halfway. No leaving broken or half-finished work. Every session ends with a clean state.

### Resumability

Checkpoints are written after every wave. Progress file tracks exact state for `/xplan-resume`. Each checkpoint captures enough context to resume without re-reading the entire codebase.
