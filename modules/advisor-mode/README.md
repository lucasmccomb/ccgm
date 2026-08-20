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

## Files

| File | Role |
|------|------|
| `commands/advisor.md` | `/advisor [on\|off\|status]` — flag file `~/.claude/advisor-mode` |
| `rules/advisor-mode.md` | The posture contract: loop, delegation ladder, floor, review contract |
| `hooks/advisor-guard.py` | PreToolUse exit-2 gate: file writes confined to work-product paths; Bash default-deny with read-only + orchestration allowlist |
| `hooks/advisor-posture.py` | UserPromptSubmit injection while the flag exists |
| `settings.partial.json` | Hook registration (merged into settings.json) |

## What the main agent keeps

Reading, conversation, spec-writing, agent dispatch, findings triage, and the
orchestration verbs: read-only git, `git checkout/switch/pull/fetch/worktree`,
`gh` PR/issue/run/label management including `gh pr merge`, and file writes
under `~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`,
worktree checkouts, and plan-mode plan files.

## Escape hatches

- `/advisor off` — end the mode
- `ADVISOR_DIRECT=1` (env or inline) — one-off, for user-directed exceptions

## Manual install

```bash
cp commands/advisor.md ~/.claude/commands/
cp rules/advisor-mode.md ~/.claude/rules/
cp hooks/advisor-guard.py hooks/advisor-posture.py ~/.claude/hooks/
# merge settings.partial.json into ~/.claude/settings.json
```

## Tests

```bash
bash modules/advisor-mode/tests/test-advisor-guard.sh
```

Covers: flag on/off, subagent passthrough, hatch, work-product path
allowances, the Bash allowlist/denylist, redirection scoping, and regression
probes for real bypasses found during development (newline-hidden commands,
single-`&` chaining, `sed -i` variants, `git checkout -- pathspec`).

## Deferred by design (v1)

- **Read-cap on orchestrator context** (baton's cost guard: deny oversized
  main-agent reads, delegate to a scout) — worth revisiting once the mode
  proves out; skipped so the mode never fights ordinary conversation.
- **Requirements-Ledger / Stop guards** — CCGM's plan/progress artifacts and
  etp's completion contract already cover run-to-completion.
- **Auto-enable on Fable sessions** — possible follow-up.
