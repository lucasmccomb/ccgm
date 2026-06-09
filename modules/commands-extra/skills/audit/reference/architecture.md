# Architecture Audit Patterns

Reference patterns for the architecture audit agent. Based on architecture-antipatterns.tech, Clean Architecture principles, and common structural issues.

## 1. Structural Antipatterns

### Big Ball of Mud
A system lacking discernible architecture - everything depends on everything.

**Indicators**:
- No clear module boundaries
- Any file can import from any other file
- Circular dependencies everywhere
- Changes cascade unpredictably

**Detection**:
- Count import depth (imports importing imports)
- Map all imports and look for cycles
- Check if there's any layering at all

### God Object / Blob
A single class/module that does everything.

**Indicators**:
- File >1000 lines with many unrelated functions
- Class with >20 methods
- Module imported by >50% of codebase
- Names like `utils.ts`, `helpers.ts`, `common.ts` with 500+ lines

**Detection**:
```
# Files with too many exports
grep -c "export" file.ts  # If >30, investigate

# Files imported everywhere
grep -r "from './utils'" --include="*.ts" | wc -l
```

### Spaghetti Code
Tangled control flow, hard to trace execution.

**Indicators**:
- Excessive use of global state
- Functions that modify distant state
- Callbacks nested 5+ levels deep
- Event chains that are hard to follow

## 2. Dependency Issues

### Circular Dependencies
Module A imports B, B imports A (directly or transitively).

**Detection**:
```bash
# Using madge (if available)
npx madge --circular src/

# Manual detection - look for:
# A.ts: import { x } from './B'
# B.ts: import { y } from './A'
```

**Severity**:
- Direct circular (A↔B): High
- Transitive circular (A→B→C→A): Medium
- Circular in types only: Low

### Dependency Direction Violations
Lower layers depending on higher layers.

**Clean Architecture Layers** (outer → inner):
```
Frameworks/UI → Controllers/Presenters → Use Cases → Entities
```

**Violations to Flag**:
- Domain/entities importing from UI components
- Business logic importing React components
- Database layer importing API handlers
- Shared/common importing from features

**Pattern**:
```
src/
├── domain/        # Should have NO imports from other src/ folders
├── application/   # Can import from domain/
├── infrastructure/# Can import from domain/, application/
└── presentation/  # Can import from all above
```

### Improper Layering
Missing or violated layer boundaries.

**Signs**:
- UI components making direct database calls
- API routes containing business logic
- Components fetching data AND rendering AND handling state
- No separation between data access and business rules

## 3. Modularity Issues

### Over-Modularization
Too many tiny modules with excessive indirection.

**Indicators**:
- Files with <20 lines that just re-export
- Folders with single files
- Deep folder nesting (>5 levels)
- Index files that only export from submodules
- Every function in its own file

### Under-Modularization
Too few modules, everything lumped together.

**Indicators**:
- Feature folders with 20+ files
- Single `components/` folder with 100+ components
- No logical grouping of related functionality
- `utils.ts` with 50+ unrelated functions

### Recommended Structure
```
src/
├── features/           # Feature-based modules
│   ├── auth/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── types.ts
│   └── photos/
├── shared/             # Truly shared code
│   ├── components/     # Generic UI components
│   ├── hooks/          # Generic hooks
│   └── utils/          # Generic utilities
└── infrastructure/     # External concerns
    ├── api/
    ├── database/
    └── storage/
```

## 4. Coupling Issues

### Tight Coupling
Components that can't function independently.

**Indicators**:
- Component A can't be tested without Component B
- Changing one file always requires changing another
- Shared mutable state between modules
- Direct DOM manipulation from business logic

### Feature Envy
Module using another module's internals extensively.

**Pattern**:
```javascript
// Bad - OrderService knows too much about Customer internals
function calculateShipping(customer) {
  const address = customer._data.addresses.find(a => a._isPrimary)
  const zone = address._zone._regionCode
  // ...
}

// Better - Ask, don't tell
function calculateShipping(customer) {
  const zone = customer.getShippingZone()
  // ...
}
```

### Inappropriate Intimacy
Modules reaching into each other's private parts.

**Indicators**:
- Accessing `_private` properties
- Using internal implementation details
- Importing from deep paths (`../../../internal/thing`)

## 5. Horizontal Slicing (Antipattern)

Organizing by technical layer instead of feature.

**Antipattern Structure**:
```
src/
├── components/     # All components from all features
├── hooks/          # All hooks from all features
├── services/       # All services
└── types/          # All types
```

**Why It's Bad**:
- Related code scattered across folders
- Hard to find all code for a feature
- Encourages coupling between unrelated features
- Makes feature deletion difficult

**Better - Vertical Slicing**:
```
src/
├── features/
│   ├── auth/       # All auth-related code together
│   └── photos/     # All photo-related code together
└── shared/         # Only truly shared code
```

## 6. Missing Abstractions

### Direct External Dependencies
Calling external APIs/services directly without abstraction.

**Bad**:
```javascript
// Throughout codebase
const response = await fetch('https://api.stripe.com/...')
```

**Better**:
```javascript
// Abstracted
const payment = await paymentService.charge(amount)
```

**Check for**:
- Direct `fetch()` calls to external APIs scattered in code
- Database queries in components
- Third-party SDK calls without wrapper

### Missing Repository Pattern
Data access logic mixed with business logic.

**Bad**:
```javascript
async function getActiveUsers() {
  const users = await db.query('SELECT * FROM users WHERE active = true')
  return users.map(u => ({ ...u, fullName: `${u.first} ${u.last}` }))
}
```

**Better**:
```javascript
// Repository
const users = await userRepository.findActive()
// Business logic
return users.map(toUserDTO)
```

## 7. Monorepo-Specific Issues

### Cross-Package Violations
Packages importing directly from other packages' internals.

**Bad**:
```javascript
// In packages/web
import { internal } from '../../packages/shared/src/internal'
```

**Good**:
```javascript
import { exported } from '@myorg/shared'
```

### Missing Package Boundaries
Monorepo without proper package.json in each package.

**Check**:
- Each `apps/*` and `packages/*` has its own `package.json`
- Dependencies declared at package level, not just root
- Proper peer dependencies declared

## Severity Guidelines

| Severity | Criteria |
|----------|----------|
| **Critical** | Circular deps blocking builds, completely missing architecture |
| **High** | Significant coupling issues, dependency direction violations |
| **Medium** | Over/under modularization, missing abstractions |
| **Low** | Minor structural issues, non-ideal but functional patterns |
