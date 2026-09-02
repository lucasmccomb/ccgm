---
description: Interactive deep research + planning + execution framework for new projects and features
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <project concept or idea> [--repo <existing-repo-path>] [--light | --autonomous] [--deepen [<plan-dir>]]
---

# xplan - Interactive Project Planning & Execution

A human-in-the-loop planning framework that interviews you upfront, deeply researches your concept, builds a contextual model, proposes tech stack and architecture for your sign-off, creates a parallelized execution plan, reviews it with specialized agents (constructive peer review + a 3-pass sequential adversarial review — 6 independent reviews in the full configuration), and then autonomously executes using parallel agents.

**Three Modes:**

| Mode | Interview | Research | Tech Stack | Scope | Reviews | Walkthrough |
|------|-----------|----------|------------|-------|---------|-------------|
| **Default** (interactive) | Full Q&A | Full | Approved by user | Approved by user | Configurable standard + **adversarial sequence** | Skipped (user already approved inline) |
| **`--light`** | Skipped | Reduced (inferred) | Internal default | Internal | Optional (no adversarial sequence) | Full section-by-section at end |
| **`--autonomous`** | Skipped | **Full** | Internal (best-fit) | Internal (best-fit) | **Full standard + adversarial sequence (always)** | Structured plan-as-artifact presentation at end |

**Reviews are two-staged**: Phase 4 runs the standard *constructive* peer review (security / architecture / business-logic) against the draft; Phase 5.7 then runs an *adversarial* review sequence — **3 sequential `adrev-reviewer` passes** (the current Opus-tier model, max effort), each attacking the plan after the previous pass's fixes are incorporated, the third being the final review of the fully-hardened plan. A completed plan has had **six independent reviews in the full configuration** (3 standard + 3 adversarial).

`--light` is the *fast* path - reduced depth, minimal interaction. `--autonomous` is the *deep* path - maximum depth, zero interruption until the final gate. Pick `--autonomous` when you know exactly what you want to plan and prefer reviewing a finished artifact to answering questions during creation.

**Flags:**
- `--repo <path>` - Analyze and plan work for an existing repo
- `--light` - Skip the interactive interview phases; uses minimal clarification + traditional walkthrough at the end (old xplan behavior)
- `--autonomous` (alias: `-a`) - Skip ALL mid-flow prompts; run the full research + planning + review pipeline end-to-end using best-guess inference, then present the completed plan as a structured artifact for review at the final gate. Mutually exclusive with `--light`.
- `--deepen [<plan-dir>]` - Skip fresh planning; load an existing plan and run targeted deepening passes on under-specified sections. See "Deepen Mode" below.

**Companion commands:**
- `/xplana` - Thin alias for `/xplan --autonomous`
- `/xplan-status` - Check progress on a running or completed plan
- `/xplan-resume` - Resume an interrupted plan execution

---

## Sub-Agent Model Optimization

Specify cheaper models when spawning sub-agents to conserve usage without sacrificing quality:

| Phase | Sub-Agent | Model |
|-------|-----------|-------|
| Phase 1 | Research agents (via /deepresearch) | sonnet |
| Phase 2 | Naming agent | sonnet |
| Phase 4 | Standard review agents (security, architecture, business) | sonnet |
| Phase 5.7 | **Adversarial review passes (`adrev-reviewer` ×3, sequential)** | **opus, maximum reasoning effort** |
| Phase 7 | Execution agents (epic implementation) | sonnet |

The orchestrator (this session) stays on the current model for all synthesis, architecture, and interactive decisions. Simple background tasks (file checks, directory setup, issue creation) can use haiku if spawned as agents.

**Exception — never downgrade the Phase 5.7 adversarial reviewers.** They are the deep-scrutiny pass; reviewer quality dominates token cost there. Always dispatch them on `opus` at maximum reasoning effort, even when other phases are running on cheaper models.

---

## CRITICAL: Interactive Prompts Are Mandatory

**This skill REQUIRES user interaction to function** (unless `--autonomous` is set - see below). xplan is an interactive framework - the user chose to run `/xplan` precisely because they want the guided research/plan/review experience. Skipping prompts defeats the purpose.

**Exception - `--autonomous` mode**: When `--autonomous` is active, ALL mid-flow `AskUserQuestion` prompts are skipped by design. The user explicitly opted into no-interruption mode. The ONLY user interaction allowed is the Phase 6.5 Final Execution Gate. Treat any other prompt as a bug when autonomous mode is set. Autonomous mode does NOT disable the final gate - 6.5 always fires.

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
- **`--autonomous`** (alias `-a`): (Optional) Flag to skip ALL mid-flow prompts and run the full pipeline end-to-end. Mutually exclusive with `--light` - if both are set, error and stop.
- **`--deepen [<plan-dir>]`**: (Optional) Iteratively deepen an existing plan instead of creating a new one. Also triggered when the free-text argument is exactly `deepen` (intent keyword). If a plan directory path follows the flag, use it; otherwise fall back to the current working directory.
- If no arguments provided, use AskUserQuestion to ask what the user wants to plan (skipped in autonomous mode - error out instead, since autonomous has no interaction channel to clarify).

Store whether `--light` is active. It affects Phases 0.5, 1.5, 2.5, 2.6, 2.7, and 6.

Store whether `--autonomous` is active. It affects Phases 0.5, 1.5, 2, 2.5, 2.6, 2.7, 4.0, 5.7, and 6. Autonomous mode implies:
- All `AskUserQuestion` calls in those phases are skipped
- Research runs at Full depth (all 7 agents) unconditionally
- Reviews run at Full (security + architecture + business) unconditionally, AND the Phase 5.7 adversarial review sequence is locked ON (3 sequential `adrev-reviewer` passes on the current Opus-tier model, each incorporating its fixes before the next; any P0/P1 the final pass leaves unresolved are surfaced at the final gate rather than prompted mid-flow)
- Tech stack and scope are chosen via best-guess inference and documented in decisions.md
- The final walkthrough (Phase 6) presents the plan as a completed artifact, not per-section sign-offs
- The Phase 6.5 Final Gate still fires - it is the single user interaction point

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

**Skip Phase 0.4 entirely when no `--repo` was given** (greenfield / new project). There is nothing to fetch or verify; proceed straight to Phase 0.5. The Source Freshness Guard below NEVER runs for greenfield plans.

#### 0.4.0 Source Freshness Guard (MANDATORY when --repo is set — runs BEFORE any repo read)

A multi-clone repo often lags `origin` by many commits, and the local working tree may hold uncommitted WIP. Planning against that stale tree builds the plan on facts that no longer hold (deleted code cited as present, reversed decisions cited as current). **Treat a fetched, SHA-pinned origin default branch as the source of truth — never the bare working tree.** This guard runs once, at the very start of Phase 0.4, before reading a single repo file and before the Phase 1.1 deepresearch delegation.

```bash
REPO="<the --repo path>"

# 1. Resolve the REAL default branch (do not hardcode main).
if [ -n "$(git -C "$REPO" remote 2>/dev/null)" ]; then
  HAS_REMOTE=1
  DEFAULT_REF="$(git -C "$REPO" rev-parse --abbrev-ref origin/HEAD 2>/dev/null)"
  if [ -z "$DEFAULT_REF" ]; then
    git -C "$REPO" remote set-head origin -a >/dev/null 2>&1
    DEFAULT_REF="$(git -C "$REPO" rev-parse --abbrev-ref origin/HEAD 2>/dev/null)"
  fi
  DEFAULT_REF="${DEFAULT_REF:-origin/main}"
else
  HAS_REMOTE=0
fi

# 2. Fetch + pin the anchor, record drift, and expose a clean read surface.
if [ "$HAS_REMOTE" = "1" ]; then
  git -C "$REPO" fetch origin
  ANCHOR="$(git -C "$REPO" rev-parse "$DEFAULT_REF")"
  BEHIND="$(git -C "$REPO" rev-list --count "HEAD..$DEFAULT_REF" 2>/dev/null || echo '?')"
  [ -n "$(git -C "$REPO" status --porcelain)" ] && DIRTY=yes || DIRTY=no
  # Temp worktree at the anchor = read CURRENT code with normal Read/Glob/Grep,
  # without mutating the user's clone (no checkout, no HEAD move, no stash).
  WORKTREE="$(mktemp -d)/xplan-anchor"
  git -C "$REPO" worktree add --detach "$WORKTREE" "$ANCHOR" >/dev/null
  echo "Anchor: $DEFAULT_REF @ $ANCHOR | local HEAD is $BEHIND commits behind | dirty=$DIRTY"
  echo "VERIFICATION SOURCE (read all repo facts here): $WORKTREE"
else
  # Local-only repo: nothing to fetch. Use the working tree, but say so.
  ANCHOR="local-only (no remote)"
  WORKTREE="$REPO"
  echo "No remote on $REPO — local-only. Reading the working tree as-is; this will be noted in research.md."
fi
```

Hold `ANCHOR`, `DEFAULT_REF`, and `WORKTREE` for the rest of the run. **`WORKTREE` is the path every downstream reader (Phase 0.4.1 below, the Phase 1.1 deepresearch agent, the Phase 4 review agents) must read from — never the original `--repo` working tree.** Clean up the temp worktree at the end of the run (see Phase 8 teardown).

**Interactive vs autonomous:**
- **`--autonomous` / `/xplana`**: the guard runs automatically with NO prompt. Default behavior = verify every repo fact against `ANCHOR`. Never fast-forward the user's clone. Record the anchor + drift in `decisions.md`.
- **Interactive / `--light`**: if `BEHIND` > 0, surface it via AskUserQuestion before continuing:
  ```
  question: "Your clone of {repo} is {BEHIND} commits behind {DEFAULT_REF}. I'll plan against {DEFAULT_REF} @ {short-SHA} either way. Also fast-forward your working tree?"
  options:
    - "Plan against origin, leave my tree alone (Recommended)"
    - "Plan against origin AND fast-forward my tree (only if clean)"
  ```
  Only fast-forward (`git -C "$REPO" merge --ff-only "$DEFAULT_REF"`) when the user opts in AND `DIRTY=no`. If `DIRTY=yes`, do not offer the fast-forward option — note the WIP and proceed against the anchor.

