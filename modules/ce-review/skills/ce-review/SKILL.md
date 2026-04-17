---
name: ce-review
description: >
  Unified code-review orchestrator. Dispatches tiered reviewer personas (correctness, testing, maintainability, plus conditional security, performance, reliability, api-contract, data-migrations) in parallel, runs an adversarial/red-team lens AFTER specialists with access to their findings, merges JSON findings with P0-P3 severity and confidence (0.0-1.0), and routes by an autofix_class (safe_auto / gated_auto / manual / advisory). Prior learnings from docs/solutions/ are pulled via learnings-researcher before dispatch. Modes - interactive / autofix / report-only / headless.
  Triggers: ce-review, review this PR, orchestrated review, tiered review, red-team review, adversarial review, review with confidence.
disable-model-invocation: false
---

# /ce-review - Unified Review Orchestrator

A single entry point that composes CCGM's review surface into one structured pipeline. Pulls relevant prior learnings, runs scope-drift first, fans out tiered reviewer personas in parallel, closes with an adversarial lens that reads the other findings, merges everything, and routes by confidence and autofix class.

This skill supersedes ad-hoc review flows that stitch `/review`, `/security-review`, `code-review:code-review`, and `pr-review-toolkit:review-pr` by hand. Those commands remain installed; this one composes their intent into one pass with structured output.

## When to Run

Run `/ce-review` when:

- A PR is up for review and the stakes go beyond a cosmetic fix
- The diff spans multiple files or touches a cross-cutting concern (security, migrations, API surface)
- You want autofix for the boring findings and a single batched question for the taste calls
- A prior review missed something and you want the red-team lens on top

Do NOT run for:

