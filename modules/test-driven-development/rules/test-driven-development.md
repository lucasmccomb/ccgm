# Test-Driven Development

No production code without a failing test first. This is the core discipline - if you did not watch the test fail, you do not know if it tests the right thing.

## The Red-Green-Refactor Cycle

### 1. RED - Write a Failing Test

- Write the smallest test that demonstrates the desired behavior
- Run it and confirm it fails
- Confirm it fails for the RIGHT reason (not a syntax error or import issue)

### 2. GREEN - Make It Pass

- Write the simplest code that makes the test pass
- Do not add extra logic, optimization, or future-proofing
- The goal is a passing test, not elegant code

### 3. REFACTOR - Clean Up

- Improve the code while keeping all tests green
- Remove duplication, improve naming, extract functions
- Run tests after each refactoring step

### 4. Repeat

One behavior at a time. Do not batch multiple behaviors into a single cycle.

## Rules

### For New Features

1. Write a test for the first behavior
2. Make it pass
3. Write a test for the next behavior
4. Make it pass
5. Continue until the feature is complete

### For Bug Fixes

1. Write a test that reproduces the bug (it should fail)
2. Confirm it fails for the right reason
3. Fix the bug
4. Confirm the test passes
5. Confirm no other tests broke

### Test Quality

- **One behavior per test** - each test should verify one thing
- **Clear naming** - test name should describe the expected behavior, not the implementation
- **Use real code** - prefer real dependencies over mocks when practical
- **Test behavior, not implementation** - assert on outputs and side effects, not internal state

## When TDD Applies

- New features and functionality
- Bug fixes (reproduce first, then fix)
- Refactoring (tests exist before you change code)
- Complex business logic and utilities

## When to Ask Before Skipping

TDD may not be practical for:
- Exploratory prototypes the user plans to throw away
- Pure UI layout changes with no logic
- Configuration-only changes

If you think TDD does not apply to the current task, say so and get confirmation before writing code without tests.

## Common Rationalizations to Reject

- "It's too simple to test" - simple code has simple tests; write them
- "I'll add tests after" - tests written after implementation prove nothing about correctness
- "I already tested it manually" - manual testing does not prevent regressions
- "It's just a refactor" - refactors without tests are just hoping nothing breaks
