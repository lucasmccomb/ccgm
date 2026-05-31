---
description: Execute an existing plan end-to-end with parallel agents, adversarial PR review, and follow-up completion. Runs to completion, stopping only for absolute blockers.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <plan-file-or-dir> [--dry-run] [--confirm] [--max-agents N]
---

# etp - Execute The Plan

Take a plan that already exists - one an agent has been building, or any plan file you point at - and drive it to completion. `etp` does not research, name, or write a plan; it **executes** one. It decomposes the plan into units, runs them with parallel agents, adversarially reviews every PR with a *separate* agent, fixes what is reasonable and valid, completes the follow-up work that surfaces along the way (reviewing those PRs too), and does not stop until everything that can be done is done.

This is the execution half of `/xplan` generalized to any plan file, with a hardened review-and-follow-through loop bolted on.

## Prime Directive

> Execute the plan that is linked in the prompt itself, according to the file path, use as many agents as makes sense, do adversarial critical reviews of all PRs and make any fixes to those PRs that are reasonable and valid, complete any follow-up issues that arise during the execution of the plan and do adversarial reviews on those PRs as well. Don't stop until everything is complete. Do your best to reason through issues that you find along the way. If there's an absolute blocker, notify me of that, but continue the plan if possible.

Everything below is the operational expansion of that directive. When a phase and the directive seem to conflict, the directive wins.

## When to use `/etp`

- A `/xplan` (or `/xplana`) plan exists and you want it executed now.
- An agent has been working a plan and you want another agent to pick it up and finish it.
- You have a hand-written plan, design doc with executable steps, or checklist at a known path and want it built.

## When NOT to use it

- There is no plan yet - use `/xplan` to create one first.
- The "plan" is pure prose with no executable units (a vision doc). `etp` will surface this rather than guess wildly - see Phase 0.3.
- You want to resume an `/xplan`-native interrupted run with its full epic/wave checkpoint structure - `/xplan-resume` is the specialized tool for that. `etp` is the general plan-file executor (and is itself resumable - see Resumability).

## Sub-Agent Model Optimization

| Role | Agent type | Model |
|------|-----------|-------|
| Implementation (one per unit) | `implementer` | sonnet |
| Adversarial review - Stage 1 | `spec-compliance-reviewer` | sonnet |
| Adversarial review - Stage 2 | `code-quality-reviewer` | sonnet |
| Follow-up fixes | `implementer` | sonnet |
| Cheap mechanical checks (status, ls) | default | haiku |
| Orchestrator (this session) | - | current model |

The orchestrator stays on the current model for synthesis, triage, and routing. It never grades a PR itself - grading is delegated to a separate agent (see Integrity, below).

---

## Input

```
$ARGUMENTS
```

Parse from `$ARGUMENTS`:
- **Plan reference** (positional): a file path, a directory, or empty.
- **`--dry-run`**: resolve and analyze the plan, print the execution model, then STOP. No branches, PRs, or merges.
- **`--confirm`**: pause for one explicit go/no-go gate after the pre-flight analysis (Phase 3). Off by default - the directive says don't stop, so the default is to proceed once the plan is resolved unambiguously.
- **`--max-agents N`**: cap concurrent implementation agents (default: the width of the widest wave, clamped to the available isolation slots).

---

## Phase 0: Resolve & Load the Plan

### 0.1 Resolve the plan reference

Resolution is deterministic - do it with shell checks, not guesses:

1. **Explicit file** - the argument is a path to a file that exists → that is the plan.
2. **Directory** - the argument is a directory → look, in order, for `plan.md`, `PLAN.md`, then the single most-recently-modified `*.md`. If a `progress.md` / `etp-progress.md` sits beside it, load that too (resumability).
3. **Empty argument** - find the plan an agent has been working on:
   - `ls -t ~/code/plans/*/plan.md` and check each sibling `progress.md` for `Status: IN PROGRESS` or `INTERRUPTED`.
   - Check the current repo root and `docs/` for a `plan.md` / `PLAN.md`.
   - If exactly one in-progress candidate exists, use it. If several, list them and ask (AskUserQuestion). If none, that is an absolute blocker → notify the user and stop.
4. **Path does not exist** - absolute blocker. Notify the user with what you looked for; do not invent a plan.

Announce the resolved path explicitly: `Resolved plan: <absolute path>`. Resolving the *wrong* plan and executing it is the most expensive failure mode this command has - make the target unambiguous before any work begins.

### 0.2 Load full context

