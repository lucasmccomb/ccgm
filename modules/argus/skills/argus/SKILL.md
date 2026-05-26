---
name: argus
description: >
  Visual-ATDD convergence loop. Iteratively develops a UI against a per-feature design spec and
  signs off on its own work — functional AND visual — by grounding every judgment in an external
  signal: deterministic gates plus a SEPARATE judge agent that scores the render against the spec,
  a reference image, and the design system. Loops until the rubric passes for two consecutive
  iterations, then commits a snapshot baseline. Platform-agnostic via a pluggable sensor+gates
  adapter (web adapter built in; iOS/macOS via a project adapter).
disable-model-invocation: true
---

# /argus — visual-ATDD convergence loop

Run an autonomous implement → render → externally-judge → converge loop for one feature's UI.
The agent edits code, the deterministic gates form an ungameable floor, a **separate** judge
agent scores the render against the target, and the loop self-signs-off only when the rubric
passes twice in a row. Human input is bounded to ≤1 reference image per screen plus one
spot-check of the first sign-off.

## Usage

```
/argus feature:habits                          # converge every target in the spec
/argus feature:habits target:list              # converge one target (alias: screen:)
/argus feature:habits mode:report-only          # one dry iteration, no edits, no commits
/argus feature:habits max-iterations:8           # override the per-view iteration budget (default 12)
```

Args (parsed from `$ARGUMENTS`): `feature:` (required), `target:`/`screen:` (optional, default all),
`max-iterations:` (optional), `mode:` (`interactive` default | `report-only` | `headless`).

## Layout (in the target project)

```
argus/specs/{feature}/
  spec.json            # machine contract (validated by spec.schema.json)
  spec.md              # prose acceptance criteria + component contracts (judge's spec-text)
  tokens.json          # generated design-system mirror
  contrast-pairs.json  # declared WCAG pairs
  rubric.json          # OPTIONAL per-feature rubric override (else the module default)
  references/          # ≤1 approved reference image per screen (HE-1)
  .argus-runs/         # per-view state.json, candidates, iteration verdicts, signoff.json
argus/adapters/{adapter}/
  sense.sh             # sensor: capture(render) + probe(structured) — REQUIRED for non-web adapters
  gates.sh             # platform gates: build/lint/type/token_compliance/snapshot/flows (optional)
```

Module scripts live at `~/.claude/skills/argus/scripts/` and contracts at `~/.claude/skills/argus/references/`.
Shorthand below: `$S` = scripts dir, `$R` = references dir.

## Invariants — DO NOT violate these (they are the integrity of the loop)

1. **The judge runs as a separate `argus-judge` subagent, dispatched fresh every iteration.** Never
   score the render yourself in the main context. Never pass the judge the diff, the implementer's
   notes, or this conversation. The judge sees outputs only.
2. **The judge never runs while gates are red.** `gates.sh` is the floor. Red gates → fix, re-gate.
3. **Two consecutive passes are required**, tracked by `loop_state.py` (not in your head). On an
   all-pass verdict you do NOT re-invoke the implementer (an edit could regress and reset the streak)
   — you re-render to confirm.
4. **3 attempts per dimension, then freeze + document.** Do not retry a frozen dimension forever.
5. **Render against deterministic fixtures, never live data.** The sensor injects the fixture so the
   render matches the reference's content.
6. **No reference image ⇒ no visual judging.** Bootstrap a candidate and emit `NEEDS_CONTEXT` (HE-1).

## Phase 0 — resolve + validate

1. Parse `$ARGUMENTS`. Require `feature:`. Set `SPEC=argus/specs/{feature}/spec.json`,
   `SPECMD=argus/specs/{feature}/spec.md`, `RUNS=argus/specs/{feature}/.argus-runs`.
2. Validate the spec: `python3 $S/spec_lint.py "$SPEC" --json`. If `valid:false` → stop, report the
   errors, return **BLOCKED**. Note the `reference_worklist` (the HE-1 items).
3. Load the rubric: `argus/specs/{feature}/rubric.json` if present, else `$R/rubric.json`. Read
   `loop.max_iterations_default` (CLI `max-iterations:` overrides).
4. Resolve the adapter from `spec.adapter`:
   - `web` → use the **built-in web sensor** (Chrome MCP / Playwright; see Phase 1). Gates adapter
     optional at `argus/adapters/web/gates.sh`.
   - any other name → require `argus/adapters/{adapter}/sense.sh`; gates adapter at
     `argus/adapters/{adapter}/gates.sh` if present. If `sense.sh` is missing → **BLOCKED** (no sensor).

