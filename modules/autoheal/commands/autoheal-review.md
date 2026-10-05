# /autoheal-review - Accept, Edit, Reject or Snooze Ready Fixes

The one place a user accepts an autoheal fix. Each ready fix is one
AskUserQuestion that carries its own evidence, and one answer is enough to
merge it. The SessionStart notice ("N fixes ready - run /autoheal-review")
points here.

## Usage

```
/autoheal-review            # up to 5 ready fixes, oldest first
/autoheal-review <id>       # one fix, by id
/autoheal-review revert <id>    # undo a merged fix (a revert PR, checked and squash-merged)
/autoheal-review redraft <id>   # ask for a new draft of a measured fix
```

The SessionStart notice names `revert <id>` and `redraft <id>` when a fix was
auto-applied or measured harmful or ineffective at +14 days.

## Revert and redraft

The user named the fix and the action in the command, so run it directly:

- `revert <id>`: `python3 ~/.claude/bin/autoheal-review.py revert <id>`. It
  takes a temporary worktree on `autoheal/revert-<id>` from `origin/main`, runs
  `git revert` on the commit carrying `Autoheal-Id: <id>` (the row's
  `merge_sha` when that is on `origin/main`), commits with an
  `Autoheal-Revert: <id>` trailer, pushes, opens a PR, waits for checks,
  squash-merges it (never `--admin`) and deletes the remote branch. The row
  becomes `reverted`. Report "Reverted with <revert_pr_url>." or the `error`
  verbatim; a failure keeps the row's state and records `revert_error`, and
  running revert again merges the PR it already opened.
- `redraft <id>`: `python3 ~/.claude/bin/autoheal-review.py redraft <id>`.
  Only for a `measured` fix. The merged rule stays; the signature stops
  counting as covered, so the next nightly run drafts it again from the newer
  samples and the new draft comes back through this command. Say so in one
  sentence.

## Steps

All computation lives in `~/.claude/bin/autoheal-review.py`. This command only
asks the questions and passes the answers back.

1. Run `python3 ~/.claude/bin/autoheal-review.py list` (add `--id <id>` when
   an id was given). It prints JSON: `total_ready`, `shown`, and `items`.
   Each item holds complete AskUserQuestion payloads: `question`, `reject_question`,
   and `edit_question` (rule fixes only). If `items` is empty, say
   "No autoheal fixes are ready." and stop. If `total_ready` is above `shown`,
   say how many remain after the last one.
2. For each item, in order, call AskUserQuestion with `item.question` exactly
   as printed. Do not rewrite it, shorten it, or move its text into your own
   message: the payload is the only part the user is sure to see, and the
   ask-context gate blocks a payload that points at context outside it.
3. Act on the answer:

   | Answer | Run |
   |---|---|
   | Apply | `python3 ~/.claude/bin/autoheal-review.py apply <id>` |
   | Edit then apply | Call AskUserQuestion with `item.edit_question`. Write the text the user types under Other to a temp file, then run `... apply <id> --insert-file <file>`. "Back to the fix" re-asks `item.question`. "Skip for now" moves on |
   | Reject | Call AskUserQuestion with `item.reject_question`. Run `... reject <id> --reason "<chosen label or typed text>"` |
   | Snooze 14d | `python3 ~/.claude/bin/autoheal-review.py snooze <id>` |
   | Other (free text) on the main question | Treat the text as replacement lines, the same as Edit then apply |
   | Dismissed | Leave the fix ready and stop the loop |

4. Every `apply`, `reject` and `snooze` prints one JSON object. Report it in
   one plain sentence:
   - `ok: true` with `pr_url`: "Merged <pr_url>." (`issue_url` for an issue.)
   - `ok: false`: say the `error` verbatim and what state the row is in.
     A failure after the PR opened leaves the PR open and the fix `ready`
     with an `apply_error`; running Apply again merges the same PR instead of
     opening another. A `dropped` state means the fix no longer fits
     `origin/main`; autoheal redrafts it after a cooldown.
   - A failed edit (more than 8 lines, empty, or failing validation) changes
     nothing. Offer the edit question again.
5. After the last item, print a three-line summary: applied, rejected and
   snoozed counts, and anything left ready.

## What Apply does (`rule_insert`)

1. Fetches `origin/main` of the CCGM source repo and re-runs `validate()`
   (`lib/apply-proposal.py`). A failure stops here with the reason.
2. Creates a temporary git worktree on `autoheal/<id>` from `origin/main`. The
   source repo's own working tree is never touched.
3. Applies the diff and commits `#auto: apply autoheal proposal <id>` with the
   trailers `Autoheal-Id` and `Autoheal-Signature`.
4. Pushes, runs `gh pr create`, waits for checks with `gh pr checks --watch`,
   then `gh pr merge --squash` (never `--admin`). A branch that is behind gets
   `gh pr update-branch --rebase` and one more try.
5. Removes the worktree and temporary branch whatever happened.
6. Marks the ledger row `applied` with `pr_url`, `merge_sha`, `merged_at`,
   `applied_by` (`review`, or `auto` from the auto-apply step) and
   `baseline_rate` (failures per 100 calls of the tool over the 14 days before
   the merge). The nightly aggregator compares it with the 14 days after the
   merge and marks the row `measured` as effective, ineffective, harmful or
   unmeasurable.

An `issue` fix (hook-denial signatures) files a GitHub issue on the source repo
with the evidence instead, and marks the row `applied` with `issue_url`.

## Reject and Snooze

- Reject records the reason and suppresses the signature for 90 days
  (`suppressed_until`). The aggregator does not redraft it before then.
- Snooze 14d hides the fix until `snoozed_until`. It returns to this list
  afterward, and the aggregator does not redraft the signature meanwhile.

## Constraints

- Never run `gh pr merge --admin`, and never push to the source repo's default
  branch.
- Never answer for the user. Each fix needs its own AskUserQuestion.
- A row that is not `ready` (or a snooze that has not ended) is not offered.

## Cross-references

- Script: `~/.claude/bin/autoheal-review.py`
- Ledger: `~/.claude/lib/ledger.py`, `~/.claude/autoheal/proposals.jsonl`
- Notice: `~/.claude/hooks/autoheal-session-notice.py`
- Rule: `~/.claude/skills/autoheal-reference/SKILL.md`
- Plan: `~/code/plans/ccgm-learning-loops/autoheal-rca.md` (3.2, 3.4, 3.5, 3.6)
