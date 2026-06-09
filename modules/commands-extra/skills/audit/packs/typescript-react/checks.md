# checks.md — TypeScript / React Pack

---

## Scope

This pack audits TypeScript and React-specific patterns: overuse of the `any` escape hatch, missing function return type annotations, React Hooks Rules violations, React Fast Refresh violations (mixed component/non-component exports), and missing `key` props in list renders. It applies to any repository that uses JavaScript or TypeScript (detected by the presence of a `package.json`), which includes plain-JS React projects and TypeScript projects alike. This pack does NOT cover general code quality smells, architecture patterns, security issues, or dependency health — those belong in their respective packs.

**Pack ID:** `ccgm/typescript-react`
**Applies when:** `language:javascript`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | The ecosystem detector emits the `javascript` ecosystem for any repository that has a `package.json`; TypeScript repos additionally emit `typescript`. The registry derives condition tokens as `language:javascript` and `language:typescript` respectively. Because `applies_when` is AND-semantics, using `language:javascript` is the broadest honest gate: it covers both plain-JS React projects and TypeScript React projects (all TS repos also satisfy `language:javascript` since both ecosystems are detected). Using `language:typescript` would exclude plain-JS React repos; using `always` would incorrectly fire on Go, Python, and other non-JS repos where none of these patterns apply. |

---

## Checks

---

### `typescript/excessive-any`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent scans TypeScript source files for `any` type annotations and evaluates whether a more specific type is inferable.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan TypeScript source files (.ts, .tsx) for excessive use of the `any` type. Flag
occurrences where a more specific type is clearly inferable from context:
- Function parameters typed as `any` when the call sites reveal the actual shape
- Return types annotated as `any` when the return value is a concrete type
- Variables declared as `any` when immediately assigned a typed value
- Generic type parameters defaulted to `any` when a concrete type is available

Do NOT flag:
- `any` in type-guard functions (x: unknown guards) where `any` is genuinely necessary
- Explicitly suppressed instances with a comment explaining why `any` is appropriate
- Auto-generated or vendored files

For each finding: mark auto_fixable: true when the correct type is clearly inferable from
the surrounding code (e.g. the function is always called with a string); mark
auto_fixable: false when the correct type requires broader context or design decisions.

Report: file path, line number, the `any` usage, and the inferred type suggestion if
available.
```

#### Spine Wiring

```yaml
check_id: typescript/excessive-any
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Excessive `any` undermines TypeScript's type safety guarantees, allowing type errors to escape the compiler and surface at runtime. Medium severity: not immediately harmful but erodes the value of using TypeScript.

**Confidence rationale:** Identifying `any` annotations is a direct textual match. Whether a better type is inferable requires more judgment, but the LLM can assess this reliably from surrounding code. High confidence.

**Rubric entry:** `typescript/excessive-any`

#### Fixture

**True positive** (`src/api/users.ts`):

```ts
// FINDS: parameter typed as `any` when string is clearly intended
async function getUserById(id: any): Promise<User> {
  return fetch(`/api/users/${id}`).then(r => r.json());
}
```

**True negative** (should produce NO finding):

```ts
// OK: explicit string type
async function getUserById(id: string): Promise<User> {
  return fetch(`/api/users/${id}`).then(r => r.json());
}
```

---

### `typescript/missing-return-type`

**Severity:** `low`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent scans exported TypeScript functions and methods for missing explicit return type annotations.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan TypeScript source files (.ts, .tsx) for exported functions and methods that are
missing explicit return type annotations. Focus on public API surface: exported functions,
exported class methods, and React component render functions (which return JSX.Element or
ReactNode).

Flag when:
- An exported function has no return type annotation and the return type is not `void`
- An async function returns a Promise without the resolved type specified (e.g. missing
  Promise<User> annotation)

Do NOT flag:
- Functions with `void` return (callbacks, event handlers where return is irrelevant)
- Private/unexported helper functions (lower priority)
- Arrow functions used as inline callbacks
- Functions whose body is a single return statement returning a literal (string, number, boolean, or template literal)

