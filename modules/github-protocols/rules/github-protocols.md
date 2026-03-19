# Maintaining Instructions

## Promoting Repo Rules to Global

When reviewing or editing a repo's `CLAUDE.md`, look for instructions marked with:

```
<!-- CANDIDATE:GLOBAL - [reason] -->
```

If you see this marker, suggest promoting the rule to the global `~/.claude/CLAUDE.md` file.

## Suggesting Promotions

When you notice a pattern that appears in multiple repo CLAUDE.md files, or when adding a new instruction to a repo that seems universally applicable, proactively ask:

> "This rule seems repo-agnostic. Should I add it to your global `~/.claude/CLAUDE.md` instead?"

Candidates for global promotion:
- Workflow conventions (git, PR, issues)
- Code style rules that apply across all projects
- Security practices
- Error handling patterns
- Testing requirements
- Any rule that does not reference project-specific paths, commands, or technologies

## When NOT to Promote

Keep rules in the repo's CLAUDE.md when they:
- Reference specific file paths, directories, or project structure
- Use project-specific commands or scripts
- Apply only to a particular tech stack used by that project
- Override global rules for a specific reason documented in the repo
