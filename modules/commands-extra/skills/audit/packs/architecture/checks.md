# checks.md — Architecture Pack

---

## Scope

This pack audits structural and architectural patterns: circular module dependencies, god objects (modules or classes with excessive responsibilities), improper layering (concerns mixed across architectural layers), and wrong-layer imports (a layer importing from a layer it should not depend on). All checks apply to any codebase regardless of language, since these structural antipatterns are language-agnostic. This pack does NOT cover code quality smells (line lengths, linting), TypeScript-specific type patterns, security vulnerabilities, or dependency health — those belong in their respective packs.

**Pack ID:** `ccgm/architecture`
**Applies when:** `always`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Circular dependencies, god objects, improper layering, and wrong-layer imports are structural smells detectable in any codebase regardless of language. The LLM can reason about module dependency graphs and layer separation in Python, Go, TypeScript, Ruby, or any other language. Running on all repos is appropriate. |

---

## Checks

---

### `architecture/circular-dependency`

**Severity:** `high`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent traces import/require graphs looking for cycles between modules.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/architecture.md
Use the structural antipattern indicators, dependency detection patterns, and severity
guidelines from that file to guide every check below. Do not rely on memory — open and
apply the file.

Detect circular dependencies between modules. A circular dependency exists when module A
imports from module B, and module B (directly or transitively) imports from module A.

Steps:
1. For JavaScript/TypeScript projects, run: npx madge --circular --extensions ts,tsx,js,jsx src/
   (if madge is available). Parse the output for cycles.
2. If madge is not available, or for other languages, manually trace the top-level import
   graph of the most-imported modules (focus on shared utilities, services, and core
   modules where cycles are most common).
3. For Python projects, scan import statements looking for mutual imports between modules
   in the same package.

For each circular dependency found, report:
- The full cycle path (e.g. A → B → C → A)
- File paths for each node in the cycle
- Assessment of which import is most likely the wrong direction

Mark auto_fixable: false — breaking a circular dependency requires restructuring modules,
extracting shared interfaces, or inverting the dependency, all of which require human
architectural judgment.
```

#### Spine Wiring

```yaml
check_id: architecture/circular-dependency
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Circular dependencies prevent clean module initialization, can cause undefined references at runtime (especially in CommonJS), impede tree shaking, and make it impossible to reason about module load order. High severity.

**Confidence rationale:** Tracing import chains to find cycles is a deterministic graph traversal. When madge is available, confidence is very high. LLM-based tracing on the most-connected modules is also reliable. High confidence overall.

**Rubric entry:** `architecture/circular-dependency`

#### Fixture

**True positive** (`src/services/auth.ts` and `src/services/user.ts`):

```ts
// src/services/auth.ts
import { getUserById } from './user';   // imports from user

// src/services/user.ts
import { verifyToken } from './auth';   // imports from auth → CIRCULAR: auth → user → auth
```

**True negative** (should produce NO finding):

```ts
// src/services/auth.ts
import { hashPassword } from '../utils/crypto';  // one-directional: auth → utils

// src/utils/crypto.ts
// (no imports from auth or user)
```

---

### `architecture/god-object`

**Severity:** `high`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent identifies modules or classes that have accumulated too many responsibilities.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/architecture.md
Use the structural antipattern indicators, dependency detection patterns, and severity
guidelines from that file to guide every check below. Do not rely on memory — open and
apply the file.

Identify god objects: modules or classes that have accumulated so many responsibilities
that they have become a central hub that everything depends on, or that handle concerns
that should be separated into distinct modules.

Indicators of a god object:
- A class or module with more than 10 public methods spanning unrelated concerns
- A "utils" or "helpers" module that has grown to contain business logic, data access,
  and presentation concerns mixed together
- A single file or module that is imported by more than 30% of other modules in the
  project
- A class that has both data access (database queries), business logic, AND presentation
  logic

Steps:
1. Check file sizes — large files (>300 lines) are candidates
2. Count the number of imports/dependents for key modules (grep -r "from './utils'" src/ | wc -l)
3. For candidate files, assess whether the exported functions/classes span multiple
   unrelated concerns

For each finding report: file path, the number of responsibilities observed, a brief
description of the mixed concerns, and which modules depend on it. Mark auto_fixable:
false (requires human-driven decomposition).
```

#### Spine Wiring

```yaml
check_id: architecture/god-object
detection: llm
```

#### Severity / Confidence

**Severity rationale:** God objects create tight coupling throughout a codebase — every change to the god object risks breaking its many dependents, and testing becomes difficult because the module cannot be imported without bringing in all its unrelated concerns. High severity.

**Confidence rationale:** Assessing whether a module has too many responsibilities requires judgment about what constitutes a "concern," making this inherently more subjective than structural checks. Medium confidence.

**Rubric entry:** `architecture/god-object`

#### Fixture

**True positive** (`src/utils/helpers.ts` with 25 exported functions spanning auth, DB, formatting, and UI):

```ts
// FINDS: single module handles authentication, database, formatting, and UI concerns
export function hashPassword(pw: string) { ... }      // auth concern
export function executeQuery(sql: string) { ... }     // database concern
export function formatCurrency(n: number) { ... }     // formatting concern
export function renderModal(content: string) { ... }  // UI concern
// ... 21 more unrelated functions
```

**True negative** (should produce NO finding):

```ts
// OK: module has a single clear responsibility (string formatting utilities)
export function formatCurrency(n: number): string { ... }
export function formatDate(d: Date): string { ... }
export function formatPhoneNumber(p: string): string { ... }
```

---

### `architecture/improper-layering`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent infers the project's layered architecture and identifies where concerns have leaked across layers.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/architecture.md
Use the structural antipattern indicators, dependency detection patterns, and severity
guidelines from that file to guide every check below. Do not rely on memory — open and
apply the file.

Audit the project's layered architecture for improper layer mixing. First, infer the
project's intended architecture by examining directory structure, naming conventions,
and import patterns. Common layer structures:

- Frontend: components/ → hooks/ → services/ → api/
- Backend: controllers/ (or routes/) → services/ → repositories/ (or models/) → db/
- Full-stack: pages/ → components/ → hooks/ → services/ → api/

Improper layering occurs when:
- A data layer module (repository, model) contains presentation logic (string formatting,
  HTML generation, UI state)
- A presentation layer module (component, view) contains direct database calls or raw
  SQL
- A service module calls a controller/route handler directly (inverted layer dependency)
- Business logic is embedded in route handlers or controllers instead of service modules

For each finding report: file path, the layer it belongs to, the type of concern that
has leaked in from another layer, and the lines where the mixing occurs. Mark
auto_fixable: false (requires human-driven restructuring).
```

