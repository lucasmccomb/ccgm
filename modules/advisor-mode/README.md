# Advisor Mode

Session posture for expensive orchestrator models (Fable/Opus): the main agent
specs, delegates, reviews, and merges — it never implements. Enforcement is
mechanical: while the mode is on, a PreToolUse hook hard-blocks the main
agent's file edits and non-orchestration Bash (exit 2, which survives bypass
mode). Subagent tool calls pass untouched, so delegated implementers work
normally.

`/etp` already runs the delegate → separate-review → fix → follow-ups loop for
ready work (plans, investigated issues). Advisor mode is the standing posture
that routes **ad-hoc** work through the same loop instead of letting the
expensive model implement inline — and hands etp-shaped work to `/etp`.

## Why hard enforcement

Prompt-only "you never implement" orchestrators demonstrably drift into
hands-on patching under integration pressure; every documented production fix
for that drift was capability removal, not better prompting. Full prior-art
research: `~/code/docs/research/claude-code-advisor-delegation-mode/research.md`.
The guard's main/subagent discriminator (hook-input `agent_id`/`agent_type`,
absent on main-agent calls) and the per-turn posture injection are adapted from
the `baton` plugin's design. Discriminator drift is asymmetric: main-agent
inputs gaining the fields makes the guard inert (fails open, visibly); subagent
inputs losing them would deny subagents too — loud and recoverable with
`/advisor off`, never a silent misroute.

## State is per session

The flag is `~/.claude/advisor-mode/<session_id>`, keyed by the `session_id`
every hook input carries (`CLAUDE_CODE_SESSION_ID` is the fallback). One
session's mode never binds another's — with many sessions running at once, a
single machine-global file meant one session's `/advisor off` removed the gate
from all of them.

Every session starts in advisor mode. Opt out with `CCGM_ADVISOR_AUTO=false` in
the environment or in `~/.claude/.ccgm.env`. Only compaction is exempt from the
auto-on, so `/advisor off` survives a compaction but a resume or a `/clear`
starts the mode again. The flag is removed when the session ends, and flags
left by sessions that died are swept at the next session start.

## Files

| File | Role |
|------|------|
| `commands/advisor.md` | `/advisor` toggles this session; explicit `on\|off\|status` accepted — `status` also lists every session in the mode |
| `rules/advisor-mode.md` | The posture contract: loop, delegation ladder, floor, review contract |
| `hooks/advisor-guard.py` | PreToolUse exit-2 gate: file writes confined to work-product paths; Bash default-deny with read-only + orchestration allowlist |
| `hooks/advisor-posture.py` | UserPromptSubmit injection while this session's flag exists; also names the session id |
| `hooks/advisor-session-start.py` | SessionStart: creates this session's flag, migrates the legacy global file, sweeps dead sessions' flags |
| `hooks/advisor-session-end.py` | SessionEnd: removes this session's flag |
| `settings.partial.json` | Hook registration (merged into settings.json) |

## What the main agent keeps

Reading, conversation, spec-writing, agent dispatch, findings triage, and the
orchestration verbs: read-only git, `git checkout/switch/pull/fetch/worktree`,
`gh` PR/issue/run/label management including `gh pr merge`, and file writes
under `~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`,
worktree checkouts, and plan-mode plan files.

Read-only recon passes too: dev-tool version and identity probes (`node -v`,
`wrangler whoami`, not `pnpm install`), shell grouping tokens, and
`$(...)`/backtick substitution whose inner commands are themselves
allowlisted (checked recursively, depth-capped, backtick bodies
unescaped first). What a checked substitution returns is an argument for
read-only commands only: `echo $(git rev-parse HEAD)` passes,
`sed $(echo -i) …` does not.

