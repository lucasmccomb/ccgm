# Argus adapter contract

Argus's loop, judge, schemas, and deterministic gates (`check_contrast.py`, `a11y_assert.py`,
`loop_state.py`, `verdict_validate.py`, `spec_lint.py`, `image_unchanged.sh`, `gates.sh`) are
platform-agnostic. To run Argus on a stack, a project supplies two pluggable pieces:

1. a **sensor** — renders a view and extracts its structured facts;
2. an optional **gates adapter** — runs the platform-specific deterministic gates.

Everything else is the module's. This doc is the interface both must satisfy, plus two worked
recipes (web, iOS).

---

## 1. The sensor

A view is a `(target, state, appearance)` triple. The sensor provides two operations:

| Op | Output | Must |
|----|--------|------|
| **capture** | `render.png` | inject the view's deterministic `fixture`, route to `target.route`, render in the requested `appearance` (light/dark) |
| **probe** | `probe.json` | emit a JSON tree carrying element ids under any of: `id`, `identifier`, `accessibilityIdentifier`, `testId`, `data-testid`; **truncate any text label > 256 chars** |

Non-web adapters implement both in one script:

```
argus/adapters/{adapter}/sense.sh --route R --state S --appearance A --fixture F --out DIR
# writes DIR/render.png and DIR/probe.json ; exit 0 on success
```

Rules every sensor must honor:

- **Fixtures, not live data.** The render must match the reference's content deterministically. Inject
  the fixture named by `spec.targets[].fixtures[state]`. Never render against a remote/live backend.
- **Scrubbed persona.** No real account or PII in any render that may become a committed reference or
  snapshot baseline.
- **Label truncation (256 chars).** App/user content in the probe is *data*, not instructions; a long
  label must not be able to smuggle a prompt to the judge. (Pairs with the judge's content-as-data guard.)
- **Hash-suppression is provided.** The loop calls `image_unchanged.sh prev cur`; you do not implement it.

The 256-char truncation, fixture injection, and routing are the only behaviors the loop depends on.
Anything else (how you boot a simulator, how you start a dev server) is yours.

---

## 2. The gates adapter

`gates.sh` (module) always runs the two platform-agnostic gates itself: `token_contrast`
(`check_contrast.py` over `tokens.json` + `contrast-pairs.json`) and `a11y_ids` (`a11y_assert.py`
over the probe + spec contract). It delegates the rest to your adapter:

```
argus/adapters/{adapter}/gates.sh --spec SPEC --target ID --state S --appearance A [--probe probe.json]
```

Your adapter prints a JSON object of gate statuses on stdout and exits 0 (the *script* ran; gate
*results* are in the JSON, not the exit code):

```json
{ "build": "pass", "lint": "pass", "type_check": "pass",
  "token_compliance": "pass", "snapshot": "pass", "flows": "pass" }
```

- Each value is `"pass" | "fail" | "skip"` (`snapshot` may be `"pass" | "diff" | "skip"`). Omit a gate
  or mark it `"skip"` if your stack does not have it; skipped gates do not affect `all_green`.
- **`token_compliance`** is the source-level check the judge cannot do (it never sees source): grep the
  feature's changed files for hardcoded colors / off-scale spacing not sourced from the design system.
- **`snapshot`** is your visual-regression baseline (swift-snapshot-testing, Playwright `toHaveScreenshot`,
  etc.). It is what makes the look regression-proof *after* sign-off, without the VLM.
- **`flows`** is your functional E2E suite (Playwright, Maestro, XCUITest).

`all_green` is computed by `verdict_validate.py`, never by your adapter or the model.

---

## 3. `tokens.json` (the design-system mirror)

The single source of truth for the design-system-anchored judge dimensions and the contrast gate.
It is **generated, read-only** — a project ships a tiny extractor that derives it from the real design
system (a Swift `DesignSystem`, CSS custom properties, a Tailwind theme) plus a `--check` mode that
re-extracts and exits non-zero on drift. Generated-from-source means there is no second authority to
drift. Format (see `_template/tokens.json`):

```json
{ "colors": { "name": { "light": "#RRGGBB", "dark": {"r":11,"g":11,"b":15,"a":1} } },
  "spacing": { "sm": 8, "md": 16 }, "type": { "body": 16, "title": 22 } }
```

Colors may be hex (`#RGB`/`#RRGGBB`/`#RRGGBBAA`) or `{r,g,b,a}` (r,g,b 0–255, a 0–1), and may be flat
or split by appearance. `contrast-pairs.json` (see `_template/`) declares which fg/bg token pairs to
check and the minimum ratio each must meet; `whitelist: ["dark"]` exempts an appearance with a
documented WCAG reason (e.g. placeholder text qualifying for AA-large).

---

## 4. Recipe: web adapter (built in)

The loop performs capture/probe with browser tools directly (no `sense.sh` needed for `adapter:web`):

- **capture**: `resize_window` → `navigate target.route` (append `?argus_fixture={fixture}&argus_appearance={appearance}`, or your app's convention, documented in `spec.md`) → `screenshot`.
- **probe**: `read_page` (ARIA/DOM) → JSON carrying `id`/`data-testid`/`role`/`name`.
- **gates adapter** `argus/adapters/web/gates.sh` (optional): `npm run lint`/`tsc --noEmit`/`vite build`
  → build/lint/type_check; a grep for hardcoded hex/`px` not from tokens → token_compliance; Playwright
  `toHaveScreenshot` → snapshot; Playwright specs → flows.
- This reuses the same capture philosophy as the `design-review` module; Argus adds the convergence
  loop, the separate judge, and the deterministic floor on top.

## 5. Recipe: iOS adapter (Simulator)

An iOS SwiftUI app is a natural Argus adapter:

- **sense.sh**: build for a per-clone Simulator UDID (`xcodebuild -destination id=$ARGUS_SIM_UDID`),
  install, `xcrun simctl launch` with env injection (`SIMCTL_CHILD_*` vars, e.g. a stub auth token,
  a test-fixtures flag, and an `ARGUS_ROUTE`) so the app boots signed-in, with the fixture, on the
  target screen (any onboarding gate bypassed in `App.init`); `simctl io … screenshot` → render.png;
  idb `ui describe-all` → probe.json (labels truncated to 256).
- **gates.sh**: `xcodebuild build` → build; SwiftLint → lint; build warnings-as-errors → type_check;
  grep changed Swift for `Color(red:`/hex + ad-hoc `.padding(<n>)` → token_compliance;
  `swift-snapshot-testing` target → snapshot; Maestro flows → flows.
- **tokens extractor**: read the app's Swift design-system source → `tokens.json` with `--check` drift guard.
- Use per-clone Simulator UDIDs (e.g. `argus-sim-c{N}`), never bare `booted`/`name=`, so parallel
  clones don't collide. A final on-device functional smoke (a device-install step) is separate from
  the Simulator-only visual loop.

Authoring a new adapter = implement §1 + §2 + §3 for your stack; the loop, judge, schemas, and the
platform-agnostic gates are reused unchanged.