For each finding: mark auto_fixable: true when the inferred type is clear and unambiguous
(TypeScript would infer it correctly); mark auto_fixable: false when the return type
depends on conditional branches or complex logic.

Report: file path, line number, and the inferred return type suggestion.
```

#### Spine Wiring

```yaml
check_id: typescript/missing-return-type
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing return type annotations reduce TypeScript's ability to catch bugs at call sites and make refactoring riskier. Low severity: TypeScript infers most return types correctly, so the immediate risk is low, but explicit annotations serve as documentation and catch inference drift over time.

**Confidence rationale:** Identifying missing annotations on exported functions is a straightforward structural scan. High confidence.

**Rubric entry:** `typescript/missing-return-type`

#### Fixture

**True positive** (`src/utils/format.ts`):

```ts
// FINDS: exported function missing return type annotation
export function formatCurrency(amount: number) {
  return `$${amount.toFixed(2)}`;
}
```

**True negative** (should produce NO finding):

```ts
// OK: explicit return type present
export function formatCurrency(amount: number): string {
  return `$${amount.toFixed(2)}`;
}
```

---

### `typescript/react-hooks-violation`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent reviews React component code for violations of the Rules of Hooks.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan React component files (.tsx, .jsx) for violations of the Rules of Hooks:
1. Hooks called inside loops: for/while loops containing useState, useEffect, etc.
2. Hooks called inside conditionals: if/else/ternary/switch containing hook calls
3. Hooks called inside nested functions: hook calls that are not at the top level of a
   React component or custom hook function
4. Hooks called outside React components or custom hooks: hook calls in plain helper
   functions, class methods, or event handlers that are not themselves hooks
5. Hooks called after a conditional early return: a hook call that appears AFTER an
   `if (!x) return null;` (or similar guard) near the top of a component — the hook
   runs on some renders but not others, violating the unconditional-call rule. Example:
   `if (!user) return null;` followed by `const [count, setCount] = useState(0);`

Custom hooks start with `use` by convention — treat them as valid hook call sites.

For each finding report: file path, line number, the hook being called incorrectly, and
the type of violation. Mark auto_fixable: false (fixing requires restructuring the
component logic, which requires human judgment).
```

#### Spine Wiring

```yaml
check_id: typescript/react-hooks-violation
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Rules of Hooks violations cause React to behave unpredictably — state associated with the wrong render, infinite re-render loops, or hooks silently not running. These are runtime bugs that are difficult to diagnose. High severity.

**Confidence rationale:** Identifying hook calls in conditional or loop contexts is a structural scan with clear rules. High confidence.

**Rubric entry:** `typescript/react-hooks-violation`

#### Fixture

**True positive** (`src/components/UserList.tsx`):

```tsx
// FINDS: hook called inside a conditional
function UserList({ isAdmin }: { isAdmin: boolean }) {
  if (isAdmin) {
    const [filter, setFilter] = useState('');  // Rules of Hooks violation
  }
  return <div />;
}
```

**True negative** (should produce NO finding):

```tsx
// OK: hooks called unconditionally at the top level of the component
function UserList({ isAdmin }: { isAdmin: boolean }) {
  const [filter, setFilter] = useState('');
  return isAdmin ? <div>{filter}</div> : <div />;
}
```

---

### `typescript/fast-refresh-violation`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent scans module files for mixed exports of React components and non-component values, which breaks React Fast Refresh.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan React source files (.tsx, .jsx) for Fast Refresh violations. React Fast Refresh
requires that files either export ONLY React components, or ONLY non-component values —
mixing both in the same file disables Fast Refresh for that file.

A React component is a function whose name starts with a capital letter and returns JSX
(JSX.Element, ReactElement, ReactNode, or null).

Flag files that export BOTH:
- One or more React components (capital-letter function names returning JSX), AND
- One or more non-component values (hooks, utility functions, constants, types, etc.)

Do NOT flag:
- Files that export ONLY components (no non-component exports)
- Files that export ONLY non-component values (hooks, utils, constants)
- Type-only exports (export type { ... }) — these do not affect Fast Refresh
- The special case of a default-export component + a named export of the component's
  PropTypes or displayName (common React pattern that does not break Fast Refresh)