Record in `decisions.md` immediately:
```markdown
## Source Freshness Guard (Phase 0.4.0)
- Verification anchor: {DEFAULT_REF} @ {ANCHOR}
- Local clone was {BEHIND} commits behind; dirty={DIRTY}
- Repo facts verified against: {WORKTREE} (temp worktree at anchor)
```

#### 0.4.1 Map Current State (read from the anchor worktree)

Reading **from `$WORKTREE` (the anchor), not the original clone**:
1. Read its CLAUDE.md, README.md, package.json, and key config files
2. Map its architecture, tech stack, and current state
3. Check `gh issue list` and `gh pr list` for open work (these query the remote, so they are already current)
4. Read recent agent logs from the log repo for the project
5. **Inventory the existing autonomous test coverage** — the E2E harness/runner in use (Playwright, XCUITest, a CLI harness, etc.), which surfaces have end-to-end tests, whether they run in CI, and — critically — whether the **areas this plan will touch are covered by E2E tests**. Record the coverage gaps in the touched areas: they become optimistic E2E-coverage work in Phase 3.3.5 (the assumption is the user always wants more E2E coverage). If the repo has *no* autonomous E2E suite at all, that is itself a gap to close for everything this plan touches.
6. This context feeds into Phase 1 research and Phase 0.5 interview

Every load-bearing fact pulled from the repo in this phase is anchored to `{file}:{line}` as read at `$WORKTREE`. Do not assert a repo fact from memory or from a stale working-tree Read.

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

For each selected candidate, spawn a focused agent (model: sonnet) whose entire job is to close that one gap. The agent's brief:

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

**Skip this phase entirely if `--light` OR `--autonomous` flag is active.**
- `--light`: proceed to Phase 1 with no interview. **Q8 (live-testing authorization) is deferred, not dropped** — ask it at Phase 3.3.5 point 7, once the suite's live-testing steps are known. A user is present in light mode, so the grant is available; skipping it would silently produce a `NOT AUTHORIZED` plan.
- `--autonomous`: proceed to Phase 1 with full-depth research forced (see Inference Rules below). Inferred answers must be written to `decisions.md` so they are visible during the final walkthrough. Q8 is the one question autonomous mode cannot answer for the user: record `NOT AUTHORIZED` in §8.6 and surface it at 6.A.

**Goal**: Reach 95%+ confidence about what the user wants to build before committing to research and planning. A wrong assumption at this stage cascades into hours of wasted work.

### Inference Rules (autonomous mode only)

When `--autonomous` is active, use these defaults in place of the user's answers. Record every inferred default under a "Phase 0.5 Inferences" block in `decisions.md` so the final walkthrough can surface them for correction.

| Original question | Autonomous default |
|---|---|
| Codebase type (new vs existing) | Use `--repo` flag presence. `--repo` set = existing codebase. Otherwise = new project. |
| Audience | Infer from concept language; default to "Launch as a product" when ambiguous (this enables the business-viability assessment and business-logic review). |
| V1 scope constraints | None specific - let research + plan decide. |
| Technical constraints | None - use hard defaults from Phase 2.5.2. |
| Success criteria | Derive from the concept statement and flag explicitly in the final walkthrough as "assumption to confirm". |
| Revenue model (if product) | Mark "TBD - address in final walkthrough". Do NOT block. |
| Timeline | Assume no hard deadline. |
| Research level | **Full** (all 7 agents, unconditionally). |
| Live-testing authorization (Q8) | **NOT AUTHORIZED.** Autonomous mode cannot grant it — no user is present to approve. Record `NOT AUTHORIZED` in plan §8.6 and surface it at the 6.A walkthrough. Never infer a grant from the plan's own testing needs. |

### 0.5.0 Menu-Gen Test

Before confirming what to build, ask whether it needs to exist at all. See `modules/code-quality/rules/menu-gen-test.md` for the full rule.

Forcing question: **Could this be a single prompt + multimodal call instead of an app/script/feature? If yes, why are we building anything?**

Ask the user to answer in one paragraph, or answer on their behalf in `--autonomous` mode using the concept statement. If the dissolvability score is 4-5, surface it explicitly in the final walkthrough and require a named justification before execution begins.

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

**Q8 - Live-testing environment (ALWAYS ask unless the work is provably headless-only):**

Live testing is anything that launches or relaunches an app, fires dictation, posts synthetic input events, changes focus, sets a machine-global input/audio override, opens the mic or camera, or drives a simulator/attached device from the host. It never runs on the dev machine — that machine's focus, keyboard, and dictation are the user's control channel to every agent stream running on it. See `~/.claude/rules/live-testing-guard.md`.

Ask this whenever the plan could plausibly include any such step. State plainly, in visible text before the question, which steps in the proposed work are live testing, so the user is approving something specific:

```
question: "This plan includes live testing ({name the specific steps}). Where does it run, and do you approve it there?"
options:
  - "Approved — run it on the dedicated runner machine (I'll name it)"
  - "Approved — run it on a specific device/runner (I'll specify)"
  - "Not approved — plan headless verification only"
  - "No live testing in this plan"
```

Record the answer verbatim in plan §8.6 (Live-Testing Authorization) with the date and the fact that the user granted it. **The absence of an answer is `NOT AUTHORIZED`, never an implied yes.** If the user approves, name the runner explicitly — a grant that does not name where it runs is not a grant.

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

**If `--autonomous`**: Research level is locked to **Full** - all 7 agents, no question. Proceed to 1.1.

**If `--light`**: Ask the research level question here using the same preset table as Phase 0.5.3.

**If default (interactive)**: The research level was already confirmed in Phase 0.5.3. Skip this question entirely - do not double-prompt.

### 1.1 Delegate to /deepresearch

Spawn a single agent (model: sonnet) that executes the `/deepresearch` skill with the concept, depth selection, plan directory, and repo (if provided).

The agent's prompt should be:

```
Read the file ~/.claude/commands/deepresearch.md and follow its instructions exactly.

Topic: {concept from Phase 0}
Arguments: --depth {user's selection from 0.5.3 or 1.0} --plan-dir ~/code/plans/{concept-name} {--repo WORKTREE if --repo was provided — pass the Phase 0.4.0 anchor worktree path, NOT the user's original clone}

Execute the full /deepresearch workflow: parse arguments, run the research pipeline, and write research.md to the plan directory.
```

**Anchor propagation (only when --repo was given).** Append this hard instruction to the delegation prompt so the research agent cannot read a stale tree:

```
SOURCE FRESHNESS — repo facts:
- Verification anchor: {DEFAULT_REF} @ {ANCHOR} (from Phase 0.4.0).
- The user's original working tree may be STALE (it was {BEHIND} commits behind). Read and verify EVERY repo fact against the anchor: either via the anchor worktree at {WORKTREE} (normal Read/Glob/Grep) or `git -C {REPO} show {DEFAULT_REF}:<path>`. Never a bare Read of the original --repo working tree.
- research.md MUST open with: `Verification anchor: {DEFAULT_REF} @ {ANCHOR}` and anchor every load-bearing repo fact to `<file>:<line>` as read at that anchor (Verified Facts Log pattern — see deepresearch.md Phase 4).
```

### 1.2 Verify Research Output

After the agent completes:

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

**Skip this phase entirely if `--light` OR `--autonomous` flag is active.**
- `--light`: proceed to Phase 2 with no research review.
- `--autonomous`: proceed to Phase 2 with no mid-flow review, BUT prepare a condensed "key research findings" summary (top 3-5 insights + business-viability signal if applicable) and stash it for the final walkthrough in Phase 6. Store it as an inline note so Phase 6 does not have to re-derive it.

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

**Autonomous mode**: Determine naming internally without prompting.
- If the concept clearly contains or implies a name (e.g., a single proper-noun candidate is obvious from the input), use it directly and skip the naming agent.
- Otherwise, spawn the naming agent (2.1) silently and auto-select the top-ranked candidate as the working project name for planning. Still write `naming.md` with the full ranked list; the top-5 are surfaced in the Phase 6 final walkthrough so the user can swap the choice before execution.
- No `AskUserQuestion` fires in this phase under `--autonomous`.

**Interactive / light mode**: Use AskUserQuestion:

```
question: "Before I start planning, would you like me to brainstorm project names and check domain availability?"
options:
  - "Yes - spin up a naming agent (.com/.io/.ai/.pro/.work checks)"
  - "No - skip naming, proceed to planning"
  - "I already have a name in mind (I'll provide it)"
```

If yes or "I already have a name":

### 2.1 Spawn Naming Agent

Launch an agent (model: sonnet) that:
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

**Interactive / light mode**: Show the top 5 names and ask the user to pick one (or provide their own). The chosen name becomes the project name throughout the plan.

**Autonomous mode**: Do NOT prompt. Auto-select the top-ranked name from `naming.md` as the working project name. Record the auto-selection in `decisions.md` under "Phase 2 Inferences". The top-5 list will be re-presented in the Phase 6 final walkthrough so the user can swap in a different pick before execution.

---

## Phase 2.5: Tech Stack Proposal & Sign-off

**Skip user sign-off if `--light` OR `--autonomous` flag is active.** Tech stack is decided internally.
- `--light`: pick the stack silently in Phase 3.1 from hard defaults + research-informed choices; no table is built at this point.
- `--autonomous`: still run 2.5.1 (gather existing patterns) and 2.5.2 (propose stack table) so the table exists for the final walkthrough, but **skip 2.5.3 entirely** - the table is considered approved the moment it is written. Record the full table + one-line justification per row in `decisions.md` so the final walkthrough can display it without re-deriving.

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
- **E2E test infrastructure**: Playwright (web/browser); XCUITest + a cloud Mac or the paired real device for macOS & iOS; a stdin/stdout harness for CLIs & daemons. Add third-party compute whenever the surface needs it — RunPod (GPU / heavy E2E), cloud Mac instances, or a device/browser matrix. There is **no resource constraint on test infrastructure**: provision whatever gives high-certainty end-to-end coverage so the user never has to test manually.

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

**Interactive mode only**: Use AskUserQuestion:

```
question: "Does this tech stack look right?"
options:
  - "Looks good - approved, proceed to planning"
  - "I have changes (I'll describe)"
```

**Autonomous mode**: Do NOT prompt. The proposed table is auto-approved. Skip 2.5.3.