Read the entire plan plus every sibling artifact that exists - never operate on a skimmed plan:
- The plan file (required).
- `progress.md` / `etp-progress.md` (prior execution state, if any).
- `decisions.md`, `research.md`, `reviews/*.md` (xplan-style context, if present).
- The target repo's `CLAUDE.md` and `README.md` once the repo is identified (Phase 1.3).

### 0.3 Validate the plan is executable

A plan must contain actionable units. If it is pure prose - a design doc or vision statement with no steps, epics, tasks, or checklist - do **not** fabricate an execution graph. Instead, decompose it as best you can, present the decomposition you would execute, and ask the user to confirm or point you at the executable version. This is a soft blocker, handled per the Confusion Protocol, not a silent guess.

---

## Phase 1: Build the Execution Model

### 1.1 Decompose into units

Parse the plan into discrete **units** - the smallest independently-shippable pieces. Adapt to the plan's shape:
- xplan-style → one unit per agent-epic.
- Numbered/bulleted task list → one unit per task.
- Checklist → one unit per unchecked item.
- Prose with embedded steps → one unit per step you can scope concretely.

Each unit needs: a clear scope, the files/areas it touches, its acceptance criteria, and its dependencies. If the plan already specifies these, use them verbatim. If it does not, derive them and record your derivation in the progress file so the run is auditable.

### 1.2 Derive dependency order → waves

Group units into **waves**: everything in a wave is mutually independent and runs in parallel; waves run in sequence. Use the plan's own waves/dependency graph if it has one. If it is a flat list, infer dependencies from file overlap and logical ordering. When ordering is genuinely unclear, **serialize** - parallelism is an optimization, correctness is not. Only parallelize units you are confident are independent (no shared files, no producer/consumer relationship).

### 1.3 Identify the target repo and isolation model

Determine where the work lands and how agents avoid colliding:
- Find the target repo (from the plan, the `--repo` context, or the cwd).
- Detect the multi-agent setup: workspace model (`~/code/{repo}-workspaces/...`), flat clones (`~/code/{repo}-repos/...`), or single clone. If clones exist, assign one unit per clone. If not, give each implementation agent its own **git worktree** (`isolation: "worktree"`) so parallel agents never share a working tree.
- "As many agents as makes sense" = `min(units in this wave, available isolation slots, --max-agents)`. Never spawn more agents than the wave has independent units - that just creates idle agents or merge conflicts.

### 1.4 Surface prerequisites and human-only steps

Scan for anything the plan needs that an agent cannot do: credentials, API keys, OAuth/dashboard setup, DNS, paid-service signups. List these now. They become Phase 5 blockers (notify-and-continue), not silent failures mid-wave.

---

## Phase 2: Reconcile with Live State (resumability)

A plan an agent has been working on is rarely a blank slate. Before executing anything, reconcile the plan against reality so you never redo finished work:

```bash
gh pr list --state merged --limit 100      # what already landed
gh pr list --state open                    # in-flight work
gh issue list --state all --limit 200      # tracked + closed work
git branch -a                              # existing feature branches
```

For each unit, classify:
- **DONE** - its PR is merged or its acceptance criteria already hold on `main`. Skip it.
- **IN-FLIGHT** - an open PR or a branch exists. Do not restart it; enter it at the review step (Phase 4.2). For a branch with no PR, assess the commits and open the PR if the work is complete.
- **PENDING** - not started. Full treatment.

Also pull each active clone to latest `main` and note uncommitted work. Build the remaining-work list from the PENDING + IN-FLIGHT units only.

---

## Phase 3: Pre-Flight Analysis

Print the execution model so the run is legible before it starts:

```
Plan: <absolute path>
Repo: <repo>  ·  Isolation: workspace | flat-clones | worktrees
Units: N total  ·  M already done  ·  K remaining
Waves: <wave 1: units...> → <wave 2: units...> → ...
Max parallel agents: <n>
Prerequisites / human-only blockers detected: <list or none>
```

Then choose the path:
- **`--dry-run`** → stop here. The model above is the deliverable.
- **`--confirm`** → ask one AskUserQuestion go/no-go gate, then proceed on approval.
- **Default** → proceed immediately. The directive is to execute, not to ask.

**Exception - Confusion Protocol.** If a genuine high-stakes ambiguity exists, stop and ask even in default mode. The triggers are narrow: the plan could not be resolved to one file; the plan is prose with no executable units (0.3); the plan calls for destructive or irreversible actions it does not clearly authorize (dropping data, deleting resources, force-pushing shared branches, production deploys not named in the plan); or two incompatible interpretations of a unit's scope exist and the choice shapes everything downstream. Name the ambiguity in one sentence, give 2-3 options with tradeoffs, and wait. This is the directive's "absolute blocker → notify me" path. Everything outside these triggers, you reason through yourself.

