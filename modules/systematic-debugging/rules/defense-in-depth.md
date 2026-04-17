# Defense-in-Depth Validation

Once root-cause-tracing has identified where a bad value originated, a single fix at that point is necessary but not sufficient. A single validation is a check a future refactor can remove. Layered validation makes the bug structurally impossible.

This is a companion to `systematic-debugging.md` and `root-cause-tracing.md`. Use it in Phase 4 (Implementation), after you have found the origin and are deciding where to put the fix.

## The Core Move

One validation is "we fixed this bug." Validation at every layer the bad value passed through is "we made this bug impossible." Each layer catches different cases - entry validation blocks bad input, business-logic validation blocks bad state, environment guards block dangerous context, and instrumentation captures anything the first three missed.

**The goal is not redundancy. It is independence.** Four layers each with one weakness catch more bugs than one layer with four weaknesses.

## The Four Layers

### Layer 1 - Entry Point Validation

Reject obviously invalid input at the API boundary. Empty strings, nulls, wrong types, missing required fields.

- Validate at the public entry point so callers see failures early
- Throw with a specific message that names the invalid value
- This layer catches most real-world bugs and prevents bad values from entering the system

### Layer 2 - Business Logic Validation

Within the operation, assert that the data makes sense for the specific action about to occur. Entry-level validation accepts any non-empty string; business-logic validation rejects a string that is syntactically valid but semantically wrong (a path that does not exist, a user without the required role, a state that forbids this transition).

- Use guard clauses at the top of the operation, not deep inside it
- Fail with context: what operation, what input, what invariant was violated
- This layer catches what entry validation cannot, because it depends on runtime state

### Layer 3 - Environment Guards

Forbid dangerous operations in the wrong context. Refuse to run destructive code outside a test sandbox. Refuse to write to production tables from a development build. Refuse to call a paid API without the expected feature flag.

- Gate the dangerous operation on an invariant about the environment, not the input
- Prefer "refuse unless proven safe" over "allow unless proven dangerous"
- This layer catches bugs that entry and business validation cannot see, because the bad context comes from the wrong machine, wrong process, or wrong mode

### Layer 4 - Debug Instrumentation

Structured logging immediately before the dangerous operation, capturing the value, the caller, the environment, and a stack trace. This layer does not prevent bugs; it makes the *next* bug fast to diagnose.

- Log enough context that a stack trace alone would identify the broken caller
- Use stderr or an unfiltered channel so the log survives when the operation fails
- Leave the instrumentation in for some period after the fix ships; remove it only when the code path has been stable

## How to Apply the Pattern

1. Trace the data flow from origin to failure point (see `root-cause-tracing.md`)
2. List every layer the bad value passed through
3. Add a layer-appropriate check at each boundary, not only the one closest to the symptom
4. Test that each layer fires independently by temporarily disabling the others

Four weak layers of independent validation catch more bugs than one strong layer.

## Anti-Patterns

- **Fixing only at the origin.** The fix is correct but fragile; a future code path can re-introduce the bad value without tripping any check.
- **Fixing only at the symptom.** The origin continues to produce bad values; the same class of bug reappears through different paths.
- **Duplicating the same validation at every layer.** Each layer should catch a different class of failure. If all four layers check "non-empty string," you have one layer, repeated.
- **Skipping instrumentation because "the fix is enough."** Future debugging will be slower without it, and the next bug in this area will have no leverage.
