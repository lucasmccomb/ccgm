# Performance Audit Pack

**Pack ID:** `ccgm/performance`
**Applies when:** `always`

---

## Scope

This pack audits common performance anti-patterns in application code. It checks for N+1
query patterns (a data-fetching loop that issues one query per item rather than batching),
React components that re-render unnecessarily due to missing `React.memo`, and large
library imports that pull in entire packages when only a small subset is needed. It does NOT
audit server infrastructure, network latency, database index design, or build pipeline
performance. React-specific checks (missing-react-memo) produce no findings on non-React
repositories.

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | N+1 query and large-bundle-import checks apply to any stack; missing-react-memo is React-specific but produces no findings on non-React repos, making `always` the correct gate (same behavior as today's Agent 8 category prompt). |

---

## Checks

---

### `performance/n-plus-one-query`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit performance patterns. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table and confidence levels from that file when classifying findings.
Do not rely on memory — open and apply the file.

Check for N+1 query patterns:
- Scan data access code (ORM calls, raw SQL, Supabase/Prisma/TypeORM/Mongoose queries,
  fetch calls to internal APIs, etc.) for patterns where a query or fetch is issued
  inside a loop or array map.
- Flag code where:
    - A `.findMany()`, `.select()`, `.query()`, or equivalent is called inside a
      `for`, `while`, `forEach`, `map`, `reduce`, or `flatMap` over a result set.
    - Each iteration fetches related data that could be obtained via a JOIN or
      batch query (e.g. fetching a user for each order in a list of orders).
- Do NOT flag cases where the loop body is performing non-database work (calculations,
  transformations) and the DB call is outside the loop.
- Do NOT flag intentional per-item operations where batching is not possible or
  where the set size is bounded to 1.

Report each finding with: file path, line number, a brief description of the pattern
(e.g. "fetches user inside orders loop"), severity HIGH, and auto_fixable=false (requires
a refactor to batch queries or use eager loading).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: performance/n-plus-one-query
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** N+1 query patterns cause quadratic or worse database load as
dataset size grows, directly degrading response times and database resource usage.
High severity reflects the production impact when these patterns hit real data volumes.

**Confidence rationale:** Identifying a query inside a loop requires understanding the
semantics of the called function and the loop's purpose, which the LLM can reason about
but may misidentify in complex or abstracted code, yielding medium confidence.

**Rubric entry:** `performance/n-plus-one-query`

#### Fixture

**True positive** (`src/api/orders.ts` fetches user inside orders loop):

```typescript
// src/api/orders.ts
async function getOrdersWithUsers(orderIds: string[]) {
  const orders = await db.orders.findMany({ where: { id: { in: orderIds } } });
  // N+1: one user query per order
  return Promise.all(orders.map(async (order) => {
    const user = await db.users.findUnique({ where: { id: order.userId } });
    return { ...order, user };
  }));
}
```

Finding: `src/api/orders.ts:5` — `db.users.findUnique` called inside `map` over orders list;
batch with `findMany` and join in memory.

**True negative** (should produce NO finding):

```typescript
// src/api/orders.ts
async function getOrdersWithUsers(orderIds: string[]) {
  const orders = await db.orders.findMany({
    where: { id: { in: orderIds } },
    include: { user: true },   // eager-loaded in single query
  });
  return orders;
}
```

No finding: user is loaded via `include` in a single batched query.

---

### `performance/missing-react-memo`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit performance patterns. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table and confidence levels from that file when classifying findings.
Do not rely on memory — open and apply the file.

Check for missing React.memo:
- Scan React component files (*.tsx, *.jsx) for functional components that:
    - Accept props (not zero-prop components).
    - Are re-exported or used as children of other components.
    - Have a parent component that re-renders frequently (e.g. contains state that
      changes on user interaction) where the child's props do not change.
- Flag components where wrapping in React.memo would prevent unnecessary re-renders.
- Be conservative: only flag when there is evidence the parent re-renders on state
  change and the child's props are stable (primitives, stable references via useMemo/
  useCallback). Do NOT flag every component — only those where memo would have clear value.
- Do NOT flag components that use context or internal state, as memo does not prevent
  re-renders caused by context changes.

