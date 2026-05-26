# Argus — Visual-ATDD Convergence Loop

Argus is a closed-loop harness for developing UI against a per-feature design spec where the agent
**signs off on its own work** — functional and visual — because every judgment is grounded in an
external signal, not introspection. Invoke it with `/argus feature:{name}`.

## When to use `/argus`

- Building or refining a UI feature against a design spec + reference screenshots.
- You want autonomous fix-and-recheck iteration with minimal human direction (≤1 reference image per
  screen + one spot-check), not hand-judging every change.
- A feature has an Argus spec at `argus/specs/{feature}/` (or you are about to author one from
  `~/.claude/skills/argus/references/_template/`).

## When NOT to use it

- Bug fixes with no visual/spec target (use `/debug`).
- Backend-only work, or a feature with no reference and no intent to supply one.
- Pure refactors (the snapshot baseline guards the look; Argus is for *changing* the UI to a target).

## The integrity principle (why self-sign-off is trustworthy here)

Ungrounded self-critique is epistemically inert. Argus is only trustworthy because:

1. **Deterministic gates are the floor** (build/lint/type/contrast/a11y/snapshot/flows). The judge
   never runs while a gate is red.
2. **The judge is a SEPARATE subagent** (`argus-judge`) that sees the spec, the reference, the design
   tokens, the render, and the probe — **never the diff**. Coupled self-grading inflates grades.
3. **Two oracles**: the structured probe (functional) + the screenshot (perceptual).
4. **Convergence is bounded**: two consecutive passes to sign off; three attempts per dimension then
   freeze + document. No death loops, no infinite "one more fix."

If you find yourself scoring a render in the main context, or handing the judge the diff, stop — that
breaks the property that makes the sign-off mean anything.

## Platform-agnostic by design

The loop, judge, schemas, and deterministic gates are generic. Each project plugs in a **sensor**
(`capture` + `probe`) and optional **gates adapter** for its stack. A web adapter is built in; iOS,
macOS, or anything that renders a screen + exposes a structured tree can be added. See
`~/.claude/skills/argus/references/adapter-contract.md`.
