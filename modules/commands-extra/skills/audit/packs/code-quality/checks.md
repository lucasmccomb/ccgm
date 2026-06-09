# checks.md — Code Quality Pack

---

## Scope

This pack audits source code for common quality issues: linting violations, formatting drift, unused imports, oversized methods and files, and unhandled error paths (empty catch blocks). It covers all languages for the language-agnostic checks (long-method, large-file, empty-catch-block) and JavaScript/TypeScript projects for the ESLint-backed checks; the ESLint checks degrade gracefully on non-JS repos (the tool is simply absent and the llm fallback runs). This pack does NOT cover security vulnerabilities, dependency health, architectural patterns, or TypeScript/React-specific type checks — those belong in their respective packs.

**Pack ID:** `ccgm/code-quality`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Long-method, large-file, and empty-catch-block are language-agnostic structural smells detectable by the LLM in any codebase. The ESLint-backed checks (eslint-violation, unused-import) only run when ESLint is present; they degrade gracefully to llm fallback on non-JS repos, so running on all repos produces no false noise. |

---

## Checks

---

### `code-quality/eslint-violation`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `tool`

#### Detection

ESLint is invoked by the spine against the repository root. Any rule violation reported at error or warning level is a finding.

**Tool (if detection = tool or hybrid):**
`eslint`

Rule / rule-id: `(all enabled rules in the project's ESLint config)`

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories, thresholds, and severity guidelines from that file to inform
your checks. Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

The ESLint spine tool was not available. Scan JavaScript and TypeScript source files for
common ESLint rule violations that are statically detectable:
- no-unused-vars: variables declared but never referenced
- no-console: console.log/warn/error left in production code
- eqeqeq: == or != used instead of === or !==
- no-var: var declarations instead of let/const
- prefer-const: let declarations that are never reassigned

For each finding report: file path, line number, the rule name, and the offending code
snippet. Mark auto_fixable: true (eslint --fix resolves these mechanically).
```

#### Spine Wiring

```yaml
check_id: code-quality/eslint-violation
detection: tool
tool: eslint
fallback: llm
```

#### Severity / Confidence

**Severity rationale:** ESLint violations indicate code that breaks project-defined quality rules. Medium severity: violations create maintenance debt and can mask bugs, but do not typically cause immediate runtime failures on their own.

**Confidence rationale:** ESLint is deterministic — it parses the AST and applies rules exactly. When the tool runs, confidence is high. The llm fallback covers only common rule patterns and has the same high confidence for those patterns.

**Rubric entry:** `code-quality/eslint-violation`

#### Fixture

**True positive** (`src/utils/format.js`):

```js
// FINDS: == used instead of === (eqeqeq violation)
function isAdmin(role) {
  return role == 'admin';
}
```

**True negative** (should produce NO finding):

```js
// OK: strict equality used
function isAdmin(role) {
  return role === 'admin';
}
```

---

### `code-quality/prettier-violation`

**Severity:** `low`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent checks for formatting inconsistencies against the project's Prettier configuration or common defaults.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories and formatting guidelines from that file to inform your checks.
Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Check JavaScript and TypeScript files for Prettier formatting violations. If a
.prettierrc, prettier.config.js, or "prettier" key in package.json exists, use that
configuration; otherwise assume Prettier defaults (2-space indent, double quotes,
trailing commas in ES5 positions, 80-char print width).

Look for:
- Inconsistent indentation (tabs vs spaces, wrong indent width)
- Lines exceeding the configured print width
- Missing or extra trailing commas
- Inconsistent quote style (single vs double)
- Inconsistent semicolon usage

Run: npx prettier --check . (if prettier is installed locally)
If Prettier is not available, flag the most egregious formatting inconsistencies found by
visual inspection of representative files.

For each finding report: file path, line number or range, and description of the
formatting violation. Mark auto_fixable: true (prettier --write resolves these).
```

#### Spine Wiring

