# Frontend CSS Gotchas

## Tailwind v4: cursor: pointer Missing on Interactive Elements

**Problem**: Tailwind v4's preflight does NOT set `cursor: pointer` on `<button>` elements. Browsers default to `cursor: default` for buttons, so every clickable thing on the page looks non-interactive on desktop.

**Rule**: When starting any new project with Tailwind v4, add cursor: pointer base styles immediately - before writing any components.

### Pattern (put this in a shared CSS file imported by all apps)

```css
/* packages/ui/src/theme/base.css or equivalent */
@layer base {
  button,
  [role="button"],
  [type="button"],
  [type="reset"],
  [type="submit"],
  a[href],
  label[for],
  select,
  summary {
    cursor: pointer;
  }

  [disabled],
  [aria-disabled="true"] {
    cursor: not-allowed;
  }
}
```

### Where to put it

- **Monorepo with shared UI package**: Add to `packages/ui/src/theme/base.css`, import in each app's CSS entry point after `@import 'tailwindcss'`
- **Single app**: Add directly to `src/index.css` or `src/globals.css` after `@import 'tailwindcss'`
- **Next.js**: Add to `app/globals.css` or `styles/globals.css`

### Import order matters

```css
@import 'tailwindcss';
@import './base.css';   /* cursor: pointer and other base resets */
@import './tokens.css'; /* design tokens */
```

The base import must come after `tailwindcss` so `@layer base` is available, but before component styles.

### Why this happens

Tailwind v4 changed their preflight philosophy - they removed the `cursor: pointer` override that existed in v3. The browser's native stylesheet sets `cursor: default` on `<button>`, which takes precedence unless explicitly overridden. This affects:
- All `<button>` elements (form submits, icon buttons, toggles)
- Custom interactive divs without a `cursor-pointer` class
- Select dropdowns, file inputs, etc.
