---
description: Promote Repo Rules to Global
allowed-tools: Agent
---

# /promote-rule - Promote Repo Rules to Global

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: sonnet
- **description**: promote repo rules

Pass the agent all workflow instructions below.

After the agent completes, relay its findings to the user exactly as received.

---

## Workflow Instructions

Review repo-level CLAUDE.md files and suggest rules that should be promoted to the global configuration.

### 1. Find Explicit Candidates

Search the current repo's CLAUDE.md for the `CANDIDATE:GLOBAL` marker:

```
<!-- CANDIDATE:GLOBAL - [reason] -->
```

Any instruction marked with this tag has been explicitly flagged for promotion. Collect these first.

### 2. Detect Implicit Candidates

Scan the repo's CLAUDE.md for rules that appear to be repo-agnostic. Good candidates for global promotion include:
- Workflow conventions (git, PR, issues)
- Code style rules that apply across all projects
- Security practices
- Error handling patterns
- Testing requirements
- Any rule that doesn't reference project-specific paths, commands, or technologies

### 3. Check for Duplicates Across Repos

If multiple repo CLAUDE.md files contain similar rules, that is a strong signal for promotion. Check sibling repos for overlapping instructions:
```bash
# Search for similar headings across repos
grep -r "## Rule Heading" ~/code/*/CLAUDE.md ~/code/*-repos/*/CLAUDE.md
```

### 4. Check Against Global

Before suggesting a promotion, verify the rule is not already covered in the global CLAUDE.md (`~/.claude/CLAUDE.md`). If a similar rule exists globally:
- Check if the repo version adds anything new
- If yes, suggest merging the additions into the global version
- If no, suggest removing the duplicate from the repo

### 5. Present Findings

For each candidate, present:

```
**Candidate: [Rule Title]**
- Source: [repo]/CLAUDE.md
- Type: Explicit (CANDIDATE:GLOBAL) | Implicit (repo-agnostic pattern)
- Already in global: Yes (partial) | No
- Recommendation: Promote | Merge | Skip (already covered)
- Content preview: [first 2-3 lines of the rule]
```

### 6. Take Action

For approved promotions:
1. Add the rule to `~/.claude/CLAUDE.md` in the appropriate section
2. Remove the rule from the repo's CLAUDE.md (or replace with a reference to global)
3. Remove the `CANDIDATE:GLOBAL` marker if present
4. Verify no project-specific references leaked into the global file

## Usage

```
/promote-rule                  # Scan current repo's CLAUDE.md
/promote-rule --all            # Scan all repos for candidates
/promote-rule --dry-run        # Show candidates without making changes
```