### 2.5.3 Iterate Until Approved (interactive only)

If the user has changes, apply them. For each change, note the tradeoff briefly (e.g., "switching from D1 to Supabase adds managed Postgres but removes the CF-native advantage"). Re-present the updated table and re-confirm with the same AskUserQuestion options until "Looks good" is selected.

Record all stack decisions in `~/code/plans/{concept-name}/decisions.md`.

Once approved, store the approved stack - it is the canonical stack for Phase 3.

---

## Phase 2.6: High-Level Plan Proposal & Sign-off

**Skip user sign-off if `--light` OR `--autonomous` flag is active.**
- `--light`: skip entirely; proceed to Phase 3. Scope is inferred during plan creation.
- `--autonomous`: still build the scope + rough epic proposal (2.6.1) so it exists for the final walkthrough, but **skip 2.6.2 (sign-off gate) entirely**. Infer v1-in / v1-out from the concept + research findings. Record the proposed scope and epic structure in `decisions.md` under "Phase 2.6 Inferences". The final walkthrough will surface both so the user can still redirect before execution.

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

**Skip entirely in `--autonomous` mode.** The scope proposal is auto-approved; the user can still redirect during the final walkthrough.

**Interactive mode**: Use AskUserQuestion:

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

**Skip user prompts if `--light` OR `--autonomous` flag is active.**
- `--light`: use the default 4-clone flat model.
- `--autonomous`: infer the setup from the scope proposed in 2.6.1. Use this decision table and record it in `decisions.md`:

| Agent-epic count | Autonomous default |
|---|---|
| 9+ | Workspace model (isolated groups of 4 clones) |
| 4-8 | Flat clone model (4 sibling clones) |
| 1-3 | Single clone (no parallelism) |

If `--repo` is set and a multi-clone setup already exists, use the existing structure. If `--repo` is set without an existing multi-clone setup, apply the table above to decide whether to provision one (as a prerequisite step in the plan).

**Goal**: Decide how parallel agent execution will be structured before creating the plan.

### 2.7.1 New Codebase

**Skip in `--autonomous` mode** - apply the decision table above.

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

**Skip user prompts in `--autonomous` mode** - use the decision table above and document the inference in `decisions.md`.

**If it already has a workspace/clone setup**: Ask which clone to use as the base, or whether to create new clones for this work. (Autonomous mode: default to the lowest-numbered existing clone for the base and note this in decisions.md.)

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

### 3.0 Mission & Guiding Decision Principles

Before designing epics, capture the context an execution agent needs to **make follow-on decisions without you**. During execution, work always surfaces that the plan did not enumerate (a bug found while integrating, a missing prerequisite, a gap between two epics). For the agent to complete that work autonomously — instead of stopping to ask — it must be able to deduce the right *direction* from the plan alone. Write that context now; it becomes plan.md Section 1.4 and is the reference the follow-up-completion contract (3.4.5) points at.

Capture three things:

1. **The software's mission** — what the system is for, who it serves, and what "good" looks like. One paragraph an agent can hold in context while judging whether a discovered change serves the goal.
2. **The codebase's governing context** — the conventions, patterns, and hard constraints the code already follows (from Phase 0.4 repo analysis) or, for greenfield, the ones this plan establishes (from the approved tech stack and architecture). So a follow-on change matches the codebase rather than diverging from it.
3. **Decision principles** — the heuristics an agent uses to triage and direct unplanned work: what to prefer, what to reject as out-of-scope ("while I'm here" work, speculative features), when a matter is genuinely human-blocked (needs a credential, a dashboard action, or a product decision with no right answer) versus something to reason through. State them concretely enough that two different agents would resolve the same ambiguity the same way.

The test: *could a fresh agent, reading only plan.md, decide how to handle a plausible unplanned follow-on item the way you would?* If not, this section is too thin — expand it until it can. This is the same context the Phase 5.7 adversarial reviewer (tenet T3) will check for and expand if missing; writing it well here avoids that rework.

### 3.1 Tech Stack Documentation

**If default interactive mode (neither flag)**: The tech stack was already approved in Phase 2.5. Use the approved stack as the basis for architecture and epic design. Do not re-propose it.

**If `--autonomous` mode**: Phase 2.5.2 already built and auto-approved the stack table and wrote it to decisions.md. Use that table as the basis for architecture and epic design. Do not re-propose.

**If `--light` mode**: Select the optimal tech stack based on research findings and the hard defaults defined in Phase 2.5.2. Document reasoning in decisions.md.

Hard constraints apply in all modes:
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
- Each epic **contributes autonomous end-to-end coverage** for the surface it adds or changes — not just unit + integration. A feature epic is not "done" until an E2E test exercises its real behavior through the running system (real API, real DB, real UI/CLI). Its acceptance criteria include the E2E test(s) it adds to the suite (§8 / Phase 3.3.5).
- Define clear **inputs** (what must exist) and **outputs** (what results)
- Identify **dependency order** - parallel vs. sequential
- Define **bring-up steps** - the concrete actions required to get the app (local and/or production) into a testable state once this epic merges: migrations to run, dev servers to restart, deploys to trigger, env vars/secrets to set, caches to invalidate, seed data to load. "Code merged" is not "change testable"; the plan must close that gap explicitly.

Epic categories:
- **Foundation epics**: Repo setup, CI/CD, shared types, config - run first. **For a new project, the autonomous E2E test harness is a foundation epic** (Wave 1): the runner, the CI wiring that runs it on every PR, and any test infrastructure (ephemeral env, seeded DB, third-party compute) the surface needs. Feature epics build on it from the first wave.
- **Parallel epics**: Independent feature work running simultaneously
- **Integration epics**: Connecting parallel streams - run after dependencies
- **Testing epics**: The autonomous E2E suite and its infrastructure — the harness, cross-cutting user-journey tests, coverage gap-fill for existing surfaces (Phase 3.3.5), load/soak tests, and any agent-driven exploratory testing. The suite is the certainty oracle (green = ready-to-merge / clean; red = broken), so these are first-class epics, never optional add-ons.
- **Human-epics**: Work requiring human intervention

### 3.3.5 Autonomous E2E Test Strategy (MANDATORY)

Every plan builds a **comprehensive, autonomous end-to-end test suite** covering all testable surfaces of what it touches. This is not optional and does not scale down with project size — it exists so the suite, not the user, is the oracle for "broken" vs. "clean and ready to merge." **The user does not do manual testing.** If certainty requires spinning up testing agents or third-party infrastructure, the plan provisions it — there is no resource constraint on testing.

Design the suite now; it becomes plan.md Section 8 and is enforced by the execution gates (Phase 7), the self-review (5.6.3), and the adversarial review (5.7 tenet T4).

**1. Coverage target — every testable surface.** Enumerate the surfaces this plan adds or changes and the end-to-end journey through each: HTTP endpoints (real request → real DB → real response), UI flows (real browser, real backend), CLI invocations (real args → real stdout/exit code), background jobs/queues, auth flows, webhooks, and any cross-surface user journey. Each becomes an E2E test that runs against the *running system*, not mocks. Mocked tests prove internal consistency; they say nothing about whether the real system works.

**2. New project — build it in from the ground up.** The E2E harness is a Wave-1 foundation epic (Phase 3.3): the runner, CI wiring that runs the suite on every PR, and a reproducible test environment (ephemeral deploy or local stack, seeded DB, test credentials). Every feature epic thereafter adds its E2E tests to that harness from the first wave — the suite grows with the code, never bolted on at the end.

**3. Existing project — audit and optimistically fill gaps.** Using the Phase 0.4.1 coverage inventory, for every area this plan touches that lacks E2E coverage, **add E2E-coverage work into the plan by default — assume the user signs off.** The standing assumption is that the user always wants more autonomous E2E coverage, so gap-fill is opt-out (surfaced in the walkthrough and decisions.md), never a mid-flow yes/no question. If the repo has no E2E suite at all, the plan stands one up for the touched surfaces (and wires it into CI) as part of the work. Record each added E2E-coverage epic/task in decisions.md under "Optimistic E2E coverage additions" so the user can veto specific ones at the final gate.

**4. Platform-appropriate execution + infrastructure.** Match the harness to the surface and provision whatever infra gives high certainty (Phase 2.5.2): Playwright for web; XCUITest on a **cloud Mac instance or the paired real device** for macOS/iOS; a stdin/stdout harness for CLIs/daemons; **RunPod or equivalent** for GPU/heavy compute E2E; a device/browser matrix where it matters. Where a flow genuinely cannot be asserted programmatically, **dispatch a testing agent to drive it and report** (browser automation, device automation) rather than handing the user a manual checklist — an agent doing exploratory/manual-substitute testing is still autonomous.

**5. SDLC integration — the suite is a merge gate.** The suite runs in CI on every PR and is a **required, blocking check**: a PR does not merge until its E2E tests (and the existing suite) are green. Post-wave bring-up and final bring-up (Section 9) run the full suite against the reactivated system. "High degree of certainty" means: green suite ⇒ safe to merge / clean; red suite ⇒ broken, do not proceed.

**6. Certainty, not coverage theater.** Prefer a smaller set of tests that exercise real end-to-end behavior over a large set of shallow mocked ones. The bar is: if the suite is green, the user can ship without opening the app. State explicitly in Section 8 what the suite does and does not certify, so any residual manual check is named rather than silently assumed.

**7. Live testing runs on the runner, under a recorded grant.** Any step that launches or relaunches an app, fires dictation, posts synthetic input events, changes focus, sets a machine-global input/audio override, opens the mic or camera, or drives a simulator/attached device from the host is **live testing**. It runs on the dedicated runner machine, never on the dev machine — the dev machine's focus, keyboard, and dictation are the user's control channel to every concurrent agent stream, and one machine-global override silently corrupts all of them (see `~/.claude/rules/live-testing-guard.md`). Enumerate every live-testing step the plan needs, name the runner each one targets, and write the Phase 0.5.2 Q8 answer into **§8.6 Live-Testing Authorization**. A plan whose §8.6 says `NOT AUTHORIZED` is still a valid plan — the executor will surface those steps and ask before running them. What is not valid is omitting §8.6, or letting a plan step's own instruction ("run the dictation preflight") stand in for the user's approval.

