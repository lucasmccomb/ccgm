# {Feature} — Argus spec (prose half)

> The machine-readable contract lives beside this file in `spec.json` (validated by
> `references/spec.schema.json`). This file carries the **acceptance criteria and component
> contracts** the judge reads as `spec-text`. Keep prose here; keep structure in `spec.json`.

## Intent

One paragraph: what this feature is, who uses it, what "done" feels like. The judge reads this to
understand the target, not to score pixels.

## Targets

### `list`

**Acceptance criteria** (functional_correctness, spec-text anchor):
- [ ] The populated state shows one row per item, newest first.
- [ ] Each row exposes a primary action with an accessible label.
- [ ] The empty state shows the create affordance and one line of guidance.

**Component contract — populated**: a scrollable list; each row = title + subtitle + primary action.
**Component contract — empty**: centered empty-state = illustration + one line of copy + create button.

**State / appearance deltas** (so you supply ≤1 reference image, not one per combination):
- *empty*: same chrome as populated, list replaced by the empty-state block described above.
- *light*: same composition as the dark reference; surfaces and text invert per the design-system
  light tokens. No layout change.

**Accessibility contract** (ids enumerated in `spec.json` `a11y_contract`, documented as-found —
never invent a new id scheme):
- `screen.example`, `state.example.empty`, `button.createItem`, `row.item.*`

## Out of scope

List anything the loop must NOT touch so the implementer subagent does not creep.
