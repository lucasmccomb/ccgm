---
description: Toggle advisor mode - the orchestrator delegates implementation to cheaper agents and reviews their work; a hard PreToolUse gate blocks its own edits while the mode is on
argument-hint: "[on | off | status]"
---

# /advisor - Advisor Mode Toggle

Put this session into (or take it out of) **advisor mode**: the main agent
becomes a pure orchestrator that specs, delegates, reviews, and merges — and is
mechanically blocked from implementing directly. The full contract lives in
`~/.claude/rules/advisor-mode.md`.

State is the flag file `~/.claude/advisor-mode` (the freeze pattern). Two hooks
key on it: `advisor-guard.py` (PreToolUse, exit-2 hard gate on main-agent file
edits and non-orchestration Bash) and `advisor-posture.py` (UserPromptSubmit,
injects the posture each turn so the model delegates instead of fighting
denials).

## Usage

```
/advisor            # same as /advisor on
/advisor on         # enable advisor mode
/advisor off        # disable advisor mode
/advisor status     # report current state
```

## Workflow

Parse the argument (default `on`):

- **`on`** — write the flag with a timestamp:
  `printf 'on %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > ~/.claude/advisor-mode`
  (the guard allowlists writes under `~/.claude/`, so this passes even when the
  mode is already on). Confirm in two lines: the mode is on, and the one-line
  posture — "I orchestrate: specs, delegation, separate review, triage, merge.
  Implementation goes to subagents; `/advisor off` ends the mode."
- **`off`** — `rm -f ~/.claude/advisor-mode`. Confirm: `Advisor mode off.`
- **`status`** — `test -f ~/.claude/advisor-mode && cat` it. Report on/off and,
  when on, the timestamp it was enabled.

Then stop — the toggle is the whole command. Do not begin decomposing or
delegating anything until the user gives actual work.

## Notes

- The mode is global to the machine (one flag file), matching `/freeze`. Turning
  it on affects every concurrently running session's main agent; say so if the
  user seems to expect per-session scope.
- One-off escape hatch: `ADVISOR_DIRECT=1` (env or inline on a Bash command) —
  for user-directed exceptions only.
- If the user asks for advisor mode but then tells you to implement something
  directly, the honest responses are `/advisor off` first, or a one-off
  `ADVISOR_DIRECT=1` — not shell workarounds while the gate is up.
