# /permission-fix - Inspect Recent Friction and Apply Targeted Fixes

Surface a single permission-friction event (or list pending proposals)
and, on demand, apply a proposed fix to the canonical CCGM clone via a
reversible git commit. Read-only by default; `apply` is the only
write path and it routes through `lib/apply-proposal.py` so the same
git-tracked, test-gated workflow is used by `/autoheal-apply`.

## Usage

```
/permission-fix latest
/permission-fix list
/permission-fix apply <proposal-id>
```

## When to invoke

- The Stop hook surfaced an `<autoheal-suggestion>` block this session
  pointing at `/permission-fix latest`.
- A pause-and-confirm just fired for a routine command and you want
  to see whether an `allow:` rule could remove the friction.
- The daily digest landed and you want to apply one specific proposal
  without waiting for `/autoheal-apply`.

## When NOT to invoke

- For one-off destructive commands (`rm -rf`, force-push to `main`).
  These are friction by design; permission-fix should not loosen them.
- When you have not yet read `~/.claude/autoheal/proposals/{today}.jsonl`
  for the proposal you intend to apply. Apply is reversible but slow;
  read first.
- For changes that span multiple proposals or require analysis. Use
  `/autoheal-apply` (Epic 11) which is purpose-built for batching.

## How it works

### `/permission-fix latest`

1. Read today's events file at
   `~/.claude/autoheal/events/{today}.jsonl`.
2. Filter to events with `kind` in
   `{permission_request, tool_failure}` for the current session.
3. Pick the most recent matching event.
4. Read today's proposals file at
   `~/.claude/autoheal/proposals/{today}.jsonl`.
5. Find the proposal whose `source_events` list contains the picked
   event's id. If present: print the proposal as JSON.
6. If no analyzer-generated proposal exists yet, print the picked
   event in JSON form plus the message:

   ```
   no analyzer proposal available yet for this event.
   run modules/autoheal/bin/autoheal-analyze.sh manually,
   or wait for the next daily run.
   ```

   This is a deliberate degradation: v1 of this command does not
   call the analyzer in-line because the analyzer requires an API
   key and a sandboxed environment. The daily LaunchAgent run is the
   normal path.

7. Never modify any files in `latest` mode.

### `/permission-fix list`

1. Read today's `~/.claude/autoheal/proposals/{today}.jsonl`.
2. Print one line per proposal: `{id}  {confidence}/10  {kind}  {title}`.
3. Skip proposals where `snoozed_until` is in the future.
4. Never modify any files in `list` mode.

### `/permission-fix apply <proposal-id>`

This is the only write path. Routes through `lib/apply-proposal.py`
so the workflow is identical to `/autoheal-apply <id>`:

1. Locate the proposal in
   `~/.claude/autoheal/proposals/{today}.jsonl` by `id`.
2. Resolve the canonical CCGM clone path by walking up from `cwd`
   until a directory containing `start.sh` is found. Fall back to
   `~/code/ccgm/` if nothing is found.
3. Verify the working tree is clean on `main`. If dirty, commit
   any WIP per the no-stash rule, then continue.
4. Create branch `autoheal/{proposal-id}` (the `source` argument
   to `apply_proposal` is `"permission-fix"`; `auto-apply` uses
   `"auto-apply"` which produces `autoheal/auto/{proposal-id}`).
5. Apply the proposal's `proposed_diff` to its `proposed_diff_target`.
6. Run `tests/test-modules.sh` and `tests/test-no-personal-data.sh`.
   If either fails: revert the branch, write the failure to
   `~/.claude/logs/autoheal-apply.{today}.log`, and exit non-zero.
7. If tests pass: commit with message
   `#auto: apply autoheal proposal {proposal-id}`.
   The `#auto:` prefix is recognised by `enforce-git-workflow.py`
   as a non-issue-number commit type; otherwise use the proposal's
   recorded `issue_number` if present.
8. Append a record to `~/.claude/autoheal/applied/{today}.jsonl`.
9. Print `git diff HEAD~1` and the line:

   ```
   To undo: git revert HEAD
   ```

10. Print a suggested `gh pr create` command. Never auto-merge.

## Output

- `latest`: JSON proposal (or JSON event + no-proposal message).
- `list`: one line per proposal as described above.
- `apply`: diff + revert hint + PR-create suggestion.

## Constraints

- This command MUST NOT propose adding new tools, commands, MCP
  servers, or shell aliases. Permission-fix only narrows or widens
  existing permissions / settings; it does not introduce new
  capabilities. The system prompt at
  `lib/permission-fix-prompt.md` enforces this for any sub-agent
  analysis.
- Apply NEVER auto-merges. The user opens the PR via the printed
  `gh pr create` command.
- Apply NEVER writes to `~/.claude/settings.json` directly. It
  always writes to the canonical CCGM clone under `modules/`. The
  next `start.sh --reinstall` propagates the change.
- Apply runs both `test-modules.sh` and `test-no-personal-data.sh`
  before commit. A failing test is a hard stop, not a warning.

## See also

- `/permission-audit` — static audit of `settings.partial.json`.
- `/autoheal` — top-level help for the autoheal module.
- `/autoheal-apply` — batch apply with confidence-gated auto-apply.
