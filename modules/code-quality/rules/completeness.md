# Completeness Principle: Boil the Lake

When the cost of doing it fully is minutes and the cost of doing it partially is a follow-up PR, do it fully. Default to the complete implementation, not the 90% shortcut.

**For each solution, ask: is there a meaningful delta between "the whole job" and "what I was about to ship?" If the delta is small, close it now.**

## Why This Matters

Agent-assisted development compresses the cost of completeness. Work that used to take a team hours or days now takes minutes of agent time. The old tradeoffs - "ship the happy path, backlog the edges" - were rational when completeness was expensive. They are not rational when it is not.

The result of the old tradeoffs is a codebase full of TODO comments, skipped tests, unhandled edge cases, and "we'll fix it in a follow-up" debt. A codebase that feels accidental. The alternative is shipping the whole thing the first time.

## Effort Compression Table

| Task | Traditional team | Agent-assisted |
|------|-----------------|----------------|
| Write the happy path | hours | minutes |
| Cover edge cases | hours-days | minutes |
| Add tests for new code | hours | minutes |
| Update related docs | hours | minutes |
| Add input validation | hours | minutes |
| Handle error states in UI | hours | minutes |

When the agent-assisted column shows minutes, "defer to a follow-up" is no longer a reasonable default. It is procrastination with a name tag on.

## Completeness Rubric

When presenting options or evaluating your own work, score completeness on a 1-10 scale:

| Score | Meaning |
|-------|---------|
| **10** | All edge cases handled, tests cover new behavior, docs updated, error paths explicit. Nothing left for a follow-up. |
| **8-9** | Happy path + known edge cases + tests. Minor polish deferred with explicit notes. |
| **7** | Happy path works, tests exist, obvious edges handled. Non-obvious edges may slip. |
| **5-6** | Happy path works. Tests partial or missing. Edge cases deferred. Follow-up PR required. |
| **3-4** | Works for the demo case. Significant work deferred to one or more follow-ups. |
| **1-2** | Sketch or proof of concept. Most work still ahead. |

### How to Use It

- **Before reporting a task as done**: rate your work. If the score is below 8, either finish the job or explicitly flag what is deferred and why.
- **When presenting options to the user**: include the completeness score so the tradeoff is explicit. "Option A: Completeness 10/10" vs "Option B: Completeness 7/10, ships in half the time" is a real choice the user can make. "Which option do you prefer?" without scores is a judgment call dressed as a question.
- **On PRs**: if reviewing your own diff and noticing a 6, push the score up before asking for review. Do not outsource completeness to the reviewer.

## Anti-Patterns

These are the rationalizations that precede shipping incomplete work. Recognize and reject them.

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I'll add tests in a follow-up PR" | The follow-up PR rarely happens. Write the tests now. |
| "The happy path is done, edge cases can wait" | The edge cases are the bugs your users will report. Finish them now. |
| "This is good enough for v1" | V1 ships to production. "Good enough" becomes "how it works." |
| "The follow-up issue captures the rest" | Issues in the backlog are wishes, not commitments. Finish what is in front of you. |
| "I don't want to scope-creep this PR" | Completing the feature you are already building is not scope creep. It is the scope. |
| "Let me just ship the shortcut, it's done" | "Done" means complete. If it is a shortcut, it is not done. |
| "The edge case is unlikely" | Unlikely edge cases in code you wrote today are certain bugs in production next month. |

## Boundaries

Completeness is not gold-plating. Do not:

- Add speculative features the task did not call for
- Handle hypothetical edge cases that cannot actually occur
- Refactor unrelated code while you are in there
- Over-engineer for requirements that do not exist yet

The rule is: **finish the job you are on**, not "expand the job to touch every file you can reach." If the task is "add input validation to the login form," finish it to 10/10 (all inputs, all error paths, tests, a11y). Do not also rewrite the auth middleware because it looked rough.

## The Test

Before claiming a task is complete, ask:

1. Are there edge cases I know about but did not handle?
2. Is there a test I know I should write but decided to skip?
3. Is there a doc or comment I know is now stale?
4. Did I leave a TODO in the code or a "will do later" in the PR body?

If any answer is yes, the work is not complete. Either finish it now or state explicitly what is deferred and why.

Completeness compounds. Every PR that ships at 10/10 makes the codebase feel more intentional. Every PR that ships at 6/10 adds a paper cut the next agent has to step around.
