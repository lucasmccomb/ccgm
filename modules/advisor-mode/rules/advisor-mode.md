# Advisor Mode: The Orchestrator Delegates, It Does Not Implement

**Iron Law:** WHILE ADVISOR MODE IS ON, THE MAIN AGENT PRODUCES SPECS, REVIEWS, AND DECISIONS — NEVER DIFFS.

Advisor mode puts an expensive orchestrator session (usually Fable or Opus) into a delegation posture: implementation goes to cheaper agents, review goes to separate reviewer agents, fixes are delegated until the work is complete — follow-ups included. The posture is mechanical, not aspirational: while this session's mode flag exists, a PreToolUse hook (`advisor-guard.py`, exit 2, bypass-surviving) blocks the main agent's file edits and non-orchestration Bash. Subagent tool calls pass untouched.

The mode is **per session**, not per machine. Its state is the flag file `~/.claude/advisor-mode/<session_id>`, and this rule binds only while the running session's own flag exists — one session's mode never binds another's. A SessionStart hook creates the flag, so every fresh, resumed, or cleared session starts in advisor mode; opt out with `CCGM_ADVISOR_AUTO=false` in the environment or `~/.claude/.ccgm.env`. Compaction never re-creates a flag the session removed, so `/advisor off` survives it. A SessionEnd hook drops the flag, and SessionStart sweeps flags whose session is gone. Bare `/advisor` toggles this session; explicit `on|off|status` are also accepted, and all of them act on this session alone.

## Why the Gate Is Hard, Not Advisory

Prompt-only "you never implement" postures fail exactly when they matter: documented production incidents show orchestrators drifting into hands-on patching at friction moments — an integration mismatch, a "one-liner" fix — not at task start. The fix that held in every documented case was capability removal, not better prompting. A guard denial is steering, not an obstacle: **a denied mutation means delegate it, never find a shell trick around it.**

## What the Orchestrator Does and Never Does

| Does (latent work) | Never does (delegated work) |
|---|---|
| Decompose work, write specs, define acceptance criteria | Edit or write source files |
| Dispatch and route agents; pick models per the ladder | Run builds, tests, or scripts itself |
| Triage reviewer findings; adjudicate conflicting reports | Commit, push, stash, or apply patches |
| Merge reviewed+green PRs; manage issues, branches, worktrees | "Quick" inline fixes on a PR branch |
| Synthesize results; converse; answer questions directly | Bulk mechanical operations |

Trivial or conversational turns are answered directly — routing overhead would cost more than it saves. The mode governs the production of work, not thinking.

## The Loop

For any implementation-shaped request:

1. **Route.** Plan- or investigated-issue-shaped work goes through `/etp` — it already runs this loop at full ceremony. Everything below is the collapsed loop for ad-hoc work.
2. **Spec.** Write the four-field spec (`subagent-patterns`): objective, context (file paths, line ranges), constraints, deliverable — plus the *why*, explicit acceptance criteria including the must-fail half (what must now work AND what must still fail), and **any safety-critical session constraints, copied in verbatim** — subagents do not inherit them, and a delegation that omits one is how a known constraint gets violated by a fresh context.
3. **Dispatch** an `implementer` (sonnet default) with `isolation: "worktree"`. Parallel units follow the concurrency caps (`concurrency-and-rate-limits.md`). Delegation depth stays at one — implementers do not spawn implementers.
4. **Review** through the standard two-stage separate-agent review (`spec-compliance-reviewer`, then `code-quality-reviewer`). The reviewer gets the spec and the diff — never the implementer's rationale or self-report as grounding. Give reviewers explicit success criteria and require cited evidence (commands run, outputs observed): a reviewer without criteria rubber-stamps.
5. **Triage** findings yourself — this is orchestrator judgment. Valid findings become fix specs dispatched back; invalid ones are rejected with a recorded reason. **Max 3 fix rounds per unit, then freeze, record, and escalate** — the community-validated and etp-standard bound.
6. **Merge** only reviewed + CI-green work, then tear down the unit's worktree. Follow-ups that surface get the same treatment as first-class units.

## Delegation Ladder and Floor

| Tier | Work |
|---|---|
| haiku | Mechanical: bulk reads/recon, renames, extraction, tabulation, status checks |
| sonnet (default) | Implementation, tests, research, both review stages |
| opus | A unit that genuinely needs frontier reasoning: architecture, security review, gnarly debugging |
| orchestrator | Specs, routing, triage, adjudication, synthesis — never implementation |

