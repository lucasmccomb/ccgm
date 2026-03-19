---
description: Check progress on a running or completed xplan
allowed-tools: Bash, Read, Glob, Grep
argument-hint: [plan-name]
---

# xplan-status - Plan Progress Dashboard

Check the status of a running or completed `/xplan` execution.

## Input

```
$ARGUMENTS
```

## Instructions

### 1. Find the Plan

If a plan name was provided in `$ARGUMENTS`, look for it directly:
```bash
ls ~/code/plans/{plan-name}/
```

If no plan name was provided, list all plans and show the most recently modified:
```bash
ls -lt ~/code/plans/ | head -20
```

If multiple plans exist and none was specified, use AskUserQuestion to ask which plan to check.

### 2. Read Progress File

Read `~/code/plans/{plan-name}/progress.md` for execution state.

### 3. Check Live State (if status is IN PROGRESS)

If the plan is still in progress, also check live state:

```bash
# Get project name from progress.md or plan.md
# Check GitHub issues
gh issue list --state open --repo {your-username}/{project-name} --limit 50

# Check open PRs
gh pr list --state open --repo {your-username}/{project-name}

# Check clone states
for i in 0 1 2 3; do
  dir=~/code/{project-name}-repos/{project-name}-$i
  if [ -d "$dir" ]; then
    echo "=== Clone $i ==="
    git -C "$dir" branch --show-current
    git -C "$dir" status --short
  fi
done
```

### 4. Present Dashboard

Display a concise dashboard:

```
Plan: {plan-name}
Status: {IN PROGRESS / COMPLETE / INTERRUPTED}
Progress: {N}/{total} epics complete

Wave Status:
  Wave 1: COMPLETE (3/3 epics merged)
  Wave 2: IN PROGRESS (1/4 epics complete, 2 active, 1 pending)
  Wave 3: PENDING

Active Agents:
  agent-0 (clone-0): Epic 5 - "User Dashboard" [in-progress]
  agent-1 (clone-1): Epic 6 - "API Endpoints" [PR open]

Open PRs:
  #12 - Epic 6: API Endpoints (agent-1) - awaiting CI

Human-Epics:
  Human-Epic 1: "Google OAuth Setup" - BLOCKING Wave 3
    Instructions: [brief summary]

Last Checkpoint: Wave 2 partial - {timestamp}
```

### 5. Suggest Actions

Based on the state, suggest what the user can do:
- If INTERRUPTED: "Run `/xplan-resume {plan-name}` to continue execution"
- If blocked by human-epic: Show the walkthrough instructions for the blocking human-epic
- If COMPLETE: "Run `cat ~/code/plans/{plan-name}/retro.md` to see the retrospective"
- If all agent work is done but human-epics remain: List exactly what the user needs to do
