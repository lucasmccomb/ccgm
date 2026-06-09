# Documentation Audit Pack

**Pack ID:** `ccgm/documentation`
**Applies when:** `always`

---

## Scope

This pack audits the quality and completeness of inline code documentation and project-level
documentation. It checks for exported symbols missing JSDoc, code comments that no longer
accurately describe the code they annotate (stale comments), and README files that are
incomplete or missing key sections. It does NOT audit auto-generated API docs, test
documentation, or changelog formatting. All three checks are NOT auto-fixable: generated
documentation stubs do not substitute for meaningful human-authored documentation.

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `always` | Documentation gaps are relevant in every project regardless of ecosystem; language-specific nuances (e.g. JSDoc on TypeScript files) simply produce no findings on non-matching repos. |

---

## Checks

---

### `documentation/missing-jsdoc`

**Severity:** `low`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit documentation.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings. In particular:
the `documentation` fix_type is NOT auto-fixable (auto-fixable = No) — generated stubs
do not substitute for meaningful documentation and require human authorship.
Do not rely on memory — open and apply the file.

Check for missing JSDoc on exports:
- Enumerate all exported functions, classes, interfaces, and type aliases in TypeScript or
  JavaScript source files.
- For each exported symbol, check whether a JSDoc comment block (/** ... */) is present
  immediately above the declaration.
- Flag exported symbols that lack a JSDoc comment.
- Do NOT flag internal (non-exported) symbols.
- Do NOT flag symbols in generated files (e.g. *.generated.ts, *.d.ts).
- Do NOT flag test files.

Report each finding with: file path, line number, symbol name, severity LOW,
and auto_fixable=false (documentation fix_type requires human-authored documentation,
not generated stubs).
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: documentation/missing-jsdoc
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** Missing JSDoc on exports reduces discoverability and usability of
public APIs, but the code remains functional. Low severity reflects that this is a quality
and maintainability concern rather than a correctness or security issue.

**Confidence rationale:** The presence or absence of a JSDoc block above an exported symbol
is syntactically detectable; the LLM can enumerate exports reliably, making false positives
unlikely for well-structured TypeScript/JavaScript codebases.

**Rubric entry:** `documentation/missing-jsdoc`

#### Fixture

**True positive** (`src/utils/format.ts` exports `formatDate` without JSDoc):

```typescript
// src/utils/format.ts
export function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
```

Finding: `src/utils/format.ts:2` — exported `formatDate` has no JSDoc comment.

**True negative** (should produce NO finding):

```typescript
// src/utils/format.ts

/**
 * Formats a Date to a human-readable string.
 * @param date - The date to format.
 * @returns A formatted string like "Jan 1, 2024".
 */
export function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
```

No finding: JSDoc block is present above the exported function.

---

### `documentation/stale-comment`

**Severity:** `low`
**Confidence:** `low`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit documentation.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings. In particular:
the `documentation` fix_type is NOT auto-fixable (auto-fixable = No) — generated stubs
do not substitute for meaningful documentation and require human authorship.
Do not rely on memory — open and apply the file.

