# Persist

An opt-in Stop hook that keeps the main agent working on a declared task until
it is marked done. Without a started loop it does nothing.

Adapted from the guard-stack idea in oh-my-claudecode's `ralph` mode; the
implementation is CCGM's own.

## Use

```
/persist <task> [--criteria TEXT] [--max N]   # start the loop and begin work
/persist status                               # iteration count and criteria
/persist done                                 # only after fresh-evidence verification
/persist cancel                               # abandon the task
```

Under the hood, `bin/ccgm-persist start|status|done|cancel` writes and removes
`~/.claude/persist/<session_id>.json`:

```json
{"task": "...", "iteration": 0, "max_iterations": 50,
 "started_at": "2026-01-01T00:00:00Z", "done_criteria": "..."}
```

While that file exists and is fresh, each stop attempt returns
`{"decision": "block", "reason": ...}`. The reason repeats the task and the
done criteria, says to mark done only after verifying them with fresh
evidence, and gives the exact command to do so.

## Session identity

The CLI reads `$CLAUDE_CODE_SESSION_ID`, which Claude Code sets in Bash tool
environments (advisor-mode relies on the same variable), and the hook reads
`session_id` from its input. Both name the same file, so no
UserPromptSubmit hook is needed. `--session ID` overrides the variable. With
no id available, the CLI exits 2 rather than guess.

## Fail-open guards

The hook lets the stop through when any of these hold:

| # | Guard |
|---|-------|
| 1 | `stop_hook_active` is true (re-entrancy) |
| 2 | The stop is a context-limit stop (blocking it deadlocks compaction) |
| 3 | Transcript context is at or above 95 percent |
| 4 | The user aborted or interrupted |
| 5 | Auth error (401/403 and related) |
| 6 | The state file was last updated more than 2 hours ago |
| 7 | `iteration` reached `max_iterations` (default 50, hard max 200); the state is set `active: false` |
| 8 | `~/.claude/persist/<session_id>.cancel` exists (written by `cancel`) |
| 9 | The state belongs to another session (files are keyed by id) or another project (`CLAUDE_PROJECT_DIR` differs from the `project` recorded at start) |

Any parse or IO error also allows the stop.

Guards 2, 4 and 5 are heuristics: they key off stop-reason fields
(`stop_reason`, `end_turn_reason`) that Claude Code may not send in Stop hook
input. The input fields this module relies on, `session_id`,
`transcript_path` and `stop_hook_active`, are the ones the repo's other hooks
use; the stop-reason field names could not be checked against the Claude Code
hooks docs from the authoring environment and remain unverified. The real
backstops are `stop_hook_active`, the iteration cap, staleness and cancel.

## Notes

- Each block rewrites the state file, which refreshes the 2-hour staleness clock.
- Run the CLI by its path, `$HOME/.claude/bin/ccgm-persist`, not through
  `python3`. Advisor mode's Bash gate allows exactly that form (installed
  symlink, its grammar, no env-var prefix) and denies `python3 ccgm-persist`
  and any other spelling. A copy install under `~/.claude/bin` is writable by
  the main agent and is denied; use the symlink install. The block reason also
  gives `rm -f ~/.claude/persist/<session_id>.json` as an equivalent way to end
  the loop.
- `/etp` can wrap a run with `/persist` for mechanical run-to-completion.

## Install

```bash
bash start.sh --add persist
```

Manual: copy `hooks/persist-stop.py` to `~/.claude/hooks/`, `bin/ccgm-persist`
to `~/.claude/bin/` (executable), `commands/persist.md` to `~/.claude/commands/`,
and merge `settings.partial.json` into `~/.claude/settings.json`.

## Tests

```bash
bash modules/persist/tests/test-persist.sh
```
