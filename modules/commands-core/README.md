# commands-core

Essential slash commands for everyday git and GitHub workflows.

## What This Module Does

Provides five foundational commands that cover the most common development operations:

- **/commit** - Stage and commit changes with conventional format
- **/pr** - Push branch and create a pull request that closes an issue
- **/cpm** - One-shot commit + PR + merge workflow for solo developers
- **/gs** - Show git status and project overview
- **/ghi** - Create a GitHub issue with proper labels

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/commit.md` | command | Stage all changes and commit with conventional format |
| `commands/pr.md` | command | Push branch and create PR closing an issue |
| `commands/cpm.md` | command | Commit, create PR, and merge in one shot |
| `commands/gs.md` | command | Git status dashboard with project info |
| `commands/ghi.md` | command | Create GitHub issue with labels |

## Dependencies

None.

## Manual Installation

Copy command files to your Claude Code commands directory:

```bash
# Create commands directory if it does not exist
mkdir -p ~/.claude/commands

# Copy each command
cp commands/commit.md ~/.claude/commands/commit.md
cp commands/pr.md ~/.claude/commands/pr.md
cp commands/cpm.md ~/.claude/commands/cpm.md
cp commands/gs.md ~/.claude/commands/gs.md
cp commands/ghi.md ~/.claude/commands/ghi.md
```

After copying, the commands are available as `/commit`, `/pr`, `/cpm`, `/gs`, and `/ghi` in Claude Code.
