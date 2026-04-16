# Subagent Patterns

Methodology for decomposing work and delegating to subagents (Task tool) effectively.

## When to Use Subagents

Use subagents when:
- A task has 3+ independent subtasks that can run in parallel
- Research needs to happen across multiple files or systems simultaneously
- The main context window would be polluted by verbose intermediate results
- Multiple issues or PRs need to be completed independently

Do NOT use subagents for:
- Simple file reads or searches (use Glob/Grep/Read directly)
- Sequential tasks where each step depends on the previous result
- Tasks that require maintaining conversation context with the user

## Task Decomposition

### Write a Spec for Each Subtask

Before dispatching a subagent, define:

1. **Objective** - one clear sentence describing the expected outcome
2. **Context** - relevant file paths, function names, or background the agent needs
3. **Constraints** - patterns to follow, files not to modify, libraries not to add
4. **Deliverable** - what the agent should return (code changes, research summary, test results)

Bad: "Fix the auth bug"
Good: "In /src/auth/session.ts, the refreshToken function silently swallows errors on line 47. Add proper error propagation and a test in /tests/auth/session.test.ts that verifies refresh failures are surfaced."

### Right-Size the Work

Each subagent task should be:
- **Completable in one pass** - the agent should not need to ask clarifying questions
- **Independently verifiable** - the result can be checked without running other tasks first
- **Scoped to one concern** - one bug fix, one feature, one research question

## Dispatch Patterns

### Parallel Research

When exploring a question that spans multiple areas:

```
Agent 1: "Search for all usages of TokenManager in src/ and list the call sites"
Agent 2: "Read the auth middleware in src/middleware/auth.ts and summarize the token validation flow"
Agent 3: "Check the test coverage for src/auth/ - list tested and untested functions"
```

### Parallel Implementation

When implementing changes across independent files:

```
Agent 1: "Add input validation to the /api/users endpoint in src/routes/users.ts"
Agent 2: "Add input validation to the /api/posts endpoint in src/routes/posts.ts"
Agent 3: "Write shared validation helpers in src/utils/validate.ts"
```

Note: If agents share dependencies (Agent 3's output is needed by 1 and 2), run the dependency first, then the dependents in parallel.

## Two-Stage Review

After subagent results come back, review in two passes:

### Stage 1: Spec Compliance

- Did the agent do what was asked?
- Are all deliverables present?
- Were constraints respected?

### Stage 2: Code Quality

- Does the code follow project patterns?
- Are there edge cases not handled?
- Is the solution appropriately simple (not over-engineered)?

If either stage fails, provide specific feedback and re-dispatch. Do not manually patch subagent output without understanding why it diverged.

## Coordination Rules

- **No shared state**: Subagents should not modify the same files. If two tasks need to touch the same file, either serialize them or make one task handle both changes.
- **Aggregate results**: After all subagents return, synthesize their outputs into a coherent whole before presenting to the user.
- **Report failures**: If a subagent fails or produces unexpected results, report it clearly rather than silently working around it.

## Subagent Completion Status Protocol

Every subagent must return one of four structured status values, not a free-form summary. This is the vocabulary that lets the dispatcher make an immediate routing decision without re-reading the whole result.

Instruct subagents to end their reports with one of:

| Status | Meaning | Dispatcher Action |
|--------|---------|-------------------|
| **DONE** | Task completed as specified; all deliverables present; no unresolved concerns. | Verify the artifact (read the diff, run the test) and move on. |
| **DONE_WITH_CONCERNS** | Task completed but the agent has doubts about the approach, missing context, or edge cases it could not resolve. | Read the concerns section. Decide to accept, fix, or re-dispatch with guidance. |
| **BLOCKED** | The task cannot be completed as specified. Specify what is blocking (missing file, conflicting constraint, environmental issue). | Resolve the blocker and re-dispatch, or revise the spec. |
| **NEEDS_CONTEXT** | The task is under-specified. Specify what information would unblock it. | Supply the missing context and re-dispatch. |

Free-form summaries force the dispatcher to re-read everything to decide what to do. DONE_WITH_CONCERNS in particular captures "I completed it but I have doubts" - a state that silent success would otherwise hide.

**Do not trust the self-report.** A subagent reporting DONE is a claim, not evidence. Before accepting the result, verify the artifact (read the diff, check the file exists, run the test). See the `verification` rule for the full evidence table.
