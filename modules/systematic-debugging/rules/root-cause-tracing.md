# Root Cause Tracing

A concrete technique for Phase 1 and Phase 2 of the systematic-debugging methodology. When a bug surfaces deep in a call chain, do not fix where the error appears. Trace backward until you find the original trigger, then fix at the source.

This is a companion to `systematic-debugging.md`. That rule tells you to investigate before fixing. This rule tells you *how* to investigate when the symptom is far from the cause.

## The Core Move

Errors surface where broken invariants finally fail a check. The code that raises the exception is rarely the code that produced the bad value. Tracing means following the bad value backward up the call stack to the place it was first introduced.

**Never fix only where the error appears.** Fixing the symptom leaves the originating code free to produce the same bad value again, through a different path.

## When to Use This Technique

- The stack trace is long and the failure happens far from any user input
- The immediate cause is clear but the reason that cause occurred is not
- The same symptom keeps reappearing after previous fixes
- Instrumentation or logs show a bad value, but not where it came from
- You catch yourself about to wrap the failing operation in a try/catch

## The Tracing Process

1. **Observe the symptom.** Read the full error, including the exact value that caused it (empty string, null, wrong path, unexpected state).
2. **Find the immediate cause.** What line of code raised the error? What argument or state was wrong at that point?
3. **Walk one frame up.** What called this code? What value did the caller pass in?
4. **Repeat.** Keep walking until the bad value stops being passed in and starts being *produced*. That is the origin.
5. **Fix at the origin.** Correct the place that first produced the bad value, not every place that forwarded it.

If the call chain crosses module boundaries, instrument each boundary with structured logging (value, caller, timestamp) rather than guessing. A captured stack trace at the suspicious operation is usually enough to collapse the search.

## When Manual Tracing Stalls

If you cannot trace manually because the chain is asynchronous, event-driven, or dynamically dispatched:

- Log `new Error().stack` (or the language equivalent) at the suspicious operation so the full call path is captured at runtime
- Use `console.error` (or stderr) rather than a logger that may be suppressed in the failing context
- Log the actual value, the environment, and the call path together - one of them is the clue
- For test-pollution bugs ("something gets created that should not exist"), bisect the test suite: run subsets until the offending test is identified

The goal of instrumentation is to *discover* where the bad value originated, not to confirm a theory you already have.

## Pair With Defense-in-Depth

Finding the origin tells you where to fix. But a single fix at the origin can be bypassed by a new code path, a refactor, or a mock. Once the origin is identified and fixed, add validation at the other layers the value passed through. See `defense-in-depth.md`.

## Anti-Patterns

- **Fixing at the symptom and declaring victory.** The bug returns through a different path.
- **Adding a try/catch around the failing operation.** Swallowing the error hides the next occurrence and leaves the origin untouched.
- **Guessing upward without instrumentation.** If the chain is not obvious from reading, add logging before speculating.
- **Stopping at the first plausible-looking cause.** Keep asking "what called this?" until the bad value has no caller - only then are you at the origin.
