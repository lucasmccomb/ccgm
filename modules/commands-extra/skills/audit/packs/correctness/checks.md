# Correctness / Logic Pack

## Scope

This pack audits JavaScript source files for correctness and logic errors. It covers two layers of detection. First, the deterministic layer: the spine's eslint wrapper (`wrap-eslint.sh`) runs seven core ESLint rules with `--no-config-lookup` and no type information; these rules emit findings under the `lint/*` namespace (e.g. `lint/eqeqeq`, `lint/use-isnan`) and are severitied via the rubric at HIGH confidence. Second, the LLM best-effort layer: three checks (`correctness/off-by-one`, `correctness/float-equality`, `correctness/wrong-branch-logic`) are LLM-only, LOW confidence, with no deterministic backing. This pack does NOT audit security vulnerabilities, dependency health, architectural patterns, performance, TypeScript type safety, or Python/Go/other languages.

**Pack ID:** `ccgm/correctness`
**Applies when:** `language:javascript`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | All deterministic checks are ESLint rules targeting JavaScript/TypeScript syntax. The LLM checks also scope to JS/TS logic patterns. Running on non-JS repos produces zero signal and wastes agent time. |

---

## Spine-Namespace Convention

The spine's eslint wrapper (`wrap-eslint.sh`) emits findings with `check_id: lint/<rule-name>` for every ESLint rule it fires. These `lint/*` check-ids are **not** declared in this pack's `checks[]` — they are emitted by the spine's deterministic layer and severitied via rubric entries (`lint/eqeqeq`, `lint/use-isnan`, etc.). The LLM worker triages `lint/*` candidates via `spine_triage` and may escalate them to correctness-layer findings. The check-ids declared in `pack.json` (`correctness/*`) are for the LLM best-effort layer only.

This follows the same convention established in the security pack: spine-namespace findings (`lint/*`, `secrets/*`, `sast/*`) flow through the rubric; pack-namespace check-ids (`correctness/*`, `security/*`) are LLM-originated or LLM-confirmed findings.

**Spine rule → rubric mapping:**

| ESLint rule | Spine check-id | Severity | Confidence |
|-------------|---------------|----------|------------|
| `eqeqeq` | `lint/eqeqeq` | medium | high |
| `use-isnan` | `lint/use-isnan` | high | high |
| `valid-typeof` | `lint/valid-typeof` | high | high |
| `no-unreachable` | `lint/no-unreachable` | high | high |
| `no-constant-condition` | `lint/no-constant-condition` | medium | high |
| `no-fallthrough` | `lint/no-fallthrough` | medium | high |
| `default-case` | `lint/default-case` | medium | high |

---

## Checks

---

### `correctness/off-by-one`

**Severity:** `high`
**Confidence:** `low`
**Detection:** `llm`

> **LLM best-effort, low-confidence check. No deterministic backing. Expect false positives and false negatives.**

#### Detection

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for off-by-one errors in loop bounds,
array accesses, and index arithmetic.

Look for patterns such as:
- Loop conditions using `<` vs `<=` or `>` vs `>=` that may skip the first or last
  element (e.g. `for (let i = 0; i < arr.length - 1; i++)` when the last element
  should be included)
- Array accesses at index `arr.length` (out-of-bounds)
- Slice/substring calls where end index is off by one (e.g. `str.slice(0, n-1)`
  when the intent is to include the character at `n-1`)
- Range comparisons where a boundary value is incorrectly included or excluded
  (e.g. `if (x > 0 && x < 10)` vs `if (x >= 0 && x <= 10)`)

Do NOT flag:
- Intentional half-open ranges (e.g. `slice(0, n)` where the last element is
  correctly excluded)
- Idiomatic patterns where the off-by-one is clearly the intent
- Loop patterns that are correct for their data structure (e.g. iterating pairs
  with `i < arr.length - 1`)

For each finding report: file path, line number, the code snippet, and an explanation
of the suspected off-by-one. Mark auto_fixable: false — correct fix requires
understanding the intended semantics.