```yaml
check_id: code-quality/prettier-violation
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Formatting violations are purely cosmetic and do not affect runtime behavior. Low severity: they create diff noise and review friction but pose no functional risk.

**Confidence rationale:** Prettier's rules are deterministic given a config. When the LLM evaluates against explicit Prettier config, matches are precise. High confidence.

**Rubric entry:** `code-quality/prettier-violation`

#### Fixture

**True positive** (`src/components/Button.tsx`):

```tsx
// FINDS: inconsistent indentation (tabs used, project uses spaces)
function Button({label}) {
	return <button>{label}</button>
}
```

**True negative** (should produce NO finding):

```tsx
// OK: consistent 2-space indentation, double quotes, no missing semicolons
function Button({ label }: { label: string }) {
  return <button>{label}</button>;
}
```

---

### `code-quality/unused-import`

**Severity:** `low`
**Confidence:** `high`
**Detection:** `hybrid`

#### Detection

ESLint's `no-unused-vars` / `@typescript-eslint/no-unused-vars` rule detects unused imports when the spine tool runs. LLM fallback scans import statements against usages in the file body.

**Tool (if detection = tool or hybrid):**
`eslint`

Rule / rule-id: `no-unused-vars` / `@typescript-eslint/no-unused-vars`

Fallback when tool absent: `llm`

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories and severity guidelines from that file to inform your checks.
Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

ESLint was not available. Scan JavaScript and TypeScript source files for import or require
statements where the imported binding is never referenced in the file body. This includes:
- Named imports: import { Foo } from './foo' where Foo is never used
- Default imports: import Bar from './bar' where Bar is never used
- Namespace imports: import * as Baz from './baz' where Baz is never used
- CommonJS: const { x } = require('./x') where x is never used

Do NOT flag:
- Type-only imports used only as type annotations (import type { ... })
- Re-exports: export { Foo } from './foo'
- Imports used in JSX (e.g. React import in older React)

For each finding report: file path, line number, the unused binding name, and the import
statement. Mark auto_fixable: true (eslint --fix removes these).
```

#### Spine Wiring

```yaml
check_id: code-quality/unused-import
detection: hybrid
tool: eslint
rule: no-unused-vars
fallback: llm
```

#### Severity / Confidence

**Severity rationale:** Unused imports are dead code that inflate bundle size and create confusion about what a file depends on. Low severity: they add noise but do not cause runtime errors in most cases.

**Confidence rationale:** Static analysis of import/use pairs is deterministic. Both ESLint and LLM-based scanning produce precise results for this pattern. High confidence.

**Rubric entry:** `code-quality/unused-import`

#### Fixture

**True positive** (`src/pages/Dashboard.tsx`):

```tsx
// FINDS: Spinner is imported but never referenced below
import React from 'react';
import { Spinner } from '../components/Spinner';

export function Dashboard() {
  return <div>Dashboard</div>;
}
```

**True negative** (should produce NO finding):

```tsx
// OK: all imports are used
import React from 'react';
import { Spinner } from '../components/Spinner';

export function Dashboard({ loading }: { loading: boolean }) {
  return loading ? <Spinner /> : <div>Dashboard</div>;
}
```

---

### `code-quality/long-method`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent counts function/method body lines and flags any exceeding the threshold.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories, thresholds, and severity guidelines from that file to inform
your checks. Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan source files for functions or methods longer than 50 lines. Count lines from the
opening brace (or colon for Python) to the closing brace, inclusive, excluding blank
lines and comment-only lines from the line count only when doing so would not affect the
threshold determination — in practice, count all lines for simplicity.

Flag every function/method body that exceeds 50 lines as a finding.

Do NOT flag:
- Generated code files (*.generated.ts, *.pb.go, etc.)
- Minified files

For each finding report: file path, start line, end line, function/method name, and
actual line count. Mark auto_fixable: false (requires human refactoring).
```

#### Spine Wiring

```yaml
check_id: code-quality/long-method
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Functions exceeding 50 lines are difficult to test, review, and maintain. They often encode multiple responsibilities, making them a source of bugs and future regressions. Medium severity.

**Confidence rationale:** Line counting is deterministic. The LLM can count lines reliably. High confidence.

**Rubric entry:** `code-quality/long-method`

#### Fixture

**True positive** (`src/services/auth.ts`):

```ts
// FINDS: handleLogin is 55 lines (exceeds 50-line threshold)
async function handleLogin(req, res) {
  // ... 55 lines of login logic ...
  // line 1
  // line 2
  // ... (55 lines total)
}
```

**True negative** (should produce NO finding):

```ts
// OK: handleLogout is only 8 lines
async function handleLogout(req, res) {
  await destroySession(req.session);
  res.clearCookie('auth');
  res.redirect('/login');
}
```

---

