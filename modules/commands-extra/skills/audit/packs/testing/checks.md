# Testing Audit Pack

**Pack ID:** `ccgm/testing`
**Applies when:** `always`

---

## Scope

This pack audits test coverage and test quality across the codebase. It checks for source files
that lack corresponding test files, test files that contain no assertions (and therefore prove
nothing), test files that omit edge-case scenarios (empty inputs, boundary values, error paths),
arbitrary-sleep-based synchronization in tests that causes flakiness, committed `.only`/`.skip`
modifiers that silently narrow or disable the suite, tests that assert on mock call-logs rather
than real system behavior, and production code that exposes test-only setter or reset methods.

It does NOT audit test runtime performance, test framework configuration, or whether coverage
percentage meets a threshold. Worker agents MAY run the repo's own coverage command (e.g.
`npm test -- --coverage`, `pytest --cov`, or `go test -cover`) as an OPTIONAL advisory
read-only action to surface files with zero coverage; they must treat tool output as one signal
alongside the LLM checks and must not fail the pack run if the coverage command is absent or
fails. All checks require human-authored fixes; generated test stubs or mechanical edits do not
substitute for meaningful test logic.

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Testing gaps are relevant in every project regardless of language or ecosystem; React-specific or language-specific nuances simply produce no findings on non-matching repos. |

---

## Checks

---

### `testing/missing-test-file`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit test coverage and quality. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings (in particular,
`test_implementation` fix_type is NOT auto-fixable). Do not rely on memory — open and apply the file.

Check for missing test files for components:
- Enumerate source files (components, utilities, services, hooks) under src/ or equivalent.
- For each source file, look for a corresponding test file (e.g. Foo.test.ts, Foo.spec.ts,
  __tests__/Foo.ts, or a test directory mirroring the source structure).
- Flag source files that have no associated test file as findings.
- Do NOT flag test helper/fixture files, generated files, or files that are trivial re-exports
  with no logic.
- Do NOT flag files that are already covered by an integration or e2e test suite if that
  coverage is documented in the project.

Report each finding with: file path of the untested source file, severity MEDIUM,
and auto_fixable=false (test_implementation fix_type requires human authorship).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: testing/missing-test-file
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** Source files without any test coverage create a gap where regressions go
undetected on changes. Medium severity because the absence of a test does not cause an immediate
failure but degrades long-term maintainability and confidence in changes.

**Confidence rationale:** The presence or absence of a test file for a given source file is a
deterministic structural check; the LLM can enumerate files reliably, making false positives
unlikely for well-structured projects.

**Rubric entry:** `testing/missing-test-file`

#### Fixture

**True positive** (`src/components/UserCard.tsx` has no test file):

```
src/
  components/
    UserCard.tsx   ← source file
    Avatar.tsx
    Avatar.test.tsx
```

Finding: `src/components/UserCard.tsx` — no corresponding test file found.

**True negative** (should produce NO finding):

```
src/
  components/
    UserCard.tsx
    UserCard.test.tsx   ← test file present
```

No finding: `UserCard.test.tsx` covers `UserCard.tsx`.

---

### `testing/no-assertions`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit test coverage and quality. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings (in particular,
`test_implementation` fix_type is NOT auto-fixable). Do not rely on memory — open and apply the file.

