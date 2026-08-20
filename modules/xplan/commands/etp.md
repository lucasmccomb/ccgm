---
description: Execute a ready plan OR GitHub issue(s) end-to-end with parallel agents, adversarial PR review, and follow-up completion. Runs to completion, stopping only for absolute blockers.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <plan-file-or-dir | #issue [#issue ...] | issue-url> [--dry-run] [--confirm] [--max-agents N] [--light-review]
---

# etp - Execute the Plan or Issue(s)

Take work that is ready to build - a plan an agent has been developing, any plan file you point at, or one-or-more GitHub issues that have been investigated and are ready to complete - and drive it to done. `etp` does not research, name, or write the work; it **executes** it. It resolves the target into units, runs them with parallel agents, adversarially reviews every PR with a *separate* agent, fixes what is reasonable and valid, completes the follow-up work that surfaces along the way (reviewing those PRs too), and does not stop until everything that can be done is done.

A plan and an issue are two **sources** of work that both resolve into the same thing - **units** - and everything downstream (review → fix → merge → follow-ups → audit) is shared. **Ceremony scales to the work**: a single issue skips the multi-clone / wave / bring-up machinery a multi-epic plan needs and collapses to implement → adversarial review → fix → merge → follow-ups → done.

## Prime Directive

> Execute the plan that is linked in the prompt itself, according to the file path, use as many agents as makes sense, do adversarial critical reviews of all PRs and make any fixes to those PRs that are reasonable and valid, complete any follow-up issues that arise during the execution of the plan and do adversarial reviews on those PRs as well. Don't stop until everything is complete. Do your best to reason through issues that you find along the way. If there's an absolute blocker, notify me of that, but continue the plan if possible.

Everything below is the operational expansion of that directive. When a phase and the directive seem to conflict, the directive wins. The directive was written for a plan; it applies identically when the work source is one or more GitHub issues - read "plan" as "the work you pointed me at."

## When to use `/etp`

- A `/xplan` (or `/xplana`) plan exists and you want it executed now.
- An agent has been working a plan and you want another agent to pick it up and finish it.
- You have a hand-written plan, design doc with executable steps, or checklist at a known path.
- **One or more GitHub issues** have been investigated and are ready to build: `/etp #42`, or a batch `/etp #42 #43 #45`.

## When NOT to use it

- There is no ready work yet - neither a plan nor an investigated issue. Create a plan (`/xplan`) or flesh out the issue first.
- The issue is vague or un-investigated (no acceptance criteria, no approach, no root-cause). `etp` surfaces this rather than guessing - see Phase 0.5. Investigate it first (`/debug` for a bug, `/xplan` for a feature).
- The "plan" is pure prose with no executable units (a vision doc). Same handling: surfaced, not guessed.
- You want to resume an `/xplan`-native interrupted run with its full epic/wave checkpoint structure - `/xplan-resume` is the specialized tool. `etp` is the general work executor (and is itself resumable - see Resumability).

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
- **Target** (positional): a plan path (file or directory), **one or more issue references** (`#N`, a bare number, or a GitHub issue URL), or empty.
- **`--dry-run`**: resolve and analyze the target, print the execution model, then STOP. No branches, PRs, or merges.
- **`--confirm`**: pause for one explicit go/no-go gate after the pre-flight analysis (Phase 3). Off by default - the directive says don't stop, so the default is to proceed once the target is resolved unambiguously.
- **`--max-agents N`**: cap concurrent implementation agents (default: the width of the widest wave, clamped to the available isolation slots).
- **`--light-review`**: downgrade the adversarial review to a single separate-agent spec-compliance pass (skip the Stage-2 code-quality pass). For trivial diffs only. **The default is the full two-stage review regardless of diff size** - this flag is an explicit opt-out, never the default.

---

## Phase 0: Resolve & Load the Work Source

### 0.1 Classify the target

Determine the target type deterministically - with shell/pattern checks, not guesses:
- Every positional token matches an **issue reference** (`^#?\d+$`, or a `github.com/.../issues/N` URL) → **issue target** (single if one, **batch** if several).
- The positional token is a **path** that exists (file or directory) → **plan target**.
- **Empty** → autodetect an in-progress **plan** only (see 0.2.3). Do not autodetect an issue - guessing which issue to build is the wrong kind of guess.
- Anything that resolves to neither (a path that does not exist, a malformed ref) → absolute blocker: notify the user with what you looked for; do not invent a target.