- Trivial single-line fixes (use scope-drift + Fix-First from `pr-review-toolkit` directly)
- Exploratory prototypes the user plans to throw away
- Design docs or plans (use `/document-review` once it ships - see issue #278)

## Mode Selection

On invocation, parse `$ARGUMENTS` for a mode token:

- `mode:interactive` (or no mode token) - Full pipeline, ask one batched question for taste calls, apply `safe_auto` fixes, report everything. Default.
- `mode:autofix` - No questions. Apply `safe_auto` fixes immediately. Write the run artifact and report `gated_auto` / `manual` findings as todos. Use for headless CI-like runs.
- `mode:report-only` - Strictly read-only. No edits, no questions. Safe for concurrent runs and for reviewing someone else's branch.
- `mode:headless` - Skill-to-skill invocation. No edits, no questions, no chatty narration. Emit only the structured output envelope and the terminal line `Review complete.` so a calling skill can parse it.

The four modes also govern what happens on ambiguity. Interactive asks; autofix applies the cautious default; report-only records the question; headless records and moves on.

## Scope

The orchestrator is responsible for:

1. Collecting inputs and prior learnings
2. Running scope-drift first
3. Fanning out always-on reviewers in parallel
4. Selecting and fanning out conditional reviewers based on the diff
5. Running the adversarial reviewer last with access to prior findings
6. Merging, deduplicating, scoring, and routing findings
7. Emitting output in the Fix-First format

Each reviewer is a separate agent under `agents/reviewers/`. The orchestrator never inlines reviewer logic - agents own their "what you flag / what you don't flag" boundaries.

## Phase 0: Inputs

Collect the inputs once and pass them by path, not content, to the subagents (see `modules/subagent-patterns/rules/subagent-patterns.md`):

- `base_ref` - usually `origin/main`; override from `$ARGUMENTS` if the user said `base:{ref}`
- `head_ref` - `HEAD` unless specified
- `diff_files` - paths returned by `git diff --name-only {base_ref}...{head_ref}`
- `diff_stat` - output of `git diff --stat {base_ref}...{head_ref}` (short; safe to include inline)
- `pr_body` - `gh pr view --json body,title` if a PR is open
- `issue_body` - `gh issue view {num}` for any issue the PR closes
- `commit_messages` - `git log {base_ref}..{head_ref} --pretty=format:"%s%n%b"`

If no base ref resolves (rare; e.g., detached HEAD with no upstream), state that explicitly and fall back to reviewing the last commit only.

## Phase 1: Prior Learnings

Dispatch the `learnings-researcher` agent (from `modules/compound-knowledge/agents/learnings-researcher.md`). Pass:

- `task_summary` - one paragraph derived from the PR title, PR body first paragraph, and the diff stat
- `files_hint` - `diff_files`
- `tags_hint` - tags inferred from touched directories (e.g., `supabase` if `supabase/migrations/` changed; `chrome-extension` if `manifest.json` changed; language tags by file extension)
- `problem_type_filter` - absent (pull both bugs and knowledge priors)
- `max_results` - 5

Include the returned prior blocks as grounding context for every downstream reviewer. This is what compound-knowledge buys the review loop - prior decisions and known-bad patterns surface before specialists pattern-match from scratch.

If the repo has no `docs/solutions/` directory, the agent returns `no_solutions_directory: true`. Record that, skip the priors block, and proceed.

## Phase 2: Scope-Drift

Invoke the `scope-drift` skill (from `modules/pr-review-toolkit/skills/scope-drift/SKILL.md`). This runs the intent-versus-diff audit and returns:

- A Plan Completion list (DONE / PARTIAL / NOT DONE / CHANGED)
- Out-of-Scope Changes
- Impact ratings (HIGH / MEDIUM / LOW)
- A batched gating question if HIGH items exist

In `interactive` mode, if scope-drift returns a HIGH gating question and the user answers "block", STOP. Do not dispatch specialists on code the author has not decided to keep.

In `autofix`, `report-only`, and `headless` modes, record the scope-drift findings as part of the final envelope but do not block - the gating decision is informational for the caller.

## Phase 3: Tiered Reviewer Fan-Out

Dispatch reviewer agents in parallel using the Task tool. Each reviewer returns a JSON array of findings matching `references/finding.schema.yaml`.

### Always-on reviewers (every run)

- `correctness-reviewer` - logic errors, off-by-ones, wrong branch handling, control-flow mistakes
- `testing-reviewer` - missing tests, untested branches, missing-for-the-right-reason assertions, flake-prone patterns
- `maintainability-reviewer` - duplication, naming, dead code, excessive complexity, unclear boundaries
- `project-standards-reviewer` - conformance to the repo's stated conventions (CLAUDE.md, AGENTS.md, lint/type configs, existing patterns in sibling files)

The `learnings-researcher` priors from Phase 1 are already in the context, so each reviewer sees relevant past decisions without re-retrieving.

### Conditional reviewers (selected from the diff)

Decide per run based on what the diff touches. Use the table below. Multiple conditions can fire.

| Reviewer | Fire condition |
|----------|----------------|
| `security-reviewer` | Diff touches auth, session, crypto, input validation, SQL, env/secret handling, permissions, OAuth, RLS |
| `performance-reviewer` | Diff touches loops in hot paths, N+1 DB call patterns, bundle size, memoization, large data structures, animation code |
| `reliability-reviewer` | Diff touches retries, timeouts, circuit breakers, background jobs, queues, idempotency keys, error recovery |
| `api-contract-reviewer` | Diff changes a public API surface, route handler, exported type, SDK function, or RPC schema |
| `data-migrations-reviewer` | Diff touches migration files, schema definitions, RLS policies, index changes, or data-backfill scripts |

If none of the conditions fire, run only the always-on set.

### Dispatch pattern

Use the parallel-research pattern from `modules/subagent-patterns/rules/subagent-patterns.md`. Pass each reviewer:

- `base_ref`, `head_ref`, `diff_files`, `diff_stat` (inputs)
- The prior-learnings block from Phase 1
- The scope-drift audit from Phase 2
- The reviewer's role name

Reviewers are independent. Do not share their drafts between each other in this phase.

## Phase 4: Adversarial / Red-Team Lens

After Phase 3 completes, dispatch the `adversarial-reviewer` agent with:

- Everything Phase 3 received
- All Phase 3 reviewer outputs (this is the key difference - the adversarial reviewer reads their findings)

The adversarial reviewer runs five lenses (attack the happy path, find silent failures, exploit trust assumptions, break edge cases, find integration-boundary issues) and is specifically told to find what the specialists MISSED. It does not re-state their findings; it augments.

Gating condition - the adversarial reviewer fires in every mode, but its autofix_class is always `gated_auto` or weaker. Nothing an adversarial reviewer reports is `safe_auto` - the whole point is that these findings deserve a human decision.

## Phase 5: Merge, Dedupe, Score, Route

Collect every finding from Phases 3 and 4. Each finding is a JSON object shaped like:

```json
{
  "reviewer": "correctness-reviewer",
  "file": "src/foo.ts",
  "line": 42,
  "severity": "P1",
  "confidence": 0.85,
  "category": "off-by-one",
  "title": "Loop runs one iteration too many",
  "detail": "The condition `i <= arr.length` should be `i < arr.length`.",
  "autofix_class": "safe_auto",
  "fix": "change `<=` to `<`",
  "test_stub": "expect(process([1,2,3]).length).toBe(3)"
}
```

See `references/finding.schema.yaml` for the full schema.

### Confidence calibration (enforced)

Every reviewer prompt states this convention; the orchestrator re-checks it:

- `>= 0.80` - HIGH confidence. Reviewer has direct evidence in the diff.
- `0.60-0.79` - MODERATE. Pattern-match from code, plausible but not confirmed.
- `0.50-0.59` - LOW. Suspicion; surface only if the category is `security` or `data-integrity`.
- `< 0.50` - SUPPRESS. Drop silently.

If a reviewer returns a finding with confidence below 0.50, the orchestrator drops it before routing.

### Severity scale (enforced)

- `P0` - Blocking. Merge would break production, leak data, corrupt state, or violate a stated hard requirement.
- `P1` - Must fix before merge. Observable bug, test gap in critical path, contract break.
- `P2` - Should fix before merge. Maintainability, clarity, or a narrow-impact bug.
- `P3` - Nice to fix. Nits, cosmetics, optional improvements.

Severity and confidence are orthogonal. A P0 finding at confidence 0.55 is still suppressed - you cannot block merge on a suspicion.

### Deduplication

Two findings are duplicates if they have the same `file`, same `line` within ±3 lines, and overlapping `category`. Keep the one with higher confidence; if tied, keep the one from the reviewer closer to the category root (e.g., `security-reviewer` wins over `correctness-reviewer` for a security category finding).

### Autofix routing

- `safe_auto` - Apply immediately in `interactive` and `autofix` modes. Record the applied edit. Never in `report-only` or `headless` modes.
- `gated_auto` - Propose the fix; include it in the batched question in `interactive` mode; skip in `autofix` mode (too risky without a human) but list as a todo.
- `manual` - No auto-fix possible. Report with recommended direction.
- `advisory` - Informational only; do not block, do not propose a fix.

The scope-drift and adversarial layers have a hard ceiling - they can at most emit `gated_auto`.

## Phase 6: Output

The output uses the Fix-First format (see `modules/pr-review-toolkit/rules/fix-first-review.md`). The orchestrator is responsible for producing one envelope; individual reviewers are not.

### Human-facing output (interactive / autofix / report-only)

```markdown
## Review Summary

**Mode**: {interactive|autofix|report-only|headless}
**Base**: {base_ref}  **Head**: {head_ref}
**Priors loaded**: {N} from docs/solutions/
**Scope drift**: {verdict line from Phase 2}
**Reviewers run**: {comma-separated list}

### AUTO-FIXED ({count})

- {file}:{line} - {what was changed} - applied  ({reviewer}, {severity}, conf={confidence})

### NEEDS INPUT ({count})

Batched question follows. Please answer once:

1. {file}:{line} - {finding} - {proposed direction}  ({reviewer}, {severity}, conf={confidence})
2. ...

### RED-TEAM LENS ({count})

- {file}:{line} - {finding}  ({severity}, conf={confidence}) - {one-line next step}

### Strengths (optional)

- {what this PR did well}

### Next Step

{Single sentence - either "Answer the batched question" or "Ready to merge" or "Blocked on scope-drift"}
```

The AUTO-FIXED list shows only findings that were actually applied in this run. If the mode suppresses auto-apply (`report-only`, `headless`), move those findings to a `PROPOSED AUTO-FIXES` list instead.

### Structured envelope (headless and run artifact)

In any mode, write the full JSON envelope to a run artifact so other skills and later runs can consume it:

```
.context/ce-review/{timestamp}-{base_ref_short}-{head_ref_short}.json
```

The envelope schema:

```json
{
  "run_id": "2026-04-16T12:34:56Z-abc1234-def5678",
  "mode": "interactive",
  "base_ref": "origin/main",
  "head_ref": "HEAD",
  "priors": [
    {"path": "docs/solutions/.../foo.md", "score": 7, "why_relevant": "..."}
  ],
  "scope_drift": { "plan_completion": [...], "drift": [...], "verdict": "..." },
  "findings": [
    {
      "reviewer": "...", "file": "...", "line": 42,
      "severity": "P1", "confidence": 0.85,
      "category": "...", "title": "...", "detail": "...",
      "autofix_class": "safe_auto",
      "applied": true,
      "fix": "...", "test_stub": "..."
    }
  ],
  "adversarial": [ /* same shape as findings */ ],
  "summary": {
    "findings_total": 12,
    "auto_fixed": 4,
    "needs_input": 5,
    "red_team": 3,
    "p0": 0, "p1": 2, "p2": 6, "p3": 4,
    "suppressed_low_confidence": 7
  }
}
```

In `headless` mode, the stdout is limited to the envelope path and the terminal line `Review complete.`. Calling skills parse the envelope file.

## Mode-Specific Behavior Summary

| Mode | Asks question? | Applies fixes? | Writes run artifact? | Stdout |
|------|----------------|----------------|----------------------|--------|
| `interactive` | Yes, one batched | `safe_auto` applied, others proposed | Yes | Full Summary |
| `autofix` | No | `safe_auto` applied; `gated_auto` listed as todo | Yes | Full Summary |
| `report-only` | No | No | Yes | Full Summary |
| `headless` | No | No | Yes | Envelope path + `Review complete.` |

## Anti-Patterns

- **Running reviewers serially.** They are independent; parallelize. Serial execution wastes agent time and inflates the context window with reviewer boilerplate.
- **Passing content, not paths.** Reviewers should read only the files they need. The orchestrator must not pre-read and inline diffs into every subagent prompt.
- **Auto-applying adversarial findings.** The red-team lens is an opinion, not a mechanical fix. Even when the confidence is high, route to `gated_auto` or weaker.
- **Skipping scope-drift.** An in-scope review of out-of-scope code is wasted effort. Phase 2 runs first for a reason.
- **Inlining reviewer logic.** Every persona has a `what you flag / what you don't flag` boundary; keeping it in the agent file prevents overlap. Do not absorb reviewer prompts into the orchestrator.
- **Splitting findings by severity.** Severity lives inside the Fix-First bucket, not alongside it. The output format is AUTO-FIXED / NEEDS INPUT / RED-TEAM LENS - not Critical / Important / Suggestion.
- **Asking one question per finding in interactive mode.** Findings are batched into a single `AskUserQuestion`. Multiple questions fragment the review.
- **Treating `report-only` as `interactive minus the question`.** Report-only never applies edits. If a reviewer's `safe_auto` fix would land on disk in `interactive`, it must become a `PROPOSED AUTO-FIX` list entry in `report-only`.

## Integration Points

- **Prior learnings**: Phase 1 dispatches `learnings-researcher` (compound-knowledge module). If that module is not installed, Phase 1 is a no-op and the review proceeds without priors.
- **Scope-drift**: Phase 2 invokes the `scope-drift` skill (pr-review-toolkit module). If that skill is not installed, the orchestrator runs an inline 10-item scope check derived from the PR body and moves on.
- **Fix-First format**: Phase 6 output obeys `rules/fix-first-review.md` from the pr-review-toolkit module. That rule is installed globally; the orchestrator does not re-state the format.
- **Legacy commands**: `/review`, `/security-review`, `code-review:code-review`, and `pr-review-toolkit:review-pr` remain available. Each module's README marks them as legacy in favor of `/ce-review` when the full pipeline is warranted.

## Source

Ported from EveryInc/compound-engineering's `ce-review` skill (orchestrator + 27 reviewer agents, ~743 lines of skill + per-agent prompts). Adversarial lens structure adapted from garrytan/gstack's `review/specialists/red-team.md`. CCGM adaptations:

- Mode tokens match CCGM skill-authoring convention (`mode:interactive` / `mode:autofix` / `mode:report-only` / `mode:headless`)
- Reviewer agents live under `agents/reviewers/` per CCGM's `agents/` directory convention (issue #273)
- Prior learnings flow through the `learnings-researcher` agent (compound-knowledge, issue #276) instead of a CE-specific retriever
- Scope-drift uses the CCGM scope-drift skill (pr-review-toolkit, issue #293) rather than an inline version
- Output format obeys CCGM's Fix-First rule (pr-review-toolkit) instead of CE's severity-tiered format
- Ruby/Rails-specific reviewers are omitted; stack-specific reviewers can be added under `agents/reviewers/stack/` as a follow-up
