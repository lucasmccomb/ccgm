# Systematic Debugging

No fixes without root-cause investigation first. Random fix attempts waste time and introduce new bugs. When the user asks to fix a bug, debug a failure, or trace an error, invoke `/debug`, which runs this discipline on a deep-reasoning model; skip it only for a diagnostic question with no fix, a code explanation, or a one-line fix whose cause the error message states outright.

## Phase 1: Root Cause

1. Read the error carefully: full stack trace, message, exit code.
2. Reproduce consistently and identify the exact trigger.
3. Examine what changed since it last worked (`git log`, `git diff`).
4. For multi-component systems, add logging at each boundary to isolate where the failure occurs.

## Phase 2: Pattern Analysis

Find a working example of similar code, diff it against the broken version, list every difference, and trace the full call chain, configs, and environment.

## Phase 3: Hypothesis

Form one specific hypothesis ("the failure occurs because X; changing Y should fix it"), test it with one minimal change, and verify the fix works and nothing else broke. If it fails, return to Phase 1; do not stack fixes.

## Phase 4: Implementation

Write a failing test that reproduces the bug where possible, implement the single fix at the root cause, confirm the test and the existing suite pass, and document the root cause in the commit message. If the diagnosis took more than two attempts or the cause was surprising, record the pattern (see `self-improving.md`).

## Three-Strike Rule

After three failed fix attempts on the same issue, stop fixing and question the frame: is the architecture the problem, is this the wrong layer, does the source or documentation need re-reading. Escalate to the user if the root cause is still unclear, and afterward capture the misleading assumption, the actual cause, and the diagnostic that would have found it faster.

"I think I know what it is, let me try X," "one more fix attempt," "while I'm here," "the error message is misleading," "this is probably a flaky test," and "let me add a try/catch" each mean the investigation is being skipped. The `debugging-techniques` skill covers tracing a bad value to its origin, defense-in-depth validation, and how to read a model that seems to resist.