---

## Phase 4: Execute Waves

For each wave, in order. This is the core loop.

### 4.1 Implement (parallel)

Spawn one `implementer` agent per unit (model sonnet), each in its own clone or worktree. Each agent:
- Branches from `origin/main` (`git checkout -b {issue-or-slug}-{desc} origin/main`).
- Implements the unit with tests, following the existing project patterns.
- **Verifies the work actually functions** - unit tests passing is the floor, not the finish line. Run the real path where feasible.
- Pushes and opens a PR whose body references the plan unit and closes its tracking issue if one exists.
- Returns the four-state status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT) with verification evidence.

Do not trust the self-report as proof. The diff and the review are the proof.

### 4.2 Adversarial review (SEPARATE agents - this is the integrity property)

For every PR - newly created or inherited in-flight - run the two-stage adversarial review. **The reviewer is a different agent from the implementer and is given the plan's spec for that unit plus the diff - never the implementer's rationale or self-report.** Coupled self-grading inflates grades; an implementer asked to grade its own work will pass it. Independence is what makes the sign-off mean anything.

- **Stage 1 - `spec-compliance-reviewer`**: Did the PR deliver exactly the unit's spec? Every deliverable present? Any scope creep (files, helpers, adjacent "while I'm here" changes the unit did not call for)? It treats the implementer's DONE as a claim and re-verifies from the diff. Stage 1 gates Stage 2.
- **Stage 2 - `code-quality-reviewer`** (only if Stage 1 passes): correctness bugs, security holes, silent failures, unhandled edge cases, project-pattern violations, over-engineering. Runs fresh checks (tests, build) rather than trusting prior output.

Each stage returns a verdict and a specific, itemized findings list. Reviewing quality on a spec-failing PR wastes effort on code that will change - so the order is fixed, never parallel.

### 4.3 Apply reasonable and valid fixes

Triage the findings yourself (orchestrator judgment - this is latent work, not delegable):
- **Reasonable and valid** (real bug, real scope creep, real spec gap) → fix it. Dispatch an `implementer` agent against the PR branch (or fix inline for a one-liner), push, and **re-review the changed PR** (back to 4.2). 
- **Invalid, speculative, or out-of-scope** (gold-plating, hypothetical edge cases, "you could also...") → reject with a one-line reason recorded in the progress file. Completeness means finishing the unit, not expanding it. Do not implement review suggestions that have no caller or that the plan did not ask for.

Loop review → fix → re-review until the PR passes both stages. Bound it: after **3 fix rounds** on the same PR without convergence, freeze that PR, record the unresolved findings as a blocker, and move on - one stuck PR does not halt the wave.

### 4.4 Merge

Merge a PR only when: it passed both review stages, CI is green, and it does not conflict. Merge in dependency order within the wave. Use squash merge (the repo default). Never merge a PR that failed adversarial review to "keep moving" - that defeats the entire loop.

### 4.5 Bring-up & integration verification

After the wave's PRs merge, execute any bring-up the plan specifies (migrations in order, dependency installs, type regen, env/secret sets, dev-server and worker restarts, deploys) and verify every layer is actually live - DB reachable and migrated, backend responding, frontend loading, workers running, deploy current. Run the wave's smoke test against the running system, not just CI. The next wave does not start against a degraded system. If the plan specifies no bring-up, confirm that is correct (docs-only units) rather than assuming.

### 4.6 Checkpoint

Update the progress file (`progress.md` for an xplan plan, else `<plan-basename>.etp-progress.md` beside the plan) with: units done this wave + their PRs, merged SHAs, the next wave, live-state verification result, and any open blockers. This is what makes a re-run of `/etp <same-plan>` resume instead of restart.

---

## Phase 5: Follow-Up Work That Arises

Execution surfaces work the plan did not enumerate: a bug found while integrating, a missing prerequisite, a gap between two units, a flaky test that is really a real bug. Handle every one - do not let it evaporate.

For each arising item:
1. **Track it** - open a GitHub issue (or a progress-file entry if issue-tracking is not set up), so nothing is lost.
2. **Triage scope**:
   - **In-scope-now** (the plan cannot be called complete, or is not reasonable+valid, without it) → treat it as a first-class unit: branch, implement (`implementer`), then the **same adversarial two-stage review** as any other PR (Phase 4.2-4.4), then merge. The directive is explicit that follow-up PRs get adversarial review too.
   - **Out-of-scope / speculative** (a nice-to-have, an unrelated improvement, a v2 idea) → log it as a deferred issue and leave it. Surface the deferred list in the final report. Scope discipline: finish the plan and the work it necessitates, not every improvement you can see.