Report each finding with: file path, component name, severity LOW,
and auto_fixable=true at medium confidence (add memo wrapper per fix-patterns.md).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: performance/missing-react-memo
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** A component re-rendering unnecessarily wastes CPU and can cause
cascading child re-renders, but the UI remains correct. Low severity reflects that this
is a performance optimization opportunity rather than a correctness defect.

**Confidence rationale:** Determining whether `React.memo` would have net benefit requires
understanding both parent rendering frequency and prop stability; this analysis is
context-dependent and may be incorrect for complex component trees, yielding medium confidence.

**Rubric entry:** `performance/missing-react-memo`

#### Fixture

**True positive** (`src/components/UserCard.tsx` not memoized, parent re-renders on typing):

```tsx
// src/components/UserCard.tsx
interface UserCardProps {
  userId: string;
  name: string;
}

export function UserCard({ userId, name }: UserCardProps) {
  return <div className="card">{name}</div>;
}

// Parent re-renders on every keystroke via useState; UserCard props are stable.
```

Finding: `src/components/UserCard.tsx` — `UserCard` receives stable props but is not wrapped
in `React.memo`; auto_fixable=true (add `export default React.memo(UserCard)`).

**True negative** (should produce NO finding):

```tsx
// src/components/UserCard.tsx
import { memo } from 'react';

export const UserCard = memo(function UserCard({ userId, name }: UserCardProps) {
  return <div className="card">{name}</div>;
});
```

No finding: component is already memoized.

---

### `performance/large-bundle-import`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit performance patterns. Most findings need human review.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table and confidence levels from that file when classifying findings.
Do not rely on memory — open and apply the file.

Check for large bundle imports (needs tree shaking):
- Scan import statements for patterns that import an entire library when only specific
  members are needed, preventing the bundler from tree-shaking unused code. Examples:
    - `import _ from 'lodash'` instead of `import { debounce } from 'lodash-es'` or
      `import debounce from 'lodash/debounce'`
    - `import * as Icons from '@heroicons/react'` instead of named imports
    - `import moment from 'moment'` (moment does not support tree shaking at all)
    - `import { everything } from 'some-large-library'` where only one item is used
  - Check for libraries known to be non-tree-shakeable or commonly misimported (lodash,
    moment, date-fns default, antd, material-ui top-level, rxjs/Rx).
- Flag imports that are likely to add significant bundle weight unnecessarily.
- Do NOT flag imports of small libraries or where the full module is genuinely needed.
- Do NOT flag server-side code (Node.js scripts, API routes) where bundle size is
  not a concern.

Report each finding with: file path, line number, the import statement, a suggested
tree-shakeable alternative, severity MEDIUM, and auto_fixable=false (needs tree shaking
refactor and possibly a dependency change).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: performance/large-bundle-import
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** Importing entire large libraries when only a fraction is used
inflates the client bundle, directly increasing initial load time and time-to-interactive.
Medium severity reflects measurable user-facing impact in web applications.

**Confidence rationale:** Identifying commonly misimported libraries (lodash, moment) is
reliable, but assessing whether a given import is "large" and unused code is "significant"
requires bundler knowledge and project context, yielding medium confidence.

**Rubric entry:** `performance/large-bundle-import`

#### Fixture

**True positive** (`src/utils/time.ts` imports full lodash):

```typescript
// src/utils/time.ts
import _ from 'lodash';

export function debounceSearch(fn: () => void) {
  return _.debounce(fn, 300);
}
```

Finding: `src/utils/time.ts:2` — full lodash imported; replace with
`import debounce from 'lodash/debounce'` or `import { debounce } from 'lodash-es'`
for tree shaking.

**True negative** (should produce NO finding):

```typescript
// src/utils/time.ts
import debounce from 'lodash/debounce';

export function debounceSearch(fn: () => void) {
  return debounce(fn, 300);
}
```

No finding: per-method import enables tree shaking.

---

## Migration Mapping

The following table maps every bullet of the original Agent 8 category prompt to the check-id
that now owns it, proving no check was dropped.

| Original Agent 8 Bullet | Check ID |
|--------------------------|----------|
| N+1 query patterns (NOT auto-fixable) | `performance/n-plus-one-query` |
| Missing React.memo (auto-fixable: add memo wrapper — medium confidence per fix-patterns.md) | `performance/missing-react-memo` |
| Large bundle imports (NOT auto-fixable - needs tree shaking) | `performance/large-bundle-import` |

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