Do not mix types in one run (a plan path AND issue refs). If both appear, ask which the user meant.

### 0.2 Resolve a plan target

1. **Explicit file** - the argument is a path to a file that exists → that is the plan.
2. **Directory** - look, in order, for `plan.md`, `PLAN.md`, then the single most-recently-modified `*.md`. If a `progress.md` / `etp-progress.md` sits beside it, load that too (resumability).
3. **Empty argument (autodetect)** - find the plan an agent has been working on:
   - `ls -t ~/code/plans/*/plan.md` and check each sibling `progress.md` for `Status: IN PROGRESS` or `INTERRUPTED`.
   - Check the current repo root and `docs/` for a `plan.md` / `PLAN.md`.
   - Exactly one in-progress candidate → use it. Several → list them and ask (AskUserQuestion). None → absolute blocker, notify and stop.

Announce explicitly: `Resolved plan: <absolute path>`. Resolving the *wrong* target and executing it is the most expensive failure mode this command has.

### 0.3 Resolve an issue target

For each issue reference, load the full issue - the body **and the comments** (the comments are where investigation, root-cause, and the agreed approach usually live):

```bash
gh issue view <N> --json number,title,body,comments,labels,state,assignees
```

- Announce each: `Resolved issue: #<N> "<title>" (<state>)`.
- If an issue is **CLOSED**, warn and ask whether to proceed (it may already be done - see Phase 2).
- The issue's title + body + acceptance criteria + investigation comments **become the unit's spec** - this is exactly what the adversarial reviewer will check the PR against (Phase 4.2). Capture it.
- For a **batch**, resolve every issue before building the model so dependencies between them are visible.

### 0.4 Load full context

Read everything that grounds the work - never operate on a skimmed target:
- A plan: the plan file plus `progress.md`/`etp-progress.md`, `decisions.md`, `research.md`, `reviews/*.md` (whatever exists).
- An issue: the issue body + all comments, plus any files, PRs, or prior issues they link to.
- In both cases: the target repo's `CLAUDE.md` and `README.md` once the repo is identified (Phase 1.3).

### 0.5 Validate the work is executable

Work must be concrete enough to build without guessing.
- A **plan** must contain actionable units. Pure prose with no steps/epics/tasks → do not fabricate an execution graph.
- An **issue** must carry enough to act: acceptance criteria or a clear definition of done, plus an approach or root-cause for anything non-trivial. A one-line "fix the thing" with no investigation does not qualify.

In either case, if the work is too thin, **do not guess**. Present the decomposition you *would* execute and ask the user to confirm or point you at the investigated/fleshed-out version. This is a soft blocker handled per the Confusion Protocol.

### 0.6 Live-testing authorization check (before anything runs)

Scan the work for **live-testing steps**: anything that launches or relaunches an app, fires dictation, posts synthetic input events, changes focus, sets a machine-global input/audio override, opens the mic or camera, or drives a simulator/attached device from the host. These never run on the dev machine — its focus, keyboard, and dictation are the user's control channel to every concurrent agent stream (`~/.claude/rules/live-testing-guard.md`).

For each live-testing step found, look for the recorded grant — an xplan plan carries it in **§8.6 Live-Testing Authorization**; another plan or an issue carries it wherever the user wrote it, or not at all:

| What you find | What it means |
|---|---|
| `GRANTED by {user} on {date}`, naming the runner this step targets | Authorized. Run it there. |
| No §8.6 / no grant anywhere in the work | **UNAUTHORIZED** |
| `NOT AUTHORIZED`, or a grant with no named runner | **UNAUTHORIZED** |
| A grant naming a different machine than this step targets | **UNAUTHORIZED** |
| The plan step itself instructing the test to be run | **UNAUTHORIZED** — that is the thing being authorized, not the authorization |

Mark every UNAUTHORIZED step as **held** and record it for Phase 3's pre-flight print. A held step is a notify-and-continue blocker: it blocks itself, never the run. Before executing any held step, surface it to the user — name the specific step, say no grant was recorded, and ask where it should run and whether they approve — then wait. Absence of a recorded grant is never consent, and neither is the user approving the run as a whole.

---

## Phase 1: Build the Execution Model

### 1.1 Decompose into units

