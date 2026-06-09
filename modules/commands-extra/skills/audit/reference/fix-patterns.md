# Auto-Fix Patterns Reference

Guide for determining which findings can be auto-fixed and how.

## Fix Confidence Levels

### HIGH Confidence - Auto-Fix Without Hesitation

These fixes are safe, well-tested, and unlikely to cause issues.

#### ESLint Auto-Fixes
```bash
# Fix all auto-fixable ESLint issues
npx eslint --fix {file}

# Fix specific rules
npx eslint --fix --rule 'no-unused-vars: error' {file}
```

**Auto-fixable ESLint rules:**
- `no-unused-vars` (remove unused imports)
- `no-extra-semi` (remove extra semicolons)
- `semi` (add/remove semicolons)
- `quotes` (fix quote style)
- `indent` (fix indentation)
- `comma-dangle` (fix trailing commas)
- `object-curly-spacing` (fix spacing)
- `array-bracket-spacing` (fix spacing)
- `eol-last` (fix end of file newline)
- `no-multiple-empty-lines` (remove extra blank lines)
- `no-trailing-spaces` (remove trailing whitespace)

#### Prettier Auto-Fixes
```bash
# Format file
npx prettier --write {file}

# Format all files
npx prettier --write "src/**/*.{ts,tsx}"
```

#### NPM Audit Fix (Non-Breaking)
```bash
# Safe fix - only non-breaking changes
npm audit fix

# Check what would change first
npm audit fix --dry-run
```

**Note:** Never use `npm audit fix --force` automatically - it may introduce breaking changes.

#### Remove Unused Imports
```bash
# Using eslint
npx eslint --fix --rule 'unused-imports/no-unused-imports: error' {file}

# Or manually identify and remove
```

**Pattern to match:**
```typescript
// BEFORE
import { used, unused } from 'package'

// AFTER
import { used } from 'package'
```

---

### MEDIUM Confidence - Fix with Extra Verification

These fixes require running the full test suite after application.

#### Add Explicit Return Types
```typescript
// BEFORE
function getUser(id: string) {
  return users.find(u => u.id === id)
}

// AFTER (infer from implementation)
function getUser(id: string): User | undefined {
  return users.find(u => u.id === id)
}
```

**When to auto-fix:**
- Return type is clearly inferable
- No complex generics involved
- Single return statement or consistent return types

**When NOT to auto-fix:**
- Multiple return types that need union
- Async functions with complex promise chains
- Generics that need manual type parameters

#### Replace Simple `any` Types
```typescript
// BEFORE
function process(data: any) {
  return data.name
}

// AFTER (if usage is clear)
function process(data: { name: string }) {
  return data.name
}
```

**When to auto-fix:**
- Usage pattern makes type obvious
- Single property access
- Function parameter with clear usage

**When NOT to auto-fix:**
- Complex object shapes
- Dynamic property access
- External API responses

#### Add React.memo Wrapper
```typescript
// BEFORE
export function ExpensiveComponent({ data }) {
  return <div>{/* expensive render */}</div>
}

// AFTER
export const ExpensiveComponent = React.memo(function ExpensiveComponent({ data }) {
  return <div>{/* expensive render */}</div>
})
```

**When to auto-fix:**
- Component receives primitive props
- No callback props that change frequently
- Confirmed expensive render

**When NOT to auto-fix:**
- Props include objects/arrays that change reference
- Component uses context that changes often

---

### LOW Confidence - Human Review Required

These should NEVER be auto-fixed. Create GitHub issues instead.

#### Refactoring Long Methods
- Requires understanding business logic
- Multiple valid ways to split
- Risk of breaking functionality

#### Resolving Circular Dependencies
- Requires architectural decisions
- May need interface extraction
- Could require significant restructuring

#### Adding Error Boundaries
- Requires understanding error recovery strategy
- Needs appropriate fallback UI
- May require error reporting integration

#### Writing Test Implementations
- Requires understanding expected behavior
- Needs appropriate test data
- Should cover edge cases human understands

#### Major Version Upgrades
- May have breaking changes
- Requires reading migration guides
- May need code changes throughout codebase

---

## Fix Type Reference

When reporting findings, use these `fix_type` values:

