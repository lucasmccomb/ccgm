---
description: Deep research + planning + execution framework for new projects
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, AskUserQuestion, WebSearch, WebFetch
argument-hint: <project concept or idea> [--repo <existing-repo-path>]
---

# xplan - Autonomous Project Planning & Execution

A comprehensive framework that deeply researches concepts, builds a contextual model, creates a parallelized execution plan, reviews it with specialized agents, walks the user through it interactively, and then autonomously executes the entire plan using parallel agents.

**Companion commands:**
- `/xplan-status` - Check progress on a running or completed plan
- `/xplan-resume` - Resume an interrupted plan execution

---

## CRITICAL: Interactive Prompts Are Mandatory

**This skill REQUIRES `AskUserQuestion` to function.** xplan is an interactive framework - the user chose to run `/xplan` precisely because they want the guided research/plan/review/walkthrough experience. Skipping prompts defeats the purpose.

**If `AskUserQuestion` is blocked** (e.g., "don't ask" mode, autonomous mode, or any permission setting that prevents it):

1. **STOP IMMEDIATELY.** Do not proceed with any phase.
2. **Tell the user explicitly:**
   > "xplan requires interactive prompts (AskUserQuestion) but your current permission mode is blocking them. Please switch to a mode that allows AskUserQuestion (e.g., normal mode or add AskUserQuestion to your allowlist) and re-run `/xplan`."
3. **Do NOT fall back to "reasonable defaults"** or guess what the user would have chosen.
4. **Do NOT proceed autonomously.** The research, review, and walkthrough configuration prompts exist because the user's choices materially change what xplan does.

**This override applies to ALL autonomy instructions**, including global CLAUDE.md rules about "don't ask, just do it." Those rules are for routine operations. xplan is not a routine operation - it is an interactive planning session that the user explicitly invoked.

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
- **`--repo <path>`**: (Optional) Path to an existing repo to analyze and plan work for
- If no arguments provided, use AskUserQuestion to ask what the user wants to plan

### 0.2 Create Plan Directory

Derive a short, descriptive kebab-case directory name from the main concept (e.g., "a SaaS for pet grooming" becomes `pet-grooming-saas`).

```bash
mkdir -p ~/code/plans/{concept-name}
mkdir -p ~/code/plans/{concept-name}/reviews
```

### 0.3 Check Template Library

Check `~/code/plans/_templates/` for existing plan templates that match this type of project. If a relevant template exists, use it to accelerate Phase 3 (plan creation) - but still do full research in Phase 1. Templates inform structure and common patterns, they do not replace research.

```bash
ls ~/code/plans/_templates/ 2>/dev/null
```

### 0.4 Existing Repo Analysis (if --repo provided)

If an existing repo path was given:
1. Read its CLAUDE.md, README.md, package.json, and key config files
2. Map its architecture, tech stack, and current state
3. Check `gh issue list` and `gh pr list` for open work
4. Read recent agent logs from your log repo for the project
5. This context feeds into Phase 1 research alongside the new concepts from the prompt

---

## Phase 1: Deep Research

**Goal**: Build a thorough contextual model of the problem space before planning anything. This is the foundation everything else builds on. Do not rush this phase.

### 1.0 Research Configuration

Before spawning agents, ask the user what kind of research they want using AskUserQuestion. Present a **preset** question first, then optionally drill into individual agents.

**Preset question** (single-select):

> "What level of research should I run?"

| Option | Agents Spawned | Best For |
|--------|---------------|----------|
| **Full (Recommended)** | All 4 core + complexity-based extras | New products, unfamiliar domains |
| **Technical Only** | Technical Architecture + Data & Infrastructure | Adding features to existing projects, technical spikes |
| **Market & Product** | Domain & Problem Space + Competitive Landscape + Monetization | Validating a product idea, market analysis |
| **Lite** | Domain & Problem Space + Technical Architecture | Quick planning, well-understood domains |
| **Custom** | User picks individual agents | Full control |

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

**Note**: If `--repo` was provided, the **Codebase Analysis Agent** is always included regardless of selection (it analyzes the existing repo, not the problem space).

### 1.1 Spawn Research Agents

