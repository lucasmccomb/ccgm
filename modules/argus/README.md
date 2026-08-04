# Argus — Visual-ATDD Convergence Loop

A closed-loop harness that lets an agent develop a UI feature against a per-feature design spec and
**sign off on its own work** — functional *and* visual — with minimal one-time human direction
(≤1 reference image per screen + one spot-check). Self-sign-off is trustworthy here because every
judgment is anchored to an external signal: deterministic gates plus a **separate** judge agent that
scores the render against the spec, a reference image, and the design system — and never sees the diff.

```
  ┌──────────────  /argus  (orchestrator skill)  ──────────────┐
  │  SPEC ──▶ implementer ──▶ DETERMINISTIC GATES ──▶ SENSOR ──▶ JUDGE (separate ctx) │
  │ (target)   (edits)        build/lint/type/         render +     argus-judge        │
  │ + reference               contrast/a11y/snapshot   probe        rubric, NO diff    │
  │ + tokens                  (red ⇒ fix, judge waits)              verdict JSON       │
  └──── sign off when rubric passes 2 iters in a row AND gates green ⇒ commit baseline ┘
```

## Why it isn't just "ask the model if it looks good"

Ungrounded self-critique is epistemically inert — a model grading its own work inflates the grade.
Argus fixes that with four structural properties:

1. **Deterministic gates are the floor.** build / lint / type / WCAG-contrast / a11y-ids / snapshot /
   flows. The judge is never dispatched while a gate is red. The VLM only judges the perceptual layer
   on top of a green floor.
2. **The judge is a separate subagent** (`argus-judge`) that sees the spec, the reference, the design
   tokens, the render, and the probe — never the diff or the implementer's rationale. Coupled
   self-grading structurally inflates grades.
3. **Two oracles.** The structured probe (accessibility tree / DOM) is the functional check; the
   screenshot is the perceptual check. The tree catches dead buttons; pixels catch slop.
4. **Bounded convergence.** Two consecutive passes to sign off; three attempts per dimension then
   freeze + document. No death loops, no infinite "one more fix."

A committed snapshot baseline then makes the look regression-proof *without* the VLM thereafter.

## Platform-agnostic by design

The loop, judge, schemas, and the two platform-agnostic gates (WCAG contrast, a11y-id assertion) are
generic. Each project plugs in a **sensor** (`capture` + `probe`) and an optional **gates adapter**
for its stack. A **web adapter is built in** (Chrome MCP / Playwright capture); an **iOS adapter**
(simctl + idb + Maestro + swift-snapshot-testing) is a documented recipe. Anything that renders a
screen and exposes a structured tree can be added. See
[`skills/argus/references/adapter-contract.md`](skills/argus/references/adapter-contract.md).

## What's in the box

| File | Role |
|------|------|
| `skills/argus/SKILL.md` | The `/argus` orchestrator loop (modes: interactive / report-only / headless) |
| `agents/argus-judge.md` | The separate judge agent (read-only tools; never sees the diff) |
| `rules/argus.md` | Lean always-on rule: what Argus is, when to use it, the integrity principle |
| `skills/argus/references/spec.schema.json` | Contract for a feature's `spec.json` |
| `skills/argus/references/verdict.schema.json` | The judge's verdict envelope |
| `skills/argus/references/gate-result.schema.json` | The deterministic gate-result shape |
| `skills/argus/references/rubric.json` | Default 7-dimension rubric (per-dimension anchor + threshold) |
| `skills/argus/references/adapter-contract.md` | How to write a sensor + gates adapter (web + iOS recipes) |
| `skills/argus/references/_template/` | `spec.json` / `spec.md` / `contrast-pairs.json` / `tokens.json` starters |
| `skills/argus/scripts/*.py`, `*.sh` | Six dependency-free deterministic helpers (below) |

### Deterministic scripts (python3 stdlib + bash + jq, no external deps)

These are the deterministic computations the loop must not do in its head:

