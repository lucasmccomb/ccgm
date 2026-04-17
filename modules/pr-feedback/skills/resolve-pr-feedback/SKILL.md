---
name: resolve-pr-feedback
description: >
  Structured resolver for PR review comments. Fetches unresolved review threads via GraphQL, triages new vs already-handled, and if 3+ new items arrive (or a cross-invocation signal fires) runs cluster analysis across 11 fixed concern categories grouped by spatial proximity. Dispatches parallel pr-comment-resolver subagents for unambiguous fixes, posts inline replies via gh api, and resolves threads; taste questions are batched for human decision. Skips cluster overhead when only 1-2 new comments exist.
  Triggers: resolve pr feedback, address review comments, work through pr comments, burn down pr review, fix reviewer feedback, unresolved threads, tackle pr review.
disable-model-invocation: true
---

# /resolve-pr-feedback - Structured PR Review Resolver

Turn a stack of PR review comments into a small number of cluster-aware fix plans, dispatch them in parallel, and close the loop on GitHub. The cluster-gate is the key idea: ten one-off "nit" replies are usually three systemic issues, and surfacing the systemic view changes the fix.

This skill does **not** replace human taste on architectural comments. It batches those for explicit decisions while burning through the unambiguous fixes in parallel.

## When to Run

Run `/resolve-pr-feedback` after:

- A PR review lands with 3+ unresolved threads
- A reviewer comes back with a second round after prior fixes
- You return to a stale PR and want to see what threads are still open

Do not run:

- Before a review exists (no comments to resolve)
- During active feature development on the same files - the parallel fan-out will conflict with in-flight edits
- On PRs that are already merged - threads cannot be resolved post-merge

## Mode Selection

Parse `$ARGUMENTS` for a mode token:

- `mode:interactive` (default) - Plan clusters, show the plan, confirm before dispatching
- `mode:autofix` - Dispatch without asking; write a run artifact at `.claude/pr-feedback/runs/YYYYMMDD-HHMM.md`
- `mode:report-only` - Fetch, triage, and cluster; stop before dispatch. Safe for concurrent runs and for audit-only uses
- `mode:headless` - For skill-to-skill composition. Structured output envelope, no prompts, terminal "Resolve complete" line

See `modules/subagent-patterns/rules/subagent-patterns.md` for the full mode contract.

## Arguments

- `pr:NNN` - target PR number. Required unless the current branch has exactly one open PR (in which case pick it).
- `repo:owner/name` - override the repo. Default is the current working directory's repo.
- `only:1,3,5` - restrict to explicit thread indices from the triage listing
- `cluster:force` - force cluster analysis even for 1-2 threads
- `cluster:skip` - force per-thread dispatch even for 3+ threads

## Phase 1: Fetch Unresolved Threads

Invoke the bundled fetcher script. It uses GraphQL because REST cannot tell you whether a thread is resolved:

```
!`bash scripts/get-pr-comments NNN --state unresolved --format json`
```

The script returns structured JSON with one entry per thread - `thread_id`, `path`, `line`, `is_resolved`, `is_outdated`, and all comments in chronological order.

If the script exits non-zero:

- `gh not authenticated` - stop and tell the user to run `gh auth login`
- `repo not found` or `pr not found` - stop and ask for the correct `pr:` / `repo:` argument
- Rate limit error - wait and retry once; if it fails again, stop and report

## Phase 2: Triage - New vs Already-Handled

Not every unresolved thread needs new work. Some were already addressed in a later commit the reviewer has not seen yet.

For each thread, classify as:

- **new** - the last comment is from a reviewer and no commit on the branch addresses the specific `path:line` after that comment. These are what the skill works on.
- **handled-not-replied** - a later commit touched the relevant file and line range, but no reply was posted. Reply acknowledging and referencing the commit SHA; do not re-fix.
- **handled-and-replied** - both a fix commit and a reply exist; the reviewer has not resolved the thread yet. Leave alone. Note in the plan.
- **outdated** - thread's `is_outdated` flag is true. Reply suggesting the reviewer re-review the current code; do not re-fix without new evidence that the concern still stands.

