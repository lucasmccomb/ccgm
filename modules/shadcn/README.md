# shadcn

shadcn/ui component patterns and best practices.

`rules/shadcn.md` is path-scoped (#1061): it carries `paths:` frontmatter and loads only after Claude reads a file matching one of `**/components/ui/**`, `**/components.json`. It costs no context at session start otherwise.

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
mkdir -p ~/.claude/rules
cp rules/shadcn.md ~/.claude/rules/shadcn.md

# Project-level
mkdir -p .claude/rules
cp rules/shadcn.md .claude/rules/shadcn.md
```

## Files

| File | Description |
|------|-------------|
| `rules/shadcn.md` | shadcn/ui patterns covering composition, theming, forms, and workflow |