| Script | Does |
|--------|------|
| `check_contrast.py` | WCAG 2.x contrast over `tokens.json` + declared pairs; alpha-composites; honors a whitelist |
| `a11y_assert.py` | Harvests element ids from the probe (any shape) and checks the spec's a11y contract (`*` = prefix family) |
| `loop_state.py` | Durable streak/attempt counters; emits the `should_signoff` / `fix_dimensions` / `frozen` decision |
| `verdict_validate.py` | Re-derives `all_pass`/`failed_dimensions` (and gate `all_green`) from scores — does not trust the self-report |
| `spec_lint.py` | Validates `spec.json` against the schema + checks `present` references exist; lists the HE worklist |
| `image_unchanged.sh` | Perceptual-hash suppression (ImageMagick if present; sha256 byte-equality fallback) |
| `gates.sh` | Runs the two platform-agnostic gates + a project gates adapter; writes `gate-result.json` |

## Install

Part of the `full` preset. Standalone:

```bash
bash start.sh --add argus      # pulls subagent-patterns as a dependency
```

Or manually:

```bash
mkdir -p ~/.claude/skills ~/.claude/agents ~/.claude/rules
cp -R skills/argus ~/.claude/skills/argus
cp agents/argus-judge.md ~/.claude/agents/argus-judge.md
cp rules/argus.md ~/.claude/rules/argus.md
chmod +x ~/.claude/skills/argus/scripts/gates.sh ~/.claude/skills/argus/scripts/image_unchanged.sh
```

Re-running the block? Remove `~/.claude/skills/argus` first — `cp -R` into an existing directory
nests a second `argus/` inside it instead of overwriting.

Either way, ensure `subagent-patterns` is installed (for the `implementer` agent + the four-state
status protocol).

## Usage

```bash
# 1. Author a spec (copy the template into your repo)
mkdir -p argus/specs/myfeature && cp ~/.claude/skills/argus/references/_template/* argus/specs/myfeature/
#    edit spec.json + spec.md; generate tokens.json from your design system

# 2. Validate it
python3 ~/.claude/skills/argus/scripts/spec_lint.py argus/specs/myfeature/spec.json

# 3. Converge
/argus feature:myfeature                 # all targets
/argus feature:myfeature mode:report-only # one dry iteration, no edits
```

Per-screen the loop will: render the current implementation, run the gates, dispatch the judge, and
either sign off (after two consecutive passes) or hand the implementer the specific failed dimensions.
If a screen has no reference yet, it renders a *candidate* and asks you to approve/replace it (HE-1);
the first sign-off pauses for a spot-check (HE-2).

## Run artifacts & `.gitignore`

Iteration logs under `argus/specs/{feature}/.argus-runs/` hold raw screenshots and probe dumps that
can contain fixture/Simulator data. Commit **only** the sign-off record. In the target repo:

```gitignore
argus/specs/*/.argus-runs/**
!argus/specs/*/.argus-runs/
!argus/specs/*/.argus-runs/signoff.json
```

Committed *reference* images and snapshot baselines must come from a scrubbed persona (see the
adapter contract) so no real data lands in git.

## Relationship to other CCGM modules

Argus composes the existing review/loop primitives rather than duplicating them:

- **`subagent-patterns`** (dependency) — supplies the `implementer` agent and the four-state status
  protocol the loop uses for the edit step.
- **`design-review`** — shares the multi-viewport screenshot + scored-dimension capture idea; the web
  sensor reuses that philosophy. Argus adds the convergence loop, the separated judge, and the gate floor.
- **`atdd` / `test-vision`** — same "spec is the immutable target" stance, but Argus's oracle is a
  rubric judge + visual gates, not only pass/fail E2E tests.
- **`ce-review` / agent-native self-eval rubric** — same adversarial-separate-evaluator and threshold/budget
  discipline (the latter via `agent-native`'s `rules/agent-native-self-eval.md`), applied to an iterative
  *build* loop instead of a single review pass.

## Testing

```bash
bash modules/argus/tests/test-argus.sh    # 32 assertions pinning every deterministic script + gates.sh
```
