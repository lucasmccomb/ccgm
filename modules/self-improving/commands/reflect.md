# /reflect - Structured Reflection

Run the self-improving reflection loop for the current session. This command runs inline (not delegated to a subagent) to preserve full session context.

Learnings are written to the schema-validated JSONL store at `~/.claude/learnings/{project-slug}/learnings.jsonl`; a pointer line is appended to MEMORY.md as a human-readable index.

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

### Phase 4: Search Before Logging

For each candidate learning from Phase 3, search the store before writing:

```bash
ccgm-learnings-search --query "<one or two keywords>" --max 5
```

If a matching entry exists, reinforce it instead of creating a duplicate:

```bash
ccgm-learnings-log verify <id>
```

If no match exists, proceed to Phase 5.

### Phase 5: Write to the Learnings Store

Pick the right `type` from the vocabulary:

| Pattern type | `--type` | Example content |
|---|---|---|
| Root cause / debugging lesson | `pitfall` | "Never stash before a branch switch; stale stashes lose context." |
| User preference | `preference` | "Lucas prefers single bundled PRs for refactors over many small ones." |
| Tool/framework gotcha | `tool` | "Tailwind v4 does not set cursor:pointer on buttons; add base styles." |
| Codebase architecture fact | `architecture` | "Auth middleware runs before rate limiting in this repo." |
| Process that worked | `pattern` | "Run migrations before regenerating TypeScript types to prevent drift." |
| Ops / deploy fact | `operational` | "Cloudflare Pages takes 2-3 min to deploy; do not test immediately after merge." |

Log the entry:

```bash
ccgm-learnings-log \
  --type <type> \
  --content "<one-paragraph rule, sanitized on write>" \
  --tag <kebab-case-tag> --tag <another> \
  --confidence <1-10> \
  --file path/to/anchor  # optional, enables staleness detection
```

Set confidence honestly:
- 8-10: confirmed 3+ times or explicitly stated by user
- 5-7: observed twice or strongly implied
- 3-4: tentative

For learnings that apply across projects, set `--project _global`.

### Phase 6: Dual-Write the MEMORY.md Index (optional)

If a legacy MEMORY.md exists at `~/.claude/projects/*/memory/MEMORY.md`, append a one-line pointer so the human-readable index stays current:

```markdown
- [{type}] {short title} — id: {id} ({date})
```

The JSONL is the source of truth; MEMORY.md is a rendered view. If the two disagree, trust the JSONL.

If nothing from the checklist warrants a learning entry, that is fine. Report "No patterns worth capturing from this session" and move on.

### Phase 7: Report

Briefly state what was captured:
- Number of learnings written (0 is valid)
- One-line summary of each, including the id
- Or "Nothing notable to capture from this session"
