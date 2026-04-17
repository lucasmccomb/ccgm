---
description: Compose careful + freeze for focused, safe sessions
---

# /guard - Compose Careful + Freeze

`guard` combines the two safety hooks shipped by the `hooks` module:

- **check-careful.py** (PreToolUse:Bash) - prompts on destructive commands
  (`rm -rf`, SQL DROP/TRUNCATE, force push, hard reset, etc.).
- **check-freeze.py** (PreToolUse:Edit|Write) - denies writes outside the
  frozen directory.

`/guard` activates both for a named scope. Use it during investigation or
refactors where you want to stay inside one module and avoid destructive
surprises.

## Usage

```
/guard                       # Guard the current working directory
/guard <absolute-or-relative-path>
```

## Workflow

1. Resolve the argument to an absolute path (same rules as `/freeze`).
2. Activate freeze by writing the path to `~/.claude/freeze-dir.txt`.
3. Confirm both hooks are installed (`~/.claude/hooks/check-careful.py` and
   `~/.claude/hooks/check-freeze.py` exist). If either is missing, warn the
   user and point to the `hooks` module README.
4. Report: `Guarded: <path>. Edit/Write scoped; destructive Bash commands will prompt.`
5. Remind the user that `/unfreeze` clears the freeze half. The careful hook
   stays active (it has no state file to clear; it runs on every Bash call).

## When Other Commands Auto-Guard

Slash commands that encourage focused scope (for example `/investigate` when
adopted) should call `/guard <target-dir>` at the start of the session so the
user does not have to remember.

## Notes

- `check-careful.py` has no enable/disable state - it inspects every Bash
  command. The only way to quiet it is to not call destructive commands.
- `check-freeze.py` is gated by the state file, so `/unfreeze` fully clears
  the scope lock.