Check for test files without assertions:
- Enumerate all test files (*.test.ts, *.spec.ts, *.test.tsx, *.spec.tsx, **/__tests__/**,
  or equivalent in the project's test framework).
- For each test file, scan for assertion calls: expect(...), assert(...), should(...),
  assertEquals(...), or framework-specific assertion APIs.
- Flag test files that contain zero assertion calls — these tests can never fail and prove nothing.
- Flag individual `it()`/`test()` blocks that contain no assertions even if other blocks in the
  same file do contain assertions.
- Count mock-verification calls as valid assertions (e.g. `expect(fn).toHaveBeenCalled()`,
  `expect(fn).toHaveBeenCalledWith(...)` are assertions); only flag files that have NO
  assertion forms whatsoever.
- Do NOT flag setup/teardown files (beforeAll, afterAll, etc.) that are not themselves test blocks.

Report each finding with: file path and block name, severity HIGH,
and auto_fixable=false (test_implementation fix_type requires human authorship).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: testing/no-assertions
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** A test file with no assertions passes unconditionally and provides
zero regression protection. This is a high-severity gap because the developer may believe
coverage exists when it does not, masking bugs that would otherwise be caught.

**Confidence rationale:** The presence of assertion calls is syntactically detectable by
pattern matching on well-known assertion APIs; false positive rate is low for common frameworks.

**Rubric entry:** `testing/no-assertions`

#### Fixture

**True positive** (`src/utils/format.test.ts` contains no assertions):

```typescript
// src/utils/format.test.ts
import { formatDate } from './format';

describe('formatDate', () => {
  it('formats a date', () => {
    const result = formatDate(new Date('2024-01-01'));
    // TODO: add assertion
  });
});
```

Finding: `src/utils/format.test.ts` — test block "formats a date" contains no assertions.

**True negative** (should produce NO finding):

```typescript
// src/utils/format.test.ts
import { formatDate } from './format';

describe('formatDate', () => {
  it('formats a date', () => {
    expect(formatDate(new Date('2024-01-01'))).toBe('Jan 1, 2024');
  });
});
```

No finding: assertion `expect(...).toBe(...)` is present.

---

### `testing/missing-edge-cases`

**Severity:** `low`
**Confidence:** `low`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit test coverage and quality. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings (in particular,
`test_implementation` fix_type is NOT auto-fixable). Do not rely on memory — open and apply the file.

Check for missing edge case tests:
- For each test file, examine the source file it covers (if identifiable).
- Review the source function signatures and logic branches.
- Flag test files that appear to test only the happy path and omit clearly important edge
  cases such as: null/undefined inputs, empty arrays/strings, boundary values (0, -1, MAX),
  error/exception paths, and async rejection handling.
- Be conservative: only flag when the missing edge case is clearly important given the
  function's documented or inferred behavior. Do NOT generate speculative findings for
  hypothetical inputs that are unreachable or explicitly excluded.
- Do NOT flag edge cases that are already covered elsewhere in the test suite.

Report each finding with: file path, the specific edge case missing, severity LOW,
and auto_fixable=false (test_implementation fix_type requires human authorship).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: testing/missing-edge-cases
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** Missing edge cases leave specific code paths unprotected against
regression, but the immediate impact is lower than a fully untested file or a test that
never fails; it is a quality gap rather than a complete absence of protection.

**Confidence rationale:** Determining which edge cases are "important" requires semantic
understanding of the function's contract; the LLM can reason about this but may miss
project-specific invariants or incorrectly model expected behavior, so confidence is low.

**Rubric entry:** `testing/missing-edge-cases`

#### Fixture

**True positive** (`src/utils/divide.test.ts` omits division-by-zero test):

```typescript
// src/utils/divide.ts
export function divide(a: number, b: number): number {
  if (b === 0) throw new Error('Division by zero');
  return a / b;
}

// src/utils/divide.test.ts
describe('divide', () => {
  it('divides two numbers', () => {
    expect(divide(10, 2)).toBe(5);
  });
});
```

Finding: `src/utils/divide.test.ts` — no test for division-by-zero error path.

**True negative** (should produce NO finding):

```typescript
// src/utils/divide.test.ts
describe('divide', () => {
  it('divides two numbers', () => {
    expect(divide(10, 2)).toBe(5);
  });
  it('throws on division by zero', () => {
    expect(() => divide(10, 0)).toThrow('Division by zero');
  });
});
```

No finding: edge case (division by zero) is covered.

---

### `testing/sleep-based-flake`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans test files for `sleep(`, `setTimeout(`, `time.sleep(`, `asyncio.sleep(`,
or equivalent arbitrary-duration waits used as a synchronization mechanism — waiting for an
async operation to complete by sleeping for a fixed duration instead of waiting for the actual
condition. The grep pre-screen surfaces candidates; the LLM disambiguates by reading context
(a `sleep` inside a non-test retry helper is not a finding; a `sleep(50)` before asserting that
a DOM update occurred is).

**LLM instruction (if detection = llm or hybrid):**

```
Scan test files for sleep-based synchronization — arbitrary-duration pauses used to wait for
an async operation to complete instead of waiting for the actual condition.

A sleep used as a synchronization mechanism is a timing bug: it guesses at how long an async
operation takes rather than waiting for evidence that it completed. The test passes on fast
machines and fails intermittently under load or CI.

Flag as a finding:
- setTimeout(() => { /* assertion */ }, N) used as a wait inside a test body
- await sleep(N) or await new Promise(r => setTimeout(r, N)) placed before an assertion
  where N is a guessed duration (not a documented, semantically meaningful interval)
- time.sleep(N) or asyncio.sleep(N) in Python tests used before an assertion
- Any similar pattern in other languages (Thread.sleep in Java/Kotlin, usleep in C, etc.)

