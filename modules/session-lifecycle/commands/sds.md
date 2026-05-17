---
description: Shutdown Sequence - autonomous end-of-session wrap-up (commit, issues, reflect, handoff, broadcast)
---

# /sds — Shutdown Sequence

Autonomous end-of-session wrap-up. Commits dirty work, updates referenced issues, runs `/reflect`, writes a handoff, broadcasts to sibling clones. The bookend to `/startup`.

## Usage

```
/sds              Run the full shutdown sequence
/sds --dry-run    Show what would happen without doing anything
```

## Principles

- **Autonomous by default.** Do not prompt unless you genuinely cannot proceed (e.g., merge conflict on the WIP commit, ambiguous issue reference).
- **Compose, do not duplicate.** Use existing tools: `handoff.py`, `/reflect`, `ccgm-learnings-log`, `agent_tracking.py`, `gh` CLI.
- **Conservative on writes that touch other people's view.** Closing an issue is bigger than commenting on one.
- **One screen summary at the end.** The user should see exactly what changed without scrolling.

## The Sequence

Execute these phases in order. Report a brief status line per phase as you go. Do not narrate intermediate reasoning — terse status updates only.

### Phase 0 — Detect mode and identity

```bash
bash ~/.claude/lib/sds-broadcast.sh --siblings-only
```

This JSON gives you: agent id, repo, workspace, sibling list (with dirty state), handoff dir, event log path. Use these throughout. If `--dry-run` was passed to `/sds`, pass it through to all write operations in later phases.

### Phase 1 — Background work check

Use TaskList to see active background tasks the agent owns. For each running task:
- If it's near completion (last status update < 60s ago and progressing), wait briefly.
- If it's stalled or long-running, report it and ask once: "Background task `<id>` is still running. Wait, kill, or leave it?"
- If nothing is running, say so in one line and move on.

Sub-agents spawned via the Task tool that have already returned are out of scope — they don't need shutdown. Only `run_in_background` work and persistent background shells matter here.

### Phase 2 — Working tree commit

```bash
git status --porcelain
git branch --show-current
```

Decision tree:
- **Clean working tree**: report "clean" and skip to Phase 3.
- **Dirty on a feature branch**: stage all, commit as WIP, push:
  ```bash
  git add -A
  git commit -m "WIP: <one-line summary of what was in progress>"
  git push --set-upstream origin "$(git branch --show-current)" 2>/dev/null || git push
  ```
  The WIP message should be specific (file or feature name), not generic.
- **Dirty on main**: do NOT auto-commit. Report the dirty files and ask: "Dirty changes on main. Commit, stash to a branch, or leave?"

If the commit fails (pre-commit hook, conflict), report the error and stop the sequence — don't proceed to issue updates with dirty state.

### Phase 3 — Issue updates

Find issue references from three sources:
1. Branch name leading digits: `^(\d+)[-/]` (e.g., `423-deepresearch-followups` → 423)
2. Recent commits since branching from main: `git log --pretty=%B origin/main..HEAD` — extract `#\d+` and `closes/fixes/resolves #\d+`
3. The open PR for this branch (if any): `gh pr view --json number,body`

For each unique issue number:

```bash
# Check state
gh issue view <N> --json state,title,number
```

- **If issue is open**: post a comment summarizing what was done this session for it. Use commit titles + PR link as evidence. Keep it under ~150 words. Format:
  ```
  Session update from agent-<id>:
  - <commit title 1>
  - <commit title 2>
  PR: #<N> (status: <merged|open>)
  Next: <one line on what's left, or "issue work complete">
  ```
- **If issue is closed**: skip (no comment, no action).
- **Auto-close ONLY when**: issue is still open AND a merged PR's commit body contains `closes #<N>` or `fixes #<N>` or `resolves #<N>`. GitHub usually handles this automatically; this phase is a safety net for cases where the squash-merge stripped the keyword. Use `gh issue close <N> --comment "Closed by merged PR #<P>"`.
- **Never close**: issues where the work isn't actually complete. Err on the side of leaving open.

