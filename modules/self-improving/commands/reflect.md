# /reflect - Structured Reflection

Run the self-improving reflection loop for the current session. This command runs inline (not delegated to a subagent) to preserve full session context.

---

## When to Use

- After completing a feature, bug fix, or significant task
- When prompted by the PostToolUse reflection hook (after PR merge)
- When prompted by the PreCompact hook (before context compaction)
- Any time you want to deliberately capture learnings

## Workflow

Follow these phases in order. Do not skip phases, but any phase that yields nothing notable can be completed in one sentence.

### Phase 1: Recall Session Context

Think about what happened in this session:
- What was built, fixed, or changed?
- What debugging paths were tried and abandoned?
- What did the user correct or confirm?
- What took longer than expected?

This step uses your in-session memory. Do not rely solely on git history.

### Phase 2: Ground in Git History

```bash
git log --oneline -10
```

Review recent commits to ground your recall in concrete changes. Note any commits that represent significant decisions or non-obvious fixes.

### Phase 3: Reflection Checklist

Walk through each item:

1. **What was the task?** (one sentence summary)
2. **What surprised me or took longer than expected?** Note anything non-obvious.
3. **Is there a reusable pattern here?** A lesson that would help in future sessions across any project.
4. **Did I discover a common mistake?** Something that wasted significant time and could recur.
5. **Did I learn a user preference?** A working style, communication preference, or approach the user validated.
6. **Did I discover a tool/framework gotcha?** A non-obvious behavior, config requirement, or pitfall.

### Phase 4: Write to Memory (if warranted)

For each pattern worth capturing from Phase 3, write it to the appropriate memory file:

| Pattern type | Memory file type | Example filename |
|---|---|---|
| Root cause / debugging lesson | feedback | `feedback_debugging_pattern.md` |
| User preference | user | `user_preference_prs.md` |
| Tool/framework gotcha | feedback | `feedback_tailwind_gotcha.md` |
| Codebase discovery | project | `project_auth_architecture.md` |

Use the standard memory file format:

```markdown
---
name: {pattern name}
description: {one-line description for relevance matching}
type: {user|feedback|project|reference}
---

{Pattern content. For feedback/project types: rule/fact, then **Why:** and **How to apply:** lines.}
```

After writing, update MEMORY.md with a pointer to the new file.

If nothing from the checklist warrants a memory entry, that is fine. Report "No patterns worth capturing from this session" and move on.

### Phase 5: Report

Briefly state what was captured:
- Number of memory entries written (0 is valid)
- One-line summary of each pattern captured
- Or "Nothing notable to capture from this session"