Based on the user's selection in 1.0, launch the chosen research agents in parallel using the Task tool. Each agent targets a different facet.

**Available research agents (spawn only those selected):**

1. **Domain & Problem Space Agent** - Research the core problem domain. What does this space look like? Who are the users? What are their pain points? What existing solutions exist? What do they get right and wrong? What market gaps exist?

2. **Technical Architecture Agent** - Research the best technical approaches for this type of system. What architectures work best? What are the scalability concerns? What are the data modeling challenges? What are the performance considerations? Research specific technical challenges unique to this domain.

3. **Competitive Landscape Agent** - Deep dive on existing products, apps, and tools in this space. Feature matrices. Pricing models. User reviews and complaints. What is missing from the market? What would make this product stand out?

4. **Adjacent Domains Agent** - What related fields, technologies, or concepts should inform the design? What lessons from adjacent industries apply? What integrations would users expect? What regulatory or compliance considerations exist?

5. **UX/Design Patterns Agent** - Research UI/UX patterns for this type of application. What conventions do users expect? What innovative approaches exist?

6. **Data & Infrastructure Agent** - Research data storage patterns, API design approaches, and infrastructure requirements specific to this problem

7. **Monetization & Business Model Agent** - Research pricing strategies, conversion funnels, and business models that work in this space

If `--repo` was provided, always also spawn:
- **Codebase Analysis Agent** - Deep dive into the existing repo's architecture, patterns, tech debt, test coverage, and current state

### 1.2 Synthesize Research

Once all research agents return:
1. Synthesize findings into a **contextual model** - a mental framework for how to think about this problem and its solution
2. Identify key insights that should drive architectural and product decisions
3. Flag risks, unknowns, and areas that need user input
4. Document everything in `research.md`

### 1.3 Write research.md

Create `~/code/plans/{concept-name}/research.md` with:

```markdown
# Research: {Concept Name}

## Table of Contents

## Executive Summary
[2-3 paragraph synthesis of all research findings]

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
[Numbered list of the most important findings that should drive decisions]

## Risks & Unknowns
[Identified risks with severity and mitigation strategies]

## Sources
[Links and references from research]
```

---

## Phase 2: Naming Ideation (Optional)

After research is complete, ask the user:

> "Research is complete. Before I start planning, would you like me to spin up an agent to brainstorm project names and check domain availability? This agent will generate name ideas based on the research and verify .com, .io, .ai, .pro, and .work domain availability."

If yes:

### 2.1 Spawn Naming Agent

Launch a Task agent that:
1. Generates 15-25 name candidates based on the research and concept
2. Considers: memorability, brandability, brevity, relevance, uniqueness
3. Checks for conflicts with existing apps/products (web search)
4. Checks domain availability for each name across: `.com`, `.io`, `.ai`, `.pro`, `.work`
   - Use `dig` or web search to verify domain availability
5. Checks npm package name availability (if relevant)
6. Checks GitHub org/repo name availability
7. Ranks names by overall viability

### 2.2 Write naming.md

Save results to `~/code/plans/{concept-name}/naming.md` with a ranked table:

```markdown
# Name Ideation: {Concept}

| Rank | Name | .com | .io | .ai | .pro | .work | Conflicts | Notes |
|------|------|------|-----|-----|------|-------|-----------|-------|
| 1    | ... | ... | ... | ... | ... | ... | ... | ... |
```

### 2.3 Present to User

Show the top 5 names and ask the user to pick one (or provide their own). The chosen name becomes the project name used throughout the plan.

---

## Phase 3: Plan Creation

**Goal**: Create a comprehensive, parallelized execution plan divided into agent-epics.

### 3.1 Tech Stack Selection

Select the optimal tech stack based on:
- **Research findings** from Phase 1 (what the problem actually demands)
- **Best tool for each job** - do NOT default to familiar tools. Evaluate options objectively.
- **Performance requirements** identified in research
- **Scale requirements** identified in research
- **Template patterns** from Phase 0.3 (if a matching template was found)

