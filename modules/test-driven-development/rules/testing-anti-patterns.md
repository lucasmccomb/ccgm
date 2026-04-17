# Testing Anti-Patterns

Five testing mistakes agents default to under pressure. Each has a **Gate Function** - a question to ask before writing the test. If the answer is wrong, stop and redesign the test.

This is a companion to the main TDD rule. The red-green-refactor cycle keeps you honest about *when* tests exist. These anti-patterns keep you honest about *what* the tests actually prove.

## 1. Testing Mock Behavior Instead of Real Behavior

The test asserts that a mock was called with certain arguments, not that the real system produced the correct result. When the mock's contract drifts from reality, the test keeps passing while production breaks.

**Gate Function:** "If I deleted the production code under test and replaced it with a stub that just calls the mock, would this test still pass?"

If yes, the test is asserting on the mock, not the behavior. Rewrite it to assert on outputs or observable side effects.

- Prefer integration-style tests that exercise the real collaborators when practical
- When mocking is necessary, assert on the *effect* of the system's behavior, not on the mock's call log
- A passing test that doesn't change when you break the production code is worse than no test

## 2. Test-Only Methods on Production Classes

A method like `_resetForTest()`, `setPrivateField()`, or an otherwise-unjustified public getter exists solely so the test can reach into internals. The production API is now shaped by the test harness.

**Gate Function:** "Would this method exist if I weren't testing?"

If no, the method does not belong on the production class. Options:
- Test the class through its real public API
- Extract the state you want to inspect into a collaborator with its own tested behavior
- Use a test double that exposes internals, not the production class itself

Test-only methods leak test concerns into production, invite misuse, and usually mean the test is coupled to implementation rather than behavior.

## 3. Mocking Without Understanding the Dependency

The agent mocks a library or service without reading its actual interface, then writes assertions that encode incorrect assumptions. The tests pass against the imagined API; production fails against the real one.

**Gate Function:** "Have I read the real dependency's interface, or am I guessing at it?"

Before mocking any dependency:
- Open the real source or docs. Note the actual return types, error shapes, and side effects
- Verify the mock matches - including edge cases (null, empty, failure modes)
- If the dependency is fast and deterministic, prefer using it directly over mocking

Never mock an API you haven't read. The mock is a model of your assumptions, and untested assumptions are the bug.

## 4. Incomplete Mocks

The mock returns only the two or three fields the test happens to assert on. Real responses contain more fields that production code reads, but the test never exercises those paths. Shipped code crashes on a missing property.

**Gate Function:** "If I ran this mock against the real consumer in production, would it satisfy every access the consumer makes?"

- Base mocks on real captured responses when possible (sample from a fixture, not memory)
- When hand-writing a mock, include all fields the production code touches, not only the ones the current test checks
- Prefer typed mocks (schema-validated) that fail loudly when incomplete

An incomplete mock creates a false signal: the test passes because the code never meets the rest of the response shape.

## 5. Tests as Afterthought

Tests are written after the feature "looks right" manually. They are shaped to match the code as written, not to express the behavior the code should have. A test written to match existing code proves only that the code matches itself.

**Gate Function:** "Did I watch this test fail before I wrote the code that makes it pass?"

If no, the test is not a test - it is a snapshot of current behavior, correct or not.

- Always RED first. If you skipped the failing run, delete the test and write it again
- A test that passed on the first run without a confirmed RED state is suspect; re-verify it actually constrains behavior by breaking the code and watching it fail
- Tests written after the fact miss the entire class of bugs the implementation *quietly* has

## Cross-Reference

- The main TDD rule (`test-driven-development.md`) covers when and how tests get written
- The code-quality rule covers broader testing expectations (coverage areas, error handling)
- Anti-pattern #5 (Tests as Afterthought) is the one the TDD cycle structurally prevents - if you are doing red-green-refactor honestly, you cannot fall into it
