# Completeness Principle: Boil the Lake

When doing it fully costs minutes and doing it partially costs a follow-up PR, do it fully. For each solution, ask whether there is a meaningful delta between "the whole job" and "what I was about to ship." If the delta is small, close it now.

Agent-assisted development compresses the cost of completeness. Edge cases, tests, docs, validation, and error states each take minutes, so "ship the happy path and backlog the edges" is no longer a reasonable default. The follow-up PR rarely happens; the deferred edge cases are the bugs users report.

## Completeness Rubric

| Score | Meaning |
|-------|---------|
| 10 | All edge cases handled, tests cover new behavior, docs updated, error paths explicit. Nothing left for a follow-up. |
| 8-9 | Happy path, known edge cases, tests. Minor polish deferred with explicit notes. |
| 7 | Happy path works, tests exist, obvious edges handled. Non-obvious edges may slip. |
| 5-6 | Happy path works. Tests partial or missing. Edge cases deferred. Follow-up PR required. |
| 3-4 | Works for the demo case. Significant work deferred. |
| 1-2 | Sketch or proof of concept. |

- Before reporting a task done, rate the work. Below 8, either finish the job or state explicitly what is deferred and why.
- When presenting options, include the score so the tradeoff is explicit: "Option A: 10/10" versus "Option B: 7/10, ships in half the time" is a real choice; "which do you prefer?" without scores is not.
- Reviewing your own diff at a 6, push the score up before asking for review.

## Boundaries

Completeness governs the depth of the job, not the breadth of the design. Finish every case the current requirements imply; do not add speculative features, handle hypothetical edge cases that cannot occur, refactor unrelated code, or build for requirements that do not exist yet. The simplest implementation that fully meets the current requirements, finished completely, is a 10. An extra abstraction nothing uses does not raise the score. See `code-quality.md`, "Simplest Implementation That Fully Meets the Requirements."

## The Test

Before claiming a task is complete:

1. Are there edge cases I know about but did not handle?
2. Is there a test I know I should write but decided to skip?
3. Is there a doc or comment I know is now stale?
4. Did I leave a TODO in the code or a "will do later" in the PR body?

Any yes means the work is not complete. Finish it now or state what is deferred and why.
