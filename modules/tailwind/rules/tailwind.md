# Tailwind CSS Design System

Patterns for building design systems with Tailwind CSS v4. Emphasizes CSS-first configuration and token-based architecture.

## CSS-First Configuration (v4)

Tailwind v4 uses CSS for configuration instead of `tailwind.config.ts`:

```css
@theme {
  --color-primary: oklch(0.7 0.15 250);
  --color-surface: oklch(0.98 0.01 250);
  --spacing-page: 2rem;
  --font-display: "Cal Sans", sans-serif;
}
```

Do NOT create `tailwind.config.ts` or `tailwind.config.js` in v4 projects. All configuration belongs in CSS.

## Design Token Hierarchy

Organize tokens in three layers:

1. **Primitive tokens** - raw values (colors, sizes, font families)
2. **Semantic tokens** - purpose-driven references (`text-primary`, `bg-surface`, `border-subtle`)
3. **Component tokens** - specific UI usage (`button-bg`, `card-radius`)

Use semantic token names, not visual descriptions. `text-primary` not `dark-gray`. `bg-surface` not `light-beige`.

## Color System

Use OKLCH color space for better perceptual uniformity:

```css
@theme {
  --color-primary-50: oklch(0.97 0.02 250);
  --color-primary-100: oklch(0.93 0.04 250);
  --color-primary-500: oklch(0.65 0.15 250);
  --color-primary-900: oklch(0.30 0.10 250);
}
```

- Define full color scales (50-950) for primary, neutral, and accent palettes
- Never use hardcoded hex or rgb values in component code
- Reference tokens exclusively: `bg-primary-500` not `bg-[#3b82f6]`

## Component Variants with CVA

Use Class Variance Authority for type-safe component variants:

```typescript
import { cva, type VariantProps } from "class-variance-authority";

const button = cva("inline-flex items-center justify-center rounded-md font-medium", {
  variants: {
    variant: {
      primary: "bg-primary-500 text-white hover:bg-primary-600",
      secondary: "bg-surface border border-subtle hover:bg-muted",
      ghost: "hover:bg-muted",
    },
    size: {
      sm: "h-8 px-3 text-sm",
      md: "h-10 px-4",
      lg: "h-12 px-6 text-lg",
    },
  },
  defaultVariants: {
    variant: "primary",
    size: "md",
  },
});
```

## Dark Mode

Use class-based dark mode with `@custom-variant`:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

- Implement via a context-based theme provider
- Detect system preference with `prefers-color-scheme`
- Persist user choice to localStorage
- Test both modes for every component

## Responsive Patterns

- Mobile-first: write base styles for mobile, add breakpoint overrides for larger screens
- Use grid variants for responsive column layouts (1 column mobile, 2-3 tablet, 4-6 desktop)
- Use `size-*` shorthand when width and height are equal
- Use `gap-*` instead of `space-x-*` or `space-y-*`

## Animations

Define animations in `@theme` using native CSS `@keyframes`:

```css
@theme {
  --animate-fade-in: fade-in 0.2s ease-out;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
```

Use `@starting-style` for entry animations on elements that appear dynamically.

## Migration Notes (v3 to v4)

| v3 Pattern | v4 Pattern |
|-----------|-----------|
| `tailwind.config.ts` | `@theme` in CSS |
| `theme.extend.colors` | `--color-*` custom properties |
| Plugin-based animations | `@keyframes` in `@theme` |
| `darkMode: 'class'` | `@custom-variant dark` |
| Separate `w-*` / `h-*` | `size-*` shorthand |
