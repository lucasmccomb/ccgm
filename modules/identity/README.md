# Identity & Context Module

Two foundational context files that give Claude Code a persistent identity layer, surviving across sessions and context resets.

## Files

| File | Purpose |
|------|---------|
| `soul.md` | Defines the AI's personality, philosophy, reasoning principles, communication style, and boundaries |
| `human-context.md` | Defines who you are - your background, goals, domain expertise, working style, and life intentions |

## Why Two Files?

These serve fundamentally different purposes and evolve independently:

- **soul.md** answers "who is this AI?" - how it should think, communicate, and behave
- **human-context.md** answers "who is this human?" - what they know, what they're building, where they're going

Together they transform generic AI sessions into a working relationship with a consistent, aligned collaborator.

## How It Works

Both files are installed as global rules (`~/.claude/rules/`), which means they're automatically loaded in every Claude Code session. No manual steps needed.

If the `startup-dashboard` module is also installed, `/startup` will surface this context at session start.

## Customization

After installation, edit both files to match your preferences and identity:

```bash
# Edit your AI's personality
$EDITOR ~/.claude/rules/soul.md

# Edit your personal context
$EDITOR ~/.claude/rules/human-context.md
```

### Design Principles

Based on community research and best practices:

1. **Concision beats comprehensiveness** - 1-3 pages per file outperforms longer dumps
2. **Declarative values beat procedural rules** - "I value simplicity" works better than "never use complex abstractions"
3. **High-signal anchors** - a few strong statements outperform exhaustive lists
4. **Stable identity, not current tasks** - these files capture who you are, not what you're doing today (that's what the memory system handles)
5. **Onboarding doc mental model** - write it like you're briefing a brilliant new colleague, not configuring a settings file

## Relationship to Other Systems

| System | Purpose | How identity files relate |
|--------|---------|--------------------------|
| `CLAUDE.md` | Operational rules and procedures | soul.md provides the philosophical foundation; human-context.md provides the user grounding |
| Memory system | Learned facts, feedback, project state | human-context.md is stable identity; memory captures evolving details |
| Rule files | Specific behavioral rules | soul.md provides values that inform why rules exist |

## Manual Installation

If not using the CCGM installer:

```bash
# Copy template files to your Claude Code rules directory
cp rules/soul.md ~/.claude/rules/soul.md
cp rules/human-context.md ~/.claude/rules/human-context.md

# Edit with your content
$EDITOR ~/.claude/rules/soul.md
$EDITOR ~/.claude/rules/human-context.md
```
