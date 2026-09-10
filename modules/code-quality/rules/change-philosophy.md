# Change Philosophy: Elegant Integration

When changing an existing system, do not patch, bolt on, or work around. For each change, ask how the system would look if the change had been a foundational assumption from the start, then refactor toward that. The result should read as if it was always designed this way.

In practice: understand the full system the change touches before adding to it, prefer making a difference a parameter over duplicating logic with variations, and leave the system more coherent than before.

## Do Not Preserve Backward Compatibility

Compatibility shims are how "bolted on" happens: a second code path kept alive so an old shape can coexist with the new one. When a change makes an old shape wrong, delete the old shape and update every caller in the same change.

Delete rather than preserve:

- Deprecated aliases, wrappers, and re-exports kept "just in case"
- Readers for a format nothing writes any more
- Version flags with exactly one live value
- Adapters for callers that no longer exist
- `if (legacy)` branches nothing sets `legacy` for
- Dead options left in a signature so an old call site still type-checks

Compatibility doubles the paths under test, hides which one is real, and defers a rename that costs minutes now and an archaeology session later.

### Where Compatibility Is a Real Requirement

Compatibility is a requirement when something outside this change depends on the old shape and cannot be updated with it:

- Published APIs, packages, or CLIs with consumers you do not control
- On-disk data, databases, or persisted state already in the field
- Wire protocols between independently deployed peers
- Anything under a stated support or versioning commitment

Treat it as a requirement, not a reflex: name it in the spec, write the migration, version the break deliberately.

### The Grep Test

Before keeping any compatibility path, find its callers:

```bash
grep -rn "old_function_name" src/ tests/ scripts/
```

If the only hits are the definition and the shim, delete both. If you cannot name the caller, there is no caller. For a published surface the callers are outside the repo, which is exactly why that case is a requirement rather than a reflex.

## When to Apply

Adding features to existing code, fixing bugs that reveal a design flaw, integrating a new dependency, extending a data model, renaming or reshaping anything with callers inside the repo.

## When Not to Apply

Trivial one-line fixes where the existing design is fine, time-critical hotfixes (patch now, redesign later), code you do not own or fully understand yet, cases where the elegant solution would rewrite half the codebase for a minor feature, and surfaces with consumers outside this change.

## Example

Bolted on:

```typescript
// Added special case for premium users
if (user.isPremium) {
  // duplicate 40 lines of logic with slight variations
}
```

Redesigned as if foundational:

```typescript
// Tier-aware from the start
const config = getTierConfig(user.tier)
return processWithConfig(data, config)
```
