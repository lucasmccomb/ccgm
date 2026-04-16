# Test-Driven Development

**Iron Law:** NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.

Violating the letter of this rule is violating the spirit of this rule. If you did not watch the test fail, you do not know if it tests the right thing.

**Announce at start:** "I'm using the TDD discipline. Writing the failing test first."

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

## Rationalizations That Mean You Are About to Skip TDD

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "It's too simple to test" | Simple code has simple tests. Write them. |
| "I'll add tests after" | Tests written after the fact prove nothing about correctness. A test you did not watch fail may be passing for the wrong reason. |
| "I already tested it manually" | Manual testing does not prevent regressions. Tomorrow's refactor needs today's automated test. |
| "It's just a refactor" | Refactors without tests are hoping nothing breaks. If tests do not yet exist, they are a prerequisite of the refactor. |
| "This is a one-off script" | One-off code written without tests is code written without understanding. |
| "I'll mock the whole thing" | Heavy mocking tests the mock, not the code. |
| "The test doesn't really matter here" | If the test does not matter, the behavior does not matter. Delete the code instead. |
| "Tests are slow, I'll skip them this time" | "This time" is how every untested codebase was born. |

## Red Flags

Stop and write the test if you catch yourself:

- "One more implementation first, then tests"
- "Being pragmatic, not dogmatic"
- "I'll add coverage later in a follow-up PR"
- Reaching for production code before any test file exists
- Writing or modifying tests AFTER the feature code is already written
- Telling yourself the task is "too small" to bother
- Accepting a passing test you did not watch fail first