3. **Absolute blocker** (needs a credential you do not have, a human-only dashboard action, an external dependency) → notify the user immediately with the exact ask, file a `blocked` issue, and **continue all non-blocked work**. A blocker stops one unit, never the run.

---

## Phase 6: Reason Through Problems

When a unit fails - red CI, merge conflict, failing test, an ambiguous step - do not stop and do not stack random fixes. Apply systematic debugging:
1. Read the actual error fully.
2. Find the root cause (trace it; do not patch the symptom).
3. Form one hypothesis, make the minimal change, verify it.
4. If three focused attempts fail (three-strike rule), stop guessing: question the assumption, re-read the relevant source/docs, or escalate that single unit as a blocker - then continue the rest of the plan.

Distinguish "something I can reason through" (the overwhelming majority - ambiguous wording, an obvious-once-traced bug, a missing import) from "an absolute blocker that genuinely needs the human" (missing credentials, a product decision with no right answer, an irreversible action the plan does not authorize). Reason through the first kind. Notify on the second. Never conflate "this is hard" with "this is blocked."

---

## Phase 7: Run to Completion

Loop Phases 4-6 until every condition holds:
- All units DONE or explicitly escalated as blocked.
- All in-scope follow-ups DONE.
- All PRs merged (or frozen-and-recorded as blocked).
- CI green, no uncommitted changes in any clone, no unexpected open PRs.
- All layers confirmed live; end-to-end smoke test passes.

"Don't stop until everything is complete" means: do not stop while completable work remains. Blocked units are set aside with a clear notification; they do not end the run. The run ends when the only thing left is genuinely human-blocked, and the user has been told exactly what each blocker needs.

---

## Phase 8: Final Audit & Report

### 8.1 Fresh audit (evidence, not memory)

```bash
gh pr list --state open
gh issue list --state open
# per clone: git status; then run the project's test + build
```

### 8.2 Report to the user

- **Completed**: units finished, PRs merged, with evidence (test output, smoke-test result, live URLs).
- **Blocked**: each blocker, why, and the exact human action that unblocks it.
- **Deferred**: out-of-scope follow-ups logged but intentionally not done.
- **Live state**: the verification that the system actually runs end-to-end.

### 8.3 Finalize the progress file

Mark it `COMPLETE`, or `BLOCKED - WAITING ON HUMAN` with the blocker list. A later `/etp <same-plan>` reads this and resumes from exactly here.

---

## Guardrails

**Integrity - the separate judge.** The agent that reviews a PR is never the agent that wrote it, and the reviewer never sees the implementer's rationale or self-report - only the unit's spec and the diff. The orchestrator does not grade PRs in its own context either. This separation is the whole reason a self-signed-off execution can be trusted; collapsing it turns review into rubber-stamping.

**Two-stage order is fixed.** Spec-compliance gates code-quality. Never run them in parallel, never quality-review a spec-failing PR.

**Verify, don't trust.** A subagent's DONE is a claim. Read the diff, run the tests, check the artifact before treating a unit as complete. Fresh evidence before every completion claim.

**Scope discipline.** Execute the plan plus the follow-ups it necessitates. Reject "while I'm here" work, speculative features, and review suggestions with no caller. Finishing the job is not expanding the job.

**Notify-and-continue.** Absolute blockers are reported the moment they are found and never halt non-blocked work. The run degrades gracefully around blockers; it does not stop dead.

**Safety on irreversible / outward actions.** Even in autonomous mode, anything destructive or externally-visible that the plan did not clearly authorize - production deploys, resource deletion, force-pushing shared branches, sending external communications - requires notifying the user first. The plan authorizes its own scope; it does not authorize off-plan irreversible acts.

**No AI attribution** in commits or PR bodies (per the git-workflow rule). Use the repo's PR template if one exists.

**Resumability.** Checkpoint after every wave. The progress file beside the plan is the resume point - re-invoking `/etp` on the same plan continues rather than restarts.

---

## Relationship to xplan

- `/xplan`, `/xplana` - create a plan (research → plan → review). `etp` consumes a plan; it never creates one.
- `/xplan-resume` - resumes an `/xplan`-native interrupted execution using xplan's epic/wave checkpoint structure. Prefer it when the plan is a live xplan run.
- `/etp` - executes **any** plan file, xplan-authored or not, with the hardened adversarial-review and follow-up loop above. It is the general-purpose execution engine.