**Hard constraints** (unless a competitor has a clear, documented advantage):
- **Cloud**: Cloudflare (Pages, Workers, D1/KV/R2, DNS, domain registration) - keep everything tightly coupled on CF
- **Email**: Resend
- **Auth**: Google OAuth initially, architected for adding more providers later
- **E2E Testing**: Playwright
- **CI/CD**: GitHub Actions

**Banned** (never use, no exceptions):
- **Vercel (entire ecosystem)** - No Vercel services, hosting, platform, or any package under the Vercel/AI SDK umbrella. This includes: `ai`, `@ai-sdk/*`, `next`, `@next/*`, `@vercel/*`, `v0`, `turbo`, `turborepo`, `swr`. Nothing with Vercel's name on it.
- **Next.js** - No Next.js. For React apps, prefer Vite + React Router (or equivalent). For SSR needs, consider Astro, Remix, or Cloudflare Workers with a React renderer.
- **AI SDK alternatives** - For LLM integration, use provider SDKs directly: `@anthropic-ai/sdk`, `openai`, `@google/generative-ai`. Build streaming UI hooks manually or use a non-Vercel abstraction layer.

For everything else (language, framework, database, state management, etc.), choose based purely on what is best for this specific problem. Document the reasoning for each choice.

### 3.2 Architecture Design

Design the system architecture including:
- Component diagram (described in text/ASCII)
- Data model overview
- API design approach
- Authentication & authorization flow
- Deployment architecture (Cloudflare services map)
- Monitoring & observability approach

### 3.3 Define Agent-Epics

Break the plan into **agent-epics**: large, isolated chunks of work that a single agent can complete autonomously.

**Sizing principle**: The constraint is **scope isolation**, not time. An agent can work for hours on a well-scoped epic. What matters is:

- **Isolation** - Does this epic have clear boundaries? Can the agent work without stepping on other agents' files?
- **Testability** - Can the output be independently verified? Does the epic produce working, tested code on its own?
- **Merge safety** - Will this epic's changes conflict with concurrent agents? If so, it needs to be sequenced, not parallelized.
- **Context coherence** - Is the scope focused enough that the agent will not lose critical context during long execution? A sprawling epic touching 15 unrelated files is worse than a focused one touching 30 related files.

Split an epic into multiple when:
- It spans multiple unrelated subsystems
- It requires context from too many disparate parts of the codebase
- Its changes would conflict with another concurrent epic
- It mixes infrastructure work with feature work

Do NOT split just because the work is large. A 3-hour epic that is focused, isolated, and testable is better than three 1-hour epics with artificial seams between them.

Rules for agent-epics:
- Each epic is **isolated** - minimal file overlap with other concurrent epics
- Each epic results in **working, tested code**
- Epics include their own tests (unit + integration)
- Define clear **inputs** (what must exist before this epic starts) and **outputs** (what exists when complete)
- Identify **dependency order** - which epics can run in parallel vs. which must be sequential

Epic categories:
- **Foundation epics**: Repo setup, CI/CD, shared types, config - these run first
- **Parallel epics**: Independent feature work that can run simultaneously
- **Integration epics**: Work that connects parallel streams - runs after its dependencies
- **Testing epics**: E2E test suites, load testing, etc.
- **Human-epics**: Work requiring human intervention (API key setup, service signups, DNS config)

### 3.4 Define Human-Epics

Identify ALL work that requires human intervention. For each:
- Exact step-by-step instructions (walkthrough-style)
- When it needs to happen relative to agent-epics (what it blocks)
- Whether it can be done in parallel with agent execution
- Links to relevant dashboards/services

**Minimize human-epics**. For each one, ask: "Can this be done via CLI/API instead?" If yes, make it an agent-epic with the CLI/API approach. Only create human-epics for things that genuinely require browser-based human action (OAuth app creation in Google Console, payment provider setup, etc.).

### 3.5 Define Prerequisites

Before execution begins, identify everything needed:
- API keys and credentials the user must provide
- CLI tools that must be installed
- Services that must be signed up for
- DNS/domain configuration
- Any other blockers

These are presented to the user during the walkthrough so they can prepare.

### 3.6 Execution Strategy

Define:
- **Wave 1**: Foundation epics (sequential, must complete first)
- **Wave 2+**: Parallel epic groups with their dependency constraints
- **Agent allocation**: How many agents to run in parallel for each wave
- **Integration points**: Where parallel streams merge
- **Verification gates**: Checkpoints where all work is verified before proceeding

