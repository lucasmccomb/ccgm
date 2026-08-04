# tailwind

Tailwind CSS v4 design system patterns.

## What It Does

Installs two rules files covering Tailwind v4 architecture and a known gotcha:

- **CSS-first configuration** - Use @theme in CSS instead of tailwind.config.ts
- **Design token hierarchy** - Primitive, semantic, and component token layers
- **OKLCH color system** - Perceptually uniform colors with full scales
- **CVA component variants** - Type-safe variant composition with class-variance-authority
- **Dark mode** - Class-based switching with @custom-variant, context providers, localStorage persistence
- **Responsive patterns** - Mobile-first, grid variants, size-* shorthand
- **Native CSS animations** - @keyframes in @theme, @starting-style for entry animations
- **v3 to v4 migration** - Reference table for common pattern changes
- **cursor: pointer gotcha** - Tailwind v4 preflight drops `cursor: pointer` on buttons; base-style fix and where to put it

## Manual Installation

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/tailwind.md ~/.claude/rules/tailwind.md
cp rules/frontend-css.md ~/.claude/rules/frontend-css.md

# Project-level
mkdir -p .claude/rules
cp rules/tailwind.md .claude/rules/tailwind.md
cp rules/frontend-css.md .claude/rules/frontend-css.md
```

## Files

| File | Description |
|------|-------------|
| `rules/tailwind.md` | Tailwind v4 design system guide with tokens, CVA, dark mode, and migration notes |
| `rules/frontend-css.md` | Tailwind v4's missing `cursor: pointer` on buttons - base-style fix and where to put it in a project |
