# test-driven-development

Strict red-green-refactor TDD discipline for all new features and bug fixes.

`rules/testing-anti-patterns.md` is path-scoped (#1061): it carries `paths:` frontmatter and loads only after Claude reads a file matching one of `**/*.test.*`, `**/*.spec.*`, `**/tests/**`, `**/test/**`, `**/__tests__/**`, `**/e2e/**`. It costs no context at session start otherwise.

## What It Does

Installs a rules file that enforces test-first development:

- **RED** - Write a failing test that demonstrates desired behavior
- **GREEN** - Write the simplest code to make it pass
- **REFACTOR** - Clean up while keeping tests green

Covers new features (test each behavior incrementally), bug fixes (reproduce first, then fix), test quality standards, and when TDD may be skipped (with user approval).

## Manual Installation

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/test-driven-development.md ~/.claude/rules/test-driven-development.md
cp rules/testing-anti-patterns.md ~/.claude/rules/testing-anti-patterns.md

# Project-level
mkdir -p .claude/rules
cp rules/test-driven-development.md .claude/rules/test-driven-development.md
cp rules/testing-anti-patterns.md .claude/rules/testing-anti-patterns.md
```

## Files

| File | Description |
|------|-------------|
| `rules/test-driven-development.md` | TDD methodology with cycle rules, quality standards, and skip criteria |
| `rules/testing-anti-patterns.md` | Five testing mistakes agents default to under pressure, each with a Gate Function |