### 3.7 Create decisions.md

Create `~/code/plans/{concept-name}/decisions.md`:

```markdown
# Decision Log: {Project Name}

| # | Decision | Options Considered | Rationale | Date |
|---|----------|--------------------|-----------|------|
| 1 | ... | ... | ... | ... |
```

Document every significant technical and product decision made during planning.

---

## Phase 4: Plan Review

**MANDATORY**: Before presenting the plan to the user, run review agents. The user chooses which reviews to run.

### 4.0 Review Configuration

Ask the user what level of review they want using AskUserQuestion. Present a **preset** question first, then optionally drill into individual reviewers.

**Preset question** (single-select):

> "What level of plan review should I run?"

| Option | Reviewers Spawned | Best For |
|--------|------------------|----------|
| **Full (Recommended)** | Security + Architecture + Business Logic | New products, anything user-facing |
| **Technical Only** | Security + Architecture | Internal tools, technical features |
| **Architecture Only** | Architecture | Small features, well-understood domains |
| **Security Only** | Security | When you just want a security gut-check |
| **Skip Review** | None | Iterating fast on a known pattern (plan goes straight to walkthrough) |
| **Custom** | User picks individual reviewers | Full control |

If the user selects **Custom**, follow up with a multi-select AskUserQuestion:

> "Which review agents should I spawn?"

Options (multiSelect: true):
1. **Security** - Auth flow vulnerabilities, data exposure, OWASP Top 10, secrets management, RLS/access control
2. **Architecture** - Scalability, over/under-engineering, tech stack optimization, data model, single points of failure
3. **Business Logic** - Alignment with research, user needs coverage, competitive advantages, epic completeness, edge cases

**Note**: If "Skip Review" is selected, Phase 4.1-4.4 are skipped entirely. The plan proceeds directly to Phase 5 (write plan.md) and then Phase 6 (walkthrough). The walkthrough is still mandatory.

### 4.1 Spawn Review Agents

Based on the user's selection in 4.0, launch the chosen review agents in parallel using the Task tool.

**Available review agents (spawn only those selected):**

1. **Security Review Agent**
   - Review the planned architecture for security vulnerabilities
   - Check auth flow design, data exposure risks, API security
   - Verify OWASP Top 10 coverage
   - Check for secrets management approach
   - Review RLS/access control design
   - Output: `~/code/plans/{concept-name}/reviews/security.md`

2. **Architecture Review Agent**
   - Review for scalability, maintainability, and performance
   - Check for over-engineering or under-engineering
   - Verify the tech stack choices are optimal
   - Review data model for normalization and query patterns
   - Check for single points of failure
   - Verify cloud services are used appropriately
   - Output: `~/code/plans/{concept-name}/reviews/architecture.md`

3. **Business Logic Review Agent**
   - Review the plan against the research findings
   - Verify all user needs identified in research are addressed
   - Check that the competitive advantages are preserved in the plan
   - Verify the epic breakdown covers all features
   - Look for missing edge cases or user flows
   - Output: `~/code/plans/{concept-name}/reviews/business-logic.md`

### 4.2 Wait for ALL Selected Review Agents to Complete

**HARD GATE - NO EXCEPTIONS** (unless "Skip Review" was selected in 4.0):

All selected review agents MUST be launched in **foreground** (not background). Do NOT proceed to Phase 4.3, 5, or 6 until every selected agent has returned. If an agent is slow, wait. Do NOT start writing plan.md. Do NOT start the walkthrough. Do NOT present anything to the user. You are blocked here until all selected agents finish.

If "Skip Review" was selected in 4.0, skip to Phase 5.

### 4.3 Verify Reviews Exist (MANDATORY GATE)

Before doing ANYTHING else, verify that all **selected** review files exist:

```bash
# MANDATORY - Check only the reviews that were selected in 4.0
# Adjust this list based on user's selection
for f in {selected-reviews}; do
  if [ ! -f ~/code/plans/{concept-name}/reviews/$f ]; then
    echo "BLOCKED: $f missing - review agent did not complete"
  fi
done
```

