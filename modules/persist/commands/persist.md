---
description: Keep working on a task until it is verified done - an opt-in Stop hook blocks stopping while the loop is active. /persist <task> starts it, /persist done ends it, /persist cancel abandons it.
argument-hint: "<task> [--criteria TEXT] [--max N] | done | cancel | status"
---

# /persist - Run a Task to Completion

Start a loop that the Stop hook (`persist-stop.py`) enforces: while the loop is
active, a stop attempt is blocked and you are told to continue. The hook
fails open on every safety condition (context limit, user abort, auth error,
stale state, iteration cap, cancel), so it cannot deadlock the session.

State is `~/.claude/persist/<session_id>.json`. The CLI resolves the session
from `$CLAUDE_CODE_SESSION_ID`, the same id the hook receives.

## Workflow

Parse `$ARGUMENTS`:

- **`done`** - run `$HOME/.claude/bin/ccgm-persist done`. Do this only
  after every done criterion is verified with fresh evidence: a command you ran
  this turn and its output. Reasoning that it should work is not evidence.
- **`cancel`** - run `$HOME/.claude/bin/ccgm-persist cancel`.
- **`status`** - run `$HOME/.claude/bin/ccgm-persist status`.
- **anything else** - it is the task. Pick concrete done criteria (what command
  or observation proves the task is finished; ask the user only if the task gives
  no way to tell), then run:

  ```
  $HOME/.claude/bin/ccgm-persist start --task "<task>" --criteria "<done criteria>"
  ```

  Add `--max N` to change the iteration cap (default 50, hard maximum 200).
  Then begin the task.

Run the CLI by that exact path, never through `python3` and with no env-var
prefix: advisor mode's Bash gate allows only that form. If the CLI is denied
anyway, the loop can still be ended with
`rm -f $HOME/.claude/persist/<session_id>.json`. If the
session id cannot be resolved, report that and stop; do not guess one.

Report the result of the command in one line.
