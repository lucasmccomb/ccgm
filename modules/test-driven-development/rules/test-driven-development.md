# Test-Driven Development

No production code without a failing test first. If you did not watch the test fail, you do not know whether it tests the right thing.

## The Cycle

1. **Red.** Write the smallest test that demonstrates the desired behavior. Run it and confirm it fails for the right reason, not a syntax or import error.
2. **Green.** Write the simplest code that makes it pass. No extra logic, optimization, or future-proofing.
3. **Refactor.** Improve the code while keeping the tests green: remove duplication, improve naming, extract functions.
4. Repeat, one behavior per cycle.

For new features, cycle through behaviors one at a time until the feature is complete. For bug fixes, write a test that reproduces the bug, confirm it fails for the right reason, fix, confirm it passes, and confirm the rest of the suite still passes.

## Test Quality

One behavior per test. Name the test for the expected behavior, not the implementation. Prefer real dependencies over mocks when practical; heavy mocking tests the mock. Assert on outputs and side effects, not internal state.

## When TDD Applies

New features, bug fixes, refactoring (tests must exist before the change), and complex business logic. It may not be practical for exploratory prototypes the user plans to throw away, pure UI layout changes with no logic, or configuration-only changes. If TDD does not seem to apply, say so and get confirmation before writing code without tests.

A test written after the code, or one that passed on its first run without a confirmed red state, proves only that the code matches itself; delete it and write it again. "Too simple to test," "I'll add tests after," "I tested it manually," and "it's just a refactor" are the usual routes to an untested codebase.