## Phase 1 — the sensor contract

A sensor provides two operations for a view `(target, state, appearance)`:

- **capture** → writes `render.png` (the perceptual artifact).
- **probe** → writes `probe.json` (structured facts: accessibility tree / DOM-ARIA snapshot, with
  any text label > 256 chars truncated so app content cannot smuggle a long instruction to the judge).

Both must inject the view's `fixture` (deterministic data), route to `target.route`, and use the
appearance (light/dark). For non-web adapters, `argus/adapters/{adapter}/sense.sh` implements both:

```
argus/adapters/{adapter}/sense.sh --route R --state S --appearance A --fixture F --out DIR
# writes DIR/render.png and DIR/probe.json
```

**Built-in web sensor** (adapter `web`), performed by you with browser tools:
1. `resize_window` to the appearance's viewport (default 1440×900; honor a `viewport` in the spec).
2. `navigate` to `target.route`, appending the fixture + appearance the project's convention expects
   (default `?argus_fixture={fixture}&argus_appearance={appearance}` — document yours in `spec.md`).
3. `computer` action `screenshot` → save as `render.png`.
4. `read_page` (ARIA/DOM) → transform to `probe.json` (objects carrying `id` / `data-testid` /
   `role` / `name`). Truncate any text value > 256 chars.

## Phase 2 — expand views + bootstrap references

Expand the (filtered) targets into views = `target × states × appearances`. For each target, the
**canonical** view (`target.canonical` or `states[0]+appearances[0]`) is the one that needs a
reference image; other views are deltas described in `spec.md` prose.

For the canonical view, check its reference `status` in `spec.json`:
- `present` → proceed to Phase 3.
- `needed` → run the sensor once to render a candidate to `RUNS/candidates/{target}-{state}-{appearance}.png`,
  set the manifest entry to `candidate`, and **emit `NEEDS_CONTEXT`** describing HE-1 (the human moves
  it into `references/` as-is, replaces it, or writes a one-line correction in `spec.md`). Do **not**
  visually judge this target until a reference exists. In `report-only`, just report the gap.
- `candidate` → a render is awaiting approval; emit `NEEDS_CONTEXT` and skip. (Once the human moves it
  to `references/` and flips it to `present` with `source: candidate`, the next run proceeds.)

## Phase 3 — the convergence loop (per view with a present reference)

`reference_source` = the manifest entry's `source` (`human` or `candidate`). State file:
`STATE=RUNS/state-{target}-{state}-{appearance}.json`. Initialize once:

```
python3 $S/loop_state.py init --state "$STATE" --feature {feature} --target "{target}/{state}/{appearance}" \
  --reference-source {reference_source}
```

Then loop up to `max-iterations` (in `report-only`, run exactly ONE iteration and stop before any edit/commit):