Check for stale comments:
- Scan source files for inline comments (// and /* ... */) and JSDoc blocks.
- Flag comments that appear to describe code that has changed such that the comment is now
  inaccurate. Common signs of staleness:
    - A comment references a function, variable, or parameter name that no longer exists.
    - A comment describes a behavior (e.g. "returns null on error") that the code no longer
      implements.
    - A comment contains a TODO or FIXME that refers to a fix that appears to have already
      been applied.
    - A comment references a version, date, or external ticket in a way that is clearly
      outdated.
- Be conservative: only flag when the mismatch between comment and code is clear from
  static reading. Do NOT flag comments that are vague or aspirational but not provably wrong.
- Do NOT flag auto-generated comment blocks or lint-suppression comments.

Report each finding with: file path, line number, the stale comment text (truncated to 80
chars), severity LOW, and auto_fixable=false.
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: documentation/stale-comment
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** A stale comment misleads future readers about the code's behavior,
increasing maintenance burden and risk of introducing bugs. Low severity reflects that the
code itself is correct; only the documentation is wrong.

**Confidence rationale:** Determining whether a comment is stale requires semantic comparison
between the comment's claims and the actual code behavior, which the LLM can reason about
but may get wrong for ambiguous or context-dependent comments, yielding low confidence.

**Rubric entry:** `documentation/stale-comment`

#### Fixture

**True positive** (`src/auth/session.ts` comment describes removed `null` return):

```typescript
// src/auth/session.ts

/**
 * Returns the current user, or null if not authenticated.
 */
export function getCurrentUser(): User {
  // Throws if not authenticated (changed from returning null in v2.0)
  if (!store.user) throw new AuthError('Not authenticated');
  return store.user;
}
```

Finding: `src/auth/session.ts:3` — comment says "returns null if not authenticated" but the
function now throws; comment is stale.

**True negative** (should produce NO finding):

```typescript
// src/auth/session.ts

/**
 * Returns the current user, or throws AuthError if not authenticated.
 */
export function getCurrentUser(): User {
  if (!store.user) throw new AuthError('Not authenticated');
  return store.user;
}
```

No finding: comment accurately describes the throwing behavior.

---

### `documentation/incomplete-readme`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

**LLM instruction (if detection = llm or hybrid):**

```
Audit documentation.

READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file when classifying findings. In particular:
the `documentation` fix_type is NOT auto-fixable (auto-fixable = No) — generated stubs
do not substitute for meaningful documentation and require human authorship.
Do not rely on memory — open and apply the file.

Check for README completeness:
- Look for a README.md (or README.rst, README.txt) in the repository root and in major
  package directories.
- Flag a README as incomplete if it is missing one or more of the following sections that
  are appropriate for this project type:
    - Project description / purpose (what does this project do?)
    - Installation or setup instructions
    - Usage examples or quickstart
    - Configuration reference (if the project has non-trivial configuration)
    - Contributing or development guide (for libraries and open-source projects)
- Flag if no README exists at all at the repo root.
- Be proportional: a small utility library has different README expectations than a full
  application. Use the project's apparent type and complexity to calibrate.
- Do NOT flag missing sections for content that is genuinely not applicable (e.g. a
  private internal tool does not need a Contributing guide).

Report each finding with: file path of the README (or "README.md missing"), the missing
section name, severity MEDIUM, and auto_fixable=false.
```

#### Spine Wiring

This check is LLM-only. No spine tool is involved.

```yaml
check_id: documentation/incomplete-readme
detection: llm
tool: ~
```

#### Severity / Confidence

**Severity rationale:** An incomplete README increases onboarding friction and the risk that
new contributors misuse or misconfigure the project. Medium severity reflects that this
directly affects the project's usability and accessibility to contributors.

**Confidence rationale:** Determining whether a README section is "present and sufficient"
requires understanding the project's type and the reader's needs; the LLM can assess this
reasonably but may disagree on threshold, yielding medium confidence.

**Rubric entry:** `documentation/incomplete-readme`

#### Fixture

**True positive** (`README.md` missing installation instructions):

```markdown
# MyApp

A web application for tracking habits.

## Contributing

Submit a PR.
```

Finding: `README.md` — missing "Installation" and "Usage" sections.

**True negative** (should produce NO finding):

```markdown
# MyApp

A web application for tracking habits.

## Installation

```bash
npm install
npm run dev
```

## Usage

Visit http://localhost:3000 and create your first habit.
```

No finding: README contains description, installation, and usage.

---

## Migration Mapping

The following table maps every bullet of the original Agent 7 category prompt to the check-id
that now owns it, proving no check was dropped.

| Original Agent 7 Bullet | Check ID |
|--------------------------|----------|
| Missing JSDoc on exports (NOT auto-fixable: requires human-authored documentation) | `documentation/missing-jsdoc` |
| Stale comments (NOT auto-fixable) | `documentation/stale-comment` |
| README completeness (NOT auto-fixable) | `documentation/incomplete-readme` |

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
