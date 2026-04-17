---
description: Scope-lock Edit/Write to a directory until /unfreeze
---

# /freeze - Scope-Lock Writes to a Directory

Activate the `check-freeze.py` PreToolUse hook by writing a directory path to
`~/.claude/freeze-dir.txt`. While a freeze is active, Edit and Write operations
outside that directory are blocked with a `deny` permission decision.

Use freeze during debugging or focused investigation to prevent scope creep.

## Usage

```
/freeze                      # Freeze to the current working directory
/freeze <absolute-or-relative-path>
```

## Workflow

1. Resolve the argument to an absolute path:
   - No argument: use the current working directory.
   - Relative path: resolve against the current working directory.
   - Absolute path: use as-is.
2. Verify the path exists and is a directory. If not, report the error and stop.
3. Write the resolved absolute path to `~/.claude/freeze-dir.txt` (overwriting
   any previous freeze).
4. Confirm to the user: `Frozen to: <path>`. Remind them that `/unfreeze`
   clears the scope.

## Example

```
/freeze modules/hooks
# -> Frozen to: /home/user/code/ccgm/modules/hooks
# Subsequent Edit/Write calls outside modules/hooks are denied.
```

## Notes

- The freeze state is a single file at `~/.claude/freeze-dir.txt`. Only one
  directory can be frozen at a time; `/freeze` overwrites the previous value.
- Paths with symlinks and `..` are resolved before the containment check, so
  trivial escapes are caught.
- Bash commands are NOT scope-locked - only Edit and Write. Pair with
  `/guard` if you also want destructive-command warnings.