IMPORTANT: This is a low-confidence check. Only flag instances where you have strong
reason to believe the boundary is wrong, not merely unusual. If uncertain, do not flag.
```

#### Spine Wiring

```yaml
check_id: correctness/off-by-one
detection: llm
```

Note: No spine tool emits `correctness/off-by-one`. Deterministic eslint findings for
related issues appear under `lint/no-unreachable` (unreachable code that may result from
logic errors). The LLM handles this check directly.

#### Severity / Confidence

**Severity rationale:** Off-by-one errors produce incorrect results — wrong number of iterations, missed final elements, or out-of-bounds accesses that crash at runtime. HIGH severity because the consequence is data corruption or a runtime exception.

**Confidence rationale:** Off-by-one detection requires understanding the intended semantics of a loop or range, which the LLM must infer from context. The LLM is often right but can misread intent. LOW confidence — flag only high-certainty cases, expect false positives.

**Rubric entry:** `correctness/off-by-one`

#### Fixture

**True positive** (`src/utils/paginate.ts`):

```typescript
// FINDS: off-by-one — last item excluded when it should be included
function getPage(items: number[], page: number, size: number): number[] {
  const start = page * size;
  const end = start + size - 1;  // off-by-one: should be start + size
  return items.slice(start, end);
}
```

**True negative** (should produce NO finding):

```typescript
// OK: correct slice semantics — end is exclusive in Array.prototype.slice
function getPage(items: number[], page: number, size: number): number[] {
  const start = page * size;
  const end = start + size;
  return items.slice(start, end);
}
```

---

### `correctness/float-equality`

**Severity:** `medium`
**Confidence:** `low`
**Detection:** `llm`

> **LLM best-effort, low-confidence check. No deterministic backing. Expect false positives and false negatives.**

#### Detection

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for direct equality comparisons between
floating-point values using === or == where the values are the result of arithmetic
operations, trigonometry, or string-to-float conversion.

Look for patterns such as:
- `someFloat === 0` or `someFloat === 1.0` after arithmetic (e.g. the result of
  multiplication or division)
- `a === b` where both a and b are floating-point results of computations
- Comparisons of currency amounts, percentages, or measurement values using strict
  equality

Do NOT flag:
- Comparisons of floats to integer literals where the float is known to be an integer
  (e.g. `Math.floor(x) === 5`)
- Comparisons using Number.EPSILON or an explicit tolerance (already correct)
- Integer comparisons that happen to use float-typed variables

For each finding report: file path, line number, the comparison expression, and the
recommended fix (compare with an epsilon tolerance instead of strict equality).
Mark auto_fixable: false.

IMPORTANT: This is a low-confidence check. Only flag instances where floating-point
precision loss is likely (post-arithmetic comparisons). If uncertain, do not flag.
```

#### Spine Wiring

```yaml
check_id: correctness/float-equality
detection: llm
```

Note: The spine's `lint/use-isnan` (ESLint `use-isnan` rule) catches the specific case of
comparing a float to `NaN` with `===`; that is a separate, higher-confidence check in the
`lint/*` namespace. This check covers the broader pattern of float equality after arithmetic.

#### Severity / Confidence

**Severity rationale:** Direct float equality fails silently on values that should be equal but differ by floating-point rounding error, producing subtly wrong results in calculations. MEDIUM because the bug is usually latent rather than immediately crashing.

**Confidence rationale:** Determining whether a comparison involves a float subject to arithmetic error requires tracing the type and origin of the compared values, which the LLM must infer. LOW confidence — many comparisons look float-like but are safe.

**Rubric entry:** `correctness/float-equality`

#### Fixture

**True positive** (`src/billing/tax.ts`):

```typescript
// FINDS: float equality after arithmetic — precision loss likely
function applyDiscount(price: number, discount: number): number {
  const discounted = price * (1 - discount);
  if (discounted === 0) {  // may never be exactly 0 after multiplication
    return 0;
  }
  return discounted;
}
```

**True negative** (should produce NO finding):

```typescript
// OK: epsilon comparison avoids float precision issues
function applyDiscount(price: number, discount: number): number {
  const discounted = price * (1 - discount);
  if (Math.abs(discounted) < Number.EPSILON) {
    return 0;
  }
  return discounted;
}
```

