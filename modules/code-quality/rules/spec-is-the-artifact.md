# Spec Is the Artifact

The spec is the durable artifact. Code is regenerable output.

> "I actually don't even like the plan mode... You have to work with your agent to design a spec that is very detailed and maybe basically the docs and then get the agents to write them and you're in charge of the oversight."
> — Andrej Karpathy, Sequoia Capital, 2026-04-29

When agents can write code from a spec in minutes, the spec becomes more valuable than the code. The code can be deleted, regenerated, or rewritten. A good spec cannot — it encodes decisions, constraints, and intent that took time to discover.

## The Principle

Write the spec before the code. Review the spec before the code runs. When behavior diverges from spec, fix the spec first, then bring the code into alignment. The spec is the source of truth.

Code without a spec is behavior without intent. Behavior without intent drifts.

## Sizing Guidance

Not every task needs an xplan. Use judgment:

| Work | Spec overhead | What fits |
|------|--------------|-----------|
| Typo fix, one-line config change | None needed | Comment in commit message is enough |
| Single-PR feature, small refactor | One-page spec | Problem, deliverables, constraints, done-when |
| Multi-PR feature, architectural change | Full spec | Problem, deliverables, constraints, done-when, non-goals, open questions |
| New project, major system redesign | xplan | Full research + plan + reviews + execution phases |

The one-page spec for a single PR is not bureaucracy. It is the document you would write to explain the work in a PR description — written before the code, not after.

### One-Page Spec Structure

A spec does not need to be formal. It needs four things:

1. **Problem** — What is broken or missing? Why does it matter?
2. **Deliverables** — What will exist when this is done that did not exist before?
3. **Constraints** — What must not change? What approaches are off the table?
4. **Done-when** — How will we verify the work is complete?

That is the minimum. The rest is optional.

## Drift Protocol

When a deployed behavior diverges from its spec:

1. Update the spec to reflect the correct intended behavior
2. Then bring the code into alignment with the updated spec

Never silently update behavior without updating the spec. The spec is the record of why things work the way they do. A codebase whose behavior has drifted past its spec is a codebase that no future agent can reason about safely.

## When to Apply

- Starting a new feature, however small
- Starting a refactor that touches more than one file
- Starting any change where "done" is not self-evident from the task description

## When NOT to Apply

- Obvious one-line fixes (typo, missing semicolon, wrong constant value)
- Changes that are fully described by the failing test or error message
- Exploratory spikes the user explicitly plans to throw away

If in doubt, write the spec. A ten-line spec takes two minutes. Reworking a feature because the intent was unclear takes hours.

## Anti-Patterns

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I'll write the spec after I see what the code looks like" | A spec written to match code that already exists is a description, not a design. It cannot catch mistakes because the mistakes are already in the code it is describing. |
| "The PR description captures this" | PR descriptions are tied to the diff, not the behavior. They disappear into git history. A spec lives where the code lives and stays current. |
| "I'll just put this in a comment" | Comments describe what the code does at the line it appears on. They do not describe the problem, the constraints, or why the design tradeoffs were made. |
| "The agent will figure out the spec as it writes the code" | The agent writing both the spec and the code in one pass with no human review of the spec in between is vibe coding with extra steps. The spec review is the gate. Skip it and you have skipped the oversight Karpathy is describing. |
| "This is a small task, a spec is overkill" | A one-page spec for a single PR takes two minutes. The alternative is a follow-up PR explaining why the first one did the wrong thing. |

## Relationship to Neighboring Rules

**`xplan`** is the heavyweight variant of this principle. xplan runs research, planning, multi-agent review, and structured execution. Use xplan when the scope warrants it. Use a one-page spec for everything else. The principle is the same at every scale: spec first, code second, human reviews the spec before the code runs.

**`completeness.md`** defines a 10/10 rubric for done work. The 10/10 rubric assumes there is a target to be complete against. The spec is that target. Without a spec, "done" is undefined and the rubric cannot be applied.