Evidence for "addressed by commit":

- `git log --format="%H %s" origin/main..HEAD -- <path>` where a commit message references the concern, OR
- `git log -L :<function>:<path> origin/main..HEAD` shows a change in the called-out region after the thread's `created_at`

When unsure, classify as `new` and let the cluster analysis route it. Triage errors are cheap; missed fixes are not.

## Phase 3: Cluster Gate

Count `new` threads. Decide whether to run cluster analysis:

- `new_count >= 3` - run clustering (Phase 4)
- `new_count in {1, 2}` - skip clustering, dispatch one `pr-comment-resolver` per thread with a thin spec (Phase 6)
- `cluster:force` - run clustering regardless
- `cluster:skip` - skip clustering regardless

Cross-invocation signal: if `.claude/pr-feedback/runs/` contains a recent artifact (within 24 hours, same `pr:`) with unfinished clusters, resume from that artifact rather than starting fresh. Merge newly arrived comments into the existing cluster set.

## Phase 4: Cluster Analysis

For each `new` thread, classify into one of 11 fixed categories. See `references/cluster-categories.md` for the list, definitions, sample phrases, spatial-proximity rules, and autofix-class routing.

Output of this phase is a list of clusters, each with:

- `category` (one of the 11)
- `proximity` (`same-file` / `subtree:<prefix>` / `cross-cutting`)
- `thread_ids` (list of GraphQL thread node ids this cluster covers)
- `paths` (deduped list of file paths touched)
- `autofix_class` (`safe_auto` / `gated_auto` / `manual` / `advisory`)
- `fix_hypothesis` (one paragraph: what a resolver subagent should do)
- `taste_questions` (if `manual`, the open decisions to surface)

Example:

```
Cluster 1: validation / same-file / src/api/users.ts
  threads: 3 (T1, T4, T7)
  autofix: safe_auto
  hypothesis: Add input validation for empty string, negative age,
    and unknown role - one validator function covers all three.

Cluster 2: architecture / cross-cutting
  threads: 2 (T2, T5)
  autofix: manual
  taste_questions:
    - Extract AuthContext into a shared package vs keep inline?
    - Should the middleware own rate limiting or delegate?
```

Three threads that individually read as nits often become one architectural finding at this stage. That is the point.

## Phase 5: Plan and Confirm

Print the plan:

```
Plan: resolve NNN.
  fetched:        N threads
  triaged:
    new:                  M
    handled-not-replied:  K
    handled-and-replied:  J
    outdated:             L
  clusters:
    safe_auto:   P (dispatch in parallel)
    gated_auto:  Q (dispatch after confirm)
    manual:      R (batch for human decision)
    advisory:    S (reply-only, no code change)
```

In `mode:interactive`: list each `gated_auto` cluster and ask per-cluster `[y/skip/manual]`. `manual` promotes it to the manual batch for the end. `skip` leaves the cluster alone for this run.

In `mode:autofix`: proceed with `safe_auto` and `gated_auto` automatically. Never auto-dispatch `manual` or `security`-category clusters without at least one human-in-the-loop prompt.

In `mode:report-only`: stop here and write the plan to stdout. Do not dispatch.

In `mode:headless`: proceed with `safe_auto` only. Return `manual`, `gated_auto`, and `advisory` clusters in the output envelope for the caller to handle.

## Phase 6: Dispatch pr-comment-resolver Subagents

Dispatch one `pr-comment-resolver` per cluster (or per thread, when clustering was skipped), in parallel. Pass paths, not contents - see `modules/subagent-patterns/rules/subagent-patterns.md`.

Per-subagent spec:

**Objective** - Implement the `fix_hypothesis` for this cluster; post an inline reply on each covered thread; resolve each thread if the reply is a fix (not an acknowledgment).

**Context (paths)**:

- Path to a temp cluster brief written by this skill at `.claude/pr-feedback/runs/YYYYMMDD-HHMM/cluster-NNN.md`
- Paths from the cluster's `paths` field
- Path to the repo's `AGENTS.md` or `CLAUDE.md` for house style

**Constraints**:

- Modify only files listed in the cluster brief. Expanding scope is `BLOCKED`, not "while I am here."
- One commit per cluster; message format `pr:NNN resolve <cluster-slug>`.
- Post one inline reply per thread referencing the commit SHA; do not paraphrase the fix across threads - cite the commit once.
- Resolve the thread via `gh api` only when the reply represents a code change. Advisory replies do not resolve.

**Deliverable** (four-state):

- `DONE` + diff + commit SHA + list of threads replied and resolved
- `DONE_WITH_CONCERNS` + same + concerns (e.g., "fixed but tests are missing")
- `BLOCKED` + reason (e.g., "fix requires editing a file not in scope")
- `NEEDS_CONTEXT` + specific missing info

## Phase 7: Two-Stage Review

Do not trust self-reports. Two passes (see subagent-patterns):

1. **Spec compliance** - Did the subagent respect the cluster's `paths` constraint? Commit message format correct? Replies posted?
2. **Code quality** - Does the diff match project patterns? Any missed edge cases the cluster hypothesis implied?

Re-dispatch with specific feedback for any subagent that failed either stage. Do not silently patch subagent output.

## Phase 8: Post Advisory Replies

For `advisory` clusters, no code changes. Post a single acknowledging reply on each covered thread. Example voice:

```
Thanks - leaving as-is for this PR; noted for a future cleanup pass.
```

Do not post content-free acknowledgments. If there is genuinely nothing to say, leave the thread alone for the reviewer to resolve.

## Phase 9: Manual Batch Report

For `manual` clusters, do not dispatch. Instead, write a decision brief to `.claude/pr-feedback/runs/YYYYMMDD-HHMM/manual-decisions.md` with:

- Each cluster's `fix_hypothesis` and `taste_questions`
- Proposed directions (2-3 options per question when possible, with trade-offs)
- Recommended default (the one to pick if the user does not weigh in)

Surface this file to the user at the end of the run. Do not auto-post anything to GitHub for manual clusters.

## Phase 10: Run Artifact and Summary

Write `.claude/pr-feedback/runs/YYYYMMDD-HHMM.md` summarizing:

```
PR:       owner/repo#NNN
fetched:  N threads
resolved: M threads  (commits: <shas>)
replied:  K threads  (advisory or handled-not-replied)
manual:   J threads  (see manual-decisions.md)
blocked:  P threads  (see per-cluster notes)
```

Print the same summary to the terminal. In `mode:headless`, the envelope contains the same fields as structured JSON, and the final line is literally `Resolve complete` so the caller can detect termination.

If the user was running with `/compound` installed and the run surfaced a pattern across clusters, suggest (do not auto-invoke):

```
Consider running /compound to capture the pattern that surfaced
across these clusters - this looked like a systemic <category>
issue.
```

## GraphQL vs REST

The REST `gh pr view --comments` surface returns comments but not thread state (`isResolved`). This skill uses GraphQL via the bundled `scripts/get-pr-comments` fetcher. `gh pr view --comments` is still a fine first-look tool for humans, but it cannot drive the cluster gate because it does not distinguish resolved from unresolved threads.

Resolving a thread programmatically uses the GraphQL `resolveReviewThread` mutation via `gh api graphql`. The `pr-comment-resolver` agent handles this.

## Why Cluster

A PR with ten review comments typically encodes two or three real concerns. Dispatching ten one-off fixes churns files, produces ten tiny commits, and still leaves the systemic concern un-addressed. Clustering by category + spatial proximity surfaces the systemic view before any code is touched. That is the only reason the gate exists. Below three new threads, the ratio of orchestration overhead to insight is wrong; above three, the opposite.