---

### `correctness/wrong-branch-logic`

**Severity:** `high`
**Confidence:** `low`
**Detection:** `llm`

> **LLM best-effort, low-confidence check. No deterministic backing. Expect false positives and false negatives.**

#### Detection

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: n/a (detection is always llm)

**LLM instruction (if detection = llm or hybrid):**

```
Scan JavaScript and TypeScript source files for conditional logic that appears to have
its branches swapped, inverted conditions, or incorrectly composed boolean expressions.

Look for patterns such as:
- Inverted guard clauses (e.g. `if (isAuthenticated) { throw new Error("Unauthorized") }`
  when the intent is to throw on the negative case)
- AND vs OR confusion in compound conditions (e.g. `if (!a || !b)` when the intent is
  `if (!a && !b)` — De Morgan's law violations)
- Conditions that contradict function name or comment intent
  (e.g. a function called `isValid` that returns `false` on success)
- Negated conditions on the happy-path branch (e.g. early-return on !error when the
  caller expects error-first)

Do NOT flag:
- Intentionally inverted logic that is clearly documented
- Standard error-first callback patterns
- Negative conditions that correctly model the problem domain

For each finding report: file path, line number, the condition, and an explanation of
why the branch logic appears incorrect. Mark auto_fixable: false — correct fix requires
understanding the intended control flow.

IMPORTANT: This is a low-confidence check. Only flag instances where the intent is
clearly stated (via function name, comment, or context) and contradicts the code.
If uncertain, do not flag.
```

#### Spine Wiring

```yaml
check_id: correctness/wrong-branch-logic
detection: llm
```

Note: The spine's `lint/no-constant-condition` catches conditions that are always true or
always false (e.g. `if (true)`, `while (false)`), which is the deterministic subset of this
class. The broader pattern — inverted or swapped conditions — requires LLM reasoning.

#### Severity / Confidence

**Severity rationale:** Wrong branch logic means the code does the opposite of what was intended — rejecting valid inputs, allowing invalid ones, or executing the wrong path. HIGH severity because the consequences are typically data corruption, security bypass, or user-visible incorrect behavior.

**Confidence rationale:** Determining whether branch logic is wrong requires understanding the intent behind the code, which the LLM must infer from names, comments, and context. LOW confidence — many inverted conditions are intentional.

**Rubric entry:** `correctness/wrong-branch-logic`

#### Fixture

**True positive** (`src/middleware/auth.ts`):

```typescript
// FINDS: inverted guard — throws when user IS authenticated (should throw when NOT)
function requireAuth(user: User | null): void {
  if (user !== null) {
    throw new Error("Unauthorized: must be logged in");
  }
}
```

**True negative** (should produce NO finding):

```typescript
// OK: correctly throws when user is NOT authenticated
function requireAuth(user: User | null): void {
  if (user === null) {
    throw new Error("Unauthorized: must be logged in");
  }
}
```

---

## Migration Mapping

Every correctness check category is mapped to its owning check-id or spine namespace:

| Check category | Detection layer | Check-id / namespace |
|----------------|-----------------|----------------------|
| Type-unsafe equality (`==` / `!=`) | Deterministic (spine) | `lint/eqeqeq` |
| Comparison to NaN | Deterministic (spine) | `lint/use-isnan` |
| Invalid typeof string | Deterministic (spine) | `lint/valid-typeof` |
| Unreachable code after return/throw | Deterministic (spine) | `lint/no-unreachable` |
| Always-true/always-false condition | Deterministic (spine) | `lint/no-constant-condition` |
| Switch case fallthrough | Deterministic (spine) | `lint/no-fallthrough` |
| Missing default case in switch | Deterministic (spine) | `lint/default-case` |
| Off-by-one in loops/indices | LLM best-effort (LOW confidence) | `correctness/off-by-one` |
| Float equality after arithmetic | LLM best-effort (LOW confidence) | `correctness/float-equality` |
| Inverted / swapped branch logic | LLM best-effort (LOW confidence) | `correctness/wrong-branch-logic` |

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