Do NOT flag:
- sleep(N) inside a retry-with-backoff helper that has documented fixed delay semantics
- sleep used for rate limiting between iterations in a load test
- Waits that use a condition-based polling helper (waitFor, eventually, poll_until) —
  these are the correct pattern
- sleep inside a fixture teardown that intentionally gives a server time to shut down,
  with a comment explaining why

For each finding report: file:line, the sleep call, and the assertion it is guarding.
Suggest replacing with a condition-based waitFor / eventually / poll_until pattern.
```

#### Spine Wiring

This check is LLM-only (grep pre-screen for candidates). No spine tool is involved.

```yaml
check_id: testing/sleep-based-flake
detection: llm
tool: ~
```

Grep pre-screen (advisory, narrows LLM context): `sleep(` | `setTimeout(` | `time.sleep(` in
test files. The LLM reads the surrounding context to determine whether the sleep is acting as
a synchronization guard before an assertion.

#### Severity / Confidence

**Severity rationale:** A sleep-based synchronization guard is a latent flakiness bug: it passes
on a developer's machine and fails intermittently in CI under load. Flaky tests erode trust in
the test suite — teams begin ignoring failing tests, and the suite loses its regression-detection
value. Medium severity: does not cause incorrect behavior today but degrades the test suite's
reliability signal over time.

**Confidence rationale:** Most `sleep` calls before assertions in test files are genuine
synchronization guards. However, some sleeps have explicit semantic meaning (debounce intervals,
rate limits) and are correct; the LLM must read context to distinguish them. Medium confidence.

**Rubric entry:** `testing/sleep-based-flake`

#### Fixture

**True positive** (`src/components/Search.test.tsx` uses setTimeout to wait for a debounced
search result):

```typescript
// FINDS: sleep(100) before assertion — guesses that debounce fires within 100ms
it('shows search results after debounce', async () => {
  fireEvent.change(input, { target: { value: 'hello' } });
  await new Promise((r) => setTimeout(r, 100));  // <-- timing guess
  expect(screen.getByText('Result 1')).toBeInTheDocument();
});
```

Finding: `src/components/Search.test.tsx:4` — `setTimeout(r, 100)` used as synchronization
guard before assertion. Replace with `waitFor(() => screen.getByText('Result 1'))`.

**True negative** (should produce NO finding):

```typescript
// OK: condition-based waitFor — waits for the actual DOM state, not a duration
it('shows search results after debounce', async () => {
  fireEvent.change(input, { target: { value: 'hello' } });
  await waitFor(() => expect(screen.getByText('Result 1')).toBeInTheDocument());
});
```

No finding: `waitFor` polls for the condition rather than guessing a duration.

---

### `testing/only-or-skip-committed`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

Grep the test files for `.only(`, `.skip(`, `fdescribe(`, `fit(`, `xit(`, `xdescribe(`, and
`xtest(` — focus/skip modifiers left committed to the repo. These silently narrow the test suite
(`.only`/`fdescribe`/`fit`) or disable individual tests (`.skip`/`xit`/`xdescribe`/`xtest`),
producing false confidence in a CI green status.

**LLM instruction (if detection = llm or hybrid):**
n/a — detection is tool (grep) only.

**Tool:** `grep` (POSIX built-in, no external binary dependency).

Pattern:
```
grep -rn --include="*.test.*" --include="*.spec.*" \
  -E '\.(only|skip)\s*\(|^[[:space:]]*(fdescribe|fit|xit|xdescribe|xtest)\s*\(' \
  <test-dir>
```

Exclude:
- Lines that are in a comment (`//`, `#`, `/* ... */`)
- Files under `node_modules/`, `.git/`, `dist/`, `build/`

#### Spine Wiring

This check uses `detection: tool` with `tool: grep`. `grep` is a POSIX built-in with no
external binary required. The spine runs the pattern above and emits a finding for each match.

```yaml
check_id: testing/only-or-skip-committed
detection: tool
tool: grep
```

#### Severity / Confidence

**Severity rationale:** A committed `.only` narrows the entire test suite to one block — every
other test is silently skipped. CI reports green while hundreds of tests never ran. A committed
`.skip` disables a specific test, often hiding a known failure that was never fixed. Both
patterns produce false confidence in coverage. High severity because the impact is immediate and
invisible: the suite appears to pass while tests are disabled.

**Confidence rationale:** The grep pattern for `.only(`, `fdescribe(`, `fit(`, `.skip(`,
`xit(`, `xdescribe(`, `xtest(` in test files is a deterministic structural match. False
positives (a word in a comment) are excluded by the pattern filter. High confidence.

**Rubric entry:** `testing/only-or-skip-committed`

#### Fixture

**True positive** (`src/auth/login.test.ts` has a `.only` block):

```typescript
// FINDS: .only narrows the suite — all other tests in this file are skipped
describe('login', () => {
  it.only('accepts valid credentials', () => {
    expect(login('alice', 'secret')).toBe(true);
  });
  it('rejects empty password', () => {   // ← silently skipped
    expect(login('alice', '')).toBe(false);
  });
});
```

Finding: `src/auth/login.test.ts:3` — `.only` committed; suite narrowed silently.

**True negative** (should produce NO finding):

```typescript
// OK: no .only or .skip modifiers — all blocks run
describe('login', () => {
  it('accepts valid credentials', () => {
    expect(login('alice', 'secret')).toBe(true);
  });
  it('rejects empty password', () => {
    expect(login('alice', '')).toBe(false);
  });
});
```

No finding: no focus or skip modifiers present.

---

### `testing/mock-not-behavior`

**Severity:** `medium`
**Confidence:** `low`
**Detection:** `llm`

#### Detection

The LLM agent scans test files for tests that assert exclusively on mock call-logs (`.toHaveBeenCalled()`, `.toHaveBeenCalledWith(...)`, call count checks) without any assertion on the actual output or observable side effect of the system under test. These tests verify that a mock was called, not that the system produced the correct result. When the mock's contract drifts from the real implementation, the test keeps passing while production breaks.

**LLM instruction (if detection = llm or hybrid):**

```
Scan test files for tests that assert only on mock call-logs rather than on the real
output or observable side effect of the system under test.

A mock-only test verifies that a function was called with certain arguments but never
checks whether the code produced the correct result. When the mock's behavior drifts
from the real dependency, the test passes while production breaks.

Flag as a finding when ALL of these are true:
1. The test sets up one or more mocks (jest.fn(), sinon.stub(), Mock(), MagicMock, etc.)
2. The ONLY assertions in the test body are call-log checks:
   - expect(mockFn).toHaveBeenCalled()
   - expect(mockFn).toHaveBeenCalledWith(...)
   - expect(mockFn).toHaveBeenCalledTimes(N)
   - sinon assert.calledWith / assert.calledOnce
   - Python mock.assert_called_with / assert_called_once_with
3. There are NO assertions on the return value of the function under test, the state
   of a passed-in object after the call, or any other observable output

Do NOT flag:
- Tests that combine call-log assertions with output assertions (e.g. both
  expect(mockFn).toHaveBeenCalledWith(x) AND expect(result).toBe(y))
- Tests for event emitters or pub/sub systems where the side effect IS the call to
  a registered listener — asserting the listener was called with correct args is the
  correct verification strategy
- Tests explicitly documented as "interaction tests" with a comment explaining why
  call-log verification is the right approach

For each finding report: file:line, the test name, and which assertion type is present
(call-log only) versus what is missing (output or state assertion).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: testing/mock-not-behavior
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** A test that asserts only on mock call-logs verifies the call contract
with the mock, not the behavior of the code under test. When the real dependency changes its
interface or semantics, the mock diverges silently and the test keeps passing. Medium severity:
a real regression protection gap, but it manifests only when the real dependency changes.

**Confidence rationale:** Distinguishing "interaction test by design" from "forgot to assert on
output" requires reading the test's intent. Pure call-log-only tests are a clear smell, but
some architectures (event-driven, pub/sub) legitimately verify only call interactions. Low
confidence because the LLM must infer intent from structure alone.

**Rubric entry:** `testing/mock-not-behavior`

#### Fixture

**True positive** (`src/services/email.test.ts` only asserts mock was called):

```typescript
// FINDS: only call-log assertion — never checks that the email was correct
it('sends a welcome email on signup', async () => {
  const mockSend = jest.fn();
  await signupUser({ email: 'alice@example.com' }, { send: mockSend });
  expect(mockSend).toHaveBeenCalledTimes(1);  // ← only assertion: call count
  // Missing: expect(mockSend).toHaveBeenCalledWith({ to: 'alice@...', subject: '...' })
  // Missing: or an assertion on the signup result / returned user object
});
```

Finding: `src/services/email.test.ts:5` — test asserts only on mock call count, not on
email content or function return value.

**True negative** (should produce NO finding):

```typescript
// OK: combines call-log assertion with output assertion
it('sends a welcome email on signup', async () => {
  const mockSend = jest.fn();
  const user = await signupUser({ email: 'alice@example.com' }, { send: mockSend });
  expect(mockSend).toHaveBeenCalledWith({
    to: 'alice@example.com',
    subject: 'Welcome!',
  });
  expect(user.id).toBeDefined();  // ← output assertion
});
```

No finding: both the call arguments and the output are asserted.

---

### `testing/test-only-prod-method`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans production source files (non-test files) for methods or properties whose
name suggests they exist solely for test harness access: `_resetForTest`, `setForTest`,
`_testOnly`, `resetState`, `__test__`, `setPrivateField`, `getPrivateField`, or any method
annotated with a comment like `// for testing only` or `// test helper`. These methods expose
internals that production callers have no business touching and indicate a design smell where
the test harness is driving production API shape.

**LLM instruction (if detection = llm or hybrid):**

```
Scan production source files (NOT test files) for methods, functions, or properties that
appear to exist only to support test harness access.

A test-only production method is a method on a production class or module that has no
legitimate caller in production code — it exists only so tests can reach into internals
(reset state, inject values, inspect private fields).

Flag as a finding when a production file (not a *.test.*, *.spec.*, __tests__/ file)
contains a method or property matching any of these patterns:
- Name contains: resetForTest, _resetForTest, setForTest, testOnly, _testOnly,
  forTesting, forTest, __test__, resetState (when it has no production callers)
- A method annotated with a comment containing "for test", "test only", "test helper",
  "used by tests", "only called from tests", or similar
- A setter for a private field whose only purpose is to allow tests to inject a value
  (e.g. setDependency, setClient, setConfig on a class whose constructor already
  accepts the dependency — the setter exists only because tests cannot call the
  constructor again)

Do NOT flag:
- Test files themselves (*.test.ts, *.spec.ts, __tests__/)
- Factory methods or builders that are legitimately used in both test and production
  (e.g. UserBuilder.build(), TestFactory patterns in DDD are NOT findings)
- Dependency injection setters that are documented as part of the public API and used
  by production code (e.g. framework-level injection points)
- Methods that reset application state on logout or session end (production use case)

For each finding report: file:line, the method/property name, and why it appears
test-only (no production callers, naming convention, or comment evidence).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: testing/test-only-prod-method
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** A test-only method on a production class leaks test concerns into the
production API: the method may be called accidentally by production code, it incentivises
coupling tests to internals rather than behavior, and it creates a maintenance burden (the
method must be kept in sync with the internals it exposes). Medium severity: a design smell
with real maintenance risk but not an immediate runtime failure.

**Confidence rationale:** Naming conventions (`_resetForTest`, `setForTest`, `// test only`
comments) are reliable signals. Ambiguous cases — setters that could serve both test and
production callers — require reading call sites. Medium confidence.

**Rubric entry:** `testing/test-only-prod-method`

#### Fixture

**True positive** (`src/services/AuthService.ts` exposes `_resetForTest`):

```typescript
// src/services/AuthService.ts  (PRODUCTION file)
export class AuthService {
  private _currentUser: User | null = null;

  async login(credentials: Credentials): Promise<User> {
    this._currentUser = await this.api.authenticate(credentials);
    return this._currentUser;
  }

  // FINDS: method exists only for tests to reset state between test runs
  _resetForTest() {
    this._currentUser = null;
  }
}
```

Finding: `src/services/AuthService.ts:9` — `_resetForTest()` exists only for test harness
access; no production caller. Tests should use a fresh instance instead.

**True negative** (should produce NO finding):

```typescript
// src/services/AuthService.ts  (PRODUCTION file)
export class AuthService {
  private _currentUser: User | null = null;

  async login(credentials: Credentials): Promise<User> {
    this._currentUser = await this.api.authenticate(credentials);
    return this._currentUser;
  }

  async logout(): Promise<void> {
    this._currentUser = null;  // production use case: session end
    await this.api.invalidateSession();
  }
}
```

No finding: `logout()` is a production operation, not a test-only reset.

---

## Migration Mapping

The following table maps every bullet of the original Agent 6 category prompt to the check-id
that now owns it, proving no check was dropped.

| Original Agent 6 Bullet | Check ID |
|--------------------------|----------|
| Missing test files for components (NOT auto-fixable) | `testing/missing-test-file` |
| Test files without assertions (NOT auto-fixable) | `testing/no-assertions` |
| Missing edge case tests (NOT auto-fixable) | `testing/missing-edge-cases` |

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
