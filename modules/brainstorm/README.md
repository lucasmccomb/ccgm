# Brainstorm

Design-before-implementation gate. Forbids code, scaffolding, or implementation until a design spec has been written and the user has explicitly approved it.

## `/brainstorm [topic] [--from-concept {path}] [--resume]`

Enforces the spec-before-plan-before-code discipline. Explores context, proposes 2-3 genuinely distinct approaches with tradeoffs, writes a design spec, self-reviews for TBDs and contradictions, then waits for explicit user approval before any implementation work.

**What it does:**
- Hard gate: no code, scaffolding, or implementation commands until the spec is approved
- Explores the affected code area with read-only tools (Glob/Grep/Read, no edits)
- Asks context questions one at a time (not a survey)
- Proposes 2-3 concrete approaches with honest tradeoffs, recommends one, lets the user pick
- Writes a design spec to `docs/brainstorm-notes/YYYY-MM-DD-{topic}/design.md`
- Self-reviews the spec for TBDs, contradictions, vague tradeoffs, and missing sections
- Waits for explicit user approval via AskUserQuestion
- Hands off to `/xplan` for execution planning, or allows direct implementation for small changes

**Usage:**

```
/brainstorm "add a rate limiter to the API gateway"
/brainstorm "migrate auth from Supabase to Clerk"
/brainstorm                                    # Asks what you want to design
/brainstorm --from-concept {path}              # Start from an /ideate concept brief
/brainstorm --resume                           # Resume an in-progress design session
```

## How it fits with /ideate and /xplan

| Command | Input | Output | Question answered |
|---------|-------|--------|--------------------|
| `/ideate` | Loose idea, fuzzy concept | Concept Brief (problem, audience, solution) | What are we building? |
| `/brainstorm` | Approved concept or concrete problem | Design Spec (approach, interfaces, tradeoffs) | How are we building it? |
| `/xplan` | Approved design spec | Execution Plan (phases, tasks, files) | What are the concrete steps? |

`/brainstorm` can run standalone when the problem is already well-defined - you do not need `/ideate` first.

## Manual Installation

```bash
mkdir -p ~/.claude/skills/brainstorm
cp skills/brainstorm/SKILL.md ~/.claude/skills/brainstorm/SKILL.md
```