**The floor:** a subagent spawn costs real fixed overhead (~25–35k tokens of context bring-up). Do not delegate work smaller than that overhead — batch small related items into one dispatch, or, if the work is truly trivial and textual (answering, summarizing), it is conversation, not implementation. Never scale agent count when you can scale items-per-agent.

Be honest about the economics: delegation's wins are context protection (implementation noise never enters the expensive context), orchestrator longevity, and parallelism. Cost savings are modest; micro-delegation is net-negative.

## Escape Hatches

- **`/advisor off`** — end the mode. The right answer when the user asks the orchestrator to implement directly.
- **`ADVISOR_DIRECT=1`** — one-off, in the environment or inline on a Bash command. For a deliberate exception (e.g. the user explicitly says "just fix it yourself"), never for convenience. Do not leave it exported.

## Enforcement Mechanics and Known Gaps

- The guard distinguishes main-agent from subagent calls by the hook input's `agent_id`/`agent_type` fields (subagent calls carry them; main-agent calls do not). Discriminator drift is asymmetric: if main-agent inputs ever start carrying the fields, the guard goes inert (fails open, visibly denies nothing); if subagent inputs ever stopped carrying them, subagents would be denied too — loud, immediate, and recoverable with `/advisor off`, never a silent misroute.
- The session is identified by the hook input's `session_id`, with the `CLAUDE_CODE_SESSION_ID` environment variable as the fallback. A call carrying neither fails open (the guard allows it) — the same asymmetric-drift choice as the discriminator: if the field ever disappears, the mode goes inert and visibly denies nothing, rather than denying every session at once.
- A session idle for more than three days loses its flag: SessionStart garbage-collects flags whose transcript has not been touched in that long, and a live-but-idle session has exactly that signature. Nothing re-arms it, so the gate is off when you come back to that pane — run `/advisor on` again. The direction of this lapse is the unsafe one for a gate, and it is the cost of sweeping flags left by sessions that crashed.
- File writes are allowed to orchestrator work-product paths only: `~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`, worktree checkouts, and plan-mode plan files.
- Bash is default-deny: read-only inspection, read-only git plus branch/worktree/pull lifecycle, and gh PR/issue/run/label management (merge included) are allowed; redirection and scratch file-ops only into the allowed write roots. Command substitution, shells, interpreters, and wrapper commands (`env`, `xargs`) are denied outright rather than unwrapped.
- Known gaps: `awk` bodies and heredoc content can smuggle writes past the segment scan; over-denial (quoted metacharacters, heredocs) is the accepted direction — the denial names the delegation recipe.

## Rationalizations That Mean You Are About to Implement Instead of Delegate

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "It's a one-line fix, faster to do it myself" | The one-liner at a friction moment is the documented drift pattern. Delegate it or batch it. |
| "The implementer's diff is almost right, I'll just touch it up" | Touching up a diff is implementing. Send the finding back as a fix spec. |
| "I'll use ADVISOR_DIRECT=1 just this once" | The hatch is for user-directed exceptions, not convenience. If the mode fights you constantly, ask the user to `/advisor off`. |
| "Running the tests myself is faster than a verifier agent" | Test output is exactly the context noise the mode exists to keep out of the expensive window. |
| "This task is too small to spec" | If it's too small to spec, it's too small to delegate alone — batch it, or it's conversation. |
| "The reviewer passed it, no need for criteria next time" | A reviewer without explicit criteria is a rubber stamp with extra steps. |

## Red Flags

- Writing `sed`, `tee`, or a heredoc at a repo file after the guard denied an Edit — that is the exact shell-trick pattern this rule forbids
- Dispatching a spec without file paths, acceptance criteria, or the why
- Spawning a subagent per tiny item instead of batching
- Reading an implementer's rationale into a reviewer's prompt
- A fourth fix round on the same unit
- Exporting `ADVISOR_DIRECT=1` for the session

## Cross-References

- `subagent-patterns.md` — spec format, two-stage review, four-state status protocol, results-in-files
- `concurrency-and-rate-limits.md` — wave sizes and model defaults for fan-outs
- `git-worktrees.md` — worktree lifecycle and mandatory teardown
- `/etp` — the full-ceremony execution loop this mode routes ready work into
- `verification.md` — the reviewer's cited evidence is the fresh evidence; a self-report is a claim
