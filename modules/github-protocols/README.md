# github-protocols

GitHub repository management protocols covering the full lifecycle: repository setup, issue-first planning, implementation workflow, PR conventions, label taxonomy, and code review standards.

## What This Module Does

Defines a comprehensive, opinionated workflow for managing GitHub repositories with Claude Code agents. Key aspects:

- **Repository setup**: Standard labels, repo settings, initial files, PR templates
- **Issue-first workflow**: Every piece of work starts with a GitHub issue
- **Planning protocol**: Plan mode for non-trivial work, epic/sub-issue structure
- **Implementation workflow**: Claim, branch, implement, test, commit, PR, merge
- **PR conventions**: One issue = one branch = one PR
- **Label taxonomy**: Status, priority, type, and agent labels
- **Human-agent issues**: Tasks requiring manual human intervention

## Files

| File | Type | Description |
|------|------|-------------|
| `rules/github-protocols.md` | rule | Instruction promotion system (CANDIDATE:GLOBAL markers) |
| `github-repo-protocols.md` | doc | Full GitHub repo lifecycle documentation |

## Dependencies

None.

## Manual Installation

```bash
# Copy the rule file
mkdir -p ~/.claude/rules
cp rules/github-protocols.md ~/.claude/rules/github-protocols.md

# Copy the protocols documentation
cp github-repo-protocols.md ~/.claude/github-repo-protocols.md
```

### Optional: Add to CLAUDE.md

Reference the protocols in your global CLAUDE.md:

```markdown
# GitHub Protocols

See `~/.claude/github-repo-protocols.md` for the full repository lifecycle protocol.
See `~/.claude/rules/github-protocols.md` for the instruction promotion system.
```