Report per issue: `#423: commented` / `#423: closed (closes-#N + PR #X merged)` / `#423: already closed, skipped`.

### Phase 4 — Reflect

Invoke the `/reflect` workflow inline (do NOT spawn a subagent — reflection needs in-session context).

Follow the abbreviated reflection pass:
1. What was the task this session?
2. What surprised you or took longer than expected?
3. Is there a reusable pattern, common mistake, user preference, or tool gotcha worth capturing?

For each candidate learning:
```bash
# Check for duplicates first
ccgm-learnings-search --query "<keyword>" --max 3

# If new, log it
ccgm-learnings-log --type <pattern|pitfall|preference|tool|architecture|operational> \
  --content "<one-paragraph rule>" \
  --tag <kebab-tag> \
  --confidence <1-10>

# If existing, reinforce
ccgm-learnings-log verify <id>
```

If nothing notable, say "no learnings captured" and move on. Do not force.

### Phase 5 — Handoff

Build a handoff body (markdown, ~200 words max). Use the template:

```markdown
# Handoff — <one-line description>

## What I did

<one paragraph: what shipped, files/modules touched, PR link>

## What's next

<bullet list of immediate follow-ups, ideally concrete enough that the next agent acts without re-deriving context>

## Blockers / context

<known landmines, decisions made and why, anything that would surprise the next agent. Skip if nothing applies.>
```

Write it via the existing handoff lib (auto-detects repo, branch, agent, PR, issue):

```bash
python3 ~/.claude/lib/handoff.py write --body "$(cat <<'EOF'
<your handoff body here>
EOF
)"
```

The file lands at `~/.claude/handoffs/<repo>/<timestamp>-<agent>.md` where `auto-startup.py` will auto-inject it into the next session for this clone AND for every sibling clone.

### Phase 6 — Sibling broadcast + event log

```bash
bash ~/.claude/lib/sds-broadcast.sh
```

This appends a `session-ended` event to `~/.claude/sessions/<repo>/events.jsonl` and re-prints the sibling status JSON.

For each sibling with `dirty: true` on a feature branch, note it in the final summary so the user can decide whether to switch clones and run `/sds` there as well. Do NOT directly invoke `/sds` in sibling clones — they may be mid-task.

### Phase 7 — Final summary

Print a one-screen report. Format:

```
/sds complete — agent-<id> on <branch>

Phase 1 — Background: <none | killed N | waited on N>
Phase 2 — Commit: <clean | WIP committed: <sha> | <skipped, reason>>
Phase 3 — Issues: #<N> commented, #<N> closed, ...
Phase 4 — Reflect: <N> learning(s) captured | nothing notable
Phase 5 — Handoff: <path>
Phase 6 — Broadcast: <N> sibling(s) notified via event log

Sibling state:
- agent-w0-c1 on <branch> (clean | dirty)
- ...

Next: <one line — "safe to exit" or "consider running /sds in dirty sibling X">
```

## Failure handling

- Any phase that fails should report the failure and stop the sequence. Do not continue past a broken phase silently.
- The only phase where partial completion is acceptable is Phase 3 (Issues) — a failed comment on one issue doesn't prevent commenting on another. Report per-issue.
- If the git push in Phase 2 fails (auth, branch protection), commit locally and report the push failure — don't roll back the commit.

## When NOT to use

- Mid-task. `/sds` is for end-of-session, not pausing. Use `/checkpoint save` to pause.
- Right after a fresh `/startup`. Nothing to wrap up.
- When you've been in read-only mode (no commits, no issues touched). The phases will be no-ops; you can run it but a one-line "nothing to wrap up" is the right report.

## Cross-reference

- `/startup` — the other bookend; reads handoffs `/sds` writes
- `/handoff` — invoked by Phase 5 under the hood
- `/reflect` — invoked by Phase 4 inline
- `/checkpoint save` — different concern (pause mid-task vs. end session)
- `/cpm` — for the "ship the PR and merge" flow before /sds is appropriate