If ANY selected file is missing, you are **BLOCKED**. Do NOT proceed. Wait for the missing agent or re-spawn it.

If "Skip Review" was selected in 4.0, skip to Phase 5.

### 4.4 Incorporate Review Feedback

Only after 4.3 passes (all selected review files exist), read all review files. For each finding:
- **Critical issues**: Must be addressed before presenting plan
- **Recommendations**: Incorporate if they improve the plan without adding scope
- **Nice-to-haves**: Note for future consideration

Revise the plan based on critical and recommended findings. The plan is NOT finalized until this revision is complete.

---

## Phase 5: Write plan.md

**Prerequisite**: Phase 4 must be FULLY complete - all selected review files verified to exist (4.3) and feedback incorporated (4.4), OR "Skip Review" was selected in 4.0. If reviews were selected and you have not run the verification check in 4.3, go back and run it now.

Create `~/code/plans/{concept-name}/plan.md` with this structure:

```markdown
# {Project Name} - Execution Plan

## Table of Contents

## 1. Overview
### 1.1 Vision
### 1.2 Key Insights from Research
### 1.3 Scope

## 2. Tech Stack
[Each choice with rationale]

## 3. Architecture
### 3.1 System Overview
### 3.2 Component Diagram
### 3.3 Data Model
### 3.4 API Design
### 3.5 Auth Flow
### 3.6 Deployment Architecture

## 4. Prerequisites
[Everything needed before execution begins]
[CLI tools, API keys, service signups, DNS config]

## 5. Agent-Epics
### Epic 1: {Name}
- **Scope complexity**: Focused / Broad (with justification if broad)
- **Dependencies**: None / Epic N
- **Wave**: 1 / 2 / 3
- **Scope**: [What this epic covers]
- **Inputs**: [What must exist before starting]
- **Outputs**: [What exists when complete]
- **Tests**: [What tests are written]
- **Files created/modified**: [List]
- **Acceptance criteria**: [Checkboxes]
- **Checkpoint notes**: [Key context to preserve if session compacts]

### Epic 2: {Name}
...

## 6. Human-Epics
### Human-Epic 1: {Name}
- **When**: Before Wave N / During Wave N / After Wave N
- **Blocks**: Epic N, Epic M
- **Instructions**: [Step-by-step walkthrough]

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

## 9. Review Findings
[Include only sections for reviews that were selected in Phase 4.0]
[If "Skip Review" was selected, note that and omit subsections]
### 9.1 Security Review Summary (if selected)
### 9.2 Architecture Review Summary (if selected)
### 9.3 Business Logic Review Summary (if selected)
### 9.4 Changes Made Based on Reviews

## 10. Risk Register
| Risk | Severity | Likelihood | Mitigation | Owner |
|------|----------|------------|------------|-------|

## 11. Scope Estimate
[See Phase 5.5 for generation details]

## 12. Post-Execution Verification Checklist
- [ ] All agent-epics completed and merged
- [ ] All tests passing (unit, integration, e2e)
- [ ] No open PRs (except human-blocked)
- [ ] No uncommitted changes in any clone
- [ ] No open issues (except human-agent/human-epic)
- [ ] CI/CD pipeline green
- [ ] Deployment working
- [ ] All review findings addressed
- [ ] README.md generated and merged
```

### Phase 5.5: Scope Estimate

Before presenting the plan, generate a scope estimate and add it to plan.md Section 11:

```markdown
## 11. Scope Estimate

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
| ... | Yes/No | Wave N |
```

Present this estimate to the user during the walkthrough so they understand the scope before committing to execution.

---

## Phase 6: Walkthrough

**HARD GATE - NON-BYPASSABLE - MANDATORY REGARDLESS OF PERMISSION MODE**

This phase MUST involve the user interactively. It cannot be skipped, auto-approved, or fast-tracked even if Claude is running with full bypass permissions, auto-approve enabled, or any other autonomy mode. The entire point of xplan is that the user reviews and approves the plan before execution begins. Without explicit human confirmation at each walkthrough step, Phase 7 (Execution) MUST NOT start.

**Before starting the walkthrough, re-verify:**