**Ask Q8 here if it has not been asked yet** (`--light` defers it to this point), or if designing the suite produced live-testing steps that the Phase 0.5.2 answer did not cover. Use the same Q8 payload, naming the specific steps. In `--autonomous`, do not ask — write `NOT AUTHORIZED`.

### 3.4 Define Human-Epics

For each human-epic:
- Exact step-by-step instructions
- When it needs to happen (what it blocks)
- Whether it can be done in parallel with agent execution
- Links to relevant dashboards/services

**Minimize human-epics.** For each, ask: "Can this be done via CLI/API instead?" Only create human-epics for things that genuinely require browser-based human action (OAuth app setup in Google Console, payment provider setup, etc.). If an agent can do it with a CLI or API, it is not a human-epic.

**Bucket unavoidable human work to the edges.** The user should not be a step *inside* the execution run. Every human-epic that survives the minimization test is scheduled to one of two buckets, never the middle:

- **Front-loaded** — done *before* Wave 1 begins, as a prerequisite (API keys, service signups, OAuth setup, DNS). Preferred: the human does their part once, up front, and then execution runs to done untouched.
- **Deferred** — done *after* all agent work completes (final DNS cutover, store submission, a human sign-off on the finished product).

Only place a human-epic mid-execution when it *genuinely* blocks a specific wave and cannot be front-loaded (rare — most "mid" human work can be pulled forward). When one is unavoidable mid-run, say so explicitly and justify why it could not move to an edge. The goal: once execution starts, it does not pause waiting on a person.

### 3.4.5 Follow-Up Work Completion Contract

The plan must state, in a clearly-defined and locatable clause, that **any follow-on work discovered during execution is completed before execution is reported complete.** This becomes plan.md Section 9.5 and is enforced in Phase 7 (execution) and Section 13 (completion checklist).

Define the contract concretely:

- **Discover & track** — anything an agent finds that the plan did not enumerate but that the work needs (a bug, a missing prerequisite, a gap between epics) is opened as a tracked GitHub issue labeled `follow-up`, so nothing evaporates.
- **Triage by the decision principles (§3.0 / plan §1.4)** — the agent decides *in-scope-now* (the work cannot be called complete or valid without it), *out-of-scope/deferred* (a nice-to-have or v2 idea — logged, not done), or *human-blocked* (needs a credential/dashboard/decision the agent cannot supply). Because §3.0 gives the mission + principles, the agent makes this call itself instead of asking.
- **Complete before done** — every in-scope-now follow-up is implemented, reviewed with the same discipline as planned work, and merged. Execution is **not complete** while any in-scope, non-human-blocked follow-up remains open.
- **Only human-blocked may remain** — human-blocked follow-ups are surfaced explicitly (bucketed and notified, per 3.4), never buried, and are the only work allowed to be open at completion.

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
- **Verification gates**: Checkpoints before proceeding. **The autonomous E2E suite (§8) is the gate**: no PR merges until its E2E tests are green in CI, and no wave advances until the full suite passes against the reactivated system. Green suite ⇒ proceed; red ⇒ stop and fix.
- **Post-wave bring-up**: Aggregate the bring-up steps from every epic in the wave into a single ordered runbook. Include: migrations (with correct order if multiple), which services to restart (local dev servers, workers, background jobs), which deploys to trigger and verify, env vars/secrets to set, and the command that runs the **full autonomous E2E suite** against the reactivated system (superseding a bare smoke test). This runbook executes between waves - agents do not advance to the next wave until the previous wave's app state is reactivated and the E2E suite is green.

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

This is the **first of two review stages**. Phase 4 is *constructive* peer review (security / architecture / business-logic) run against the draft, before `plan.md` is written. The *adversarial* second stage — Phase 5.7 — runs three sequential hostile reviews against the finished plan, each incorporating its fixes before the next. If "Skip Review" is selected here, Phase 5.7 is skipped as well.

### 4.0 Review Configuration

**In `--autonomous` mode**: Skip the question. Lock the review set to **Full** - Security + Architecture + Business Logic, all three agents, all in parallel. Proceed to 4.1.

**In interactive / light mode**: Use AskUserQuestion:

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

**Note**: If "Skip Review" is selected, Phases 4.1-4.4 are skipped entirely. Proceed directly to Phase 5. "Skip Review" is NOT available in `--autonomous` mode - the whole point of autonomous is full-depth planning.

### 4.1 Spawn Review Agents

Launch chosen review agents in parallel using the Agent tool (model: sonnet).

1. **Security Review Agent** - Output: `~/code/plans/{concept-name}/reviews/security.md`
2. **Architecture Review Agent** - Output: `~/code/plans/{concept-name}/reviews/architecture.md`
3. **Business Logic Review Agent** - Output: `~/code/plans/{concept-name}/reviews/business-logic.md`

**Anchor propagation (only when --repo was given).** Each review agent verifies plan claims against the actual codebase, so it MUST read the same anchor the planning used — not the stale working tree. Append to every review agent's prompt:

```
SOURCE FRESHNESS — repo facts:
- Verification anchor: {DEFAULT_REF} @ {ANCHOR} (from Phase 0.4.0). The user's original working tree may be STALE.
- When you check a plan claim against the codebase, read/verify it against the anchor: the anchor worktree at {WORKTREE} (normal Read/Glob/Grep) or `git -C {REPO} show {DEFAULT_REF}:<path>`. Never a bare Read of the original --repo working tree.
- Flag any plan claim that disagrees with the anchor as a finding (e.g., plan cites code that no longer exists on {DEFAULT_REF}).
```

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
### 1.4 Mission & Guiding Decision Principles
[From Phase 3.0. The context an execution agent uses to make follow-on decisions WITHOUT the user. Three parts, all concrete:
- **Mission**: what the system is for, who it serves, what "good" looks like.
- **Codebase governing context**: conventions, patterns, and hard constraints a follow-on change must match (from repo analysis, or established by this plan for greenfield).
- **Decision principles**: heuristics for triaging unplanned work — what to prefer, what to reject as out-of-scope, when a matter is genuinely human-blocked vs. reason-through. Concrete enough that two agents resolve the same ambiguity the same way.
This section is what makes the Section 9.5 follow-up contract executable autonomously.]

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
[Minimized (anything an agent can do via CLI/API is NOT here) and bucketed to the edges — see §3.4.]
### Human-Epic 1: {Name}
- **When (bucket)**: Front-loaded (before Wave 1) / Deferred (after all agent work) / Mid-run (only if genuinely unavoidable — justify why it cannot move to an edge)
- **Blocks**: Epic N, Epic M
- **Instructions**: [Step-by-step]

## 7. Execution Strategy
### 7.1 Wave Breakdown
### 7.2 Parallel Agent Allocation
### 7.3 Dependency Graph (ASCII)
### 7.4 Integration Points
### 7.5 Verification Gates

## 8. Testing Strategy

[From Phase 3.3.5. This section specifies the **comprehensive autonomous E2E suite** that lets the user ship without manual testing. It is the certainty oracle: green ⇒ clean / ready-to-merge, red ⇒ broken.]

### 8.1 Unit Tests (per epic)
[Per-epic unit coverage — the fast inner loop.]

### 8.2 Integration Tests
[Cross-module/service integration — real collaborators where practical.]

### 8.3 Autonomous End-to-End Suite (the certainty oracle)
- **Surfaces covered**: [every testable surface this plan touches — HTTP endpoints, UI flows, CLI invocations, background jobs/queues, auth, webhooks, cross-surface journeys. Each row: surface → the real end-to-end journey the test drives.]
- **Harness & environment**: [runner (Playwright / XCUITest / CLI harness / …), the reproducible test environment (ephemeral deploy or local stack, seeded DB, test credentials), and how it is torn up/down.]
- **Test infrastructure**: [any third-party compute the surface requires — cloud Mac instance, RunPod, real device (the paired iPhone), device/browser matrix. "None beyond CI" only if genuinely none.]
- **Agent-driven testing** (if any): [flows that cannot be asserted purely programmatically and are driven by a testing agent (browser/device automation) that reports pass/fail — never handed to the user as a manual checklist.]
- **Existing-repo gap-fill** (if `--repo`): [E2E coverage added optimistically for touched areas that lacked it — see decisions.md "Optimistic E2E coverage additions".]

### 8.4 CI Integration & Merge Gate
- The suite runs on **every PR** as a **required, blocking check**; a PR does not merge while it is red.
- Post-wave and final bring-up (Section 9) run the **full** suite against the reactivated system.
- [exact commands to run the suite locally and in CI.]

### 8.5 Coverage Targets & What the Suite Certifies
- [coverage targets per layer.]
- **Certifies**: [what a green suite guarantees — the flows the user can trust without opening the app.]
- **Does NOT certify**: [any residual surface not covered and why — named explicitly, never silently assumed. The goal is zero residual manual testing; any exception is justified here.]

### 8.6 Live-Testing Authorization

[From Phase 0.5.2 Q8 / Phase 3.3.5 point 7. MANDATORY section — present in every plan, even when the answer is "none". The executor reads this before running anything; a missing or incomplete block means UNAUTHORIZED.]

