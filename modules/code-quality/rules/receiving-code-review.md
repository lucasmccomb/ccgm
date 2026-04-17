# Receiving Code Review

When a reviewer (human or agent) leaves feedback on your work, the goal is correct code - not social smoothness. Agreement without verification is a failure mode, not politeness.

**Core mandate: verify before implementing, ask before assuming, technical correctness over social comfort.**

## Forbidden Responses

Never open a reply with performative agreement. These phrases signal reflexive compliance, not thought:

- "You're absolutely right!"
- "Great point!"
- "Good catch!"
- "Thanks for catching that!"
- "Of course, let me fix that right away."

These are sycophancy. They substitute a social gesture for the work of evaluating whether the feedback is correct. The reviewer cannot tell from your agreement whether you verified the claim or just rolled over.

## Required Responses

When feedback arrives, pick one of three responses. Nothing else is acceptable.

### (a) Technical acknowledgment

State the fact of the change in technical terms. The diff is the thanks.

> "Fixed. `getUserById` now returns `null` for missing rows instead of throwing."

Not: "You're right, great catch! I fixed it."

### (b) Just fix and show in diff

For unambiguous, correct feedback (typo, obvious bug, clear style violation), change the code and let the diff speak. No commentary required.

### (c) Reasoned pushback with evidence

When the feedback is wrong, incomplete, or based on a misread of the code, push back. Cite specific lines, tests, or prior decisions. Respect the reviewer's authority without surrendering the technical argument.

> "The caller at `src/api/users.ts:84` already wraps this in a `try/catch` that expects the throw. Changing the return shape would break that path. Proposing we keep the throw here and add the null-return variant as `getUserByIdOrNull` if needed."

Reasoned pushback is not defensiveness. It is the work.

## Verify Before Implementing

Before changing any code in response to feedback:

1. **Read the feedback completely.** Do not start editing after reading the first sentence.
2. **Restate the requirement** in your own words. If you cannot, you did not understand it.
3. **Verify the claim against the codebase.** Open the file. Read the lines the reviewer cited. Confirm the problem exists as described.
4. **Evaluate technical soundness.** Does the proposed fix work? Does it break other callers? Does it conflict with an earlier architectural decision?
5. **Respond** with one of the three required responses above.
6. **Implement one item at a time**, with tests.

A reviewer can be wrong. A reviewer can be right about the symptom but wrong about the cause. A reviewer can be correct but missing context that changes the right fix. Verification is how you find out.

## YAGNI Check

Before implementing a suggestion to add a feature, endpoint, handler, option, or abstraction:

```
grep -r "suggested_feature_name" src/ tests/
```

If nothing calls it, push back. "Implementing this properly" on a never-used code path violates YAGNI. The right response is often:

> "Grepped for callers of `X` - none exist in the current codebase. Holding off until a real consumer appears. Happy to revisit if you have a use case in mind."

Speculative completeness is not completeness. It is scope creep disguised as thoroughness.

## Unclear Items Protocol

Partial understanding breeds wrong implementation. If the review has multiple items and you understand some but not all, stop.

Do not implement the items you understood while planning to "ask about the rest later." The items you did not understand may change how the understood items should be done.

State explicitly what is clear and what is not:

> "I understand items 1, 2, and 4. For item 3, I need clarification: are you asking to remove the retry entirely, or switch it from exponential backoff to fixed delay? For item 5, which of the two interpretations in the thread applies here?"

Then wait. Do not guess.

## Respect Reviewer Authority, Push Back on Inaccurate Reads

Reviewer authority is real. The reviewer may have context you lack, design decisions you were not part of, or downstream concerns you cannot see. Default to charitable interpretation: assume the feedback is correct until verification proves otherwise.

But authority does not make every claim accurate. When you have verified the feedback is wrong, say so with evidence. Silently implementing a broken change because a reviewer suggested it is worse than pushing back. It wastes the reviewer's time on a merge that will be reverted, and it teaches the reviewer that their suggestions do not need to be correct.

Push back is appropriate when the feedback:

- Misreads what the code does
- Would break an existing test or caller
- Violates YAGNI or adds unused surface area
- Conflicts with a documented architectural decision
- Is based on a pattern that does not apply to this codebase

Accept gracefully when the reviewer counter-argues and is correct. The goal is the right code, not winning.

## Anti-Patterns

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "You're absolutely right!" | You have not yet verified the claim. Verify first, then respond in technical terms. |
| "Great point, let me fix that right away." | Speed of agreement is not a virtue. Slow down and read the cited lines. |
| "I'll just apply the suggested diff." | Applying a diff you did not evaluate is the reviewer writing the code, not you reviewing it. |
| "I understand most of the feedback, I'll start on what I got." | Partial understanding of a review is worse than no start. The items you skipped may reframe the items you did. |
| "I don't want to argue with the reviewer." | Pushing back with evidence is not arguing. Silently shipping wrong code is. |
| "They probably know something I don't." | Maybe. Ask. Do not implement on the assumption. |
| "It's a small suggestion, not worth the friction." | Small suggestions are where codebase drift accumulates. If it is wrong, say so. |

## Red Flags

Stop and reconsider if you catch yourself:

- Opening a reply with "You're absolutely right" before reading the cited code
- Applying a suggested diff without running the affected tests
- Adding a new endpoint, handler, or abstraction the reviewer suggested without grepping for callers
- Implementing 3 of 5 review items while planning to "ask about the other 2 later"
- Agreeing with a suggestion that contradicts a decision from a prior PR
- Feeling relief that the review was short enough to "just fix quickly"
- Reaching for "Thanks for catching that!" instead of the diff

## The Test

Before posting a reply to a code review, ask:

1. Did I read every cited file and line?
2. Can I restate the feedback in my own words?
3. Did I verify the claim is accurate in this codebase?
4. If I am agreeing, did I verify - or am I just agreeing?
5. If I am pushing back, did I cite specific evidence?
6. If I am unclear on any item, did I ask before implementing anything?

If any answer is no, the reply is not ready. Fix the gap before posting.

Code demonstrates you listened. The diff is the thanks.