```bash
# Re-confirm all SELECTED reviews exist and plan.md was written AFTER reviews
# Only check the review files that were selected in Phase 4.0
# If "Skip Review" was selected, only verify plan.md exists
ls -la ~/code/plans/{concept-name}/reviews/{selected-reviews} \
       ~/code/plans/{concept-name}/plan.md
```

If any selected review file is missing, STOP. Go back to the incomplete phase. The walkthrough MUST use a plan that incorporates all selected review agents' feedback. If reviews were selected but not completed, the plan is a draft, not a plan. (If "Skip Review" was chosen, only plan.md needs to exist.)

Enter walkthrough mode:

### 6.1 Start with Research

Walk the user through `research.md`:
- Present the executive summary and contextual model
- Highlight key insights
- Discuss risks and unknowns
- **Use AskUserQuestion** to collect feedback. Do NOT proceed to 6.2 until the user explicitly responds.
- Update research.md with any changes

### 6.2 Walk Through the Plan

Then walk through `plan.md` section by section:
- Present each section one at a time
- **Use AskUserQuestion after EVERY section** to get the user's feedback or confirmation before advancing
- Update plan.md in real-time with any changes
- Pay special attention to:
  - Tech stack choices (user may have preferences)
  - Epic breakdown (user may want different granularity)
  - Scope estimate (does the size feel right?)
  - Prerequisites (user needs to understand what they will need to provide)
  - Human-epics (user needs to understand their role)

### 6.3 Present Prerequisites

Before asking about execution, clearly present:
1. Everything the user needs to set up before or during execution
2. Walkthrough-style instructions for each prerequisite
3. Which prerequisites block which epics
4. Which can be done in parallel with agent execution

### 6.4 Confirm Naming

If naming was done in Phase 2, confirm the chosen name. If not done, ask if they want to choose a name now.

### 6.5 Final Walkthrough Gate (MANDATORY)

After completing all walkthrough sections (6.1-6.4), use AskUserQuestion to ask:

> "Walkthrough complete. I've presented the full research and plan. Do you want to proceed to execution, or revisit any section?"

Options: "Proceed to execution" / "Revisit a section" / "Stop here (don't execute)"

**This question is NON-NEGOTIABLE.** Do NOT proceed to Phase 7 without an explicit "Proceed to execution" answer from the user via AskUserQuestion. No autonomy setting, permission bypass, or global instruction overrides this gate. If the user selects "Stop here", save the plan state and end gracefully.

---

## Phase 7: Execution

**PREREQUISITE**: Phase 6.5 must have completed with the user explicitly selecting "Proceed to execution" via AskUserQuestion. If Phase 6.5 was not completed, or the user did not explicitly approve execution, STOP and go back to Phase 6.5. Do NOT rely on any implicit approval, auto-approve setting, or permission bypass. The user must have actively chosen to proceed.

If the user confirmed execution in Phase 6.5:

### 7.1 Pre-Execution Setup

1. **Create GitHub repo** (private):
   ```bash
   gh repo create {your-username}/{project-name} --private --description "{description}"
   ```

2. **Create local clones directory and clones**:
   ```bash
   mkdir -p ~/code/{project-name}-repos
   # Create 4 clones (0-3) for parallel agent work
   for i in 0 1 2 3; do
     gh repo clone {your-username}/{project-name} ~/code/{project-name}-repos/{project-name}-$i
   done
   ```

3. **Create CLAUDE.md** in the repo with project-specific instructions

4. **Create GitHub labels**:
   ```bash
   # Agent labels
   gh label create "agent-0" --color "0E8A16"
   gh label create "agent-1" --color "1D76DB"
   gh label create "agent-2" --color "D93F0B"
   gh label create "agent-3" --color "FBCA04"
   # Epic/work labels
   gh label create "agent-epic" --color "5319E7"
   gh label create "human-epic" --color "B60205"
   gh label create "human-agent" --color "D93F0B"
   gh label create "epic" --color "3E4B9E"
   gh label create "blocked" --color "B60205"
   # Status labels
   gh label create "in-progress" --color "0E8A16"
   gh label create "in-review" --color "1D76DB"
   ```