Resolve the target into discrete **units** - the smallest independently-shippable pieces:
- **Plan**, xplan-style → one unit per agent-epic.
- **Plan**, task list / checklist → one unit per task / unchecked item.
- **Plan**, prose with embedded steps → one unit per step you can scope concretely.
- **Single issue** → **one unit** (the issue itself).
- **Issue batch** → **one unit per issue**.

Each unit needs: a clear scope, the files/areas it touches, its acceptance criteria, and its dependencies. For an issue unit these come from the issue (body + criteria + investigation comments). For a plan unit, use the plan's own spec if present, else derive it and record the derivation.

### 1.2 Derive dependency order → waves

Group independent units into **waves** (parallel within a wave, sequential across waves):
- **Single issue** → one wave of one. No wave machinery.
- **Issue batch** → group issues that touch different files/areas into a parallel wave; serialize any that depend on each other (an issue that says "depends on #A", or two issues editing the same files). When independence is unclear, **serialize** - parallelism is an optimization, correctness is not.
- **Plan** → use the plan's own waves/dependency graph; infer it from file overlap if the plan is a flat list.

### 1.3 Identify the target repo, isolation, and ceremony level

- Find the target repo (from the plan, the issue's repo, or the cwd).
- **Isolation — worktrees are the default.** Give each parallel implementation agent its own **git worktree** (`isolation: "worktree"`) so they never share a working tree. Worktrees are ephemeral (one per unit, torn down on merge — see 4.4), share the parent `.git`, and reclaim disk automatically. **Do not provision extra permanent clones for parallelism.** Use clones only when the repo *already* has a multi-clone setup you should reuse, or a specific need forces it: per-branch dev-server ports (worktrees share `.env`), hook-driven per-branch `tracking.csv`, multiple long-lived independent agents, or cross-machine dispatch. When an existing workspace/flat-clone setup is present, assign one unit per clone; otherwise (the common case) use worktrees. See `git-worktrees.md`.
- **"As many agents as makes sense"** = `min(units in this wave, available isolation slots, --max-agents)`. Never spawn more agents than the wave has independent units. With worktrees the "isolation slots" are effectively the concurrency cap (below), not a fixed clone count.
- **Ceremony scales to the work.** Match the apparatus to the size:

  | Target | Waves | Isolation | Bring-up runbook | Checkpoint record |
  |--------|-------|-----------|------------------|-------------------|
  | Single issue | none (1 unit) | one worktree | only if the issue calls for it | the issue + its PR |
  | Issue batch | group independents | one worktree per parallel unit | per-issue if any call for it | live GitHub state (re-run reconciles) |
  | Plan | from the plan | worktrees (or an existing clone/workspace setup) | per the plan (Phase 4.5) | progress file beside the plan |

  Do not impose plan-scale ceremony (multi-clone provisioning, wave checkpoints, bring-up runbooks) on a single issue. Do not skip it for a real multi-epic plan. Every worktree created here is torn down after its unit merges (4.4) and any leaks are swept at the end (Phase 8) — teardown is mandatory, not best-effort.

### 1.4 Surface prerequisites and human-only steps (bucket them to the edges)

Scan for anything the work needs that an agent cannot do: credentials, API keys, OAuth/dashboard setup, DNS, paid-service signups. First apply the minimization test — anything an agent *can* do via CLI/API is not human work; do it, don't ask. Whatever genuinely remains is **bucketed to the edges**, never left to stall the run mid-stream:

- **Front-loaded** — surface every up-front human-only step *now*, before any unit runs, so the human can clear them once and the run then proceeds untouched.
- **Deferred** — human steps that only make sense at the end (final DNS cutover, store submission, a human sign-off) are queued for after all agent work completes.

They become Phase 5 blockers (notify-and-continue), not silent failures mid-run. The user should not be a step *inside* the run: never pause the whole run waiting on human work that could have been front-loaded.

### 1.5 Establish the decision context (so follow-on calls need no human)

Execution will surface unplanned follow-on work (Phase 5). To triage and direct it *without stopping to ask the user*, ground yourself in the decision context first:

- **Plan target**: read the plan's **Mission & Guiding Decision Principles** (xplan plans: §1.4) — the software's mission, the codebase's governing conventions, and the plan's decision heuristics. This is what lets you decide follow-on direction the way the plan's author would.
- **Issue target, or a plan missing that section**: derive the equivalent from the codebase — its `CLAUDE.md`, `README.md`, and the conventions visible in the code — plus the issue's own stated intent. If you cannot form a confident decision context this way, that gap itself is a Phase 5 human-blocked item (a product decision with no right answer), not a reason to guess.

Hold this context for Phases 5 and 6: it is the reference you triage and reason against.

---

## Phase 2: Reconcile with Live State (resumability)

Work that an agent has touched is rarely a blank slate. Before executing, reconcile against reality so you never redo finished work:

```bash
gh pr list --state merged --limit 100      # what already landed
gh pr list --state open                    # in-flight work
gh issue list --state all --limit 200      # tracked + closed work
git branch -a                              # existing feature branches
```

Classify each unit:
- **DONE** - its PR is merged, its issue is already closed by a merged PR, or its acceptance criteria already hold on `main`. Skip it.
- **IN-FLIGHT** - an open PR or a branch exists. Do not restart it; enter it at the review step (Phase 4.2). A branch with no PR → assess the commits and open the PR if the work is complete.
- **PENDING** - not started. Full treatment.

For an issue **batch**, this is the resume mechanism: re-running `/etp #42 #43 #45` skips the ones already merged and continues the rest - no progress file needed, live GitHub state is the checkpoint. Build the remaining-work list from PENDING + IN-FLIGHT only.

---

## Phase 3: Pre-Flight Analysis

Print the execution model so the run is legible before it starts:

```
Work source: <plan path | issue #N | issues #N #M #… (batch)>
Repo: <repo>  ·  Isolation: workspace | flat-clones | worktrees | single
Units: N total  ·  M already done  ·  K remaining
Waves: <wave 1: units…> → <wave 2: units…> → …   (or "single unit" / "N independent issues")
Review: full two-stage (default)  |  light (spec-compliance only)
Max parallel agents: <n>
Prerequisites / human-only blockers detected: <list or none>
Live-testing steps: <none | N authorized on {runner} | N HELD - unauthorized (list them)>
```

Then choose the path:
- **`--dry-run`** → stop here. The model above is the deliverable.
- **`--confirm`** → ask one AskUserQuestion go/no-go gate, then proceed on approval.
- **Default** → proceed immediately. The directive is to execute, not to ask.

**Exception - Confusion Protocol.** Stop and ask even in default mode when a genuine high-stakes ambiguity exists. Narrow triggers: the target could not be resolved; the work is too thin to build without guessing (0.5); it calls for destructive or irreversible actions it does not clearly authorize (dropping data, deleting resources, force-pushing shared branches, production deploys not named in the work); a live-testing step is held as UNAUTHORIZED (0.6) and its turn has come; or two incompatible interpretations of a unit's scope exist and the choice shapes everything downstream. Name the ambiguity in one sentence, give 2-3 options with tradeoffs, and wait. This is the directive's "absolute blocker → notify me" path. Everything outside these triggers, you reason through yourself.

---

## Phase 4: Execute

For each wave, in order (a single issue is a wave of one). This is the core loop, identical for plans and issues.

### 4.1 Implement (parallel within a wave)

Spawn one `implementer` agent per unit (model sonnet), each in its own **worktree** (`isolation: "worktree"`) — or its assigned clone when the repo uses the multi-clone setup (1.3). Each agent:

> **Concurrency — avoid the 429 throttle.** `implementer` agents run on `sonnet` (light), so a wave of up to ~8 is safe. But the default `--max-agents` (widest wave, clamped to isolation slots) can exceed that in a workspace with many clones — **cap the live wave at 8 light agents, or 4 if you raise `implementer` to a heavier model / higher effort**. If a wave has more units than the cap, split it into sub-waves. Bursting too many heavy agents trips a server-side rate limit (`Server is temporarily limiting requests · Rate limited`) that fails the whole wave; if you hit it, wait 30–60s and re-spawn only the unfinished units in smaller sub-waves. See `~/.claude/rules/concurrency-and-rate-limits.md`.
- Branches from `origin/main` (`git checkout -b {issue#}-{desc} origin/main` for an issue unit, `{slug}-{desc}` for a plan unit).
- Implements the unit with tests, following the existing project patterns.
- **Verifies the work actually functions** - unit tests passing is the floor, not the finish line. Run the real path where feasible.
- Pushes and opens a PR. For an issue unit the PR body **closes the issue** (`Closes #N`); for a plan unit it references the plan unit and closes its tracking issue if one exists.
- Returns the four-state status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT) with verification evidence.

