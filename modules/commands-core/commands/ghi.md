---
description: Create a new GitHub issue with proper labels
allowed-tools: Agent
---

# /ghi - Create GitHub Issue

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: create GitHub issue

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its report to the user exactly as received.

---

## Workflow Instructions

Create a new GitHub issue with appropriate labels based on the type of work.

Arguments: $ARGUMENTS

### 1. Gather Issue Details

If the arguments provide enough context (title and description), use them directly. Otherwise, ask the user for:

- **Title**: A concise, descriptive title
- **Type**: feature, bug, refactor, chore, documentation, or human-agent
- **Description**: What needs to be done and why

### 2. Determine Issue Type and Labels

Map the issue type to the appropriate label:

| Type | Label | Color | Description |
|------|-------|-------|-------------|
| feature | `enhancement` | `a2eeef` | New feature or improvement |
| bug | `bug` | `d73a4a` | Something is not working |
| refactor | `chore` | `e4e669` | Maintenance, refactoring, config |
| chore | `chore` | `e4e669` | Maintenance, dependencies, config |
| documentation | `documentation` | `0075ca` | Documentation changes |
| human-agent | `human-agent` | `f9d0c4` | Requires manual human action |

### 3. Check Existing Labels

Verify the required label exists in the repo:

```bash
gh label list | grep -i "{label-name}"
```

If the label does not exist, create it:

```bash
gh label create "{label-name}" --color "{color}" --description "{description}"
```

### 4. Build the Issue Body

Structure the issue body based on the type:

**For features/enhancements:**
```markdown
## Summary
{What this feature does and why it is needed}

## Implementation Steps
{Numbered steps if known, or "TBD - to be planned"}

## Acceptance Criteria
- [ ] {Criterion 1}
- [ ] {Criterion 2}
```

**For bugs:**
```markdown
## Bug Description
{What is happening vs. what should happen}

## Steps to Reproduce
1. {Step 1}
2. {Step 2}

## Expected Behavior
{What should happen}

## Actual Behavior
{What is happening}
```

**For human-agent tasks:**
```markdown
## Context
{Why this manual action is needed}

## Required Actions
- [ ] {Action 1}
- [ ] {Action 2}

## Instructions
{Step-by-step guide for the human}
```

### 5. Create the Issue

```bash
gh issue create \
  --title "{title}" \
  --label "{label}" \
  --body "{body}"
```

For human-agent issues, also assign to the repo owner if known:

```bash
gh issue create \
  --title "{title}" \
  --label "human-agent" \
  --body "{body}"
```

### 6. Report Result

Display:
- Issue number
- Issue URL
- Title
- Labels applied
- Suggested next step (e.g., "Create a branch with `git checkout -b {issue-number}-{description} origin/main`")
