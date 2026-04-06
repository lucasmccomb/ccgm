---
description: Check progress on a running or completed xplan
allowed-tools: Agent
argument-hint: [plan-name]
---

# xplan-status - Plan Progress Dashboard

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: xplan status check

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its dashboard output to the user exactly as received.

---

## Workflow Instructions

Check the status of a running or completed `/xplan` execution.

Arguments: $ARGUMENTS

### Step 1: Find the Plan

If a plan name was provided in the arguments, look for it directly:
```bash
ls ~/code/plans/{plan-name}/
```

If no plan name was provided, list all plans and show the most recently modified:
```bash
ls -lt ~/code/plans/ | head -20
```

If multiple plans exist and none was specified, ask which plan to check.

### Step 2: Read Progress File

Read `~/code/plans/{plan-name}/progress.md` for execution state.

Extract the project name and GitHub username from progress.md or plan.md.

### Step 3: Gather Live State (if IN PROGRESS)

If the plan is still in progress, run the gather script:

```bash
bash ~/.claude/lib/xplan-status-gather.sh "{project-name}" "{github-user}"
```

This outputs structured `=== SECTION ===` blocks: ISSUES, PRS, CLONES, TRACKING.

### Step 4: Present Dashboard

```
Plan: {plan-name}
Status: {IN PROGRESS / COMPLETE / INTERRUPTED}
Progress: {N}/{total} epics complete

Wave Status:
  Wave 1: COMPLETE (3/3 epics merged)
  Wave 2: IN PROGRESS (1/4 epics complete, 2 active, 1 pending)
  Wave 3: PENDING

Active Agents:
  {clone}: {branch} [status from CLONES section]

Open PRs:
  {from PRS section}

Human-Epics:
  {any blocking human tasks from progress.md}

Last Checkpoint: {from progress.md}
```

### Step 5: Suggest Actions

Based on the state:
- If INTERRUPTED: "Run `/xplan-resume {plan-name}` to continue execution"
- If blocked by human-epic: Show the walkthrough instructions for the blocking task
- If COMPLETE: "Run `cat ~/code/plans/{plan-name}/retro.md` to see the retrospective"
- If all agent work done but human-epics remain: List exactly what the user needs to do
