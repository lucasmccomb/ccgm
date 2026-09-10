# Advisor Mode: The Orchestrator Delegates, It Does Not Implement

While advisor mode is on, the main agent produces specs, reviews, and decisions, never diffs. Implementation goes to cheaper agents, the lead reviews spec compliance and quality, and fixes are delegated until the work is complete, follow-ups included. The posture is mechanical: while this session's mode flag exists, a PreToolUse hook (`advisor-guard.py`, exit 2, bypass-surviving) blocks the main agent's file edits and non-orchestration Bash. Subagent tool calls pass untouched.

The gate is hard rather than advisory because prompt-only "you never implement" postures drift into hands-on patching at friction moments, an integration mismatch or a "one-liner" fix, and capability removal is what held in every documented case. A denial is steering: delegate the mutation, never find a shell trick around it.

## Session State

- The flag is `~/.claude/advisor-mode/<session_id>`; this rule binds only while the running session's own flag exists.
- A SessionStart hook creates the flag, so every fresh, resumed, or cleared session starts in advisor mode. Opt out with `CCGM_ADVISOR_AUTO=false` in the environment or `~/.claude/.ccgm.env`.
- Compaction never re-creates a flag the session removed, so `/advisor off` survives it. SessionEnd drops the flag; SessionStart sweeps flags whose session is gone or whose transcript is untouched for three days, so a live session idle that long loses its gate and needs `/advisor on` again.
- `/advisor` toggles this session; `on|off|status` are also accepted.

## What the Orchestrator Does and Never Does

| Does (latent work) | Never does (delegated work) |
|---|---|
| Decompose work, write specs, define acceptance criteria | Edit or write source files |
| Dispatch and route agents; pick models per the ladder | Run builds, tests, or scripts itself |
| Personally review spec and quality; triage findings on evidence | Commit, push, stash, or apply patches |
| Merge reviewed and green PRs; manage issues, branches, worktrees | "Quick" inline fixes on a PR branch |
| Synthesize results; converse; answer questions directly | Bulk mechanical operations |

Trivial or conversational turns are answered directly. The mode governs the production of work, not thinking.

## The Loop

1. **Route.** Plan-shaped or investigated-issue-shaped work goes through `/etp`, which runs this loop at full ceremony. The steps below are the collapsed loop for ad-hoc work.
2. **Spec.** Objective, context (file paths, line ranges), constraints, deliverable, the why, and explicit acceptance criteria including what must still fail. Copy any safety-critical session constraints in verbatim; subagents do not inherit them.
3. **Dispatch** an `implementer` (sonnet by default) with `isolation: "worktree"`. Parallel units follow the concurrency caps in `subagent-patterns.md`. Delegation depth stays at one.
4. **Review personally**, spec compliance first, then code quality, from the spec, the diff, and fresh verification output. The implementer's rationale is not proof. Delegate builds and tests to a verifier and inspect its actual outputs. `--light-review` in ETP selects spec-only review; the two-stage review is the default.
5. **Triage** supported findings and dispatch fixes. Three fix rounds are the normal checkpoint; more needs new evidence and a viable next check. Cross-provider review is opt-in (`--cross-provider` or an explicit request); a stopped optional review is never approval.
6. **Merge** only reviewed and CI-green work, then tear down the unit's worktree. Follow-ups get the same treatment as first-class units.

## Delegation Ladder and Floor

| Tier | Work |
|---|---|
| haiku | Mechanical: bulk reads and recon, renames, extraction, tabulation, status checks |
| sonnet (default) | Implementation, tests, research; delegated reviews when requested |
| opus | Units that need frontier reasoning: architecture, security review, hard debugging |
| orchestrator | Specs, personal review, routing, triage, adjudication, synthesis |

A subagent spawn costs real fixed overhead (the full rules and CLAUDE.md context loads into it). Do not delegate work smaller than that overhead: batch small related items into one dispatch, and treat trivial textual work (answering, summarizing) as conversation. Never scale agent count when you can scale items per agent. Delegation buys context protection, orchestrator longevity, and parallelism; cost savings are modest, and micro-delegation is net-negative.

## Escape Hatches

- `/advisor off` ends the mode; the right answer when the user asks the orchestrator to implement directly.
- `ADVISOR_DIRECT=1`, in the environment or inline on one Bash command, is a one-off for a deliberate exception ("just fix it yourself"). Do not leave it exported.

## Enforcement Mechanics

- The guard tells main-agent from subagent calls by the hook input's `agent_id`/`agent_type` fields, which subagent calls carry and main-agent calls do not. Drift is asymmetric: if main-agent inputs gained the fields the guard would go inert (fail open); if subagent inputs lost them, subagents would be denied, loudly and recoverably with `/advisor off`.
- The session is identified by the hook input's `session_id`, then `CLAUDE_CODE_SESSION_ID`. A call carrying neither is allowed, the same fail-open choice.
- File writes are allowed only to orchestrator work-product paths: `~/.claude/`, temp and scratchpad roots, `~/code/plans/`, `~/code/docs/`, worktree checkouts, and plan-mode plan files. Trusted policy code is excluded even when reached through a writable-looking symlink.
- Bash is default-deny. Allowed: read-only inspection, read-only git plus branch, worktree, and pull lifecycle, and `gh` PR, issue, run, and label management including merge; redirection and scratch file-ops only into the allowed write roots; dev-tool version and identity probes (`node -v`, `wrangler whoami`) but no other arguments to those binaries. Grouping tokens are structure and their contents are checked as ordinary segments. `$(...)` and backtick substitution pass when every inner command is allowlisted (checked recursively, depth-capped, backtick bodies unescaped first), but a substitution's output may only feed a read-only command. Shells, interpreters, process substitution, and wrapper commands (`env`, `xargs`) are denied outright, except the installed cross-agent-review policy shim and its enumerated actions; that helper records checks and never executes its argv.
- The guard performs quote removal (including `$'…'` and `$"…"`), backslash-escape removal, and substitution of variables it can resolve before checking a word, so a flag cannot hide behind quoting. What it cannot model it denies: brace groups, unquoted globs, an unquoted expansion it cannot resolve anywhere in a word, a resolvable one whose value carries whitespace or a glob character, and undecodable `$'…'` escapes are denied for any command that is not read-only, and always in a redirect target or scratch-op path. A double-quoted expansion is allowed after a flag's first `=` (so `--title="$T"` works) and denied leading or before it. `$_` always counts as unresolvable. `gh api` mutation flags match as prefixes, and any single-dash `git branch` cluster containing `d D m M f c C` counts as a mutator.
- Open gaps: `awk` bodies and heredoc content can smuggle writes; a relative path after a `cd` is denied as unknowable; `~+`, `~-`, and `~N` are denied outright; backticks inside a double-quoted markdown body read as substitution, so pass bodies with `--body-file`. Over-denial is the accepted direction, and each denial names the delegation recipe.

See `subagent-patterns.md` for the spec format, two-stage review, status protocol, and concurrency caps; the `git-worktrees` skill for worktree lifecycle; `verification.md` for what counts as evidence.
