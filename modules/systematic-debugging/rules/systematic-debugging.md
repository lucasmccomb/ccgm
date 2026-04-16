# Systematic Debugging

**Iron Law:** NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.

Violating the letter of this rule is violating the spirit of this rule. Random fix attempts are a failure mode - they waste time and often introduce new bugs.

**Announce at start:** "I'm using the systematic-debugging discipline. Investigating root cause before proposing a fix."

## Phase 1: Root Cause Investigation

Before proposing any fix:

1. **Read the error carefully** - full stack trace, error message, exit code
2. **Reproduce consistently** - confirm the failure happens reliably and identify the exact trigger
3. **Examine recent changes** - what changed since it last worked? (`git log`, `git diff`)
4. **Add instrumentation** - for multi-component systems, add logging at each boundary to isolate where the failure occurs

Do NOT skip this phase. Do NOT guess at the root cause.

## Phase 2: Pattern Analysis

1. **Find a working example** - locate similar code that works correctly
2. **Compare systematically** - diff the working version against the broken one
3. **Identify all differences** - not just the obvious ones
4. **Understand dependencies** - trace the full call chain, check configs, environment

## Phase 3: Hypothesis and Testing

1. **Form a specific hypothesis** - "The failure occurs because X, and changing Y should fix it"
2. **Test with minimal change** - one change at a time, never multiple simultaneous fixes
3. **Verify the result** - confirm the fix works AND nothing else broke
4. **If it fails, return to Phase 1** - do not stack fixes on top of each other

## Phase 4: Implementation

1. **Write a failing test** that reproduces the bug (when possible)
2. **Implement the single fix** addressing the root cause
3. **Verify the test passes** and all existing tests still pass
4. **Document the root cause** in the commit message
5. **Extract the pattern** - If the bug took more than 2 attempts to diagnose, or if the root cause was surprising, write the pattern to a feedback memory file. Focus on what would help identify this class of bug faster next time.

## Rationalizations That Mean You Are About to Skip Root-Cause Investigation

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "I think I know what it is, let me just try X" | If you knew, you would not be guessing. Investigate first. |
| "One more fix attempt" | The previous two did not work. This one probably will not either. Stop guessing and read the code. |
| "While I'm here, let me also..." | Unrelated changes hide the signal when the fix fails. Stay focused. |
| "The error message is misleading" | Often true, but it is the first evidence. Trace it before dismissing it. |
| "It works on my machine" | Then the machine is part of the bug. Identify the delta. |
| "Let me just add a try/catch" | Swallowing the error does not fix it; it hides the next failure. |
| "This is probably a flaky test" | Sometimes true. Run it 20 times before believing it. Flake is itself a bug. |

## Red Flags

Stop and reassess if you catch yourself:

- Proposing a fix before understanding why the bug exists
- Making multiple changes at once ("while I'm here...")
- Assuming you know the cause without evidence
- Trying the same approach a second time expecting different results
- "One more fix attempt" - you have exhausted your budget; it is time to question assumptions
- Adding logging only to confirm what you already believe, not to discover something new
- Reaching for `try/catch` to make the symptom disappear

## Three-Strike Rule

After three failed fix attempts on the same issue, stop fixing and start questioning:

- Is the architecture itself the problem?
- Am I debugging the wrong layer?
- Do I need to re-read the docs or source code for the system involved?

Escalate to the user if the root cause remains unclear after three attempts.

After resolving a three-strike situation (whether by finding the root cause or escalating), capture the debugging pattern to memory:
- What was the misleading assumption?
- What was the actual root cause?
- What diagnostic step would have found it faster?

This prevents repeating the same debugging dead-ends in future sessions.
