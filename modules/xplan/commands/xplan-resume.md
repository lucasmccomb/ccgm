---
description: Resume an interrupted xplan execution
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <plan-name>
---

# xplan-resume - Resume Interrupted Plan Execution

Resume a previously interrupted `/xplan` execution from its last checkpoint.

## Sub-Agent Model Optimization

When spawning execution agents to resume epic work, set model to **sonnet** in the Agent tool call. The orchestrator remains on the current model for coordination and decision-making.

---

## Input

```
$ARGUMENTS
```

## Instructions

### 1. Find the Plan

If a plan name was provided in `$ARGUMENTS`, look for it:
```bash
ls ~/code/plans/{plan-name}/
```

If no plan name was provided, find plans with IN PROGRESS or INTERRUPTED status:
```bash
for dir in ~/code/plans/*/; do
  if [ -f "$dir/progress.md" ]; then
    name=$(basename "$dir")
    status=$(grep "^## Status:" "$dir/progress.md" | head -1)
    echo "$name: $status"
  fi
done
```

If multiple resumable plans exist, use AskUserQuestion to ask which one.

### 2. Read Plan State

Read these files to reconstruct full context:

1. **progress.md** - Current execution state, completed epics, last checkpoint
2. **plan.md** - Full plan with all epic definitions
3. **decisions.md** - Decisions made during execution
4. **research.md** - Original research (for context on goals and constraints)

### 3. Analyze Last Checkpoint

From the most recent checkpoint in progress.md, determine:
- **Last completed wave**: Which wave finished successfully
- **Current wave**: Which wave was in progress when interrupted
- **Completed epics**: Which epics have been merged to main
- **In-flight epics**: Which epics were being worked on (may have partial work)
- **Pending epics**: Which epics have not been started
- **Resume context**: Key decisions, patterns, and gotchas noted in checkpoint

### 4. Verify Live State

Check actual state against checkpoint (things may have changed):

```bash
# Get project name
# Check what is actually merged to main
gh pr list --state merged --repo {your-username}/{project-name} --limit 100

# Check open PRs (in-flight work)
gh pr list --state open --repo {your-username}/{project-name}

# Check issue state
gh issue list --state open --repo {your-username}/{project-name} --limit 100
gh issue list --state closed --repo {your-username}/{project-name} --limit 100

# Check clone states (auto-detect workspace vs flat model)
# Workspace model: look for {project}-workspaces/{project}-w*/{project}-w*-c*/
WORKSPACES_DIR=~/code/{project-name}-workspaces
REPOS_DIR=~/code/{project-name}-repos

if [ -d "$WORKSPACES_DIR" ]; then
  for dir in "${WORKSPACES_DIR}"/{project-name}-w*/{project-name}-w*-c*/; do
    [ -d "$dir" ] || continue
    echo "=== $(basename $dir) ==="
    git -C "$dir" fetch origin
    git -C "$dir" branch --show-current
    git -C "$dir" status --short
    git -C "$dir" log --oneline -3
  done
elif [ -d "$REPOS_DIR" ]; then
  for dir in "${REPOS_DIR}"/{project-name}-[0-9]*/; do
    [ -d "$dir" ] || continue
    echo "=== $(basename $dir) ==="
    git -C "$dir" fetch origin
    git -C "$dir" branch --show-current
    git -C "$dir" status --short
    git -C "$dir" log --oneline -3
  done
fi
```

### 5. Handle In-Flight Work

For epics that were in progress when interrupted:

1. **Check if PR exists** - If yes, check CI status:
   - CI green: Merge the PR and mark epic complete
   - CI red: Read the failure, fix it, push, wait for green, merge
   - No CI yet: Wait for it

2. **Check for uncommitted work** - If a clone has uncommitted changes:
   - Read the changes to understand what was in progress
   - Determine if the work is complete enough to commit and PR
   - If partial, assess whether to continue or start fresh

3. **Check for branches without PRs** - If work was committed but no PR created:
   - Review the commits
   - Create the PR if work is complete
   - Continue the work if incomplete

### 6. Sync All Clones

Before resuming execution, ensure all clones are on latest main:
```bash
for i in 0 1 2 3; do
  dir=~/code/{project-name}-repos/{project-name}-$i
  if [ -d "$dir" ]; then
    git -C "$dir" fetch origin
    git -C "$dir" checkout main
    # Safe: resets to remote ref (auto-approved by hook)
    git -C "$dir" reset --hard origin/main
  fi
done
```

### 7. Present Resume Plan

Show the user:
```
Resuming: {plan-name}
Last checkpoint: Wave N - {timestamp}

Completed (verified):
  - Epic 1: "Repo Setup" (PR #1, merged)
  - Epic 2: "Shared Types" (PR #3, merged)
  - Epic 3: "Auth Flow" (PR #5, merged)

Recovered (in-flight at interruption):
  - Epic 4: "User Dashboard" - PR #7 exists, CI green, merging now
  - Epic 5: "API Endpoints" - partial work on clone-1, continuing

Remaining:
  Wave 3: Epic 6, Epic 7, Epic 8 (all pending)
  Wave 4: Epic 9, Epic 10 (all pending)

Human-epics still needed:
  - Human-Epic 2: "Stripe Setup" (blocks Wave 4)

Resuming from: Wave N (continuing in-flight) / Wave N+1 (all prior complete)
```

### 8. Resume Execution

Continue execution using the same protocol as Phase 7 of `/xplan`:
- Pick up from the current wave
- Spawn agents for remaining epics
- Continue writing checkpoints after each wave
- Update progress.md throughout
- Do not stop until all completable work is done

### 9. On Completion

Follow Phase 8 of `/xplan`:
- Full audit
- Final report
- Generate or update retro.md (note the interruption and resume in the retro)
- Offer to save as template
- Update agent logs
- Mark progress.md as COMPLETE