- **Live-testing steps in this plan**: [each step named individually — app launches/relaunches, dictation firing, synthetic input events, focus changes, machine-global input/audio overrides, mic/camera capture, simulator or attached-device runs driven from a host. "None — this plan is headless-only" if genuinely none.]
- **Where they run**: [the specific dedicated runner machine or device. Never the dev machine.]
- **Permission granted**: [`GRANTED by {user} on {ISO date}` — the user's explicit approval at planning time — or `NOT AUTHORIZED`.]
- **Dev machine**: headless only (builds, unit tests, lint, type checks, read-only queries). Non-negotiable.

`NOT AUTHORIZED` is the correct value whenever the user did not explicitly approve, including every `--autonomous` run. Absence of an answer is never an implied grant.

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
10. Run the full autonomous E2E suite (Section 8): `{exact command}` — must be green before the next wave. This is the certainty gate; it supersedes a bare smoke test and proves all layers are live end-to-end.
```

Every step has an exact command or link. Vague instructions like "restart the server" do not belong here.

### 9.2 Local vs. Production Parity

Specify which bring-up steps apply to local vs. production vs. both. Production deploys often need extra steps (DNS propagation, CDN cache purge, health checks) that local doesn't.

### 9.3 Rollback Plan

For each wave's bring-up, specify the rollback: how to revert migrations, redeploy previous version, restore env vars. Rollback needs to be as well-defined as roll-forward.

### 9.4 Final Bring-Up (end of execution)

The last-wave bring-up runbook that takes the fully-merged project to a confirmed-live state, ending with a **full run of the autonomous E2E suite (Section 8) that must be green**. This is the single source of truth for "app is ready" — because the suite is green, "ready to test" means the user can use it, not that they still need to test it. Anything that was deferred or flagged during waves gets resolved here.

### 9.5 Follow-Up Work Completion Contract

[From Phase 3.4.5. Execution is NOT complete while in-scope follow-on work discovered during the run remains open.]

Any work that surfaces during execution but was not enumerated in this plan is handled as follows, and this run is not reported complete until the contract is satisfied:

1. **Track** — open a GitHub issue labeled `follow-up` for every discovered item so nothing is lost.
2. **Triage against §1.4** — using the Mission & Decision Principles, classify each item:
   - **In-scope-now** — the work cannot be called complete or valid without it. Implement it, review it with the same discipline as planned work, merge it.
   - **Out-of-scope / deferred** — a nice-to-have, unrelated improvement, or v2 idea. Log it as a deferred issue; do not do it. Surface the deferred list in the final report.
   - **Human-blocked** — needs a credential, a browser/dashboard action, or a product decision with no right answer. Notify the user with the exact ask, file a `blocked` issue, and continue all non-blocked work.
3. **Complete before done** — every in-scope-now follow-up is DONE (implemented, reviewed, merged, verified) before execution is reported complete.
4. **Only human-blocked may remain open** at completion, and each is surfaced explicitly (never buried).

The agent decides the triage itself using §1.4 — it does not stop to ask the user how to direct in-scope follow-on work. The completion checklist (Section 13) gates on "no open in-scope follow-up work."

## 10. Review Findings
[Only sections for reviews selected in Phase 4.0]
### 10.1 Security Review Summary (if selected)
### 10.2 Architecture Review Summary (if selected)
### 10.3 Business Logic Review Summary (if selected)
### 10.4 Changes Made Based on Reviews
### 10.5 Adversarial Review Summary (if Phase 5.7 ran)
[The three sequential passes, the attacks the plan survived, and the P0/P1 findings incorporated with the section each one changed. Pull from the Phase 5.7 block in decisions.md. Note any P0/P1 the final pass left unresolved and accepted as known risks.]

## 11. Risk Register
| Risk | Severity | Likelihood | Mitigation | Owner |
|------|----------|------------|------------|-------|

## 12. Scope Estimate
[See Phase 5.5 for generation details]

## 13. Post-Execution Verification Checklist
- [ ] All agent-epics completed and merged
- [ ] All tests passing (unit, integration, e2e)
- [ ] **Full autonomous E2E suite (Section 8) green against the running system — every covered surface passes; this is the ready-to-merge / clean oracle, not a smoke test**
- [ ] **E2E suite is a required, blocking CI check on every PR**
- [ ] **Every E2E coverage gap for touched surfaces filled (optimistic additions per §3.3.5) or explicitly listed in §8.5 as not-certified with justification**
- [ ] No open PRs (except human-blocked)
- [ ] No uncommitted changes in any clone
- [ ] No open issues (except human-agent/human-epic)
- [ ] **All in-scope follow-up work (Section 9.5) completed — no open `follow-up` issues except genuinely human-blocked ones**
- [ ] **Every human-blocked follow-up surfaced to the user with the exact ask (not buried)**
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

**Autonomous-execution readiness** (plan-level, not per-epic) — verify the plan can be executed without the user having to direct unplanned work:

- **§1.4 Mission & Guiding Decision Principles is present and concrete** - the mission, codebase governing context, and decision principles are all filled in, not placeholders. The test: could a fresh agent, reading only plan.md, triage a plausible unplanned follow-on item the way the author would? If not, expand §1.4 until it can.
- **§9.5 Follow-Up Work Completion Contract is present** - the plan states that in-scope follow-on work discovered during execution is completed before the run is reported complete, and Section 13's checklist includes "no open in-scope follow-up work."
- **Human work is bucketed to the edges** - every human-epic is scheduled front-loaded (before Wave 1) or deferred (after all agent work), or carries an explicit justification for why it must sit mid-run. No agent-doable step is labeled human work.
- **§8 specifies a comprehensive autonomous E2E suite** - every testable surface this plan touches maps to an E2E test against the running system; the suite is wired into CI as a blocking merge gate; for `--repo`, coverage gaps in touched areas are filled (optimistic additions) or explicitly listed in §8.5 as not-certified with justification. The test: could the user ship on a green suite without opening the app? If not, expand §8 until they can. No surface is left to manual testing without a named §8.5 exception.

These map to the four tenets the Phase 5.7 adversarial reviewer enforces (T1–T4); satisfying them here means the adversarial pass confirms rather than reworks them.

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

## Phase 5.7: Adversarial Review Sequence (MANDATORY)

**Prerequisite**: Phase 5.6 (self-review) reports clean — `plan.md` is fully written and free of placeholders and identifier drift. Adversarial review attacks the *finished* artifact; running it against a draft wastes the high-cost reviewers on problems the self-review already catches.

**Goal**: Subject the completed plan to **three sequential hostile reviews**, each one attacking the plan *after* the previous review's changes have already been incorporated. This is the **second of two review stages**: Phase 4 is *constructive* peer review (security / architecture / business-logic, run pre-write on the draft); Phase 5.7 is *adversarial* review (run post-write on the finished plan). Together they give the plan **six independent reviews in the full configuration** — three constructive, three adversarial — so the plan that reaches the final gate has already survived a hostile pass, not just a friendly one.

**Why sequential, not parallel**: each review must see the plan as hardened by the one before it. Review 2 should attack the plan *with Review 1's fixes already in place* (and probe whether those fixes introduced new weaknesses); Review 3 — the final review — attacks the plan with both prior passes incorporated, so it judges the fully-hardened artifact. Running them in parallel would have all three attack the same un-hardened plan and re-raise the same issues. Sequential reviews compound; parallel reviews duplicate. This also lets each reviewer use the `adrev-reviewer` agent's native **apply** mode safely — only one reviewer ever edits `plan.md` at a time, so there is no concurrent-write hazard.

**Announce at start**: "Running the Phase 5.7 adversarial review sequence — three sequential `adrev-reviewer` passes (the current Opus-tier model, maximum reasoning effort). Each attacks the plan after the previous pass's fixes are incorporated; the third is the final review of the fully-hardened plan."

### 5.7.0 When This Phase Runs

| Mode | Adversarial sequence |
|------|----------------------|
| Default (interactive) | **Runs.** Skipped only if "Skip Review" was selected in Phase 4.0 — skipping all review skips this too; note the skip in decisions.md. |
| `--autonomous` / `/xplana` | **Locked ON.** Always runs, no question. This is the deep path; maximum scrutiny is the entire point. |
| `--light` | Skipped by default (fast path). Runs only if the optional Phase 4 reviews were actually run in this `--light` session. |

This phase scopes to the **main planning flow (Phases 5 → 6)**. Deepen Mode re-runs Phase 5.6 only; it does not re-enter 5.7.

### 5.7.1 The Sequence

Compute the date once for the run: `date +%F`. Then run **exactly three `adrev-reviewer` passes, one at a time** (installed at `~/.claude/agents/adrev-reviewer.md`). Do NOT launch them together — pass `k` does not start until pass `k-1` has returned, its changes are incorporated, and the self-review (5.7.3) is clean:

> **Concurrency — avoid the 429 throttle.** Running these one at a time is also what keeps them under the rate limit: each pass is an Opus-4.8, max-effort agent — the heaviest dispatch in CCGM — and three of them firing together would almost certainly trip the server-side throttle (`Server is temporarily limiting requests · Rate limited`). Do not parallelize the passes to "save time." If a single pass returns the throttle, wait 30–60s and retry that one pass. See `~/.claude/rules/concurrency-and-rate-limits.md`.

```
Pass 1  →  incorporate  →  5.6 self-review clean
   ↓
Pass 2 (attacks the plan with Pass 1's fixes in place)  →  incorporate  →  5.6 self-review clean
   ↓
Pass 3 — FINAL review (attacks the fully-hardened plan)  →  incorporate  →  5.6 self-review clean
   ↓
proceed to Phase 6
```

Every pass uses **`model: opus`** (the current Opus-tier model) **at maximum reasoning effort**. Do NOT downgrade these to sonnet: adversarial review is the one phase where reviewer quality dominates cost, and the user pays for the deep pass precisely here.

Each pass runs the full attack battery. Give each a **distinct lead lens** via `focus` so the three passes press hardest on different angles rather than repeating one another:

| Pass | Lead lens (`focus`) |
|------|---------------------|
| **1 — premises** | "The plan's load-bearing *unstated* premises, the falsifiability of its claims, and the strongest opposing case including do-nothing. What does this assume about users, scale, data shape, ordering, and the behavior of other systems that nobody examined?" |
| **2 — execution & failure modes** | "How execution breaks: which step fails first when an assumption is wrong and whether the plan notices or plows on; partial failure mid-wave; concurrency and merge conflicts across parallel agent-epics; retries and idempotency; the gap between 'PR merged' and 'app live' in the bring-up runbook. Press tenets T1, T2, and T4: is human work minimized and bucketed to the edges (plan §6 Human-Epics) rather than wedged mid-run (T1); is the follow-up-completion contract (§9.5) present, clearly defined, and gated by the Section 13 checklist (T2); and does §8 specify a comprehensive autonomous E2E suite covering every testable surface, wired into CI as a blocking merge gate, with existing-repo gaps filled — such that the user need never test manually (T4)? Attack the testing claim hardest: which surface has no real end-to-end test, which 'test' only exercises mocks, where would a green suite still let a broken build merge? Also check whether Pass 1's revisions introduced any new weakness." |
| **3 — final / reversal cost & second-order** | "This is the FINAL adversarial pass on a plan already hardened by two prior reviews. Decisions expensive to undo (schema, public API contracts, file formats, dependency choices, naming that leaks into URLs/configs/env vars) with thin justification; second-order effects once it ships — what becomes load-bearing, what gets gamed, what maintenance burden appears in month two. Press tenet T3: does §1.4 carry enough mission + codebase + decision-principles context that an agent can direct unplanned follow-on work without the user? If it cannot, expand it. Then do a holistic final read: do the prior passes' edits hang together, or did they leave seams? Anything P0/P1 you raise here is the last chance to catch it before the gate." |

### 5.7.2 Dispatch One Pass

For pass `k` (1, 2, or 3), dispatch a single `adrev-reviewer` agent with `apply: true` so it incorporates its own findings directly into the plan (review-first, then edit — its Apply Protocol). Pass paths, not contents:

```
Target: ~/code/plans/{concept-name}/plan.md
target_kind: plan
apply: true
review_date: {YYYY-MM-DD}
review_artifact_path: ~/code/plans/{concept-name}/reviews/adversarial-{YYYY-MM-DD}-{k}.md
focus: {the lead lens for pass k from the table above}
Reference files (read as needed):
  - ~/code/plans/{concept-name}/research.md
  - ~/code/plans/{concept-name}/decisions.md
  - ~/code/plans/{concept-name}/reviews/  (the Phase 4 constructive reviews AND any earlier adversarial passes — do not merely re-raise what they already covered; attack what they missed or what the prior fixes introduced)

You are pass {k} of 3 sequential adversarial reviews. The plan you are reading already incorporates the fixes from passes 1..{k-1}. Reason at maximum depth. A review that returns "looks good, minor nits" is a FAILED review unless you genuinely attacked from every angle and the plan survived — and then your report must show the attacks in `survived`, not just the verdict.

Apply protocol: write the full review artifact first, then incorporate. P0/P1 (confidence ≥0.80) → revise the affected plan section directly, marking any premise fork with `> **Revised {date} (adversarial review):** ...`. P1/P2 (0.60–0.79) → add a row to the plan's existing Risk Register (Section 11), citing the finding id; do NOT create a separate "Risks & Open Questions" section — this plan already has Section 11. Confidence <0.60 → artifact-only. Append one line per incorporated finding to decisions.md. Never touch progress.md or completed-work records.

Plan-execution tenets (T1–T4) are requirements, not judgment calls: enforce them by editing plan.md. If human work is agent-doable or wedged mid-run, revise the plan's Human-Epics (§6) / Prerequisites (§4) to drop or edge-bucket it (T1). If the follow-up-completion contract (§9.5) is missing or vague, add it (T2). If §1.4's mission/codebase/decision-principles context is too thin for an agent to direct unplanned follow-on work, expand it (T3). If §8's autonomous E2E suite leaves a testable surface uncovered, is not wired into CI as a blocking merge gate, or (for `--repo`) leaves a touched-area coverage gap unfilled, expand §8 to close it — add the E2E-coverage epics/tasks optimistically (the user wants more coverage) rather than deferring to a question (T4). Park a tenet in the Risk Register only if it genuinely needs an author decision you cannot make — and say so.
```

**Anchor propagation (only when `--repo` was given).** Append the same `SOURCE FRESHNESS — repo facts` block used for the Phase 4 review agents (verification anchor `{DEFAULT_REF} @ {ANCHOR}`; read every repo fact from `{WORKTREE}` or `git -C {REPO} show {DEFAULT_REF}:<path>`, never the stale working tree; flag any plan claim that disagrees with the anchor as a finding).

Run the agent in **foreground** and wait for it to return before doing anything else. Then verify its artifact exists and read its ledger:

```bash
f=~/code/plans/{concept-name}/reviews/adversarial-{YYYY-MM-DD}-{k}.md
[ -f "$f" ] || echo "BLOCKED: pass $k artifact $f missing — re-dispatch pass $k"
```

If the artifact is missing, re-dispatch pass `k` before continuing. **Do not trust the agent's self-report**: read the artifact's findings JSON and confirm against `plan.md` that the P0/P1 findings it claims to have incorporated were actually applied (per the verification discipline — a `DONE` is a claim, not evidence).

### 5.7.3 Self-Review Between Passes

A pass's apply edits are themselves plan edits and can reintroduce placeholders or identifier drift (a rewritten epic that now trails off in "etc.", a new type name that disagrees with an old one). After each pass incorporates, **re-run Phase 5.6 (5.6.1–5.6.4) against the patched plan and loop it to clean** before dispatching the next pass. Do not modify 5.6 — it is the same self-review the main flow uses.

Only after 5.6 is clean does the next pass start, so each subsequent reviewer reads a consistent, drift-free plan.

### 5.7.4 The Final Pass and Residual Findings

Pass 3 is the **final review**. By the time it runs, the plan has incorporated two prior rounds of hardening, so Pass 3 judges the finished, fully-hardened artifact and does a holistic read for seams left by the earlier edits.

After Pass 3 incorporates and 5.6 is clean, the sequence is complete — proceed to Phase 6. The three sequential passes are the bound; there is no further round.

**If Pass 3 still surfaces unresolved P0/P1 findings** (≥0.80 it could not fully resolve by editing — e.g., a finding that invalidates a core premise the plan is built on), do not silently proceed:

- **Interactive (`/xplan`)**: escalate via AskUserQuestion, listing the specific unresolved findings:
  ```
  question: "The final adversarial pass left these P0/P1 issues unresolved: {for each: id — what — why}. How do you want to proceed?"
  options:
    - "Let me revise the concept/scope to address these (I'll describe)"
    - "Accept these as known risks and proceed to the final gate"
    - "Stop here — save the plan, don't execute"
  ```
  If the user revises, re-run the three-pass sequence against the revised plan. If they accept, ensure the open risks are rows in the Risk Register, then proceed to Phase 6.
- **Autonomous (`/xplana`)**: do NOT prompt mid-flow. Record the unresolved findings in decisions.md and carry them into the Phase 6.A walkthrough and the Phase 6.5 gate, flagged as "the final adversarial pass left open P0/P1 risks: {list}."

### 5.7.5 Record the Result

Append an "Adversarial Review (Phase 5.7)" block to `decisions.md`:

```markdown
## Adversarial Review (Phase 5.7 — 3 sequential passes)
- Pass 1 (premises): findings incorporated {count} / Risk Register {count} / artifact-only {count}
- Pass 2 (execution): findings incorporated {count} / Risk Register {count} / artifact-only {count}
- Pass 3 (final): findings incorporated {count} / Risk Register {count} / artifact-only {count}
- Outcome: clean after Pass 3 / Pass 3 left {M} unresolved P0/P1 (see final gate)
- Review artifacts: reviews/adversarial-{date}-1.md, -2.md, -3.md
```

---

## Phase 6: Final Confirmation Gate

### 6.0 Mode Split

**First, attempt the web review (section 6.W below) as the default review surface.** If the web server launches successfully and the user interacts with it, use its result (the `comments.json` it writes) to drive the next step:
- If the user clicked **Submit for deepening** and `comments.json` contains non-empty comments: run Deepen Mode D.5-D.7 against the commented sections (treat each comment as a pre-selected gap, skipping D.3 and D.4), then loop back through 6.W once more so the user can review the patched plan.
- If the user clicked **Accept as-is**: the plan is approved as reviewed. Proceed to 6.5.
- If the web server fails to launch (see 6.W fallback conditions): fall through to the mode-specific text walkthroughs below.

**Fallback mode split (when web UI is unavailable):**

**If `--autonomous` flag is active**: Run the autonomous plan walkthrough (section 6.A below) before the final gate (6.5). This presents the completed plan as a single structured artifact with every inferred default called out so the user can redirect if any assumption was wrong.

**If `--light` flag is active**: Run the full interactive walkthrough (sections 6.1-6.4 below) before the final gate (6.5). This is the traditional pre-execution review.

**If default interactive mode (neither flag)**: The user has already reviewed research (Phase 1.5), approved the tech stack (Phase 2.5), approved the high-level scope (Phase 2.6), and confirmed the multi-agent setup (Phase 2.7). Skip sections 6.1-6.4 and 6.A. Go directly to 6.5.

Regardless of which path is taken, **Phase 6.5 always fires** - the web review and the text walkthroughs are the *review* mechanisms; 6.5 is the non-bypassable execution gate.

---

### 6.W Web Review Walkthrough (default review surface, all modes)

**Goal**: Render the completed plan in the user's browser with section-level comment support. Comments drive a targeted Deepen Mode pass; "Accept as-is" proceeds to the final gate.

**Launch preconditions** (ALL must hold; if any fails, skip 6.W and fall through to the text walkthrough for the current mode):
- `plan.md` exists at `~/code/plans/{concept-name}/plan.md` (Phase 5 + 5.6 complete)
- Env var `XPLAN_NO_WEB` is NOT set to `1`
- On Linux, `$DISPLAY` is set (macOS always passes this check)
- The helper script `~/.claude/lib/xplan-web-review.py` is executable

Announce before launching: "Opening the plan in your browser for review. Add comments on any sections you want deepened, then click Submit or Accept."

#### 6.W.1 Launch the server

Run the helper (foreground; it blocks until the user submits or accepts):

```bash
python3 ~/.claude/lib/xplan-web-review.py ~/code/plans/{concept-name}
```

The script:
- Picks a free port on 127.0.0.1
- Opens the default browser to the review UI
- Waits for the user to click **Submit for deepening** or **Accept as-is**
- Writes `~/code/plans/{concept-name}/comments.json` with the user's action and any comments
- Prints a single JSON line to stdout: `{"action": "deepen"|"accept", "comment_count": N}`
- Exits 0 on user action, 1 on launch failure (caller should fall back)

If exit code is non-zero, fall through to the mode-specific text walkthrough below (6.A / 6.1-6.4).

#### 6.W.2 Handle the result

Read `~/code/plans/{concept-name}/comments.json`. It contains:

```json
{
  "action": "deepen" | "accept",
  "ts": "...",
  "concept": "...",
  "comments": [
    {
      "anchor": "plan.md::2. Scope",
      "file": "plan.md",
      "section_title": "2. Scope",
      "text": "the user's comment",
      "ts": "...",
      "status": "pending"
    }
  ]
}
```

**If `action == "accept"`**: Record "User accepted plan via web review" in `decisions.md` and proceed to Phase 6.5.

**If `action == "deepen"`** and `comments` is non-empty: treat each comment as a pre-selected deepening gap and run Deepen Mode D.5-D.7 **without** asking D.3's gap categorization or D.4's user selection - the user already selected by commenting. For each comment:

- The "target section" for D.5 is the comment's `section_title` in the comment's `file`.
- The "gap description" is the comment's `text`.
- Derive the gap bucket heuristically: ambiguity / pattern / test / tech-assumption based on the comment's wording; default to ambiguity if unclear. This feeds the D.5 agent prompt.
- Dispatch one agent per comment (model: sonnet), in parallel when comments target different sections, serialized when they touch the same section.

After the deepening agents return, integrate their results into plan.md via D.6 **without** re-prompting the user per section (the user already stated their intent in the comment - applying the proposed replacement is the direct implementation of that intent). If a deepening pass produces ambiguous or conflicting output, fall back to D.6's interactive AskUserQuestion for that single comment only.

Append a Deepen Pass block to `decisions.md` per D.6's format, noting that the source was web review.

Re-run Phase 5.6 (self-review) against the updated plan, as D.7 requires.

#### 6.W.3 Second-round review

After the deepening pass lands and 5.6 passes clean, **re-launch the web server once** (second round) so the user can verify the patches. Cap at one deepening round per run to avoid loops - on the second round, only **Accept as-is** meaningfully proceeds. If the user submits more comments on the second round, apply them if resource budget allows, otherwise save them to `comments.json` and surface them at the 6.5 gate as "deferred deepening - use `/xplan --deepen` to address."

After the second round (or after a first-round Accept), proceed to Phase 6.5.

#### 6.W.4 Fallback

If 6.W cannot launch (exit code 1), or if the user closes the tab without submitting (the script blocks indefinitely; user can CTRL+C the script to signal "skip"), the orchestrator falls through to the mode-specific text walkthrough for the current mode (6.A for `--autonomous`, 6.1-6.4 for `--light`, straight to 6.5 for default interactive).

Log the fallback reason to `decisions.md` so later debugging can see whether the web path ran.

---

### 6.A Autonomous Plan Walkthrough (--autonomous only)

**Goal**: Present the fully-planned project as a single digestible artifact, with every internally-inferred assumption called out so the user can correct anything before execution.

This is NOT section-by-section sign-off. The user reads the completed plan once and then makes one decision at the final gate. Any correction they want to apply goes through `/xplan --deepen` after they stop execution, not through mid-walkthrough edits.

Structure the output in this exact order, as a single message (or a small number of tightly-grouped messages if length demands it):

**1. Executive summary** (3-5 sentences)
- What this plan builds, in plain language
- Who it's for (infer from concept; explicitly flagged as an assumption)
- The single most important decision driving the design

**2. Key research findings** (top 3-5 insights)
- Pulled from the Phase 1.5 condensed summary stashed earlier
- Each insight with one line of "this is why it shaped the plan"

**3. Tech stack** (the Phase 2.5.2 table)
- Render the full table as-is
- One-line justification per major choice
- Call out any choice that diverges from the hard defaults

**4. Scope (v1 in / v1 out)**
- What's included in v1
- What's explicitly deferred to v2+
- Any scope decisions driven by research findings

**5. Epic breakdown**
- Wave structure (names only - full epic specs live in plan.md)
- Parallel allocation per wave
- Total agent-epic count, total human-epic count
- Inferred multi-agent setup (workspace / flat / single) and why

**6. Review findings summary**
- Critical findings from security review and how the plan addressed them
- Critical findings from architecture review and how the plan addressed them
- Critical findings from business-logic review and how the plan addressed them
- **Adversarial review (Phase 5.7)**: the three sequential passes, what the plan survived, and the P0/P1 findings incorporated. If the final pass left unresolved P0/P1 findings, list them explicitly here and again at the gate — the user must see them before deciding to execute.
- If no critical findings: state that explicitly

**7. Assumptions that might need correction**
- Render the full Phase 0.5 Inferences block from decisions.md
- Include the Phase 2 naming auto-selection (with the top-5 alternatives inline so the user can swap)
- Include the Phase 2.6 scope inference
- Include the Phase 2.7 multi-agent setup inference
- Include the **Optimistic E2E coverage additions** (decisions.md) — E2E-coverage work added on the assumption the user wants it. List each so the user can veto a specific one; the default is to keep them all.
- Each row: "I assumed X; correct if wrong."

**7.5 Live-testing authorization (always shown, never folded into assumptions)**
- Render plan §8.6 verbatim: the live-testing steps, the runner they target, and the permission line.
- In autonomous mode the permission line is always `NOT AUTHORIZED` — autonomous planning cannot grant it. Say so plainly: "These steps need your approval and a named runner before an executor will run them; until then the executor will surface them and stop."
- If §8.6 lists no live-testing steps, one line: "No live testing in this plan."

**8. Open questions**
- Anything the plan could not confidently decide
- Revenue model (if flagged TBD in 0.5)
- Success criteria (always flagged for confirmation in autonomous mode)
- Any unresolved questions from the review agents

**9. Where the full detail lives**
- `~/code/plans/{concept-name}/plan.md` (full plan)
- `~/code/plans/{concept-name}/research.md` (research)
- `~/code/plans/{concept-name}/decisions.md` (decision log + all autonomous inferences)
- `~/code/plans/{concept-name}/reviews/*.md` (review agent outputs)
- `~/code/plans/{concept-name}/naming.md` (if generated)

**10. Recommended next step on correction**
- If the user sees something wrong, recommend `/xplan --deepen ~/code/plans/{concept-name}` to tighten specific sections rather than restarting planning from scratch.

After presenting the walkthrough, proceed to 6.5.

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

### 6.5 Final Execution Gate (MANDATORY - all modes)

**HARD GATE - NON-BYPASSABLE - MANDATORY REGARDLESS OF PERMISSION MODE OR FLAGS**

This gate fires in every mode, including `--autonomous`. Autonomous mode skips every other user prompt, but NOT this one - execution is expensive and irreversible, so the plan-as-artifact presentation in 6.A always precedes an explicit human decision to proceed.

Before asking, re-verify:

```bash
ls -la ~/code/plans/{concept-name}/reviews/{selected-reviews} \
       ~/code/plans/{concept-name}/plan.md
# If Phase 5.7 ran, all three sequential adversarial artifacts must exist:
ls -la ~/code/plans/{concept-name}/reviews/adversarial-*-1.md \
       ~/code/plans/{concept-name}/reviews/adversarial-*-2.md \
       ~/code/plans/{concept-name}/reviews/adversarial-*-3.md 2>/dev/null
```

If any selected review file is missing, STOP. Go back to Phase 4. If Phase 5.7 was supposed to run (not skipped) but the three `adversarial-*-{1,2,3}.md` artifacts do not all exist, STOP and complete Phase 5.7 before gating.

If the Phase 5.7 final pass left unresolved P0/P1 findings, surface them in the gate summary so the user decides to execute with eyes open — do not bury them.

Also re-read plan §8.6. If it lists live-testing steps whose permission line is `NOT AUTHORIZED`, name those steps in the gate summary and state that the executor will stop on each one until the user approves it and names a runner. **Proceeding through this gate approves execution; it does not grant live-testing permission** — only an explicit Q8 answer recorded in §8.6 does that.

Use AskUserQuestion:

```
question: "Plan complete and reviewed. Ready to proceed?\n\nQuick summary:\n- [N] agent-epics across [N] waves\n- Up to [N] parallel agents\n- [N] human-epics (things you'll need to do)"
options:
  - "Proceed to execution"
  - "Revisit a section (I'll specify which)"
  - "Stop here - save plan, don't execute yet"
```

**This question is NON-NEGOTIABLE.** Do NOT proceed to Phase 7 without an explicit "Proceed to execution" from the user. No autonomy setting, permission bypass, or global instruction overrides this gate. If the user selects "Stop here", save the plan state and end gracefully.

**Autonomous mode default recommendation**: When a user runs `--autonomous` (or `/xplana`), they haven't been in the loop during creation. Lean toward "save plan, don't execute yet" as the suggested outcome unless the user explicitly asked for "autonomous execution" in the concept itself. If the user picks "Revisit a section", recommend `/xplan --deepen ~/code/plans/{concept-name}` as the tightening path rather than re-running the whole pipeline.

---

## Phase 7: Execution

**PREREQUISITE**: Phase 6.5 must have completed with explicit "Proceed to execution". Do NOT proceed otherwise.

### 7.1 Pre-Execution Setup

1. **Create GitHub repo** (private):
   ```bash
   gh repo create {username}/{project-name} --private --description "{description}"
   ```

2. **Provision isolation** based on the Phase 2.7 decision. **On a single machine, worktrees are the default** — each parallel epic gets its own `isolation: "worktree"` worktree (ephemeral, shared `.git`, torn down after its PR merges at 7.3.4). Provision permanent clones only for the cases that actually need them (a large multi-epic plan run under the workspace model, per-branch dev-server ports, hook-driven per-branch `tracking.csv`, or long-lived independent agents). When execution runs via `/etp`, it already applies this worktree-default-with-mandatory-teardown model. See `git-worktrees.md`.

   ```bash
   # Only when Phase 2.7 chose clones (heavier multi-clone plans):
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

Then check plan §8.6 the same way `/etp` Phase 0.5 does: every live-testing step needs a `GRANTED` line naming the runner it will run on. Any step without one is **UNAUTHORIZED** — name it, ask the user, and hold that step while the rest of the wave proceeds. Never run a live-testing step on the dev machine, and never read the plan's own instruction to run one as the grant. See `~/.claude/rules/live-testing-guard.md`.

### 7.3 Execute Waves

For each wave:

#### 7.3.1 Spawn Agents

Spawn agents in parallel (model: sonnet), one per epic, assigned to different clones.

#### 7.3.2 Agent Work Loop

Each agent:
- Creates a feature branch (`git checkout -b {issue}-{desc} origin/main`) which auto-registers the claim in tracking.csv via the PostToolUse hook
- Implements the work with tests
- **Verifies the work actually functions** end-to-end (not just unit tests passing)
- Creates a PR
- Reports completion with verification evidence
- **Reports any follow-on work it discovered but did not fix in-scope** (a bug found while integrating, a missing prerequisite, a gap between epics) so the orchestrator can triage it per §9.5 — nothing discovered is allowed to evaporate

#### 7.3.3 Monitor & Report

Monitor agent progress and report status updates to user.

#### 7.3.4 Wave Completion

When all wave agents complete:
- Verify all PRs are created and passing CI
- Verify all tests pass, no conflicts between PRs
- Merge all PRs for the wave
- **Tear down each merged epic's worktree** (when epics ran in worktrees — the single-machine default; see 7.1). Removal is mandatory: a built-in worktree never auto-removes, and a merged epic whose worktree lingers is the leak that consumed 237 GB in the 2026-07-13 incident. `git worktree remove <path>` (non-force) then `git worktree prune`; the branch ref and merged work survive removal, only the checkout goes. Epics that ran in a reused clone are reset to `origin/main` instead.
- **Execute the wave's Bring-Up Runbook (plan.md Section 9.1)**: run migrations in order, install new deps, regenerate types, set new env vars/secrets, restart local dev servers, trigger/verify deploys, invalidate caches, load seed data. Do not declare the wave done until every step has run and passed.
- **Run the full autonomous E2E suite (plan.md Section 8) against the reactivated system** — this supersedes a bare smoke test. Every PR in the wave already passed the E2E suite as a blocking CI check before merge; now the full suite must be green against the integrated system. A wave is NOT done while the E2E suite is red.

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
- Autonomous E2E suite (Section 8) green: yes/no
- Open blockers: none / [list]
### Resume context
[Key decisions, patterns established, and gotchas discovered so far]
```

This checkpoint enables `/xplan-resume` to pick up where execution left off.

#### 7.3.6 Update progress.md table and proceed to next wave.

#### 7.3.7 Triage & Complete Follow-Up Work (§9.5 contract)

Collect everything the wave's agents surfaced but did not fix in-scope (7.3.2), plus anything the integration verification (7.4) turns up. For each item, execute the plan's Section 9.5 Follow-Up Work Completion Contract:

1. **Track** — open a `follow-up`-labeled issue so nothing is lost.
2. **Triage against plan §1.4** — using the Mission & Guiding Decision Principles, classify it: **in-scope-now** (the work cannot be called complete or valid without it), **out-of-scope/deferred** (a nice-to-have or v2 idea), or **human-blocked** (needs a credential, dashboard action, or a product decision with no right answer). Decide this yourself from the plan's context — do NOT stop to ask the user how to direct in-scope follow-on work. That is exactly what §1.4 exists to let you do.
3. **Complete in-scope-now items** — branch, implement, review with the same discipline as planned work, merge. Fold a small in-scope follow-up into the current wave; spin a dedicated agent for a larger one.
4. **Log deferred, notify human-blocked** — deferred items stay as open issues surfaced in the final report; human-blocked items get a notification with the exact ask, then continue-around (never halt non-blocked work).

A wave is not "done" while an in-scope-now follow-up it produced is still open. Record the follow-up disposition in the wave checkpoint (7.3.5).

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
- **Run the full autonomous E2E suite (plan.md Section 8)** against the running system — not just CI, and not just a smoke test. This is the wave's certainty gate.
- If any layer is broken or stale, or the E2E suite is red, fix it before proceeding. The next wave does NOT start against a degraded system or a red suite.
- Record completion in progress.md: bring-up done, layers verified, E2E suite green

### 7.5 Continue Until Complete

**DO NOT STOP** until:
- All agent-epics completed and merged
- All tests pass
- All issues closed (except human-epic/human-agent)
- No uncommitted changes in any clone
- No open PRs
- CI is green
- Deployment working
- **All in-scope follow-up work completed (plan.md Section 9.5)** - do a final follow-up sweep: no open `follow-up` issue remains except genuinely human-blocked ones, and each of those has been surfaced to the user with the exact ask. Execution is NOT complete while an in-scope, non-human-blocked follow-up is open.
- **Final Bring-Up (plan.md Section 9.4) executed** - all migrations applied, all services running current code, all layers confirmed live
- **The full autonomous E2E suite (plan.md Section 8) is green** against the running system - every covered surface passes. Green suite ⇒ the user can open the app and use it immediately without any manual testing on their part. Any surface not covered is named in §8.5, not silently left for the user to check.

If blocked by a human-epic or a human-blocked follow-up: create a P0 issue with exact instructions, notify the user, continue non-blocked work. Human-required work is the *only* thing allowed to remain open at completion — reason through everything else yourself using plan §1.4 rather than deferring it to the user.

---

## Phase 8: Post-Execution Verification & Retrospective

### 8.1 Full Audit

```bash
gh issue list --state open --repo {username}/{project-name}
# Follow-up issues must all be closed except genuinely human-blocked ones (§9.5 contract):
gh issue list --state open --label follow-up --repo {username}/{project-name}
gh pr list --state open --repo {username}/{project-name}
for i in 0 1 2 3; do
  echo "=== Clone $i ==="
  git -C ~/code/{project-name}-repos/{project-name}-$i status
done
cd ~/code/{project-name}-repos/{project-name}-0
npm test && npm run build
```

Any open `follow-up` issue that is NOT human-blocked means execution is not complete — return to Phase 7.3.7 and finish it before reporting. Only human-blocked follow-ups may remain, each surfaced with its exact ask.

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

### 8.7 Worktree Teardown

Two kinds of worktree can be left behind; reclaim both here. **Run this whenever the command exits, including early exits** (the user stopped at the Phase 6.5 gate, a blocker halted execution, a gate rejected the plan) — teardown must not depend on reaching a clean completion.

**Execution worktrees** — if the execution phase ran epics in worktrees (the single-machine default, 7.1), each should already have been removed at 7.3.4 when its PR merged. Sweep any that leaked (an errored epic, an early exit, a built-in `isolation:"worktree"` worktree the harness could not auto-reclaim):

```bash
/worktree-sweep    # removes only clean worktrees, preserves any with unsaved work, prunes stale metadata
```

**The temp anchor worktree** — if Phase 0.4.0 created one (`--repo` with a remote), remove it explicitly so it does not linger:

```bash
git -C "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null
rmdir "$(dirname "$WORKTREE")" 2>/dev/null
git -C "$REPO" worktree prune 2>/dev/null   # also reclaims a leaked anchor worktree if this teardown was skipped on a prior early exit
```

The anchor lives in a temp dir outside the two managed worktree locations, so `/worktree-sweep` will not remove it directly — but its `git worktree prune` step *does* clear the metadata once the temp dir is gone. Removing either kind of worktree does not touch the user's clone, branches, or committed work — only the throwaway checkout.

---

## Important Principles

### Source Freshness for Existing Repos

When planning against an existing repo (`--repo`), the source of truth is a fetched, SHA-pinned origin default branch — never the local working tree, which may lag origin by many commits or hold uncommitted WIP. The Phase 0.4.0 guard pins that anchor once and every research/review reader works from it. Greenfield plans (no `--repo`) skip the guard entirely.

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

### Human Work at the Edges

The user should not be a step *inside* an execution run. Minimize required human interaction first (anything an agent can do via CLI/API is not human work), then bucket whatever genuinely remains to the **beginning** (front-loaded prerequisites) or the **end** (final human steps) — never mid-run, where it stalls the whole run waiting on a person. Once execution starts, it proceeds to done without pausing for a human. This is tenet T1 the adversarial review (Phase 5.7) enforces.

### Quality Over Speed

- Every piece of code has tests
- Every PR passes CI before merge
- **Every feature is verified to actually work** end-to-end - unit tests passing is the bare minimum, not the finish line. Mocked tests prove internal consistency; they say nothing about whether the real system functions. Use the real API, the real database, the real UI.
- Security, architecture, and business logic reviews are mandatory unless explicitly skipped

### Autonomous End-to-End Testing — No Manual Testing

Every plan ships a **comprehensive autonomous E2E suite** covering all testable surfaces, wired into CI as a blocking merge gate (plan §8, Phase 3.3.5). The suite is the certainty oracle: green ⇒ clean and ready to merge, red ⇒ broken. **The user's time is not spent on manual testing** — where a flow can't be asserted programmatically, a testing agent drives it; where the surface needs it, the plan provisions third-party infra (RunPod, cloud Mac, real devices). There is no resource constraint on testing. New projects build the suite in from the ground up; existing projects get optimistic gap-fill for every touched area that lacks E2E coverage (the standing assumption is the user always wants more coverage). This is tenet T4 the adversarial review (Phase 5.7) enforces — it expands §8 when coverage is thin rather than deferring to a question.

### Scope Over Time

Epic sizing is about isolation, testability, and merge safety - not clock time. A focused 3-hour epic is better than three 1-hour epics with artificial seams.

### Plans are Living Documents

- plan.md is updated during interactive phases based on user feedback
- progress.md is updated during execution with checkpoints after every wave
- decisions.md is updated whenever a significant decision is made

### Complete Execution

Plans execute until ALL completable work is done. No stopping halfway. No leaving broken or half-finished work. Every session ends with a clean state.

### Follow-Up Completion Before Done

Execution always surfaces work the plan did not enumerate. Execution is **not complete** while in-scope follow-on work discovered during the run remains open. Every such item is tracked as a `follow-up` issue, triaged against plan §1.4, and — if in-scope — completed and reviewed before the run is reported done (plan §9.5). The only work allowed to remain open at completion is genuinely human-blocked, and it is surfaced explicitly. This is tenet T2 the adversarial review (Phase 5.7) enforces.

### Autonomous Follow-On Decisions

An agent triages and directs unplanned follow-on work *itself*, using the plan's Mission & Guiding Decision Principles (§1.4) — the software's mission, the codebase's governing context, and the plan's decision heuristics. It does not stop to ask the user how to handle in-scope follow-on work; the plan carries enough context to deduce the direction. If it does not, the plan is under-specified and §1.4 must be expanded — this is tenet T3 the adversarial review (Phase 5.7) enforces.

### Resumability

Checkpoints are written after every wave. Progress file tracks exact state for `/xplan-resume`. Each checkpoint captures enough context to resume without re-reading the entire codebase.