```
last_verdict = null
repeat:
  # (a) EDIT — skip on an all-pass confirm; fix only what failed.
  if last_verdict == null OR not last_verdict.all_pass:
      dispatch the `implementer` subagent (subagent_type: "implementer") with a spec:
        objective: make {target}/{state}/{appearance} satisfy these failing items:
                   {decision.fix_dimensions, OR the red gate names from the last gate-result}
        context:   spec.md acceptance criteria + component contracts; tokens.json; the failing evidence
                   from last_verdict (NOT a request to match the screenshot — give the design-system reason)
        constraints: stay inside the feature's UI; do not edit specs, tokens, fixtures, or tests;
                     no "while I'm here"
        deliverable: the diff + four-state status
      (report-only: SKIP this edit step.)
  else:
      # all-pass: do NOT edit; re-render to confirm (an edit could regress and reset the streak)

  # (b) SENSE — render this view against its fixture (the sensor builds+launches; web: navigates).
  capture + probe → $RUNS/render.png, $RUNS/probe.json   (built-in web sensor, or adapter sense.sh)
  if the sensor failed (e.g. the build broke, app would not launch):
      python3 $S/loop_state.py gate-fail --state "$STATE" --rubric {rubric}
      last_verdict = {all_pass:false, failed_dimensions:[], failing:["build"]}
      continue                                       # next EDIT fixes the build
  unchanged = read( bash $S/image_unchanged.sh "$RUNS/render.prev.png" "$RUNS/render.png" ).unchanged
  # do NOT overwrite render.prev.png yet — the judge needs the PREVIOUS frame for the pairwise rank.

  # (c) GATES — the deterministic floor, over the FRESH probe. The judge never runs unless green.
  bash $S/gates.sh --spec "$SPEC" --target {target} --state {state} --appearance {appearance} \
      --probe "$RUNS/probe.json" --adapter "argus/adapters/{adapter}/gates.sh" --out "$RUNS/gate-result.json"
      # module computes token_contrast + a11y_ids over the fresh probe; the adapter supplies
      # build/lint/type/token_compliance/snapshot/flows. all_green is derived, not modelled.
  if gate-result.all_green == false:
      python3 $S/loop_state.py gate-fail --state "$STATE" --rubric {rubric}
      last_verdict = {all_pass:false, failed_dimensions:[], failing:<gate names that are fail/diff/missing>}
      continue                                       # next EDIT fixes the red gates (judge skipped)

  # (d) JUDGE — separate subagent, OR a hash-suppressed confirm (no edit happened + render identical).
  if unchanged AND last_verdict?.all_pass:
      decision = python3 $S/loop_state.py unchanged --state "$STATE" --rubric {rubric}   # counts as the 2nd pass
  else:
      dispatch the `argus-judge` subagent (subagent_type: "argus-judge") with FILE PATHS to:
        spec.json, spec.md, tokens.json, references/{the reference}, $RUNS/render.png,
        $RUNS/probe.json, $RUNS/gate-result.json, {rubric}, $RUNS/render.prev.png (if any),
        and reference_source.  Tell it: emit verdict JSON only; you will not be given the diff.
      save its JSON → $RUNS/verdict.raw.json
      # normalize: re-derive all_pass/failed_dimensions from scores deterministically (don't trust the self-report)
      python3 $S/verdict_validate.py --kind verdict "$RUNS/verdict.raw.json" --rubric {rubric} > "$RUNS/iteration-{n}.json"
      decision = python3 $S/loop_state.py record --state "$STATE" --verdict "$RUNS/iteration-{n}.json" --rubric {rubric}
      last_verdict = read("$RUNS/iteration-{n}.json")
  cp $RUNS/render.png $RUNS/render.prev.png         # NOW advance the baseline (judge has used the old prev)

  # (e) DECIDE — from loop_state, never by counting yourself.
  if decision.newly_frozen: document each frozen dim in CONVERGENCE notes; this is an SSC rubric-gap
     signal — if a dimension freezes, report DONE_WITH_CONCERNS at the end.
  if decision.should_signoff:  → Phase 4 (sign off this view); break
  if decision.budget_exhausted: stop this view; record it unsigned; continue to the next view
```

## Phase 4 — sign-off

When a view reaches two consecutive passes:
1. Record the snapshot baseline (the adapter's visual-regression baseline, e.g. commit the
   `__Snapshots__/` for this view) so the look is regression-proof without the VLM thereafter.
2. Append the view to `argus/specs/{feature}/.argus-runs/signoff.json`:
   `{feature, target, state, appearance, signed_off_at, iterations, reference_source, final_verdict, snapshot_baseline, human_spotcheck:"pending"}`.
   `signoff.json` is the ONLY committed artifact under `.argus-runs/` (see `.gitignore` note in the README).
3. **First sign-off of the run → PAUSE for HE-2.** Emit a spot-check request (open the signed-off view,
   compare to the reference + verdict; the human sets `human_spotcheck:"approved"`, or names the
   dimension the judge got wrong so you can tune `rubric.json` and re-run that view). Do not continue to
   the remaining views until the human responds. (`headless` mode: skip the pause, leave `pending`.)

## Completion status

End with one four-state status (per the subagent protocol):
- **DONE** — every in-scope view signed off (or `report-only` produced its one iteration cleanly).
- **DONE_WITH_CONCERNS** — signed off but a dimension was frozen, or HE-2 surfaced a rubric gap. List them.
- **BLOCKED** — invalid spec, missing sensor, or a view hit the iteration budget without converging.
- **NEEDS_CONTEXT** — a reference is `needed`/`candidate` (HE-1) and visual judging cannot start.

## Modes

| Mode | Edits? | Commits? | Judge? | Stops |
|------|--------|----------|--------|-------|
| `interactive` (default) | yes | snapshot baseline on sign-off | yes, each iteration | sign-off / budget / HE pause |
| `report-only` | no | no | yes, once | after one iteration (dry run) |
| `headless` | yes | snapshot baseline on sign-off | yes | sign-off / budget; no HE pause (leaves `pending`) |
