# Receiving Code Review

When a reviewer, human or agent, leaves feedback, the goal is correct code, not social smoothness. Verify before implementing, ask before assuming, technical correctness over social comfort.

Do not open a reply with performative agreement ("You're absolutely right!", "Great point!", "Good catch!", "Thanks for catching that!"). Those phrases substitute a gesture for evaluating whether the feedback is correct, and the reviewer cannot tell whether you verified the claim or rolled over.

## The Three Responses

- **Technical acknowledgment.** State the change in technical terms: "Fixed. `getUserById` now returns `null` for missing rows instead of throwing."
- **Fix and show the diff.** For unambiguous, correct feedback (typo, obvious bug, clear style violation), change the code and let the diff speak.
- **Reasoned pushback with evidence.** When the feedback is wrong, incomplete, or based on a misread, say so with cited lines, tests, or prior decisions: "The caller at `src/api/users.ts:84` already wraps this in a `try/catch` that expects the throw. Changing the return shape would break that path."

## Verify Before Implementing

1. Read the feedback completely.
2. Restate the requirement in your own words; if you cannot, you did not understand it.
3. Open the cited file and lines and confirm the problem exists as described.
4. Evaluate the proposed fix: does it work, does it break other callers, does it conflict with an earlier architectural decision?
5. Respond with one of the three responses, then implement one item at a time, with tests.

A reviewer can be wrong, right about the symptom but wrong about the cause, or correct but missing context that changes the right fix.

## YAGNI Check

Before adding a feature, endpoint, handler, option, or abstraction a reviewer suggested, grep for callers. If nothing calls it, push back: "Grepped for callers of `X`; none exist. Holding off until a real consumer appears."

## Unclear Items

If a review has several items and you understand only some, do not implement the ones you understood while planning to ask about the rest; the unclear items may change how the clear ones should be done. State which items are clear, ask about the others, and wait.

## Authority and Accuracy

Reviewer authority is real: they may have context, design decisions, or downstream concerns you cannot see, so assume the feedback is correct until verification proves otherwise. Authority does not make every claim accurate. Push back, with evidence, when feedback misreads the code, would break an existing test or caller, violates YAGNI, conflicts with a documented architectural decision, or applies a pattern that does not fit this codebase. Accept gracefully when the counter-argument is correct. The diff is the thanks.
