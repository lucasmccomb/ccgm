---
description: Clear the active freeze scope
---

# /unfreeze - Clear the Freeze Scope

Deactivate the `check-freeze.py` PreToolUse hook by deleting
`~/.claude/freeze-dir.txt`. After `/unfreeze`, Edit and Write operations are
no longer scope-locked.

## Usage

```
/unfreeze
```

## Workflow

1. Check whether `~/.claude/freeze-dir.txt` exists.
2. If it exists, delete it and confirm: `Unfrozen (was: <previous-path>)`.
3. If it does not exist, report: `No freeze active`.

## Notes

- This does not disable the `check-freeze.py` hook itself - it only clears the
  state file the hook reads. The hook is a no-op when no freeze is set.
- Use `/freeze <dir>` to re-activate scope locking.
