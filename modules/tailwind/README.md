# tailwind

Tailwind CSS v4 design system patterns.

## What It Does

Installs a rules file covering Tailwind v4 architecture:

- **CSS-first configuration** - Use @theme in CSS instead of tailwind.config.ts
- **Design token hierarchy** - Primitive, semantic, and component token layers
- **OKLCH color system** - Perceptually uniform colors with full scales
- **CVA component variants** - Type-safe variant composition with class-variance-authority
- **Dark mode** - Class-based switching with @custom-variant, context providers, localStorage persistence
- **Responsive patterns** - Mobile-first, grid variants, size-* shorthand
- **Native CSS animations** - @keyframes in @theme, @starting-style for entry animations
- **v3 to v4 migration** - Reference table for common pattern changes

## Manual Installation

```bash
# Global (all projects)
cp rules/tailwind.md ~/.claude/rules/tailwind.md

# Project-level
cp rules/tailwind.md .claude/rules/tailwind.md
```

## Files

| File | Description |
|------|-------------|
| `rules/tailwind.md` | Tailwind v4 design system guide with tokens, CVA, dark mode, and migration notes |
