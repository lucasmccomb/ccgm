# Change Philosophy: Elegant Integration

When making changes to an existing system, do not patch, bolt on, or work around. Instead:

**For each change, examine the existing system and redesign it into the most elegant solution that would have emerged if the change had been a foundational assumption from the start.**

## What This Means in Practice

- Before adding a feature, understand the full system it touches
- Ask: "If we had known about this requirement from day one, how would the system look?"
- Refactor toward that ideal rather than adding layers of special cases
- The result should look like it was always designed this way

## Do Not Preserve Backward Compatibility

Compatibility shims are how "bolted on" happens. The shim *is* the special case: a second code path, kept alive so an old shape can coexist with the new one. Keep enough of them and the system stops having a design and starts having a history.

When a change makes an old shape wrong, delete the old shape. Update every caller in the same change.

Delete rather than preserve:

- Deprecated aliases, wrappers, and re-exports kept "just in case"
- Readers for a format nothing writes any more
- Version flags with exactly one live value
- Adapters for callers that no longer exist
- `if (legacy)` branches nothing sets `legacy` for
- Dead options left in a signature so an old call site would still type-check

Migrate the callers instead. Compatibility is not free: it doubles the paths under test, hides which one is real, and defers a rename that costs minutes now and an archaeology session later.

### Where Compatibility Is a Real Requirement

Compatibility is a requirement when something outside this change depends on the old shape and cannot be updated with it:

- Published APIs, packages, or CLIs with consumers you do not control
- On-disk data, databases, or persisted state that already exists in the field
- Wire protocols between independently deployed peers
- Anything under a stated support or versioning commitment

Where compatibility is genuinely required, treat it as a requirement, not a reflex: name it in the spec, write the migration, and version the break deliberately. What this rule forbids is preserving the old shape out of caution when nothing depends on it.

### The Grep Test

Before keeping any compatibility path, find its callers:

```bash
grep -rn "old_function_name" src/ tests/ scripts/
```

If the only hits are the definition and the shim, delete both. **If you cannot name the caller, there is no caller.** "Something might use it" is a guess; the grep is the answer.

For a published surface, the callers are outside the repo - which is exactly why that case is a requirement instead of a reflex. Everywhere else, the repo is the whole world.

### Rationalizations

| You are about to say... | The reality is... |
|-------------------------|-------------------|
| "Something might still call the old one" | Grep. If nothing calls it, nothing calls it. Keeping it costs a permanent second code path to avoid a search that takes seconds. |
| "I'll deprecate it now and remove it later" | Later does not come. The deprecation comment becomes the documentation, and the shim outlives everyone who understood it. |
| "Removing it is a breaking change" | Internal code has no consumers to break. A change is only breaking if someone outside this change depends on it - name them or delete it. |
| "Keeping the old path is the safe option" | Two live paths is the unsafe option. Tests cover one, production takes the other, and nobody knows which. |
| "It's only a small alias" | Small aliases are what codebases fill up with. Each one is individually free and collectively the reason nothing can be renamed. |
| "Updating every caller is out of scope" | Updating callers is the change. Half a rename leaves the codebase worse than before it started. |
| "I'll leave the old param so existing calls still compile" | A parameter nothing reads is a lie the signature tells the next reader. Remove it and fix the call sites. |

## When to Apply

- Adding new features to existing code
- Fixing bugs that reveal a design flaw
- Integrating a new dependency or service
- Extending a data model
- Renaming or reshaping anything with callers inside the repo

## When NOT to Apply

- Trivial one-line fixes where the existing design is fine
- Time-critical hotfixes (patch now, redesign later)
- Changes to code you don't own or understand fully yet
- When the "elegant" solution would require rewriting half the codebase for a minor feature
- Surfaces with consumers outside this change (see "Where Compatibility Is a Real Requirement")

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

## Red Flags

Stop and redesign if you catch yourself:

- Adding a branch, flag, or wrapper whose only job is keeping an older shape working
- Writing "deprecated" in a comment instead of deleting the thing
- Leaving a parameter, field, or export in place so old call sites still compile
- Duplicating logic with slight variations rather than making the difference a parameter
- Keeping a code path because "something might use it" without running the grep
- Calling a half-finished rename done because the alias makes it build
