---
description: Review and maintain memory files - find duplicates, contradictions, and stale entries
allowed-tools: Agent
---

# /consolidate - Memory Maintenance

Use the Agent tool to execute this workflow:

- **model**: sonnet
- **description**: memory consolidation

Pass the agent all workflow instructions below.

After the agent completes, relay its report to the user exactly as received.

---

## Workflow Instructions

Review all memory files and clean up duplicates, contradictions, and stale entries.

### 1. Read the Memory Index

```bash
cat "$HOME/.claude/projects/*/memory/MEMORY.md" 2>/dev/null | head -200
```

If no MEMORY.md exists, report "No memory index found - nothing to consolidate" and exit.

### 2. Read All Memory Files

For each file referenced in MEMORY.md, read it and note:
- **Name and type** (from frontmatter)
- **Content summary** (one sentence)
- **Potential issues**: duplicate of another entry? contradicts another? too specific? too vague? likely stale?

### 3. Identify Issues

Group findings into categories:

**Duplicates**: Two or more entries that capture the same pattern. Keep the more complete or general version, remove the others.

**Contradictions**: Entries that give conflicting guidance. Determine which is correct (check the codebase or context), update the correct one, remove the incorrect one.

**Stale entries**: Patterns that reference files, functions, or behaviors that no longer exist. Verify by checking the codebase. Remove confirmed stale entries.

**Too specific**: Entries tied to a single incident that are unlikely to recur. Remove or generalize.

**Too vague**: Entries so general they provide no actionable guidance. Either make concrete or remove.

### 4. Apply Changes

For each issue found:
- Edit or remove the memory file
- Update MEMORY.md index if files were added or removed

### 5. Report

```
## Memory Consolidation Report

- **Files reviewed**: N
- **Files updated**: N (list which and why)
- **Files removed**: N (list which and why)
- **Files unchanged**: N
- **New issues found**: (any patterns that need human input to resolve)
```
