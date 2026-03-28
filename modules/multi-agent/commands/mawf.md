---
description: Multi-Agent Workflow - take unstructured feedback, split into issues, spin up parallel agents
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, AskUserQuestion
---

# /mawf - Multi-Agent Workflow

Takes unstructured feedback, feature requests, or bug reports, splits them into discrete GitHub issues, and spins up parallel agents to implement them.

## Input

```
$ARGUMENTS
```

## Instructions

### Phase 1: Gather Feedback

If `$ARGUMENTS` contains the feedback directly, use it. Otherwise, prompt the user:

> "What feedback, feature requests, or bug reports do you want me to process? You can paste raw notes, bullet points, user feedback, or a mix of everything."

### Phase 2: Parse into Issues

Analyze the raw input and break it into discrete, independent work items. For each item:

1. **Identify the type**: feature, bug, refactor, chore, or human-agent
2. **Write a clear title**: Concise, actionable, imperative mood
3. **Write a description**: What needs to be done and why
4. **Assess dependencies**: Does this block or depend on other items?
5. **Assess scope**: Is this one PR or does it need to be an epic?

Present the parsed issue list to the user:

```
I've parsed your feedback into {N} issues:

1. [feature] {Title} - {one-line summary}
2. [bug] {Title} - {one-line summary}
3. [feature] {Title} - {one-line summary}
4. [human-agent] {Title} - {one-line summary}

Dependencies:
- Issue 3 depends on Issue 1
- Issue 4 requires human action (cannot be automated)

Does this look right? Should I adjust anything before creating these?
```

Wait for user confirmation before proceeding.

### Phase 3: Create GitHub Issues

For each parsed item, create a GitHub issue:

```bash
gh issue create \
  --title "{title}" \
  --label "{type-label}" \
  --body "{structured body with summary, steps, and acceptance criteria}"
```

For items with dependencies, note the dependency in the issue body:

```markdown
## Dependencies
- Depends on #{dependency-issue-number}
```

For human-agent items:

```bash
gh issue create \
  --title "{title}" \
  --label "human-agent" \
  --body "{context, required actions, step-by-step instructions}"
```

Collect all created issue numbers.

### Phase 4: Plan Agent Allocation

Determine how to allocate agents based on:

1. **Available clones**: Check how many clones exist
   ```bash
   # Detect model and discover clones
   WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')

   if [ -n "$WC_MATCH" ]; then
     # Workspace model: clones are siblings in the workspace dir
     WORKSPACE_DIR=$(dirname "$PWD")
     ls -d "${WORKSPACE_DIR}"/*-c[0-9]*/ 2>/dev/null | wc -l
   else
     # Flat clone model
     REPOS_DIR=$(dirname "$PWD")
     REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
     ls -d "${REPOS_DIR}/${REPO_BASE}"-[0-9]* 2>/dev/null | wc -l
   fi
   ```

2. **Issue dependencies**: Group into waves
   - **Wave 1**: Issues with no dependencies (can run in parallel)
   - **Wave 2**: Issues that depend on Wave 1 issues
   - **Wave N**: Issues that depend on Wave N-1 issues

3. **Agent assignment**: Map issues to clones
   - Skip human-agent issues (those are for the user)
   - Assign up to one issue per clone per wave
   - If more issues than clones, queue the extras for later waves

Present the execution plan (agent IDs match the clone directory names):

```
Execution Plan:

Wave 1 (parallel):
  {agent-id-0} ({clone-dir-0}): #{issue} - {title}
  {agent-id-1} ({clone-dir-1}): #{issue} - {title}
  {agent-id-2} ({clone-dir-2}): #{issue} - {title}

Wave 2 (after Wave 1):
  {agent-id-0} ({clone-dir-0}): #{issue} - {title}

Human tasks (for you):
  #{issue} - {title}

Proceed with execution?
```

Wait for user confirmation.

### Phase 5: Execute

For each wave:

#### 5.1 Spawn Agents

Use the Task tool to launch one agent per assigned issue, each in its own clone directory:

Each agent should:
1. Navigate to its assigned clone directory
2. Run `/startup` to initialize the session
3. Claim the issue by creating a branch (`git checkout -b {issue}-{desc} origin/main`). The PostToolUse hook auto-registers the claim in tracking.csv.
4. Create a feature branch from `origin/main`
5. Implement the work with tests
6. Run verification (lint, type-check, test, build)
7. Commit, push, and create a PR
8. Report completion

#### 5.2 Monitor Progress

Wait for all agents in the current wave to complete. Track:
- Which agents have finished
- Which PRs have been created
- Any failures that need attention

#### 5.3 Wave Completion

When all agents in a wave complete:
1. Review all PRs (check CI status)
2. Merge passing PRs: `gh pr merge --squash --delete-branch`
3. Sync all clones to latest main:
   ```bash
   # Detect model and iterate clones
   WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')

   if [ -n "$WC_MATCH" ]; then
     # Workspace model
     WORKSPACE_DIR=$(dirname "$PWD")
     for dir in "${WORKSPACE_DIR}"/*-c[0-9]*/; do
       [ -d "$dir" ] || continue
       AGENT_ID=$(grep 'AGENT_ID=' "${dir}/.env.clone" 2>/dev/null | cut -d= -f2)
       git -C "$dir" fetch origin
       git -C "$dir" checkout "${AGENT_ID}" 2>/dev/null || git -C "$dir" checkout main
       git -C "$dir" reset --hard origin/main
     done
   else
     # Flat clone model
     REPOS_DIR=$(dirname "$PWD")
     REPO_BASE=$(basename "$PWD" | sed 's/-[0-9]*$//')
     for dir in ${REPOS_DIR}/${REPO_BASE}-[0-9]*; do
       AGENT_NUM=$(basename "$dir" | grep -oE '[0-9]+$')
       git -C "$dir" fetch origin
       git -C "$dir" checkout "agent-${AGENT_NUM}" 2>/dev/null || git -C "$dir" checkout main
       git -C "$dir" reset --hard origin/main
     done
   fi
   ```
4. Proceed to next wave

#### 5.4 Continue Until Complete

Repeat for each wave until all automatable issues are resolved.

### Phase 6: Report

Present a final summary:

```
Multi-Agent Workflow Complete

Issues Created: {N}
Issues Completed: {N}
PRs Merged: {N}
Waves Executed: {N}

Completed:
  #{issue} - {title} (PR #{pr})
  #{issue} - {title} (PR #{pr})

Human Tasks Remaining:
  #{issue} - {title}
    Instructions: {brief summary}

Failed (needs attention):
  #{issue} - {title}
    Error: {what went wrong}
```