Do not trust the self-report as proof. The diff and the review are the proof.

### 4.2 Adversarial review (SEPARATE agents - this is the integrity property)

For every PR - newly created or inherited in-flight - run the adversarial review. **The reviewer is a different agent from the implementer and is given the unit's spec plus the diff - never the implementer's rationale or self-report.** For an issue unit, the **spec is the issue** (title + body + acceptance criteria + investigation comments). For a plan unit, the spec is the plan's unit. Coupled self-grading inflates grades; an implementer asked to grade its own work will pass it. Independence is what makes the sign-off mean anything.

**Default - full two-stage review** (every PR, regardless of diff size):
- **Stage 1 - `spec-compliance-reviewer`**: Did the PR deliver exactly the spec (the issue's definition of done / the plan unit's deliverables)? Everything present? Any scope creep (files, helpers, adjacent "while I'm here" changes not asked for)? It treats the implementer's DONE as a claim and re-verifies from the diff. Stage 1 gates Stage 2.
- **Stage 2 - `code-quality-reviewer`** (only if Stage 1 passes): correctness bugs, security holes, silent failures, unhandled edge cases, project-pattern violations, over-engineering. Runs fresh checks (tests, build) rather than trusting prior output.

**`--light-review`** collapses this to Stage 1 only - a single separate-agent spec-compliance pass, skipping Stage 2. Use it only for trivial diffs (a typo, a constant bump). It still keeps the integrity property (a separate reviewer, the issue as spec); it only drops depth. It is never the default.

