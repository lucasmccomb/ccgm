# Code Quality Standards

## Code Standards

### Environment Variables

- When adding new env vars, update the corresponding `.env.example` file
- Never commit actual secrets or API keys

### Database Changes

- New migrations require regenerating TypeScript types
- Document schema changes in the migration file comments
- After merging a PR with migrations, run them immediately. Do not defer migration execution to manual follow-up issues.

#### Migration Validation (REQUIRED)

**Before committing any migration file**, validate it will run without errors:

1. **Quote reserved keywords** - These PostgreSQL reserved words must be double-quoted when used as identifiers:
   - `position`, `order`, `user`, `offset`, `limit`, `key`, `value`, `type`, `name`, `check`, `default`, `time`, `index`, `comment`
   - Example: `"position" integer` not `position integer`

2. **Use idempotent patterns**:
   - Functions: `CREATE OR REPLACE FUNCTION`
   - Triggers: `DROP TRIGGER IF EXISTS ... ; CREATE TRIGGER ...`
   - Indexes: `CREATE INDEX IF NOT EXISTS`
   - Tables: `CREATE TABLE IF NOT EXISTS` (when appropriate)
   - Columns: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
   - Policies: `DROP POLICY IF EXISTS ... ; CREATE POLICY ...`

3. **Test locally before committing** (prefer non-destructive methods):
   ```bash
   # Preferred: Apply only pending migrations (preserves local data)
   supabase migration up

   # Alternative: Full reset (wipes all local data)
   supabase db reset
   ```
   Use `migration up` for iterative development. Use `db reset` only when you need a clean slate or are debugging migration order issues.

4. **Common gotchas**:
   - `ON CONFLICT` requires a unique constraint on the conflict columns
   - `SECURITY DEFINER` functions run as the owner, not the caller
   - RLS policies need `USING` (for SELECT/UPDATE/DELETE) and/or `WITH CHECK` (for INSERT/UPDATE)

### Dependencies

- Justify new npm packages in PR description
- Prefer well-maintained packages with good TypeScript support

### Component Patterns (React/TypeScript)

```typescript
// Always use functional components with TypeScript
interface ComponentProps {
  // Define props with explicit types
}

export function Component({ prop1, prop2 }: ComponentProps) {
  return <div className="container">...</div>;
}
```

### Path Aliases

Use path aliases for clean imports:
- `@/` -> `src/`
- `@components/` -> `src/components/`
- `@hooks/` -> `src/hooks/`
- `@services/` -> `src/services/`
- `@types/` -> `src/types/`

---

## Testing

Write tests for:
- **New features** - cover the happy path and key functionality
- **Edge cases** - empty states, boundary conditions, invalid inputs
- **Bug fixes** - add a test that reproduces the bug before fixing
- **Complex logic** - utilities, hooks, business logic

---

## Error Handling

### Frontend (React)
- Use error boundaries to wrap major sections
- Show toast notifications for user feedback
- Validate forms before submit with inline errors
- Handle loading and error states in data fetching

### Backend
- Centralized error middleware for consistent responses
- Never leak internal details - generic messages to client, detailed logs server-side

### General Principles
- Fail fast in development (throw, don't swallow)
- Graceful degradation in production
- Always give users actionable feedback
- Log errors for debugging

---

## Security

- Sanitize user input before rendering (DOMPurify for HTML)
- Validate image uploads (MIME type, size limits)
- Never commit .env files or secrets
- Use Row Level Security (RLS) for database access control
- Review all user-facing inputs for injection risks (SQL, XSS)

---

## Build Verification

**IMPORTANT**: After making code changes, run verification and fix any issues before completing work.

All checks must pass. Fix errors immediately - don't leave broken code.

- **Never** leave failing tests, type errors, or lint errors
- **Never** mark work as complete until all checks pass
- **Update** documentation if requirements or architecture change

### Pre-Push Verification (CRITICAL)

**Before pushing code, run ALL the same checks that CI runs.** This prevents wasting CI minutes on failures that could be caught locally.

#### Check for Pre-Push Hook
Many projects have a `.husky/pre-push` hook that runs automatically. If present, it will block the push if checks fail.

#### If No Pre-Push Hook Exists
Manually run the full verification suite before pushing:
```bash
# Typical checks (adjust commands per project):
npm run lint           # All workspaces
npm run type-check     # TypeScript projects
npm run test:run       # All test suites
npm run build          # Ensure build succeeds
```

#### Why This Matters
- CI minutes cost money (GitHub Actions, etc.)
- Failed CI = wasted time waiting for feedback
- Local checks are faster than round-trip to CI
- Catches issues before they're visible to the team

#### Adding Pre-Push Hooks to Projects
If a project doesn't have a pre-push hook, consider adding one:
```bash
# .husky/pre-push (make executable with chmod +x)
#!/bin/sh
npm run lint && npm run type-check && npm run test:run && npm run build
```

---

## Living Documents

Some projects maintain living documents (`README.md`, `docs/project-story.md`) that stay current with the codebase. After merging a PR, check whether living documents need updating.

### Post-PR-Merge Check

After every PR merge, before moving to the next task:

1. Check if the repo has a `README.md` and/or `docs/project-story.md`
2. If they exist, evaluate whether the merged PR warrants an update (see criteria below)
3. If yes, update the relevant file(s) in 5-10 minutes - not a rewrite, just targeted additions
4. Commit the updates as part of the current branch or as a fast-follow

### When to Update README.md

Update when the PR:
- Adds or removes a package
- Changes extension capabilities or permissions
- Changes dev commands, build system, or verification steps
- Changes external APIs, services, or required permissions
- Changes pricing, payment flow, or deployment configuration
- Adds significant new test coverage

**How**: Find the affected section. Add/modify the relevant table row, code block, or bullet. Keep it factual and terse.

### When to Update docs/project-story.md

Update when the PR:
- Represents a notable architectural decision or reversal
- Fixes a non-obvious bug with an interesting root cause
- Introduces or eliminates a pattern across the codebase
- Represents a methodology change (tooling, workflow, agent coordination)
- Is part of a new epic or phase
- Has an interesting human decision behind it

**How**: Find the section closest to the PR's topic. Add 2-5 sentences in narrative voice. If no section fits, add a new subsection.

### When NOT to Update

- Typo fixes, dependency bumps, or documentation-only changes
- Changes already well-described by the PR title
- The living document already covers the topic and the PR doesn't change the answer

### Scope Discipline

Living doc updates should take 5-10 minutes, not 30. If an update requires re-reading the entire codebase, add a new subsection and move on.