#### Spine Wiring

```yaml
check_id: architecture/improper-layering
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Improper layering makes the codebase harder to test (can't test a layer in isolation), harder to maintain (changes to one concern ripple across layers), and harder to understand (the role of each module is unclear). Medium severity: the code functions but the structure degrades over time.

**Confidence rationale:** Inferring the intended architecture from directory structure is reliable for well-organized projects but requires judgment. Medium confidence.

**Rubric entry:** `architecture/improper-layering`

#### Fixture

**True positive** (`src/repositories/UserRepository.ts`):

```ts
// FINDS: data repository layer contains presentation logic (formatting for display)
export class UserRepository {
  async findById(id: string): Promise<string> {
    const user = await db.query('SELECT * FROM users WHERE id = $1', [id]);
    // Presentation concern leaked into data layer:
    return `<div class="user-card">${user.name}</div>`;
  }
}
```

**True negative** (should produce NO finding):

```ts
// OK: repository only handles data access and returns plain data objects
export class UserRepository {
  async findById(id: string): Promise<User | null> {
    const row = await db.query('SELECT * FROM users WHERE id = $1', [id]);
    return row ? mapRowToUser(row) : null;
  }
}
```

---

### `architecture/wrong-layer-import`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans import statements to find imports that cross layer boundaries in the wrong direction.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/architecture.md
Use the structural antipattern indicators, dependency detection patterns, and severity
guidelines from that file to guide every check below. Do not rely on memory — open and
apply the file.

Detect imports from the wrong layer. In a well-layered architecture, dependencies flow
in one direction (outer layers depend on inner layers, not the reverse).

First infer the project's intended layer order from the directory structure. Then look for
imports that violate the expected direction:

- A service importing from a route/controller (inner layer importing outer)
- A shared utility (utils/, lib/) importing from a feature module (feature imports from
  shared are fine; shared importing from features is wrong)
- A lower-level module (models/, entities/) importing from a higher-level module
  (controllers/, views/)
- A shared data module importing from an application-specific business logic module

Approach: scan import statements in modules that are candidates for being "inner" layers
and check whether they import from "outer" layer directories.

Run: grep -r "from '../controllers" src/services/ or similar targeted greps for your
discovered layer structure.

For each finding report: file path, line number, the import statement, which layer it
belongs to, and which layer it is incorrectly importing from. Mark auto_fixable: false
when confident the dependency direction is clearly wrong; mark auto_fixable: true (with
medium confidence) when the fix is mechanical (moving the import to an appropriate
abstraction) — but flag for human verification.
```

#### Spine Wiring

```yaml
check_id: architecture/wrong-layer-import
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Wrong-direction imports create tight coupling between layers that should be independent. They make it impossible to swap out an implementation, test layers in isolation, or reason about the dependency graph. Medium severity.

**Confidence rationale:** Determining whether an import crosses a layer boundary in the wrong direction requires inferring the intended architecture — this requires judgment and may have false positives in projects with non-standard structures. Medium confidence.

**Rubric entry:** `architecture/wrong-layer-import`

#### Fixture

**True positive** (`src/services/EmailService.ts`):

```ts
// FINDS: service layer imports from route/controller layer (wrong direction)
import { handleWebhookRequest } from '../routes/webhooks';  // outer layer imported by inner

export class EmailService {
  async sendConfirmation(userId: string) {
    // ...uses handleWebhookRequest...
  }
}
```

**True negative** (should produce NO finding):

```ts
// OK: service imports from a shared utility (correct direction)
import { formatEmailAddress } from '../utils/email';

export class EmailService {
  async sendConfirmation(userId: string) {
    const addr = formatEmailAddress(userId);
    // ...
  }
}
```

---

## Migration Mapping

Maps every bullet from the original Agent 4 category prompt to the check that owns it.

| Original Agent 4 Bullet | Check ID |
|-------------------------|----------|
| Circular dependencies (NOT auto-fixable) | `architecture/circular-dependency` |
| God objects (NOT auto-fixable) | `architecture/god-object` |
| Improper layering (NOT auto-fixable) | `architecture/improper-layering` |
| Import from wrong layer (MAYBE auto-fixable with verification) | `architecture/wrong-layer-import` |

All 4 bullets accounted for. No checks dropped.

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