### `code-quality/large-file`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent checks total line counts for source files and flags any exceeding the threshold.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories, thresholds, and severity guidelines from that file to inform
your checks. Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Identify source files with more than 500 lines. Use: find . -name "*.ts" -o -name "*.tsx"
-o -name "*.js" -o -name "*.jsx" -o -name "*.py" -o -name "*.go" -o -name "*.rb" | head -200
then check line counts with wc -l on the discovered files.

Do NOT flag:
- Auto-generated files (*.generated.*, *.pb.go, *.min.js, dist/, build/, node_modules/)
- Vendored third-party files
- Lock files (package-lock.json, yarn.lock, etc.)

For each finding report: file path and line count. Mark auto_fixable: false (requires
human-driven file splitting and module reorganization).
```

#### Spine Wiring

```yaml
check_id: code-quality/large-file
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Files exceeding 500 lines typically contain multiple concerns that should be separated into distinct modules. Large files impede code review, increase merge conflict risk, and make reasoning about the code harder. Medium severity.

**Confidence rationale:** Line counting is deterministic. High confidence.

**Rubric entry:** `code-quality/large-file`

#### Fixture

**True positive** (`src/components/Dashboard.tsx` with 620 lines):

```
$ wc -l src/components/Dashboard.tsx
     620 src/components/Dashboard.tsx
# FINDS: 620 lines exceeds 500-line threshold
```

**True negative** (should produce NO finding):

```
$ wc -l src/components/Button.tsx
      42 src/components/Button.tsx
# OK: 42 lines is well under threshold
```

---

### `code-quality/empty-catch-block`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent scans try/catch blocks for empty or effectively empty catch bodies that silently swallow errors.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/code-quality.md
Use the code smell categories and severity guidelines from that file to inform your checks.
Do not rely on memory — open and apply the file.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan source files for catch blocks that are empty or that only contain a comment with no
actual error handling. These silently swallow errors and make debugging extremely difficult.

Flag as a finding:
- catch blocks with no statements at all: catch (e) {}
- catch blocks with only a comment: catch (e) { // TODO }
- catch blocks that only re-assign to a variable without rethrowing or logging

Do NOT flag:
- catch blocks that log the error (console.error, logger.error, etc.)
- catch blocks that rethrow (throw e, throw new Error(...))
- catch blocks that set state / return a fallback value AND document why

For each finding report: file path, line number of the catch keyword, and the catch block
content. Mark auto_fixable: false (requires human decision about correct error handling).
```

#### Spine Wiring

```yaml
check_id: code-quality/empty-catch-block
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Empty catch blocks silently discard errors, making runtime failures invisible and extremely difficult to debug. They indicate an unresolved error handling decision. Medium severity: not an immediate vulnerability but a reliability risk.

**Confidence rationale:** Detecting syntactically empty or comment-only catch blocks is straightforward pattern matching. High confidence.

**Rubric entry:** `code-quality/empty-catch-block`

#### Fixture

**True positive** (`src/api/client.ts`):

```ts
// FINDS: catch block is empty — error is silently discarded
try {
  const data = await fetchUser(id);
  return data;
} catch (e) {
  // TODO: handle this
}
```

**True negative** (should produce NO finding):

```ts
// OK: error is logged and rethrown
try {
  const data = await fetchUser(id);
  return data;
} catch (e) {
  console.error('fetchUser failed:', e);
  throw e;
}
```

---

## Migration Mapping

Maps every bullet from the original Agent 3 category prompt to the check that owns it.

| Original Agent 3 Bullet | Check ID |
|-------------------------|----------|
| ESLint violations (auto-fixable: eslint --fix) | `code-quality/eslint-violation` |
| Prettier violations (auto-fixable: prettier --write) | `code-quality/prettier-violation` |
| Unused imports/variables (auto-fixable: eslint --fix) | `code-quality/unused-import` (split: unused **imports** → `code-quality/unused-import`; unused **variables** → `code-quality/eslint-violation` via `no-unused-vars`, with llm fallback when eslint is absent) |
| Long methods >50 lines (NOT auto-fixable - needs refactor) | `code-quality/long-method` |
| Large files >500 lines (NOT auto-fixable - needs split) | `code-quality/large-file` |
| Empty catch blocks (NOT auto-fixable - needs error handling) | `code-quality/empty-catch-block` |

All 6 bullets accounted for. No checks dropped.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
