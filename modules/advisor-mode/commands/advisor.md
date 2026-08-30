---
description: Toggle advisor mode for THIS session - the orchestrator delegates implementation to cheaper agents and reviews their work; a hard PreToolUse gate blocks its own edits while the mode is on
argument-hint: "[on | off | status] (bare /advisor toggles this session)"
---

# /advisor - Advisor Mode Toggle

Put this session into (or take it out of) **advisor mode**: the main agent
becomes a pure orchestrator that specs, delegates, reviews, and merges — and is
mechanically blocked from implementing directly. The full contract lives in
`~/.claude/rules/advisor-mode.md`.

State is **one flag file per session**: `~/.claude/advisor-mode/<session_id>`.
Every command below acts on the current session only; other sessions keep
whatever mode they are in. Four hooks key on it: `advisor-guard.py`
(PreToolUse, exit-2 hard gate on main-agent file edits and non-orchestration
Bash), `advisor-posture.py` (UserPromptSubmit, injects the posture and this
session's id each turn), `advisor-session-start.py` (creates the flag at
session start and garbage-collects dead sessions' flags), and
`advisor-session-end.py` (removes the flag when the session ends).

## Usage

```
/advisor            # TOGGLE this session: on if off, off if on
/advisor on         # enable explicitly (idempotent)
/advisor off        # disable explicitly (idempotent)
/advisor status     # this session's state, plus every session in the mode
```

## Workflow

**First, resolve this session's id.** Everything below needs it:

1. Run `echo $CLAUDE_CODE_SESSION_ID`. A non-empty value is the id.
2. If it is empty, use the session id from the advisor-mode posture text
   injected into this turn (it names the id and the flag path).
3. If neither is available, report that the session id could not be resolved
   and stop. Never fall back to a machine-global flag file — that is the bug
   this layout removed.

The commands below use `$CLAUDE_CODE_SESSION_ID`; substitute the literal id
when you got it from the posture text instead. Do not wrap any of them in
`$(...)` or backticks — the guard denies command substitution outright.

Then parse the argument:

- **No argument (the default) — toggle.** Check this session's flag:
  `test -f ~/.claude/advisor-mode/$CLAUDE_CODE_SESSION_ID` → present means run
  the `off` branch; absent (exit 1) means run the `on` branch. The explicit
  verbs exist for scripting and for saying exactly what you mean; the bare
  command never requires them.
- **`on`** — if the flag already exists, say so and change nothing (rewriting
  it would lose the original timestamp). Otherwise create it:

  ```
  mkdir -p ~/.claude/advisor-mode
  date -u +'on %Y-%m-%dT%H:%M:%SZ' > ~/.claude/advisor-mode/$CLAUDE_CODE_SESSION_ID
  ```

  (the guard allowlists writes under `~/.claude/`, so this passes even while
  the mode is on). Confirm in two lines: the mode is on for this session, and
  the one-line posture — "I orchestrate: specs, delegation, separate review,
  triage, merge. Implementation goes to subagents; `/advisor off` ends the
  mode."
- **`off`** — `rm -f ~/.claude/advisor-mode/$CLAUDE_CODE_SESSION_ID`. Confirm:
  `Advisor mode off for this session.`
- **`status`** — report this session first, then the machine:
  `cat ~/.claude/advisor-mode/$CLAUDE_CODE_SESSION_ID` (on, with the timestamp
  it started) or note that it exits 1 when the mode is off. Then list every
  session currently in the mode with its start timestamp:

  ```
  grep -H '' ~/.claude/advisor-mode/*
  ```

  and mark which line is this session. `-H` is load-bearing — `grep` prints
  the filename only when it is given more than one file, and exactly one
  session in the mode is the common case, so without it the output has no
  session id to mark. When no session is in the mode the glob does not expand
  and the command reports `No such file or directory`: that is "no sessions in
  advisor mode", not an error to report as a failure.

Then stop — the toggle is the whole command. Do not begin decomposing or
delegating anything until the user gives actual work.

## Notes

- **The mode is per session.** Turning it on or off here never touches another
  running session. A fresh, resumed, or cleared session starts in advisor mode
  by default; opt out with `CCGM_ADVISOR_AUTO=false` in the environment or in
  `~/.claude/.ccgm.env`. Only compaction is exempt: it never re-enables a mode
  the session turned off, but a resume or a `/clear` does start the mode again,
  so `/advisor off` lasts until the session restarts.
- **Legacy state, and other ways the state directory can be missing.** The mode
  used to be a single file at `~/.claude/advisor-mode`. The SessionStart hook
  deletes that file — and a symlink standing in the same place — on first run.
  If `status` reports off in a session that never turned it off, check that
  `~/.claude/advisor-mode` is a writable directory: a leftover file, a symlink,
  or a permission problem each disables the auto-on silently, and the hook
  cannot report it (SessionStart hooks write no output). `rm
  ~/.claude/advisor-mode` once, or fix the permissions, and start a new
  session.
- Flags outlive nothing: the SessionEnd hook removes this session's flag, and
  SessionStart sweeps flags whose session is gone.
- One-off escape hatch: `ADVISOR_DIRECT=1` (env or inline on a Bash command) —
  for user-directed exceptions only.
- If the user asks for advisor mode but then tells you to implement something
  directly, the honest responses are `/advisor off` first, or a one-off
  `ADVISOR_DIRECT=1` — not shell workarounds while the gate is up.
