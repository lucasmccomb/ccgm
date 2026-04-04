# Ideation

Structured ideation framework that interviews you to refine a loose, half-formed idea into a concrete, actionable concept.

## `/ideate [idea] [--resume]`

Takes whatever you have - a sentence, a word, a half-baked concept - and runs a structured interview to reach 95% clarity across 7 dimensions: problem, audience, solution, scope, differentiation, feasibility, and motivation.

**What it does:**
- Interviews you conversationally (not a survey - follows your energy, challenges assumptions, offers concrete examples)
- Tracks confidence across all dimensions, looping until 95% clarity
- Produces a Concept Brief (one-liner, problem, audience, solution, scope, differentiation)
- Can delegate to `/deepresearch` for market validation mid-interview
- Can hand off to `/xplan` for full execution planning once the idea is locked

**Usage:**
```
/ideate "I want to build an app that helps people track habits"
/ideate "some kind of AI tool for real estate"
/ideate                                          # Asks what you're thinking about
/ideate --resume                                 # Resume a saved ideation session
```

Sessions are saved to `~/.claude/ideation/` and can be resumed later.

## Manual Installation

```bash
mkdir -p ~/.claude/skills/ideate
cp skills/ideate/SKILL.md ~/.claude/skills/ideate/SKILL.md
```
