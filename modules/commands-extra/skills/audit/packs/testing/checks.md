# Testing Audit Pack

**Pack ID:** `ccgm/testing`
**Applies when:** `always`

---

## Scope

This pack audits test coverage and test quality across the codebase. It checks for source files
that lack corresponding test files, test files that contain no assertions (and therefore prove
nothing), and test files that omit edge-case scenarios (empty inputs, boundary values, error
paths). It does NOT audit test runtime performance, mock strategy, or test framework setup.
All three checks require human-authored fixes; generated test stubs do not substitute for
meaningful test logic.

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
- Do NOT flag test files that use expectation-based framework APIs that appear assertion-free
  (e.g. jest.fn() with .toHaveBeenCalled()) — those are valid assertions.
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
