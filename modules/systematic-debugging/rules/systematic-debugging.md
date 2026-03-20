# Systematic Debugging

No fixes without root cause investigation first. Random fix attempts are failure mode - they waste time and often introduce new bugs.

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

## Red Flags

Stop and reassess if you catch yourself:

- Proposing a fix before understanding why the bug exists
- Making multiple changes at once ("while I'm here...")
- Assuming you know the cause without evidence
- Trying the same approach a second time expecting different results

## Three-Strike Rule

After three failed fix attempts on the same issue, stop fixing and start questioning:

- Is the architecture itself the problem?
- Am I debugging the wrong layer?
- Do I need to re-read the docs or source code for the system involved?

Escalate to the user if the root cause remains unclear after three attempts.
