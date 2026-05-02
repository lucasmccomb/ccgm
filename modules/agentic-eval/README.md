# agentic-eval

Rubric for evaluating agentic engineering work using the Twitter-clone-for-agents interview format.

Karpathy described the format in the Sequoia interview (April 2026):
> "Hiring has to look like... write a Twitter clone for agents... make it really good, make it really secure... I'm going to use 10 codecs... to try to break your website. They should not be able to break it."

The rubric captures that format as a self-evaluable, repeatable standard. It is useful for:
- Portfolio self-evaluation before a job search
- Agentic engineering interviews where the interviewer needs a consistent rubric
- Auditing whether a system you already built is truly agent-native

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `rules/agentic-eval-rubric.md` | `~/.claude/rules/agentic-eval-rubric.md` | Full rubric: reference surface spec, evaluation procedure, pass criteria, and scoring |

## Manual Installation

```bash
# From the CCGM repo root:
mkdir -p ~/.claude/rules
cp modules/agentic-eval/rules/agentic-eval-rubric.md ~/.claude/rules/agentic-eval-rubric.md
```

## Dependencies

- `agent-native` - the four principles (parity, granularity, composability, emergent capability) that the candidate surface must satisfy and that the red-team agents probe
- `subagent-patterns` - the parallel dispatch model used to run N red-team agents simultaneously against the surface

## Skill

A `/agentic-eval` skill that runs the rubric end-to-end against a deployed surface is a planned follow-up. The rubric document is useful as a self-eval and interview standard on its own.

When the skill ships, it will accept a surface URL or repository path and dispatch red-team agents per the parallel dispatch model in `subagent-patterns`.

## Usage (without the skill)

1. Read `rules/agentic-eval-rubric.md` to understand the minimum surface spec.
2. Build or audit a system against that spec.
3. Dispatch N red-team agents manually (see `subagent-patterns` for dispatch instructions) or evaluate the criteria manually.
4. Score against the pass criteria table in the rubric.
