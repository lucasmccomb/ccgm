# code-quality

Code standards, testing requirements, error handling patterns, security practices, build verification, and living documents maintenance.

## What It Does

This module installs a rules file that instructs Claude to:

- Follow consistent code standards (environment variables, database migrations, dependencies, component patterns, path aliases)
- Write tests for new features, edge cases, bug fixes, and complex logic
- Apply structured error handling patterns for both frontend and backend
- Enforce security practices (input sanitization, upload validation, secrets management, RLS)
- Run full build verification before pushing code
- Maintain living documents (README, project story) after PR merges

## Manual Installation

Copy `rules/code-quality.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/code-quality.md ~/.claude/rules/code-quality.md

# Project-level
cp rules/code-quality.md .claude/rules/code-quality.md
```

## Files

| File | Description |
|------|-------------|
| `rules/code-quality.md` | Rule file covering code standards, testing, error handling, security, build verification, and living documents |
| `rules/change-philosophy.md` | Rule file on elegant integration: redesign existing systems rather than bolting on |
| `rules/completeness.md` | Rule file on the Boil-the-Lake completeness principle and scoring rubric |