Each stage returns a verdict and a specific, itemized findings list. Quality-reviewing a spec-failing PR wastes effort on code that will change - so the order is fixed, never parallel.

### 4.3 Apply reasonable and valid fixes

Triage the findings yourself (orchestrator judgment - latent work, not delegable):
- **Reasonable and valid** (real bug, real scope creep, real spec gap) → fix it. Dispatch an `implementer` against the PR branch (or fix inline for a one-liner — unless advisor mode is on (`~/.claude/advisor-mode` exists), where even one-liners are delegated: the inline "quick fix" is the documented drift pattern the mode's guard blocks), push, and **re-review the changed PR** (back to 4.2).
- **Invalid, speculative, or out-of-scope** (gold-plating, hypothetical edge cases, "you could also…") → reject with a one-line reason recorded in the run record. Completeness means finishing the unit, not expanding it. Do not implement review suggestions with no caller or that the work did not ask for.

Loop review → fix → re-review until the PR passes. Bound it: after **3 fix rounds** on the same PR without convergence, freeze that PR, record the unresolved findings as a blocker, and move on - one stuck PR does not halt the wave.

### 4.35 Drive the PR to CI-green (bounded post-PR loop)

The finish line is not "PR opened" - it is "CI green and mergeable." Adversarial review (4.2-4.3) judges the diff; this step makes the *pipeline* agree. Run it for every PR after it passes adversarial review and before it can merge (4.4). It applies to inherited in-flight PRs too.

**Read CI fresh, never assume.** Poll the actual checks - do not infer state from "the implementer said tests passed":

```bash
gh pr checks <PR> --watch    # block until checks finish (or poll without --watch and re-read)
gh pr view <PR> --json mergeable,mergeStateStatus,statusCheckRollup
```

Classify the result:
- **Green and mergeable** → done with this step; proceed to 4.4.
- **Red checks** → a real failure to diagnose and fix (below).
- **Conflicting / behind base** (`mergeable: CONFLICTING`, or a `mergeStateStatus` indicating the branch is behind) → rebase the branch on the latest `origin/main` and resolve conflicts before re-checking.
- **Pending/queued** → keep waiting; do not act on an unfinished run.

**The bounded fix loop.** Each round, in order:

1. **Read the failure, fully.** Pull the failing job's logs - `gh run view <run-id> --log-failed` (find the run via `gh pr checks` or `gh run list --branch <branch>`). Read the actual error, the failing job, and the step. Do not guess from the check name.
2. **Find the root cause, then fix at the source.** This is systematic-debugging, not symptom-patching: one hypothesis, the minimal change. For a code/test failure, dispatch a targeted `implementer` (model sonnet) against the PR branch scoped to *exactly* that failure - never a broad rewrite. For a merge conflict / behind-base, rebase on `origin/main` and resolve. For a suspected flaky check, re-run it once (`gh run rerun <run-id> --failed`) before treating it as real - a check that fails twice is a real bug, not flake.
3. **Push and re-check.** Push the fix, then re-read CI fresh (back to the top of this step). A fix that introduces a new failure counts as the same loop continuing, not a fresh start.

**The bound (explicit, no infinite loop).** Allow **at most 3 CI-fix rounds** on the same PR. This mirrors the three-strike rule (Phase 6) and the 4.3 review bound. After 3 rounds without reaching green:
- **Freeze** the PR (do not merge it).
- **Record** the unresolved CI failure as a blocker on the run record (issue/batch: a one-line note + the failing-job link; plan: the progress file's blocker list).
- **Escalate to the user** with a clear, specific summary: which PR, which check failed, the root-cause read so far, the fixes already attempted, and the exact failing-log link. This is the directive's "absolute blocker → notify me" path for CI.
- **Continue all other PRs and waves.** One CI-stuck PR is set aside, never a halt for the run.

A PR that cannot be driven green within the bound is treated exactly like a PR frozen at 4.3: blocked, recorded, escalated, and stepped around - not merged, not abandoned silently.

### 4.4 Merge and tear down the unit's worktree

Merge a PR only when: it passed review (both stages, or Stage 1 under `--light-review`), CI is **green and mergeable** (verified fresh via 4.35, not assumed), and it does not conflict. Merge in dependency order within the wave. Squash merge (the repo default). Never merge a PR that failed adversarial review or has red/unresolved CI to "keep moving" - that defeats the entire loop.

**Then immediately remove that unit's worktree** (when the unit ran in a worktree, the default). This is mandatory, not best-effort — a built-in worktree does **not** auto-remove, so a merged unit whose worktree lingers is exactly the leak that filled 237 GB in the incident:

```bash
git worktree remove <unit-worktree-path>   # non-force; the branch ref and its commits survive removal
git worktree prune
```

Removing the worktree does not delete the branch or the merged work — only the checkout (and its build tree). If the non-force remove refuses (unexpected for a just-merged clean unit), do not force it blindly; leave it for the Phase 8 sweep to classify. A unit that ran in a reused clone (multi-clone setup) is not a worktree — reset that clone to `origin/main` instead of removing anything.

### 4.5 Bring-up & integration verification (when applicable)

If the work specifies bring-up (migrations, dependency installs, type regen, env/secret sets, dev-server/worker restarts, deploys), execute it and verify every layer is actually live - DB migrated, backend responding, frontend loading, workers running, deploy current - then run the **autonomous E2E suite against the running system**, not just CI. For a plan, that is its Section 8 suite; for an issue, the E2E tests covering the changed surface. The E2E suite (not a bare smoke test) is the certainty gate: green ⇒ clean / mergeable, red ⇒ broken. A single issue usually has no bring-up; confirm that is true rather than assuming. A plan wave does not advance against a degraded system or a red suite.

**If the touched surface has no E2E coverage**, adding it is an in-scope follow-up (Phase 5), not an optional extra — the standing assumption is that more autonomous E2E coverage is always wanted, so the changed behavior gets a real end-to-end test before the work is called complete. This is the executor's side of the plan's E2E mandate (adrev tenet T4).

### 4.6 Checkpoint

Record progress so the run is resumable, matched to the ceremony level (1.3):
- **Single issue** → the issue + its PR is the record. No file.
- **Issue batch** → live GitHub state is the record; a re-run reconciles (Phase 2). Optionally jot a one-line status per issue if the batch is large.
- **Plan** → update the progress file (`progress.md`, else `<plan-basename>.etp-progress.md` beside the plan) with units done, PRs, merged SHAs, next wave, live-state result, and open blockers.

---

## Phase 5: Follow-Up Work That Arises

Execution surfaces work the target did not enumerate: a bug found while integrating, a missing prerequisite, a gap between two units, a flaky test that is really a real bug. Handle every one - do not let it evaporate. This is the directive's "complete any follow-up issues that arise," and for an xplan-authored plan it is that plan's **Follow-Up Work Completion Contract (§9.5)**: execution is **not complete** while an in-scope follow-up remains open.

For each arising item:
1. **Track it** - open a GitHub issue (label it `follow-up`), so nothing is lost.
2. **Triage scope against the decision context (Phase 1.5)** - decide this *yourself* from the plan's §1.4 / the codebase's mission and conventions; do NOT stop to ask the user how to direct in-scope follow-on work. That is what the decision context is for.
   - **In-scope-now** (the work cannot be called complete, or reasonable+valid, without it) → treat it as a first-class unit: branch, implement (`implementer`), then the **same adversarial review** as any other PR (Phase 4.2-4.4), then merge. Follow-up PRs get adversarially reviewed too - this is explicit in the directive.
   - **Out-of-scope / speculative** (a nice-to-have, an unrelated improvement, a v2 idea) → log it as a deferred issue and leave it. Surface the deferred list in the final report. Scope discipline: finish the work and what it necessitates, not every improvement you can see.
3. **Absolute blocker** (needs a credential you do not have, a human-only dashboard action, a product decision with no right answer) → notify the user immediately with the exact ask, file a `blocked` issue, and **continue all non-blocked work**. A blocker stops one unit, never the run. Human-blocked follow-ups are the *only* work allowed to remain open when the run is reported complete.

---

## Phase 6: Reason Through Problems

When a unit fails - red CI, merge conflict, failing test, an ambiguous step - do not stop and do not stack random fixes. Apply systematic debugging:
1. Read the actual error fully.
2. Find the root cause (trace it; do not patch the symptom).
3. Form one hypothesis, make the minimal change, verify it.
4. If three focused attempts fail (three-strike rule), stop guessing: question the assumption, re-read the relevant source/docs, or escalate that single unit as a blocker - then continue the rest.

Distinguish "something I can reason through" (the overwhelming majority - ambiguous wording, an obvious-once-traced bug, a missing import) from "an absolute blocker that genuinely needs the human" (missing credentials, a product decision with no right answer, an irreversible action the work does not authorize). Reason through the first kind — ground the call in the decision context (Phase 1.5): the plan's mission and decision principles, or the codebase's conventions, tell you which direction the author would take. Notify on the second. Never conflate "this is hard" with "this is blocked."

---

## Phase 7: Run to Completion

Loop Phases 4-6 until every condition holds:
- All units DONE or explicitly escalated as blocked.
- All in-scope follow-ups DONE.
- All PRs merged (or frozen-and-recorded as blocked); all target issues closed by their merged PRs.
- Every merged PR reached CI-green via the bounded loop (4.35); any PR that could not be driven green within the bound is among the frozen-and-recorded blockers, not silently merged.
- CI green, no uncommitted changes in any clone, no unexpected open PRs.
- No merged unit's worktree left behind — each removed at 4.4, and `/worktree-sweep` (Phase 8) reclaimed any leak.
- All layers confirmed live (where the work has runtime impact); the **autonomous E2E suite is green** against the running system (the plan's §8 suite, or the E2E tests covering a changed issue surface) — the certainty oracle, not a bare smoke test. Any surface a plan's §8.5 names as not-certified is the only acceptable manual residue.

"Don't stop until everything is complete" means: do not stop while completable work remains. Blocked units are set aside with a clear notification; they do not end the run. The run ends when the only thing left is genuinely human-blocked, and the user has been told exactly what each blocker needs.

---

## Phase 8: Final Audit & Report

### 8.1 Fresh audit (evidence, not memory)

```bash
gh pr list --state open
gh issue list --state open
# per clone: git status; then run the project's test + build
```

**Sweep leaked worktrees (mandatory teardown backstop).** Even with per-unit removal at 4.4, a worktree can leak — a unit that errored before its merge-and-remove, a `isolation:"worktree"` worktree the harness could not auto-reclaim because it was built in, an early exit. Run the safe sweep so no worktree outlives the run:

```bash
/worktree-sweep        # removes only clean worktrees; preserves any with unsaved work; prunes stale metadata
```

Report what it reclaimed and anything it preserved (a preserved worktree means unsaved work an implementer left behind — surface it, do not force it away). **Run this even when the run exits early** (a blocker halts a unit, a gate stops the run): teardown must not depend on reaching a clean completion — that is the whole lesson of the incident.

### 8.2 Report to the user

- **Completed**: units finished, PRs merged, issues closed - with evidence (test output, **autonomous E2E suite result (green)**, live URLs).
- **Blocked**: each blocker, why, and the exact human action that unblocks it.
- **Deferred**: out-of-scope follow-ups logged but intentionally not done.
- **Live state**: the verification that the system actually runs end-to-end (where applicable).

### 8.3 Finalize the run record

A plan run: mark the progress file `COMPLETE`, or `BLOCKED - WAITING ON HUMAN` with the blocker list. An issue/batch run: live GitHub state is the record - a re-run of `/etp <same args>` reconciles and resumes from exactly here.

---

## Guardrails

**Integrity - the separate judge.** The agent that reviews a PR is never the agent that wrote it, and the reviewer never sees the implementer's rationale or self-report - only the unit's spec (the issue, or the plan unit) and the diff. The orchestrator does not grade PRs in its own context either. This separation is the whole reason a self-signed-off execution can be trusted; collapsing it turns review into rubber-stamping.

**Two-stage order is fixed.** Spec-compliance gates code-quality. Never run them in parallel, never quality-review a spec-failing PR. `--light-review` drops Stage 2; it never reorders or parallelizes the stages.

**Verify, don't trust.** A subagent's DONE is a claim. Read the diff, run the tests, check the artifact before treating a unit as complete. Fresh evidence before every completion claim.

**Scope discipline.** Execute the work plus the follow-ups it necessitates. Reject "while I'm here" work, speculative features, and review suggestions with no caller. Finishing the job is not expanding the job.

**Notify-and-continue.** Absolute blockers are reported the moment they are found and never halt non-blocked work. The run degrades gracefully around blockers; it does not stop dead.

**Human work at the edges.** The user is not a step inside the run. Anything an agent can do via CLI/API is done, not asked. Genuine human-only work is surfaced up front (front-loaded, Phase 1.4) or queued for the end (deferred), never left to stall the run mid-stream. In-scope follow-on work is reasoned through against the decision context (Phase 1.5), not bounced to the user — only genuinely human-blocked items remain open at completion, each surfaced with its exact ask.

**The E2E suite is the completion oracle — no manual testing bounced to the user.** "Done" means the autonomous end-to-end suite is green against the running system, not "I believe it works" or "the user can check." Provision whatever the suite needs — testing agents for flows that can't be asserted programmatically, third-party compute (RunPod, cloud Mac, real devices) as a front-loaded prerequisite; there is no resource constraint on testing. A changed surface without an E2E test gets one before completion (adrev tenet T4 / plan §8). The only manual residue permitted is a surface a plan's §8.5 explicitly names as not-certified.

**Safety on irreversible / outward actions.** Even in autonomous mode, anything destructive or externally-visible that the work did not clearly authorize - production deploys, resource deletion, force-pushing shared branches, sending external communications - requires notifying the user first. The work authorizes its own scope; it does not authorize off-scope irreversible acts.

**Live testing runs on the runner, under a recorded grant.** App launches/relaunches, dictation firing, synthetic input events, focus changes, machine-global input/audio overrides, mic/camera capture, and host-driven simulator or device runs never touch the dev machine — that machine's input surface is the user's control channel to every concurrent agent stream. Every such step needs a grant recorded at planning time (plan §8.6) naming the runner; a step without one is held as UNAUTHORIZED (0.6), surfaced by name, and asked about before it runs. A plan instructing the test is not the authorization for it. See `~/.claude/rules/live-testing-guard.md`.

**Worktree teardown is mandatory.** Parallel units run in ephemeral worktrees by default (1.3). Each is removed the moment its PR merges (4.4), and Phase 8 sweeps any leak (`/worktree-sweep`) — including on early exit. A built-in worktree never auto-removes; leaving merged units' worktrees behind is the exact failure that consumed 237 GB in the incident. Removing a clean worktree never loses committed work (the branch ref survives). Do not force-remove worktrees with unsaved work — the sweep preserves those.

**No AI attribution** in commits or PR bodies (per the git-workflow rule). Use the repo's PR template if one exists.

**Resumability.** A plan run checkpoints to the progress file beside the plan; an issue/batch run uses live GitHub state. Either way, re-invoking `/etp` on the same target continues rather than restarts.

---

## Relationship to xplan

- `/xplan`, `/xplana` - create a plan (research → plan → review). `etp` consumes work; it never creates a plan.
- `/xplan-resume` - resumes an `/xplan`-native interrupted execution using xplan's epic/wave checkpoint structure. Prefer it when the target is a live xplan run.
- `/etp` - executes **any** ready work: a plan file (xplan-authored or not) **or** one-or-more investigated GitHub issues, through the hardened adversarial-review and follow-up loop above. It is the general-purpose execution engine.
