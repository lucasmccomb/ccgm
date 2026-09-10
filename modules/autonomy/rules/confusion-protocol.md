# Confusion Protocol

At an architectural fork, stop and ask. Do not guess. Full autonomy means executing with confidence, not forking the codebase on a coin flip.

## When This Fires

Only at high-stakes ambiguity, when one of four triggers is true:

1. **Two plausible architectures.** The task could be implemented in fundamentally different ways and the choice affects future work: schema shape, API contract, folder structure, dependency direction.
2. **Contradictory patterns in the codebase.** Different parts of the repo do the same thing different ways and it is not obvious which is canonical.
3. **Unclear destructive scope.** About to delete, overwrite, migrate, or rewrite something without knowing whether the blast radius matches the user's intent.
4. **Missing context that would change the approach.** A config, credential, prior decision, or business constraint is unknown and the answer would change direction.

If none of the four is true, keep going.

## The Protocol

1. Stop. Do not begin implementation or "start with option A and see."
2. Name the ambiguity in one sentence: "I'm confused about X because Y."
3. Present 2 or 3 options, each with a one-line description and a one-line tradeoff.
4. Ask which to pick. One question, no unrelated asks bundled in.
5. Wait for the answer. Do not proceed on a "reasonable default" meanwhile.

```
I'm confused about {specific thing} because {specific reason}.

Option A: {approach}. Tradeoff: {what you gain/lose}.
Option B: {approach}. Tradeoff: {what you gain/lose}.
Option C (optional): {approach}. Tradeoff: {what you gain/lose}.

Which do you want?
```

## Does Not Apply To

Variable naming, file organization inside an already-decided module, formatting, which linter rule to follow, or anything answerable by reading one more file or running one more command. Do that instead of asking.

## Relationship to the Completion Status Protocol

This protocol resolves ambiguity during a task. `NEEDS_CONTEXT` (see `subagent-patterns.md`) reports it at the end of a task when the agent could not finish without more information. A subagent that hits a trigger with no user to ask returns `NEEDS_CONTEXT` with the same one-sentence ambiguity statement and 2 or 3 options, and the dispatcher decides.