5. **Create GitHub issues** for every epic and sub-task:
   - One issue per agent-epic with full scope description and acceptance criteria
   - One issue per human-epic with walkthrough instructions
   - Issues reference their wave and dependencies
   - Epic issues have the `agent-epic` or `human-epic` label

6. **Initialize progress.md** in the plan directory:
   ```markdown
   # Execution Progress: {Project Name}

   ## Status: IN PROGRESS
   ## Started: {timestamp}
   ## Plan: ~/code/plans/{concept-name}/plan.md

   | Epic | Issue | Agent | Clone | Wave | Status | PR | Notes |
   |------|-------|-------|-------|------|--------|----|-------|
   | ... | ... | ... | ... | ... | pending | - | ... |

   ## Checkpoints
   [Updated automatically during execution - see Phase 7.3.5]
   ```

### 7.2 Inform User of Human-Epics

Before spinning up agents:
1. List all human-epics with their instructions
2. Identify which can be done NOW (while agents work)
3. Identify which must wait until a specific wave completes
4. Provide walkthrough-style instructions for immediate human-epics

### 7.3 Execute Waves

For each wave:

#### 7.3.1 Spawn Agents
Spawn Task agents in parallel (one per epic in the wave, assigned to different clones).

#### 7.3.2 Agent Work Loop
Each agent:
- Claims its issue via label (`agent-N`, `in-progress`)
- Creates a feature branch
- Implements the work with tests
- Creates a PR
- Reports completion

#### 7.3.3 Monitor & Report
Monitor agent progress and report status updates to user.

#### 7.3.4 Wave Completion
When all agents in a wave complete, verify:
- All PRs are created and passing CI
- All tests pass
- No conflicts between PRs
Then merge all PRs for the wave.

#### 7.3.5 Checkpoint (MANDATORY after each wave)
After every wave completion, write a checkpoint to `progress.md`:

```markdown
## Checkpoint: Wave N Complete - {timestamp}
### Completed
- [List of completed epics with PR numbers]
### Merged to main
- [Commit SHAs]
### Next wave
- Wave N+1: [epic names]
### Agent assignments
- agent-0 (clone-0): Epic X
- agent-1 (clone-1): Epic Y
### State
- All clones synced to main: yes/no
- CI status: green/red
- Open blockers: none / [list]
### Resume context
[Key decisions, patterns established, and gotchas discovered so far
that a resuming session would need to know]
```

This checkpoint enables `/xplan-resume` to pick up where execution left off if the session is interrupted.

#### 7.3.6 Update progress.md
Update the progress table and proceed to next wave.

### 7.4 Integration Verification

After each wave:
- Pull latest main into all clones
- Run full test suite
- Verify no regressions
- Fix any integration issues before proceeding

### 7.5 Continue Until Complete

**DO NOT STOP** until:
- All agent-epics are completed and merged
- All tests pass
- All issues are closed (except human-epic/human-agent issues)
- No uncommitted changes in any clone
- No open PRs
- CI is green
- Deployment is working (if applicable)

If blocked by a human-epic:
1. Create a P0 issue in GitHub with exact instructions
2. Notify the user with walkthrough-style steps
3. Continue with any non-blocked work
4. Return to blocked work once user resolves the blocker

---

## Phase 8: Post-Execution Verification & Retrospective

When all agents report complete:

### 8.1 Full Audit

Run comprehensive checks:
```bash
# Check all issues
gh issue list --state open --repo {your-username}/{project-name}

# Check all PRs
gh pr list --state open --repo {your-username}/{project-name}

# Check all clones for uncommitted changes
for i in 0 1 2 3; do
  echo "=== Clone $i ==="
  git -C ~/code/{project-name}-repos/{project-name}-$i status
done

# Run full test suite
cd ~/code/{project-name}-repos/{project-name}-0
npm test
npm run build
```

### 8.2 Report

Present final status:
- Total epics completed
- Total PRs merged
- Test results
- Any remaining human-epic issues with instructions
- Any issues found during verification
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
[Patterns that worked, epics that were well-scoped, smooth integrations]

