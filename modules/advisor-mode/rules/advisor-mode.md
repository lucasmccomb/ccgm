# Advisor Mode: The Orchestrator Delegates, It Does Not Implement

**Iron Law:** WHILE ADVISOR MODE IS ON, THE MAIN AGENT PRODUCES SPECS, REVIEWS, AND DECISIONS — NEVER DIFFS.

Advisor mode puts an expensive orchestrator session (usually Fable or Opus) into a delegation posture: implementation goes to cheaper agents, the lead personally reviews spec compliance and quality, fixes are delegated until the work is complete — follow-ups included. The posture is mechanical, not aspirational: while this session's mode flag exists, a PreToolUse hook (`advisor-guard.py`, exit 2, bypass-surviving) blocks the main agent's file edits and non-orchestration Bash. Subagent tool calls pass untouched.

The mode is **per session**, not per machine. Its state is the flag file `~/.claude/advisor-mode/<session_id>`, and this rule binds only while the running session's own flag exists — one session's mode never binds another's. A SessionStart hook creates the flag, so every fresh, resumed, or cleared session starts in advisor mode; opt out with `CCGM_ADVISOR_AUTO=false` in the environment or `~/.claude/.ccgm.env`. Compaction never re-creates a flag the session removed, so `/advisor off` survives it. A SessionEnd hook drops the flag, and SessionStart sweeps flags whose session is gone. Bare `/advisor` toggles this session; explicit `on|off|status` are also accepted, and all of them act on this session alone.

## Why the Gate Is Hard, Not Advisory

Prompt-only "you never implement" postures fail exactly when they matter: documented production incidents show orchestrators drifting into hands-on patching at friction moments — an integration mismatch, a "one-liner" fix — not at task start. The fix that held in every documented case was capability removal, not better prompting. A guard denial is steering, not an obstacle: **a denied mutation means delegate it, never find a shell trick around it.**

## What the Orchestrator Does and Never Does

| Does (latent work) | Never does (delegated work) |
|---|---|
| Decompose work, write specs, define acceptance criteria | Edit or write source files |
| Dispatch and route agents; pick models per the ladder | Run builds, tests, or scripts itself |
| Personally review spec/quality; triage findings using evidence | Commit, push, stash, or apply patches |
| Merge reviewed+green PRs; manage issues, branches, worktrees | "Quick" inline fixes on a PR branch |
| Synthesize results; converse; answer questions directly | Bulk mechanical operations |

Trivial or conversational turns are answered directly — routing overhead would cost more than it saves. The mode governs the production of work, not thinking.

## The Loop

For any implementation-shaped request:

1. **Route.** Plan- or investigated-issue-shaped work goes through `/etp` — it already runs this loop at full ceremony. Everything below is the collapsed loop for ad-hoc work.
2. **Spec.** Write the four-field spec (`subagent-patterns`): objective, context (file paths, line ranges), constraints, deliverable — plus the *why*, explicit acceptance criteria including the must-fail half (what must now work AND what must still fail), and **any safety-critical session constraints, copied in verbatim** — subagents do not inherit them, and a delegation that omits one is how a known constraint gets violated by a fresh context.
3. **Dispatch** an `implementer` (sonnet default) with `isolation: "worktree"`. Parallel units follow the concurrency caps (`concurrency-and-rate-limits.md`). Delegation depth stays at one — implementers do not spawn implementers.
4. **Review personally**, spec compliance first, then code quality. Read the actual spec, diff/source and fresh verification evidence; the implementer's rationale is not proof. Record findings and evidence. Delegate required builds/tests to a verifier, then inspect its actual outputs. Explicit `--light-review` in ETP selects spec only; full two-stage review remains the default.
5. **Triage** supported findings and dispatch fixes, whichever agent raised them. Three fix rounds are the normal checkpoint; further bounded work needs new evidence and a viable next check. **Cross-provider review is opt-in**, through `--cross-provider` or explicit natural language. Only those runs use the policy's provider routing, frozen evidence and acknowledgment gates. On provider error, stop the optional run and preserve its reports/findings; the lead can separately assess delivery with personal review and normal checks without calling the stopped run approved. Coordinator repairs require no recursive provider consensus.
6. **Merge** only reviewed + CI-green work, then tear down the unit's worktree. Follow-ups that surface get the same treatment as first-class units.

## Delegation Ladder and Floor

