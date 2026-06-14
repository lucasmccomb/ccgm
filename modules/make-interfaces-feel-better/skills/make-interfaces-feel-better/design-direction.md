# Design Direction

High-level design decisions that set a distinctive visual identity, before the implementation-level polish in the other reference files. The rest of this skill (typography rendering, surfaces, animations, performance) makes a chosen direction feel right; this file is about *choosing the direction* and avoiding generic, cookie-cutter UI that looks like every other AI-generated interface.

> This reference is a CCGM addition, not part of the upstream `make-interfaces-feel-better` repo. When refreshing the other files from upstream, leave this one in place.

## 1. Intentional Aesthetics

Choose a clear design direction and commit to it. Every project should have a distinct visual identity, not a default Bootstrap or Material look.

- Pick a direction: minimal, brutalist, editorial, playful, corporate, retro — whatever fits the product
- Execute it consistently across every component and page
- When in doubt, reference the project's existing design language before inventing new patterns

## 2. Typography (Selection, not just Rendering)

Typeface and type-scale choices are the single highest-impact design decision. (`typography.md` covers the *rendering* details — text-wrap, font smoothing, tabular numbers — once the typefaces are chosen.)

- Choose fonts that match the product's personality (not just Inter or system fonts by default)
- Establish a clear type scale with distinct hierarchy: display, heading, subheading, body, caption
- Use font weight, size, and letter-spacing to create visual hierarchy, not just color
- Limit to 2 font families maximum (one for headings, one for body)

## 3. Color Systems

Build a cohesive color palette, not a random collection of hex values.

- Define a primary, secondary, and accent color with intentional relationships
- Use semantic color tokens (e.g., `text-primary`, `bg-surface`, `border-subtle`) not raw values
- Ensure sufficient contrast ratios (WCAG AA minimum: 4.5:1 for text, 3:1 for UI elements)
- Design for dark mode from the start if the project supports it

## 4. Spatial Composition

Layout and spacing create rhythm and readability.

- Use a consistent spacing scale (4px, 8px, 12px, 16px, 24px, 32px, 48px, 64px)
- Create visual hierarchy through whitespace, not just font size
- Break out of predictable grid layouts when appropriate (asymmetry, overlap, varied column widths)
- Generous padding and margins. When in doubt, add more space, not less.

## 5. Motion Philosophy

Animation should be purposeful, not decorative. (`animations.md` covers the implementation — interruptible transitions, enter/exit, icon micro-interactions; this is the intent behind them.)

- Focus on transitions that communicate state changes (loading, success, navigation)
- Keep durations short (150-300ms for micro-interactions, 300-500ms for page transitions)
- Use easing curves that feel natural (ease-out for entrances, ease-in for exits)
- Respect `prefers-reduced-motion` for accessibility

## What to Avoid

- **Generic AI aesthetics**: purple-to-blue gradients, overly rounded cards, generic hero sections with stock imagery
- **Framework defaults**: unstyled Bootstrap, Material Design without customization, default Tailwind gray palette
- **Inconsistency**: mixing design patterns from different systems or frameworks
- **Decoration without purpose**: shadows, borders, gradients, and icons added for visual filler rather than to communicate information

## Implementation Checklist

When building or modifying UI:

1. Check for existing design tokens, theme files, or style guides in the project
2. Follow established patterns before introducing new ones
3. Test at multiple viewport sizes (mobile, tablet, desktop)
4. Verify color contrast meets WCAG AA standards
5. Ensure interactive elements have visible focus states
6. Test with keyboard navigation
