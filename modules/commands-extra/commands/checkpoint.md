---
description: Save or resume a structured WIP checkpoint (current task, decisions, remaining work)
---

# /checkpoint - Save or Resume Session State

Capture a structured "pick up here next time" snapshot, or resume from the most
recent one. Different from the session log: session logs are chronological
narrative, checkpoints are compact WIP state meant for handoff between
sessions - or between clones in a multi-agent workspace.

Checkpoints are stored under `~/.claude/checkpoints/{repo}/` as YAML-fronted
markdown, so they survive across clones and can be grepped by branch or date.

## Usage

```
/checkpoint save [title]     # Write a checkpoint now
/checkpoint resume           # Load the most recent checkpoint for this repo
/checkpoint resume [query]   # Load by title substring or YYYYMMDD date
/checkpoint list             # Show checkpoints for this repo, newest first
```

`save` is the default verb: `/checkpoint some title` is equivalent to
`/checkpoint save some title`.

## When to Use

- About to end a session mid-task. Write a checkpoint so the next session can
  resume without rereading the whole log.
- Switching clones in a workspace. Save on clone A, resume on clone B to pick
  up the same WIP.
- Context is about to compact. Checkpoint the essentials before they get
  summarized away.
- Parking a branch to switch to a hotfix. Save, switch, come back, resume.

## Save Workflow

### 1. Derive Identifiers

```bash
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
[ -z "$REPO_NAME" ] && REPO_NAME=$(basename "$PWD")
BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
TS=$(date +%Y%m%d-%H%M%S)
CKPT_DIR="$HOME/.claude/checkpoints/${REPO_NAME}"
mkdir -p "$CKPT_DIR"
```

Build a filename-safe slug from the title argument (or the current branch if no
title was given):

```bash
TITLE="${ARG:-$BRANCH}"
SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
  | cut -c1-60)
[ -z "$SLUG" ] && SLUG="checkpoint"
CKPT_FILE="${CKPT_DIR}/${TS}-${SLUG}.md"
```

### 2. Collect State

Gather the facts you will write into the checkpoint. Do NOT invent details -
only capture what is actually observable right now.

- **status**: one-line summary of where this task stands (e.g. `in-progress`,
  `blocked-on-review`, `ready-to-push`).
- **branch**: `git branch --show-current`.
- **files_modified**: `git status --porcelain` (working copy) plus
  `git diff --name-only origin/main...HEAD` (committed deltas on this branch).
  Deduplicate. List absolute paths or repo-relative paths consistently.
- **session_duration_s**: if you can read the session start time from the
  agent log or your own memory of this session, compute it. Otherwise omit.
- **timestamp**: ISO 8601 local time.

### 3. Write the Checkpoint File

```markdown
---
title: {title}
status: {status}
branch: {branch}
timestamp: {iso8601}
session_duration_s: {integer-or-null}
files_modified:
  - {path}
  - {path}
---

# {title}

## Working on

{One to three sentences. What is the active task? What issue or PR? What is
the immediate next action?}

## Decisions Made

{Bulleted list of non-obvious choices made so far in this session - approach
selected, alternatives rejected, constraints discovered. Skip the obvious.}

## Remaining Work

{Bulleted list of concrete next steps in order. Each item should be small
enough to execute without more planning. Mark blockers with `BLOCKED:`.}

## Notes

{Anything else the next session needs: URLs, test outputs, open questions, a
command to run first, a file to reread. Keep it brief.}
```

### 4. Confirm to the User

Print:

```
Checkpoint saved: {CKPT_FILE}
Branch: {branch}  |  Files touched: {N}
Resume with: /checkpoint resume {slug}
```

## Resume Workflow

### 1. Locate the Checkpoint

```bash
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
[ -z "$REPO_NAME" ] && REPO_NAME=$(basename "$PWD")
CKPT_DIR="$HOME/.claude/checkpoints/${REPO_NAME}"

# No argument: newest checkpoint for this repo.
# Argument looks like YYYYMMDD: newest checkpoint from that date.
# Otherwise: newest checkpoint whose filename contains the query substring.
```

Resolution order:

1. If the query is an 8-digit date, filter files starting with that date prefix.
2. Otherwise treat the query as a case-insensitive substring match against the
   filename (which contains the slug).
3. If no query, take the newest file by name.
4. If still nothing, report `No checkpoints found for {REPO_NAME}` and stop.

Checkpoints saved on other branches ARE valid matches. That is the point - the
user may be resuming from a parked branch.

### 2. Read and Summarize

Read the checkpoint file. Render a concise summary to the user:

```
Resumed: {filename}
Branch: {branch from frontmatter} (current: {current branch})
Status: {status}
Saved: {timestamp}

Working on:
{Working-on section, verbatim}

Remaining Work:
{Remaining-work section, verbatim}
```

### 3. Branch Reconciliation

If the checkpoint's `branch` differs from the current branch, surface the
mismatch and ASK before switching. Never auto-checkout.

```
Checkpoint was saved on `{ckpt-branch}`, you are on `{current-branch}`.
Switch with: git checkout {ckpt-branch}
Or continue on the current branch if intentional.
```

### 4. File Staleness Check

For each path in `files_modified`, check whether it still exists and whether
the file's current state differs from what was likely present at checkpoint
time. A cheap heuristic: if the file is in `git status --porcelain` output
now AND was listed in the checkpoint, flag it as "may have drifted."

Report anything suspicious but do not block. The checkpoint is a hint, not a
lock.

### 5. Next Step

Propose the first item from `Remaining Work` as the next action. Do not
execute it automatically - the user may want to re-scope after resuming.

## List Workflow

```bash
ls -1t "$HOME/.claude/checkpoints/${REPO_NAME}/" 2>/dev/null
```

Render each as `{timestamp}  {branch}  {title}` by reading the first few
frontmatter lines of each file. Limit to the 20 most recent by default.

## Cross-Clone Usage

In the workspace model, `~/.claude/checkpoints/` is shared across all clones
of the user's machine. A checkpoint saved from `myrepo-w0-c0` is visible to
`myrepo-w0-c1`. The only prerequisite is that the other clone is on a branch
that contains the same commits referenced by `files_modified` - otherwise
paths may not exist yet.

If the log repo (session-logging module) is configured and the user prefers
remote backup, the user can symlink `~/.claude/checkpoints/` into the log
repo. This command does not do that automatically - the default is local-only
to avoid leaking WIP to the log remote.

## Conventions

- One checkpoint per invocation. Never overwrite an existing checkpoint -
  timestamps in filenames guarantee uniqueness.
- Checkpoints are ephemeral state, not audit history. It is fine to delete
  `~/.claude/checkpoints/{repo}/` when the repo is done.
- Do not include secrets, tokens, or credentials in any section. If the
  current task touches secrets, reference them by variable name only
  (e.g. `SUPABASE_SECRET_KEY`).
- Checkpoints are markdown. The frontmatter is authoritative; the prose
  sections are for the human (and the next agent) to read.
