# shadcn/ui Patterns

Guidelines for working with shadcn/ui components in React projects.

## Core Approach

### Composition Over Custom

Always search the shadcn registry before building custom components.

```bash
# Check project context
npx shadcn@latest info --json

# Search for existing components
npx shadcn@latest docs <component>

# Preview before installing
npx shadcn@latest add <component> --dry-run --diff
```

Combine existing components rather than building from scratch. A settings page combines Tabs, Card, and form controls. A data view combines Table, Pagination, and Dialog.

### Semantic Theming

Use theme tokens, not raw color values:

- `bg-primary`, `text-primary-foreground` - not `bg-blue-500`, `text-white`
- `bg-muted`, `text-muted-foreground` - not `bg-gray-100`, `text-gray-500`
- `bg-destructive`, `text-destructive-foreground` - not `bg-red-500`, `text-white`

Never hardcode colors. Never add manual `dark:` overrides - the theme system handles this.

## Component Patterns

### Forms

Use FieldGroup + Field containers with proper semantic structure:

- Wire up `aria-invalid` and `aria-describedby` for validation states
- Use `data-invalid` attributes for styling error states
- Pair every input with a Label component

### Layout

- Use `flex` with `gap-*` instead of `space-x-*` or `space-y-*`
- Use `size-*` shorthand instead of separate `w-*` and `h-*` when equal
- Use `cn()` utility for conditional class merging

### Icons in Buttons

Use `data-icon` attributes on icons inside buttons. Do not add sizing classes to icons directly - let the button component manage icon sizing.

### Overlays (Dialog, Sheet, Drawer)

- Always include a Title element for accessibility
- Use `className="sr-only"` to visually hide the title when not needed
- Never manually set z-index on overlay components

## Workflow

### Adding Components

1. Search the registry first
2. Preview with `--dry-run --diff`
3. Install the component
4. Customize by editing the installed source (these are your files, not a dependency)

### Switching Presets/Themes

Three approaches when changing visual presets:

- **Reinstall**: Overwrites component files (clean but loses customizations)
- **Merge**: Intelligently updates (preserves customizations)
- **Skip**: Keep current version

### Conventions

- Never decode preset codes manually
- Never manually set z-index on overlay components
- Use `cn()` for all conditional class composition
- Keep component source files in `components/ui/` directory
