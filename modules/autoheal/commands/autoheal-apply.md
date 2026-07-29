# /autoheal-apply - List or Apply Autoheal Proposals

Inspect the queue of pending autoheal proposals from the last 7 days,
or apply a single proposal by id through the shared `lib/apply-proposal.py`
path. Same workflow as `/permission-fix apply`: feature branch + diff +
test gate + reversible commit. Never auto-pushes or auto-merges.

## Usage

```
/autoheal-apply                          # list pending proposals
/autoheal-apply list                     # same as above
/autoheal-apply <proposal-id>            # apply a single proposal
```

## When to invoke

- The daily digest landed and you want to review the proposal queue
  before applying anything.
- You want to apply a specific proposal that was not picked up by
  opt-in auto-apply (most proposals are NOT auto-apply-eligible: the
  gate is intentionally strict).
- A previous `/permission-fix apply <id>` attempt failed and you want
  to retry after fixing the underlying issue.

## When NOT to invoke

- To configure flags (auto-apply, realtime, webhook) — use
  `/autoheal-toggle`.
- To suppress a proposal — use `/autoheal-snooze <id> [days]`.
- To trigger the daily analyzer — it runs on its LaunchAgent
  schedule; manual invocation is `bash modules/autoheal/bin/autoheal-analyze.sh`.

## How it works

### `/autoheal-apply` (no args) and `/autoheal-apply list`

Read-only enumeration of pending proposals. List mode does not modify
any files.

1. Walk back over the last 8 days of
   `~/.claude/autoheal/proposals/{date}.jsonl` (today + 7 prior).
2. Read each proposal record. Skip those whose `snoozed_until` is in
   the future or whose `id` already appears in
   `~/.claude/autoheal/applied/*.jsonl` (already applied).
3. Print one table row per remaining proposal:

   ```
   ID                  KIND                  CONFIDENCE  BREADTH  TITLE
   prop_01HW3FQQX7     settings_allow_add    9/10        1        add wrangler dev to safe-list
   prop_01HW8KLLM4     hook_narrow           7/10        3        narrow git-workflow allow-list
   ...
   ```

4. Sort by `(confidence desc, breadth_score asc, generated_at desc)`
   so the proposals most likely to be worth applying surface first.
5. After the table, print: `Found N pending proposal(s). Run
   /autoheal-apply <id> to apply one.` If `N == 0`, print: `No
   pending proposals.`

### `/autoheal-apply <proposal-id>`

The single write path. Routes through `lib/apply-proposal.py` so the
branch shape, commit message, test gate, and audit record are
identical to `/permission-fix apply <id>` and the opt-in
`autoheal-auto-apply.sh`.

1. Look up the proposal by id in
   `~/.claude/autoheal/proposals/{today}.jsonl`. The library scans
   today's file only; to apply an older proposal, copy it into today's
   file or set `CCGM_AUTOHEAL_TODAY=<date>` for the agent's environment.
2. Resolve the canonical CCGM clone path by walking up from `cwd`
   until `start.sh` is found; fall back to `~/code/ccgm/`.
3. Verify the working tree is clean on `main`. If dirty, commit any
   WIP per the CCGM no-stash rule (commit message
   `#auto: WIP before autoheal apply`).
4. Create the feature branch `autoheal/{proposal-id}` (the `source`
   argument is `"permission-fix"`; the auto-apply daemon uses
   `"auto-apply"` which produces `autoheal/auto/{proposal-id}` —
   different prefix on purpose, so the audit log can distinguish
   manual from automatic applies).
5. Apply the proposal's `proposed_diff` to its `proposed_diff_target`
   via `git apply`.
6. Run `tests/test-modules.sh` and `tests/test-no-personal-data.sh`.
   If either fails: revert the branch (`git checkout main`,
   `ALLOW_BRANCH_FORCE_DELETE=1 git branch -D autoheal/{id}`), surface the
   failure, exit non-zero. The hatch is required because force-deleting a
   branch is hard-blocked by default; discarding this just-created,
   test-failing branch is exactly the intentional case it exists for.
7. If tests pass: commit with message
   `#auto: apply autoheal proposal {proposal-id}`. The `#auto:`
   prefix is recognized by `enforce-git-workflow.py` as a non-issue
   commit type.
8. Append a record to `~/.claude/autoheal/applied/{today}.jsonl`
   with `method: permission_fix` and the resulting branch + commit
   sha.
9. Print `git diff HEAD~1` to stdout.
10. Print the line `To undo: git revert HEAD`.
11. Print a suggested `gh pr create` command. Never auto-merge.

The agent invoking this command should execute the apply through:

```bash
python3 modules/autoheal/lib/apply-proposal.py <proposal-id> permission-fix
```

The CLI exits 0 on success, 1 on apply failure, 2 on usage error.

## Output

- `list` / no args: a one-row-per-proposal table (description above).
- `<id>` apply: the unified diff + revert hint + PR-create suggestion,
  plus a JSON status line that the caller can parse for a structured
  result.

## Constraints

- Apply NEVER auto-merges. The user opens the PR via the printed
  `gh pr create` command.
- Apply NEVER writes to `~/.claude/settings.json` directly. It always
  writes to the canonical CCGM clone under `modules/`. The next
  `start.sh --reinstall` propagates the change.
- Apply runs both `test-modules.sh` and `test-no-personal-data.sh`
  before commit. A failing test is a hard stop, not a warning.
- The list mode is read-only. It MUST NOT create branches, write to
  the applied audit log, or modify any state.

## Cross-references

- `/permission-fix apply <id>` — same shared apply path; preferred
  entry point when you're acting on the proposal surfaced in
  `<autoheal-suggestion>` in the current session.
- `/autoheal-toggle autoapply on|off|status` — flip the opt-in
  daemon (gated apply, never pushes).
- `/autoheal-snooze <id> [days]` — suppress a proposal without
  applying it.
- Rule: `~/.claude/rules/autoheal.md` (apply path summary)
- Plan: `~/code/plans/ccgm-autoheal/plan.md` §3.7 (gate predicate),
  §3.9 (apply path), §5 Epic 11.