| fix_type | Description | Auto-fixable |
|----------|-------------|--------------|
| `eslint_fix` | ESLint --fix can handle it | Yes |
| `prettier_fix` | Prettier --write can handle it | Yes |
| `npm_audit_fix` | npm audit fix (non-breaking) | Yes |
| `remove_line` | Simply delete the line | Yes |
| `remove_import` | Remove unused import | Yes |
| `add_type` | Add TypeScript type annotation | Medium |
| `add_memo` | Wrap with React.memo | Medium |
| `refactor` | Needs code restructuring | No |
| `config_change` | Needs config file update | Maybe |
| `architectural` | Needs architectural change | No |
| `test_implementation` | Needs test code written | No |
| `documentation` | Needs docs written | No |

---

## Multi-Agent Fix Coordination

When running in multi-agent mode (`/audit --worker`), follow these additional rules:

### Category Ownership

Each agent is assigned specific audit categories (see `multi-agent-config.md` for assignments). During the fix cycle:

- **Only fix findings in your assigned categories.** If you discover an issue that belongs to another agent's category, record it as a `cross_category_finding` but do NOT modify the code.
- **Example:** Agent 0 (Security, Dependencies, ToS & Compliance) finds an unused import while auditing for security console.log leaks. Record it as a cross-category finding for Code Quality, but don't fix it - that's Agent 1's job.

### Commit Message Format (Multi-Agent)

In multi-agent mode, use a shorter commit format to keep merge history clean:

```
audit({category}): {brief title}
```

**Examples:**
```
audit(security): remove PII-leaking console.log
audit(dependencies): npm audit fix for 3 vulnerabilities
audit(code-quality): remove 12 unused imports
audit(typescript): add return types to exported hooks
audit(architecture): extract shared utility from god object
audit(performance): add React.memo to ExpensiveList
audit(testing): add test stubs for untested hooks
audit(documentation): add JSDoc to public API functions
```

**Do NOT include the full multi-line format** used in single-session mode. The combined PR description (created during `--collect`) will contain all finding details.

### Fix Isolation

Each agent works on its own branch. Since agents audit different categories, file-level conflicts should be rare. However:

- **Same-file conflicts can occur** when two categories overlap (e.g., Security removes a console.log on line 45, Code Quality removes an unused import on line 3 of the same file). If a conflict is detected during `--collect`, the process **halts and writes a conflict report** — it does NOT silently resolve with `--ours`. See `multi-agent-config.md` for the conflict resolution protocol.
- **Never modify files solely owned by another category.** For example, if `package.json` changes are needed for both Dependencies and Testing, only Agent 0 (Dependencies) should modify `package.json`. Agent 3 (Testing) should record the needed change as a cross-category finding.

### Shared Files (Conflict-Prone)

These files are commonly touched by multiple categories. Only the highest-priority agent should modify them:

| File | Owner Agent | Categories That Might Touch It |
|------|-------------|-------------------------------|
| `package.json` | Agent 0 (Dependencies) | Dependencies, Testing |
| `tsconfig.json` | Agent 1 (TypeScript) | TypeScript, Architecture |
| `.eslintrc` / `eslint.config.js` | Agent 1 (Code Quality) | Code Quality, TypeScript |
| `vite.config.ts` | Agent 2 (Performance) | Performance, Architecture |

If a non-owner agent needs a change to a shared file, record it as a cross-category finding.

---

## Verification Commands by Project Type

### TypeScript + React (Vite)
```bash
npm run lint          # or: npx eslint src/
npm run type-check    # or: npx tsc --noEmit
npm run test:run      # or: npx vitest run
```

### TypeScript + React (CRA)
```bash
npm run lint
npx tsc --noEmit
npm test -- --watchAll=false
```

### Node.js Backend
```bash
npm run lint
npm run type-check
npm test
```

### Monorepo (Turborepo/Nx)
```bash
npm run lint          # runs across all packages
npm run type-check    # runs across all packages
npm run test          # runs across all packages
```

---

## Commit Message Format

```
audit: {category} - {brief title}

Auto-fixed by /audit skill.
Finding: {full description}
File: {file}:{line}
Fix type: {fix_type}
```

**Examples:**
```
audit: code-quality - Remove unused import

Auto-fixed by /audit skill.
Finding: Unused import 'lodash' in utils.ts
File: src/utils.ts:3
Fix type: eslint_fix
```

```
audit: typescript - Add return type to getUser

Auto-fixed by /audit skill.
Finding: Missing return type on exported function
File: src/api/users.ts:15
Fix type: add_type
```
