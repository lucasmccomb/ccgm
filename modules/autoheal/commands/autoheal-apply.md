# /autoheal-apply - Alias for /autoheal-review

`/autoheal-review` is the one place a user accepts an autoheal fix. This
command forwards to it.

## Usage

```
/autoheal-apply              # same as /autoheal-review
/autoheal-apply list         # same as /autoheal-review
/autoheal-apply <proposal-id>    # same as /autoheal-review <proposal-id>
```

## What it does

Run `/autoheal-review` with the same argument (`list` means no argument). It
asks one AskUserQuestion per ready fix with the evidence and the exact diff,
and on Apply opens a PR to the CCGM source repo from a temporary worktree,
waits for checks, and squash-merges it. See `commands/autoheal-review.md`.

## Fixes that are not rules or issues

`/autoheal-review` applies `rule_insert` and `issue` proposals. A `check`
proposal (a new test or hook check) still needs a failing demonstration before
it lands, and goes through the local apply path instead:

```bash
python3 ~/.claude/lib/apply-proposal.py <proposal-id> permission-fix \
    --demonstration <file.json>
```

The demonstration file is JSON: `{"command": "bash tests/test-x.sh",
"clean_exit": 0, "violation": "what you broke", "violation_exit": 1,
"reverted": true}`. Run the check on clean code and confirm it passes, add one
deliberate violation and confirm it fails, then revert the violation. Without a
valid file the apply stops before it touches git. This path commits on a local
branch `autoheal/<id>` and opens no PR.

## Cross-references

- `/autoheal-review` - the interface
- `/permission-fix apply <id>` - the same local apply path for a permission fix
- `/autoheal-snooze <id> [days]` - suppress a proposal without applying it
