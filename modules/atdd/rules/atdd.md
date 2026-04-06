# Agentic Test-Driven Development (ATDD)

## Methodology

ATDD uses E2E vision specs as the source of truth for feature behavior. Specs are written first (describing what the app SHOULD do), then agents build the app to match. This inverts the typical workflow: instead of writing code and then testing it, the tests define the target and the code is built to satisfy them.

## The ATDD Contract

1. **Specs are immutable** - Never modify test files during an ATDD run. If a spec seems wrong, flag it and move on - do not "fix" the spec to match current behavior.
2. **Mocks are the API contract** - Test fixtures mock API responses. These mock shapes ARE the expected API response format. If the real API returns a different shape, change the API, not the mock.
3. **UI expectations are the design spec** - If a test expects `getByRole("button", { name: /create habit/i })`, that button must exist with that accessible name. The test defines the UX.
4. **Work incrementally** - Don't try to make all tests pass at once. Pick one failing test, make it green, move to the next. Commit every 5-10 tests.
5. **Failing for the right reason** - A test that fails because the page doesn't load is different from one that fails because a button has the wrong label. Diagnose accurately.

## When to Use /atdd

- When vision E2E specs exist in `e2e/tests/{feature}/` subdirectories
- When building out new feature areas from scratch
- When iterating on existing features to match updated specs
- When onboarding a new agent to a feature area (specs document the expected behavior)

## When NOT to Use /atdd

- For bug fixes (use /debug instead)
- When no vision specs exist for the feature (write specs first with /test-vision or /e2e)
- For backend-only work with no UI component
