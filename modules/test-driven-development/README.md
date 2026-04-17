# test-driven-development

Strict red-green-refactor TDD discipline for all new features and bug fixes.

## What It Does

Installs a rules file that enforces test-first development:

- **RED** - Write a failing test that demonstrates desired behavior
- **GREEN** - Write the simplest code to make it pass
- **REFACTOR** - Clean up while keeping tests green

Covers new features (test each behavior incrementally), bug fixes (reproduce first, then fix), test quality standards, and when TDD may be skipped (with user approval).

## Manual Installation

```bash
# Global (all projects)
cp rules/test-driven-development.md ~/.claude/rules/test-driven-development.md
cp rules/testing-anti-patterns.md ~/.claude/rules/testing-anti-patterns.md

# Project-level
cp rules/test-driven-development.md .claude/rules/test-driven-development.md
cp rules/testing-anti-patterns.md .claude/rules/testing-anti-patterns.md
```

## Files

| File | Description |
|------|-------------|
| `rules/test-driven-development.md` | TDD methodology with cycle rules, quality standards, and skip criteria |
| `rules/testing-anti-patterns.md` | Five testing mistakes agents default to under pressure, each with a Gate Function |
