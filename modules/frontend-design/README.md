# frontend-design

Principles for distinctive, production-grade web UI design.

## What It Does

Installs a rules file covering 5 core design principles:

1. **Intentional Aesthetics** - Choose and commit to a clear design direction
2. **Typography** - Type scale hierarchy, font pairing, weight and spacing
3. **Color Systems** - Cohesive palettes, semantic tokens, contrast ratios, dark mode
4. **Spatial Composition** - Consistent spacing scale, whitespace hierarchy, layout variety
5. **Motion and Interaction** - Purposeful animation, appropriate durations, reduced motion support

Explicitly warns against generic AI-generated aesthetics: purple gradients, default frameworks, inconsistent patterns.

## Manual Installation

```bash
# Global (all projects)
cp rules/frontend-design.md ~/.claude/rules/frontend-design.md

# Project-level
cp rules/frontend-design.md .claude/rules/frontend-design.md
```

## Files

| File | Description |
|------|-------------|
| `rules/frontend-design.md` | Design principles, anti-patterns, and implementation checklist |