For each finding report: file path, the component export(s), and the non-component
export(s) that are mixed together. Mark auto_fixable: false (requires splitting the
file, which involves human judgment about module organization).
```

#### Spine Wiring

```yaml
check_id: typescript/fast-refresh-violation
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Fast Refresh violations silently disable hot-reloading for the affected file, degrading the development experience. In Vite projects, ESLint's react-refresh plugin will also report these as errors, blocking the build. Medium severity.

**Confidence rationale:** Identifying mixed exports is a structural scan with clear rules. High confidence.

**Rubric entry:** `typescript/fast-refresh-violation`

#### Fixture

**True positive** (`src/components/UserCard.tsx`):

```tsx
// FINDS: mixes component export with utility function export
export function UserCard({ name }: { name: string }) {
  return <div>{name}</div>;
}

// Non-component export in the same file — breaks Fast Refresh
export function formatUserName(name: string): string {
  return name.trim().toLowerCase();
}
```

**True negative** (should produce NO finding):

```tsx
// OK: only component exports in this file
export function UserCard({ name }: { name: string }) {
  return <div>{name}</div>;
}

export function UserAvatar({ url }: { url: string }) {
  return <img src={url} alt="avatar" />;
}
```

---

### `typescript/missing-key-prop`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent scans JSX list renders for missing `key` props and flags array index usage as an anti-pattern.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan React source files (.tsx, .jsx) for list renders missing `key` props, or using
array index as the key (an anti-pattern).

Flag as findings:
1. Array.map() calls that return JSX elements without a `key` prop
2. Array.map() calls where `key={index}` or `key={i}` uses the array index — this is
   an anti-pattern because array indices are unstable when items are reordered or
   filtered, causing React to incorrectly reuse DOM nodes. Flag for human review to
   supply a stable, unique identifier (e.g. item.id, item.slug) as the key.

Do NOT flag:
- Static JSX lists (not produced by .map or iteration) — keys are not required
- Fragments with key props that have keys correctly set

For each finding report: file path, line number, the mapped expression, and whether the
issue is a missing key or an index-as-key anti-pattern. Mark auto_fixable: false (array
index as key is an anti-pattern; requires a stable, unique identifier — flag for human
review to supply the correct key).
```

#### Spine Wiring

```yaml
check_id: typescript/missing-key-prop
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing key props cause React reconciliation bugs: incorrect DOM reuse, broken animations, wrong component state after reorders. Using array index as key causes the same class of bugs when the list order changes. Medium severity.

**Confidence rationale:** Detecting `.map()` calls that return JSX without a key prop is a structural scan. High confidence for the missing-key case; also high for index-as-key since `key={index}` or `key={i}` is a recognizable pattern.

**Rubric entry:** `typescript/missing-key-prop`

#### Fixture

**True positive** (`src/components/ItemList.tsx`):

```tsx
// FINDS: missing key prop on mapped elements
function ItemList({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map(item => (
        <li>{item}</li>
      ))}
    </ul>
  );
}
```

**True negative** (should produce NO finding):

```tsx
// OK: stable unique key provided
function ItemList({ items }: { items: { id: string; label: string }[] }) {
  return (
    <ul>
      {items.map(item => (
        <li key={item.id}>{item.label}</li>
      ))}
    </ul>
  );
}
```

---

## Migration Mapping

Maps every bullet from the original Agent 5 category prompt to the check that owns it.

| Original Agent 5 Bullet | Check ID |
|-------------------------|----------|
| Excessive `any` types (auto-fixable if type is inferable) | `typescript/excessive-any` |
| Missing return types (auto-fixable: add inferred type) | `typescript/missing-return-type` |
| React hooks violations (NOT auto-fixable) | `typescript/react-hooks-violation` |
| Fast Refresh violations (NOT auto-fixable) | `typescript/fast-refresh-violation` |
| Missing key props (NOT auto-fixable: array index as key is an anti-pattern; requires a stable, unique identifier — flag for human review to supply the correct key) | `typescript/missing-key-prop` |

All 5 bullets accounted for. No checks dropped.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