## What Agents Struggled With
[Epics that required rework, merge conflicts, unclear scoping, context loss]

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
[What to do differently next time for this type of project]
```

### 8.4 Save as Template (if applicable)

If this plan type could benefit future projects, ask the user:

> "This plan could serve as a template for future {type} projects. Want me to save a generalized version to the template library?"

If yes:
```bash
mkdir -p ~/code/plans/_templates
```

Create `~/code/plans/_templates/{project-type}.md` with:
- Generalized version of the plan structure
- Tech stack recommendations (with rationale patterns, not hardcoded choices)
- Common epic patterns for this type of project
- Lessons learned from the retro
- Typical risks and mitigations

Strip all project-specific details. Keep the structural patterns and decision frameworks.

### 8.5 Generate README.md

**MANDATORY**: After all agent-epics are merged and the audit passes, generate a comprehensive `README.md` in the repo root. This is the final code artifact of plan execution.

Read all source files, plan.md, research.md, and decisions.md to produce an accurate README. Do not guess - every claim in the README must reflect the actual codebase.

Commit the README on a branch, create a PR, merge it.

```markdown
# {Project Name}

{One-paragraph statement of purpose - what this project does and why it exists}

## Table of Contents

## Overview
[Expanded description: what it does, who it is for, key differentiators]

## Tech Stack
| Layer | Technology | Rationale |
|-------|------------|-----------|
| Frontend | ... | ... |
| Backend | ... | ... |
| Database | ... | ... |
| Auth | ... | ... |
| Hosting | ... | ... |
| Email | ... | ... |
| CI/CD | ... | ... |
| Testing | ... | ... |

## Architecture
### System Overview
[High-level description of how components fit together]

### Component Diagram
[ASCII diagram of major components and their relationships]

### Data Model
[Key entities and relationships]

### API Design
[API style, key endpoints/routes, auth scheme]

## Getting Started
### Prerequisites
[Required tools, runtimes, accounts]

### Installation
[Step-by-step clone, install, configure]

### Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| ... | ... | ... |

## Development
### Running Locally
[Exact commands to start dev server]

### Project Structure
[Directory tree with descriptions of key directories]

### Key Patterns
[Important architectural patterns, conventions, or abstractions used in the codebase]

## Testing
### Running Tests
[Commands for unit, integration, e2e tests]

### Test Structure
[Where tests live, naming conventions, what is covered]

### E2E Tests
[Playwright setup, how to run, what flows are covered]

## Deployment
[How the app is deployed, CI/CD pipeline, environments]

## Key Decisions
[Summary of the most important architectural and product decisions, with rationale.
Pull from decisions.md but keep it concise - link to decisions.md for full log]

## Contributing
[Branch naming, commit format, PR process, code review expectations]

## License
[License type]
```

### 8.6 Update Logs and Progress

Update agent log with full session summary.

Mark progress.md as COMPLETE with final statistics and link to retro.md.

---

## Important Principles

### Autonomy First
- Do as much as possible without human intervention
- If CLI/API access can replace a human action, use it
- Only create human-epics for things that genuinely require the user's browser session or credentials you do not have

### Quality Over Speed
- Every piece of code has tests
- Every PR passes CI before merge
- Security, architecture, and business logic reviews are mandatory
- Post-execution verification is mandatory

### Parallelism is the Default
- Research happens in parallel
- Reviews happen in parallel
- Agent-epics within a wave execute in parallel
- Human-epics that can be done during agent execution should be

### Scope Over Time
- Epic sizing is about isolation, testability, and merge safety - not clock time
- A focused 3-hour epic is better than three 1-hour epics with artificial boundaries
- Split when scopes overlap or context would be lost, not when work is "too big"

### Plans are Living Documents
- plan.md is updated during walkthrough based on user feedback
- progress.md is updated during execution with checkpoints after every wave
- decisions.md is updated whenever a significant decision is made

### Complete Execution
- Plans execute until ALL completable work is done
- No stopping halfway through
- No leaving broken or half-finished work
- Every session ends with a clean state

### Resumability
- Checkpoints are written after every wave (Phase 7.3.5)
- Progress file tracks exact state for `/xplan-resume`
- Each checkpoint captures enough context to resume without re-reading the entire codebase
- Use `/xplan-status` to check on running or completed plans