| Tier | Work |
|---|---|
| haiku | Mechanical: bulk reads/recon, renames, extraction, tabulation, status checks |
| sonnet (default) | Implementation, tests, research; optional delegated reviews when requested |
| opus | A unit that genuinely needs frontier reasoning: architecture, security review, gnarly debugging |
| orchestrator | Specs, personal spec/quality review, routing, triage, adjudication, synthesis — never implementation |

**The floor:** a subagent spawn costs real fixed overhead (~25–35k tokens of context bring-up). Do not delegate work smaller than that overhead — batch small related items into one dispatch, or, if the work is truly trivial and textual (answering, summarizing), it is conversation, not implementation. Never scale agent count when you can scale items-per-agent.

Be honest about the economics: delegation's wins are context protection (implementation noise never enters the expensive context), orchestrator longevity, and parallelism. Cost savings are modest; micro-delegation is net-negative.

## Escape Hatches

- **`/advisor off`** — end the mode. The right answer when the user asks the orchestrator to implement directly.
- **`ADVISOR_DIRECT=1`** — one-off, in the environment or inline on a Bash command. For a deliberate exception (e.g. the user explicitly says "just fix it yourself"), never for convenience. Do not leave it exported.

## Enforcement Mechanics and Known Gaps

- The guard distinguishes main-agent from subagent calls by the hook input's `agent_id`/`agent_type` fields (subagent calls carry them; main-agent calls do not). Discriminator drift is asymmetric: if main-agent inputs ever start carrying the fields, the guard goes inert (fails open, visibly denies nothing); if subagent inputs ever stopped carrying them, subagents would be denied too — loud, immediate, and recoverable with `/advisor off`, never a silent misroute.
- The session is identified by the hook input's `session_id`, with the `CLAUDE_CODE_SESSION_ID` environment variable as the fallback. A call carrying neither fails open (the guard allows it) — the same asymmetric-drift choice as the discriminator: if the field ever disappears, the mode goes inert and visibly denies nothing, rather than denying every session at once.
- A session idle for more than three days loses its flag: SessionStart garbage-collects flags whose transcript has not been touched in that long, and a live-but-idle session has exactly that signature. Nothing re-arms it, so the gate is off when you come back to that pane — run `/advisor on` again. The direction of this lapse is the unsafe one for a gate, and it is the cost of sweeping flags left by sessions that crashed.
- File writes are allowed to orchestrator work-product paths only: `~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`, worktree checkouts, and plan-mode plan files. Trusted policy code and its resolved source are excluded from writable work products; a writable-looking symlink path does not authorize overwriting the code it resolves to.
- Bash is default-deny: read-only inspection, read-only git plus branch/worktree/pull lifecycle, and gh PR/issue/run/label management (merge included) are allowed; redirection and scratch file-ops only into the allowed write roots. Read-only recon passes: dev-tool version and identity probes (`node -v`, `wrangler whoami`) are allowed, while any other argument to those binaries (`pnpm install`, `wrangler deploy`) is not; grouping tokens (`{`, `(`) are structure, so what a group contains is checked as an ordinary segment; and `$(...)`/backtick substitution is allowed when every inner command is itself allowlisted, checked recursively and depth-capped, with a backtick body unescaped first the way the shell does it. What a checked substitution returns is an argument for read-only commands only — `echo $(git rev-parse HEAD)` passes, `sed $(echo -i) …` does not, because a read-only inner command says nothing about whether its output is a dangerous flag. An argument that begins with a variable the guard cannot resolve is denied the same way and for the same reason — `A=-i; sed $A f` really edits in place — so pass the value written out; a read-only first word still takes one (`echo $A`, `grep $PAT f`, `cd $DIR`), and one this process can resolve is checked as its expansion (`rm -rf $TMPDIR/x`). Process substitution, shells, interpreters, and wrapper commands (`env`, `xargs`) are denied outright rather than unwrapped, except the exact installed cross-agent-review policy shim and its enumerated orchestration actions. Use private optional-run files under `~/.claude/cross-agent-review/<run-id>/`. Direct transport scripts are not allowlisted. A marketplace-only Claude install does not supply the trusted installed shim; use canonical CCGM installation or delegate setup/execution under normal permissions. That helper records checks but never executes their argv or edits reviewed source; arbitrary Python scripts, options and future actions remain denied.
- Known gaps: `awk` bodies and heredoc content can smuggle writes past the segment scan; over-denial (quoted metacharacters, heredocs) is the accepted direction — the denial names the delegation recipe. Backticks inside a double-quoted argument are real substitution to the shell, so a markdown body reads as a command: pass it with `--body-file`. Six shapes that used to slip through are closed — a nested `` \` `` inside a backtick body, a substitution's output standing in for a flag or a path, an escaped quote inside a double-quoted argument hiding the rest of the line (issue #1012), an escaped quote inside an ANSI-C `$'…'` span hiding it the same way (issue #1015), a variable carrying a flag or a path past every literal check (`A=-i; sed $A f`, issue #1014), and every remaining way to spell a flag out of reach of the literal scans (issue #1017, below). One shared scanner, `scan_states`, carries the quote and escape rule for `mask_quotes`, `find_substitutions` and `match_paren`; a `$'…'` span is the one place a backslash escapes inside a `'` span, which is what decides where it ends; backtick bodies get the shell's own unescape step before the recursive check, and `match_backtick` still walks its span with its own escape loop and no quote state. Issue #1017 is the class of ways to spell a flag out of reach of a literal scan, and bash runs seven steps between the typed line and argv. The guard carries out three of them so the checks read the real word — quote removal (`'-i'`, `-''i`, `-"i"`, `$'-i'` including `\xHH`/`\NNN`/`\uHHHH`, and `$"-i"` locale quoting), backslash-escape removal including line continuation (`-delet\`+newline+`e`), and substitution of a variable it can resolve. The other four it refuses rather than models, because three of them turn ONE typed word into SEVERAL argv words and no per-word check can express that: a brace group (`-delet{e,e}`, `{--,tracked.txt}`, `$TMPDIR/{a,../repo/f}`), an unquoted glob character (`-dele*`, `[-]delete`, `?delete`), an **unquoted** expansion the guard cannot resolve **anywhere** in a word (`find <dir>$IFS-delete` is a plain, non-flag-shaped word that becomes a write predicate) or a resolvable one whose value carries `$IFS` whitespace **or a glob character** — bash expands a parameter and then globs the result, so `GLOBVAR='-dele*'` reaches find as `-delete` while the typed word shows nothing — and an undecodable `$'…'` escape — each denied outright for a command that is not read-only, and denied in a redirect target or a scratch-op path for anything. A **double-quoted** expansion cannot be word-split, so it keeps the narrower positional rules — denied leading or before a flag's first `=` (`-$A`, `--in-pl$A`), allowed after it. That carve-out exists to keep `--title="$T"` usable, and nothing more. `$_` counts as unresolvable whatever the environment says, because its real value is the shell's last argument (`: -i; sed $_ f` is the same bypass as `A=-i`). Two sibling literal-check gaps went with it: `gh api` mutation flags match as prefixes, since gh accepts `-XPOST` and `--field=k=v`, and any single-dash `git branch` cluster carrying `d D m M f c C` counts as a mutator, since git parses `-Df` as `-D -f`. The guard resolves `$CLAUDE_CODE_SESSION_ID` from its own validated session context, so the per-session `/advisor on`/`off` flag commands that write that path keep working even when the hook subprocess does not carry the variable. **What remains open:** `awk` bodies and heredoc content (above); a relative path is resolved against the hook's working directory rather than bash's, so once a command has `cd`-ed, a later relative scratch-op path or redirect target is denied for being unknowable rather than checked — and `~+`, `~-` and the `~N` dirstack forms are denied outright, with or without a `cd`, since they are the shell's own names for `$PWD` and `$OLDPWD` and Python's `expanduser` implements none of them; and anything the normalizer marks unresolvable is denied rather than read — a legitimate command built from an expansion, a brace group, or a glob has to be written out or delegated.

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
- Exceeding the ordinary three-round lead checkpoint without new evidence and a viable next check, or exceeding the optional native policy’s two correction cycles (no extension)
- Exporting `ADVISOR_DIRECT=1` for the session

## Cross-References

- `subagent-patterns.md` — spec format, two-stage review, four-state status protocol, results-in-files
- `concurrency-and-rate-limits.md` — wave sizes and model defaults for fan-outs
- `git-worktrees.md` — worktree lifecycle and mandatory teardown
- `/etp` — the full-ceremony execution loop this mode routes ready work into
- The cross-agent pilot workflow reference — provider provenance, current evidence, bounded disputes and actual handback; used only when those pilot commands invoke it
- `verification.md` — the reviewer's cited evidence is the fresh evidence; a self-report is a claim
