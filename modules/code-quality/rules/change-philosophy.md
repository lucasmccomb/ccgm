# Change Philosophy: Elegant Integration

When making changes to an existing system, do not patch, bolt on, or work around. Instead:

**For each change, examine the existing system and redesign it into the most elegant solution that would have emerged if the change had been a foundational assumption from the start.**

## What This Means in Practice

- Before adding a feature, understand the full system it touches
- Ask: "If we had known about this requirement from day one, how would the system look?"
- Refactor toward that ideal rather than adding layers of special cases
- The result should look like it was always designed this way

## When to Apply

- Adding new features to existing code
- Fixing bugs that reveal a design flaw
- Integrating a new dependency or service
- Extending a data model

## When NOT to Apply

- Trivial one-line fixes where the existing design is fine
- Time-critical hotfixes (patch now, redesign later)
- Changes to code you don't own or understand fully yet
- When the "elegant" solution would require rewriting half the codebase for a minor feature

## Examples

**Bad** (bolted on):
```typescript
// Added special case for premium users
if (user.isPremium) {
  // duplicate 40 lines of logic with slight variations
}
```

**Good** (redesigned as if foundational):
```typescript
// Tier-aware from the start
const config = getTierConfig(user.tier)
return processWithConfig(data, config)
```

The goal is not perfection - it's coherence. Every change should make the system feel more intentional, not more accidental.
