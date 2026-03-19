# /audit - Codebase Audit with Auto-Fix

Run a comprehensive codebase audit across 8 categories with optional auto-fix.

## Audit Categories

1. **Security** - Secrets in code, exposed API keys, missing input sanitization, SQL injection risks, XSS vulnerabilities, insecure dependencies
2. **Dependencies** - Outdated packages, unused dependencies, duplicate packages, missing lock files, version conflicts
3. **Code Quality** - Dead code, unused exports, large files, complex functions, inconsistent naming, missing error handling
4. **Architecture** - Circular dependencies, improper layer access, mixed concerns, missing abstractions, inconsistent patterns
5. **TypeScript/React** - Any type usage, missing return types, improper hook usage, missing error boundaries, Fast Refresh violations
6. **Testing** - Missing test coverage, untested edge cases, flaky tests, missing mocks, test anti-patterns
7. **Documentation** - Missing README sections, outdated API docs, missing JSDoc on public APIs, stale comments
8. **Performance** - Large bundle imports, missing lazy loading, unoptimized images, missing caching, N+1 queries

## Workflow

### Phase 1: Pre-Flight
- Determine project type (monorepo, single package, etc.)
- Identify available linters, formatters, and test runners
- Check for existing audit configs (.eslintrc, tsconfig strict mode, etc.)

### Phase 2: Discovery
- Map the full directory structure (use two-method verification for monorepos)
- Identify all packages, entry points, and build targets
- List all configuration files

### Phase 3: Parallel Audit
Run audit agents in parallel across the 8 categories. Each agent:
1. Scans relevant files using Glob and Grep
2. Checks against category-specific rules
3. Classifies findings as: CRITICAL, WARNING, or INFO
4. Suggests specific fixes with file paths and line numbers

### Phase 4: Collect Results
- Aggregate findings from all audit agents
- Deduplicate overlapping findings
- Sort by severity (CRITICAL first)

### Phase 5: Fix Cycle
For each fixable finding:
1. Show the finding with context
2. Apply the fix
3. Run linters/tests to verify the fix doesn't break anything
4. If the fix breaks something, revert and flag for manual review

### Phase 6: Summary
Present a summary table:
```
| Category      | Critical | Warning | Info | Fixed | Manual |
|---------------|----------|---------|------|-------|--------|
| Security      | 0        | 2       | 1    | 2     | 1      |
| Dependencies  | 1        | 3       | 0    | 3     | 1      |
| ...           | ...      | ...     | ...  | ...   | ...    |
```

### Phase 7: Issue Creation (Optional)
For findings that require manual intervention:
- Create GitHub issues with detailed descriptions
- Label with audit category and severity
- Include file paths, line numbers, and suggested fixes

## Usage

```
/audit                    # Full audit, all categories
/audit security           # Single category
/audit security,testing   # Multiple categories
/audit --fix              # Auto-fix where possible
/audit --no-issues        # Skip GitHub issue creation
```