Every argument is read the way bash will pass it — quotes removed
(`'-i'`, `-''i`, `$'-i'`, `$"-i"`), adjacent spans joined, backslash escapes
and line continuations dropped — so spelling a flag differently no longer
hides it. What bash does that the guard cannot reproduce is refused instead
of guessed at, because brace expansion, `$IFS` word splitting and globbing
each turn one typed word into several: a brace group (`-delet{e,e}`), an
unquoted glob (`-dele*`, `[-]delete`), an unquoted expansion the guard cannot
resolve anywhere in a word (`find <dir>$IFS-delete`), a resolvable one whose
value carries whitespace or a glob character (bash globs a value after it
substitutes it), and an undecodable `$'…'` escape are all denied for a
command that is not read-only. A
double-quoted expansion cannot be word-split, so it keeps the narrower rule —
denied leading or inside a flag before its first `=`, allowed after it, which
is what keeps `gh pr edit 1 --title="$T"` usable. `echo $A`, `grep $PAT f`
and `rm -rf $TMPDIR/x` still pass. A relative path after a `cd` is denied, and so are
`~+`, `~-` and `~N` anywhere: the guard resolves them against its own
working directory, not the one bash will be in. The guard resolves `$CLAUDE_CODE_SESSION_ID` from its own
validated session context, so the per-session `/advisor on`/`off` flag
commands keep working even when the hook subprocess does not carry the
variable.

## Escape hatches

- `/advisor off` — end the mode
- `ADVISOR_DIRECT=1` (env or inline) — one-off, for user-directed exceptions

## Manual install

```bash
cp commands/advisor.md ~/.claude/commands/
cp rules/advisor-mode.md ~/.claude/rules/
cp hooks/advisor-guard.py hooks/advisor-posture.py ~/.claude/hooks/
cp hooks/advisor-session-start.py hooks/advisor-session-end.py ~/.claude/hooks/
# merge settings.partial.json into ~/.claude/settings.json
```

## Cross-agent pilot compatibility

X-Plan, adrev and ETP use the installed `cross_agent_review_policy.py` orchestration shim. The guard permits only its enumerated operations and existing work-product run locations; it does not permit arbitrary Python, source writes, or executing recorded check argv. Pilot findings need other-provider evidence and current acknowledgments. Three fix rounds remain the checkpoint; a recorded evidence-backed extension retains the same total deadline and calls. Other callers keep the original bound.

## Tests

```bash
bash modules/advisor-mode/tests/test-advisor-guard.sh
bash modules/advisor-mode/tests/test-advisor-guard-differential.sh
bash modules/advisor-mode/tests/test-advisor-session.sh
```

`test-advisor-guard.sh` covers flag on/off, subagent passthrough, hatch,
work-product path allowances, the Bash allowlist/denylist, redirection
scoping, tool probes, grouping tokens, recursive substitution checking, quote
and escape handling, malformed input, and regression probes for real bypasses
found during development (newline-hidden commands, single-`&` chaining,
`sed -i` variants, `git checkout -- pathspec`, nested escaped backticks, a
substitution standing in for a flag or path, an escaped quote hiding a
trailing command inside a double-quoted or `$'…'` span, a variable standing
in for a flag or path, and a flag spelled out of reach of the literal scans
by quoting, ANSI-C quoting, or an expansion).

`test-advisor-guard-differential.sh` compares the guard against real bash. It
builds a throwaway sandbox and runs a generated carrier x command matrix —
every way of spelling a mutating flag against every command that acts on one
— through both the guard and `bash -c`, then asserts the one invariant that
matters: if bash mutated the sandbox, the guard exited 2. This is the method
that found issue #1017.

`test-advisor-session.sh` covers the per-session state: two sessions with
opposite modes, the session-id fallback and the fail-open when there is none,
auto-on at startup/resume/clear but not compaction, the `CCGM_ADVISOR_AUTO`
opt-out, legacy-file migration, SessionEnd removal, and garbage collection.

## Deferred by design (v1)

- **Read-cap on orchestrator context** (baton's cost guard: deny oversized
  main-agent reads, delegate to a scout) — worth revisiting once the mode
  proves out; skipped so the mode never fights ordinary conversation.
- **Requirements-Ledger / Stop guards** — CCGM's plan/progress artifacts and
  etp's completion contract already cover run-to-completion.
- **Model-conditional auto-enable** — every session now starts in the mode; keying the default off the session's model (Fable/Opus only) is a possible follow-up.
