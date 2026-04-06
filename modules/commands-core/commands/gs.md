---
description: Show git status and project overview
allowed-tools: Agent
---

# /gs - Git Status Dashboard

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: git status dashboard

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its dashboard output to the user exactly as received.

---

## Workflow Instructions

Display a comprehensive overview of the current repository state.

Arguments: $ARGUMENTS

### Step 1: Gather Data

Run the gather script to collect all git data in parallel:

```bash
bash ~/.claude/lib/gs-gather.sh
```

This outputs structured `=== SECTION ===` blocks with all data needed.

### Step 2: Present Dashboard

Format the gathered data into this dashboard. Omit any section that is empty.

```
Repository: {name from REPO section}
Branch: {branch} -> {upstream}
Status: {clean / N files changed based on STATUS section}

Sync:
  Main: {ahead_behind from SYNC main: line - format as "N ahead, N behind"}
  Remote: {ahead_behind from SYNC upstream: line - format as "N unpushed, N to pull"}

Recent Commits:
  {LOG section content}

Open PRs:
  {PRS section content, highlight any from current branch}

Sibling Sessions (same repo):
  {SESSIONS content, or omit if empty}

Changes:
  {DIFF section content - summarize staged/unstaged/untracked}

Suggested: {recommended next action per table below}
```

| State | Recommendation |
|-------|---------------|
| Uncommitted changes on feature branch | Run `/commit` to commit your changes |
| Committed changes, no PR | Run `/pr` to push and create a pull request |
| On main with no changes | Create a feature branch or run `/ghi` |
| Behind main on feature branch | Run `git fetch origin && git rebase origin/main` |
| PR open and CI passing | Run `gh pr merge --squash --delete-branch` |
| Clean state on main | Ready for new work |
