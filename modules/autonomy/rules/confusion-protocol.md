# Confusion Protocol

**Iron Law:** WHEN CONFUSED AT AN ARCHITECTURAL FORK, STOP AND ASK. DO NOT GUESS.

Violating the letter of this rule is violating the spirit of this rule. Full autonomy means executing with confidence, not forking the codebase on a coin flip.

**Announce at start:** "I'm using the Confusion Protocol. Naming the ambiguity before proceeding."

## When This Fires

The protocol activates at **high-stakes ambiguity** only. Specifically, when one of four triggers is true:

1. **Two plausible architectures** - the task could be implemented multiple fundamentally different ways and the choice affects future work (schema shape, API contract, folder structure, dependency direction).
2. **Contradictory patterns in the codebase** - different parts of the repo do the same thing different ways and it is not obvious which is canonical.
3. **Unclear destructive scope** - you are about to delete, overwrite, migrate, or rewrite something and cannot determine whether the blast radius matches the user's intent.
4. **Missing context that would change the approach** - a config, credential, prior decision, or business constraint is unknown AND the answer would change which direction you take.

If none of the four triggers is true, **keep going**. The protocol is not an excuse to bail out of routine decisions.

## The Protocol

When a trigger fires:

1. **STOP.** Do not begin implementation. Do not "start with option A and see."
2. **Name the ambiguity in one sentence.** Be specific: "I'm confused about X because Y."
3. **Present 2-3 options with tradeoffs.** Each option gets a one-line description and a one-line tradeoff. No more.
4. **Ask the user which to pick.** Single question. Do not bundle unrelated asks.
5. **Wait for the answer.** Do not proceed with a "reasonable default" while waiting.

### Template

```
I'm confused about {specific thing} because {specific reason}.

Option A: {approach}. Tradeoff: {what you gain/lose}.
Option B: {approach}. Tradeoff: {what you gain/lose}.
Option C (optional): {approach}. Tradeoff: {what you gain/lose}.

Which do you want?
```

## Does NOT Apply To

The Confusion Protocol is for architectural forks, not routine coding. Do NOT invoke it for:

- Variable naming, file organization within an already-decided module, formatting choices
- Questions you can answer by reading the code or running a command
- "Which linter rule to follow" or similar mechanical decisions
- Anything the `autonomy.md` rule already tells you to just execute

When in doubt: if you could answer the question yourself by reading one more file or running one more command, do that instead of asking.

## Relationship to Completion Status Protocol

This rule pairs with the four-state Completion Status Protocol in `subagent-patterns.md` (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT).

- **Confusion Protocol** is invoked **during** a task to resolve ambiguity before writing code.
- **NEEDS_CONTEXT** is reported **at the end** of a task when the agent could not complete without more information.

If you hit a trigger mid-task and the user is unreachable (subagent context, no interactive user), return `NEEDS_CONTEXT` with the same one-sentence ambiguity statement and 2-3 options. The dispatcher then acts on your behalf.

## Rationalizations That Mean You Are About to Guess Instead of Ask

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I'll just pick the reasonable default" | At an architectural fork there is no reasonable default. The choice has downstream consequences the user cares about. |
| "I can always refactor later" | Refactors cost more than asking once. The user's time is cheaper than your rewrite. |
| "They probably want X" | "Probably" is a guess. One sentence to the user replaces an hour of wrong-direction work. |
| "I'll start with A and see if it works" | Starting commits you to A. Tests, patterns, and adjacent code will accrete around it. |
| "Asking will seem like I lack autonomy" | Autonomy is executing confidently, not guessing confidently. Naming ambiguity is senior behavior. |
| "I'll note the ambiguity in the PR description" | The PR is too late. The user reviews the result of a decision they never made. |

## Red Flags

Stop and invoke the protocol if you catch yourself:

- Writing code while still unsure which of two approaches you picked
- Saying "I'll go with X for now" without the user having seen the choice
- Discovering mid-implementation that a different approach would have been cleaner
- Realizing the user's intent could be read two ways and you picked one silently
- Deleting or overwriting files without confirming the scope matches the request
- Making a decision whose wrongness would require a follow-up PR to undo
