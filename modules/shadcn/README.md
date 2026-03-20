# shadcn

shadcn/ui component patterns and best practices.

## What It Does

Installs a rules file covering shadcn/ui workflows:

- **Composition over custom** - Search the registry before building, combine existing components
- **Semantic theming** - Use theme tokens (bg-primary) not raw colors (bg-blue-500)
- **Component patterns** - Forms with FieldGroup/Field, flex with gap, icon handling, overlay accessibility
- **CLI workflow** - info, docs, add with --dry-run --diff, preset switching
- **Conventions** - cn() for class merging, no manual z-index, components in ui/ directory

## Manual Installation

```bash
# Global (all projects)
cp rules/shadcn.md ~/.claude/rules/shadcn.md

# Project-level
cp rules/shadcn.md .claude/rules/shadcn.md
```

## Files

| File | Description |
|------|-------------|
| `rules/shadcn.md` | shadcn/ui patterns covering composition, theming, forms, and workflow |
