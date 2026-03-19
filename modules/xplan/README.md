# xplan

Deep research + planning + execution framework for new projects. Spawns parallel research agents, creates comprehensive plans with review, walks the user through interactively, and executes via parallel agent waves.

## What This Module Does

xplan is a comprehensive 8-phase framework for taking a project idea from concept to working code:

1. **Parse Input & Setup** - Create plan directory, check templates, analyze existing repos
2. **Deep Research** - Spawn 4-7 parallel research agents covering domain, technical, competitive, UX, data, and business facets
3. **Naming Ideation** - (Optional) Brainstorm names with domain availability checks
4. **Plan Review** - Spawn security, architecture, and business logic review agents
5. **Write Plan** - Comprehensive plan.md with epics, waves, and execution strategy
6. **Walkthrough** - Interactive section-by-section walkthrough with the user (mandatory)
7. **Execution** - Create repo, issues, and spawn parallel agents per wave
8. **Verification & Retrospective** - Full audit, retro, optional template generation

Companion commands:
- **/xplan-status** - Check progress on a running or completed plan
- **/xplan-resume** - Resume an interrupted plan execution from its last checkpoint

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/xplan.md` | command | Main planning and execution command (/xplan) |
| `commands/xplan-status.md` | command | Plan progress dashboard (/xplan-status) |
| `commands/xplan-resume.md` | command | Resume interrupted execution (/xplan-resume) |

## Dependencies

- **multi-agent**: Required for parallel agent execution during research, review, and implementation phases

## Manual Installation

```bash
# Copy command files
mkdir -p ~/.claude/commands
cp commands/xplan.md ~/.claude/commands/xplan.md
cp commands/xplan-status.md ~/.claude/commands/xplan-status.md
cp commands/xplan-resume.md ~/.claude/commands/xplan-resume.md
```

### Plans Directory

xplan creates plan directories under `~/code/plans/`. Create this directory if it does not exist:

```bash
mkdir -p ~/code/plans
```

Optional: Create a templates directory for reusable plan patterns:

```bash
mkdir -p ~/code/plans/_templates
```

After installation, invoke with `/xplan <project concept or idea>` or `/xplan <idea> --repo <existing-repo-path>`.
