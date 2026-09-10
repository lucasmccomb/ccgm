# Subagent Patterns

How to decompose work and delegate it to subagents (the Agent tool).

## When to Use Subagents

Use them when a task has three or more independent subtasks that can run in parallel, when research spans several files or systems at once, when verbose intermediate results would pollute the main context, or when several issues or PRs need independent completion. Do not use them for simple reads or searches (use Glob, Grep, Read), for sequential steps where each depends on the previous result, or for work that needs the conversation with the user.

## Task Decomposition

Before dispatching, write a spec with four fields:

1. **Objective**: one sentence describing the expected outcome.
2. **Context**: file paths, function names, background the agent needs.
3. **Constraints**: patterns to follow, files not to modify, libraries not to add.
4. **Deliverable**: what to return (code changes, research summary, test results).

Bad: "Fix the auth bug." Good: "In `/src/auth/session.ts`, `refreshToken` silently swallows errors on line 47. Add error propagation and a test in `/tests/auth/session.test.ts` that verifies refresh failures surface."

Each task should be completable in one pass without clarifying questions, independently verifiable, and scoped to one concern. Pass file paths, not file contents: the subagent reads what it needs, the prompt stays small, and adding a tenth reference costs one line. Inline an excerpt only when the agent must match a specific passage that a search would not find unambiguously.

## Dispatch

For parallel research, one agent per area. For parallel implementation, one agent per independent file set, with any shared dependency built first and the dependents launched after. Parallel implementers get `isolation: "worktree"` so their builds and commits never collide; the worktree is created per unit and removed when the unit's PR merges, with `/worktree-sweep` as the backstop, because a worktree an agent built in does not auto-remove and forgotten ones fill the disk. The `git-worktrees` skill has the lifecycle and the safe-removal rules.

## Two-Stage Review

The lead reviews subagent results in two passes, Stage 1 gating Stage 2. Explicitly dispatched reviewers run in fresh context and receive only the spec, the diff or changed-file paths, and fresh build and test output, never the implementer's rationale; a reviewer who reads "I chose X because" grades the defense instead of the change. The implementer's `DONE` report is an audit target for Stage 1, not grounding, and Stage 2 does not need it. Dispatched reviewers write their findings to a file the caller named and reply with the path; the caller routes on the artifact, and a missing or unparseable artifact means the reviewer failed.

- **Stage 1, spec compliance**: every deliverable present, every constraint respected, no creep into files or helpers the spec did not name. On failure, re-dispatch the implementer with specific feedback; do not proceed.
- **Stage 2, code quality**: project patterns, unhandled edge cases, appropriate simplicity. Runs only after Stage 1 returns DONE, or DONE_WITH_CONCERNS the caller accepted.

Three templates live under `~/.claude/agents/`: `implementer` (does the work inside the spec), `spec-compliance-reviewer` (Stage 1, treats DONE as a claim and re-reads the diff), `code-quality-reviewer` (Stage 2, refuses to run if Stage 1 did not pass). Cross-provider review needs `--cross-provider` or an explicit request.

## Coordination

Subagents do not modify the same files; serialize or merge the tasks when two need the same file. Synthesize results into a coherent whole before presenting. Report subagent failures rather than working around them silently. Verify the artifact (read the diff, run the test) before accepting a `DONE`.

## Completion Status Protocol

Subagents end with one of four statuses instead of a free-form summary:

| Status | Meaning | Dispatcher action |
|--------|---------|-------------------|
| DONE | Completed as specified, all deliverables present, no unresolved concerns | Verify the artifact and move on |
| DONE_WITH_CONCERNS | Completed, but the agent has doubts about approach, missing context, or edge cases | Read the concerns; accept, fix, or re-dispatch |
| BLOCKED | Cannot be completed as specified; names the blocker | Resolve the blocker or revise the spec |
| NEEDS_CONTEXT | Under-specified; names what would unblock it | Supply the context and re-dispatch |

## Skill Invocation Modes

Skills with side effects expose modes parsed from `$ARGUMENTS` as `mode:{name}`:

| Mode | Behavior |
|------|----------|
| interactive (default) | May prompt, apply fixes interactively, write artifacts |
| autofix | No prompts; apply safe fixes; write a structured run artifact |
| report-only | Read-only; findings to stdout or a report file; safe to run concurrently |
| headless | For skill-to-skill calls; no prompts; structured output envelope ending with a terminal line such as "Review complete" |

A skill that may be called by another skill declares which modes it supports, with stop conditions, write policy, output contract, and prompt policy. A skill invoking another passes `mode:headless` unless there is a specific reason not to.

## Concurrency and Rate Limits

A fan-out is bounded by the server's rate limit, not by how many agents you can name. Launching too many heavy agents at once trips a server-side throttle (HTTP 429, `Server is temporarily limiting requests (not your usage limit) · Rate limited`) that fails the whole burst, because each heavy agent sends its full prompt the instant it starts. This is a launch-rate problem, never a usage cap or a code bug.

A **heavy** agent is any of: Opus or Fable, reasoning effort at or above high, or a large reference context at launch. Anything else at medium or lower effort with a small prompt is **light**.

| Lever | Default |
|-------|---------|
| Heavy agents running at once | 4, never more than 5 |
| Wave size for heavy fan-outs | 4; let a wave drain before the next |
| Light agents running at once | about 8 |
| Model for fan-out agents | Sonnet unless the task needs frontier depth |
| Effort for fan-out agents | medium or low; escalate only the stages that need it |
| Retry on a 429 | 3 attempts, backoff 30s, 60s, 120s |

Reduce agent count before throttling launches: one agent handling five items beats five agents. In a Workflow script, prefer `pipeline()` over `parallel()` for heavy stages, or chunk the array into sequential waves of 4. With direct Agent-tool dispatch, send at most 4 heavy calls per message and read the results before the next batch. Same-prefix agents launched within a few seconds of each other share the first agent's cached prefix, one more reason to keep a wave on one model.

When throttled mid-run: stop launching, wait 30 to 60 seconds, re-dispatch only the failed agents in waves of 3 or 4 (or on Sonnet at medium), halve the wave and double the cooldown if it trips again, and for Workflow runs resume from the journal with `resumeFromRunId` so completed agents return cached results.
