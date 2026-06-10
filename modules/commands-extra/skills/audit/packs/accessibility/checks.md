# checks.md — Accessibility Pack

---

## Scope

This pack audits JSX and TSX source files for common accessibility (a11y) defects: missing
`alt` attributes on images, click handlers on non-interactive elements without keyboard
support, `target="_blank"` anchors lacking `rel="noopener noreferrer"`, animations and
transitions without a `prefers-reduced-motion` guard, and interactive elements in Tailwind
v4 projects that rely on default cursor styles (Tailwind v4 no longer sets `cursor:pointer`
on buttons globally). Checks self-scope to `.jsx` and `.tsx` files; a JavaScript
back-end project with no JSX will match the `language:javascript` gate but produce zero
findings, which is the expected graceful behaviour. This pack does NOT audit semantic HTML
correctness (heading order, landmark regions, colour contrast ratios) or ARIA attribute
validity — those require specialised tooling beyond grep and LLM scanning.

**Pack ID:** `ccgm/accessibility`
**Applies when:** `language:javascript`

---

## applies_when Rationale

| Condition | Reason |
|-----------|--------|
| `language:javascript` | The ecosystem detector emits `javascript` for any repository that has a `package.json`. JSX/TSX files only appear in JavaScript (or TypeScript) projects; there is no signal to produce on Go, Python, or other non-JS codebases. Using `language:javascript` is the broadest correct gate: it covers plain-JS React, TypeScript React, and Next.js projects alike. Checks then internally scope themselves to `.jsx`/`.tsx` files, so a Node API with no JSX produces zero findings rather than false positives. |

---

## Checks

---

### `a11y/img-missing-alt`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans JSX/TSX source files for `<img>` elements (and `<Image>` from
next/image or similar) that are missing an `alt` attribute, or where `alt` is an empty
string on a non-decorative image.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan JSX and TSX source files (.jsx, .tsx) for image elements missing an `alt` attribute
or using `alt=""` on what appears to be a non-decorative image.

Flag as findings:
1. <img> elements with no `alt` attribute at all
2. <Image> elements (Next.js next/image, or similar framework wrappers) with no `alt` prop
3. <img> or <Image> elements where alt="" but the surrounding context (captions, filename,
   aria-label, or descriptive class names) suggests the image conveys meaningful content

Do NOT flag:
- <img alt=""> when there is an explicit comment, aria-hidden="true", or role="presentation"
  indicating the image is purely decorative
- Auto-generated or vendored component files (node_modules, .gen.tsx, generated/)
- SVG inline elements (use <svg aria-hidden> conventions, not alt)

For each finding report: file path, line number, the JSX element, and what alt text would
be appropriate based on context. Mark auto_fixable: false (requires a human to write
meaningful alt text describing the image content).
```

#### Spine Wiring

```yaml
check_id: a11y/img-missing-alt
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing `alt` attributes make images completely inaccessible to
screen reader users. For content-carrying images this is a WCAG 2.1 Level A failure — the
lowest passing bar. Medium severity: real impact on screen reader users but does not break
the application for sighted users.

**Confidence rationale:** Detecting absent `alt` props on `<img>` elements is a
straightforward structural scan. The LLM can identify the element, check for the attribute,
and assess whether `alt=""` is intentional based on context. Some judgment is required for
the decorative vs. non-decorative distinction, so confidence is medium rather than high.

**Rubric entry:** `a11y/img-missing-alt`

#### Fixture

**True positive** (`src/components/Avatar.tsx`):

```tsx
// FINDS: <img> missing alt attribute
function Avatar({ url }: { url: string }) {
  return <img src={url} className="avatar" />;
}
```

**True negative** (should produce NO finding):

```tsx
// OK: alt attribute provided
function Avatar({ url }: { url: string }) {
  return <img src={url} alt="User avatar" className="avatar" />;
}
```

---

### `a11y/click-without-keyboard`

**Severity:** `medium`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent scans JSX/TSX files for `onClick` handlers attached to non-interactive
elements (`<div>`, `<span>`, `<li>`, etc.) that lack both an `onKeyDown`/`onKeyUp`
handler AND an appropriate `role` attribute.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan JSX and TSX source files (.jsx, .tsx) for onClick handlers attached to non-interactive
HTML elements that are inaccessible to keyboard-only users.

Flag as findings: any non-interactive element (<div>, <span>, <p>, <li>, <td>, <section>,
<article>, <header>, <footer>) that has an onClick prop but is missing ALL of the following:
- An onKeyDown or onKeyUp handler (to handle Enter/Space key activation)
- A role attribute that makes the element interactive (role="button", role="link",
  role="menuitem", role="tab", etc.)
- A tabIndex attribute that puts it in the tab order

An element is acceptable if it has onClick AND (onKeyDown or onKeyUp) AND (role or tabIndex).
An element is also acceptable if it has onClick AND tabIndex AND role.

Do NOT flag:
- <button>, <a>, <input>, <select>, <textarea>, <label> — these are natively interactive
- Elements where onClick is a bubbled event handler (e.g. a container that stops propagation
  from children) — use judgment; flag only when the element IS the intended interaction target
- Auto-generated or vendored files

For each finding report: file path, line number, the element tag, and what accessibility
attributes are missing. Mark auto_fixable: false (requires human judgment about whether to
replace with <button> or add role + keyboard handler).
```

#### Spine Wiring

```yaml
check_id: a11y/click-without-keyboard
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Click-only handlers exclude keyboard users entirely — this is a
WCAG 2.1 Level A failure (Success Criterion 2.1.1 Keyboard). Medium severity: blocks
keyboard navigation for affected interactions.

**Confidence rationale:** Detecting onClick on a non-interactive element is structural. The
judgment call about whether it is the intended target vs. a bubbled handler reduces
confidence to medium.

**Rubric entry:** `a11y/click-without-keyboard`

#### Fixture

**True positive** (`src/components/Card.tsx`):

```tsx
// FINDS: onClick on <div> without keyboard handler or role
function Card({ onClick }: { onClick: () => void }) {
  return (
    <div className="card" onClick={onClick}>
      Click me
    </div>
  );
}
```

**True negative** (should produce NO finding):

```tsx
// OK: role="button" and onKeyDown make this keyboard accessible
function Card({ onClick }: { onClick: () => void }) {
  return (
    <div
      className="card"
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      Click me
    </div>
  );
}
```

---

### `a11y/anchor-missing-rel`

**Severity:** `medium`
**Confidence:** `high`
**Detection:** `llm`

#### Detection

The LLM agent (or agent-run grep) scans JSX/TSX and HTML-in-JS files for `<a>` elements
with `target="_blank"` that are missing `rel="noopener noreferrer"` (or at minimum
`rel="noopener"`).

Grep pattern (deterministic, run by the agent against `.jsx`, `.tsx`, `.html` files):

```
grep -rn 'target=["'"'"']_blank["'"'"']' --include='*.tsx' --include='*.jsx' --include='*.html'
```

For each grep match, the agent then checks whether `rel` contains `noopener` on the same
element. Lines without `rel="noopener"` (or `rel` containing `noopener`) are findings.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan JSX, TSX, and HTML files for anchor elements (<a>) with target="_blank" that are
missing rel="noopener noreferrer".

Detection approach: run the following grep to find candidate lines, then check each match:

  grep -rn 'target="_blank"\|target='"'"'_blank'"'"'' \
    --include='*.tsx' --include='*.jsx' --include='*.html' \
    --include='*.ts' --include='*.js'

For each match, flag it as a finding if the SAME JSX element or HTML tag does NOT contain
a rel attribute that includes "noopener". Acceptable rel values: "noopener noreferrer",
"noopener", "noreferrer noopener". Unacceptable: absent rel, or rel="noreferrer" alone
(without noopener — noreferrer alone only blocks the Referer header, not the opener
reference in older browsers).

Security note: without rel="noopener", the opened page can access window.opener and
redirect the original tab (reverse tabnabbing). This is a security-adjacent accessibility
issue.

Do NOT flag:
- <a target="_blank"> where rel already contains "noopener"
- Dynamically computed targets (e.g. target={someVar}) — flag only string literal "_blank"
- Auto-generated or vendored files

For each finding report: file path, line number, the element, and the correct rel value to
add. Mark auto_fixable: true (adding rel="noopener noreferrer" is a safe mechanical fix
with no functional side effects).
```

#### Spine Wiring

```yaml
check_id: a11y/anchor-missing-rel
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing `rel="noopener"` enables reverse tabnabbing — an opened
page can navigate the original tab to a phishing site via `window.opener.location`. This is
a well-known security-adjacent a11y issue. Medium severity: real security implication but
limited blast radius (requires a malicious page).

**Confidence rationale:** The grep pattern `target="_blank"` on a literal string is
deterministic. Post-grep inspection for the presence of `noopener` in the same element is
straightforward. High confidence.

**Rubric entry:** `a11y/anchor-missing-rel`

#### Fixture

**True positive** (`src/components/ExternalLink.tsx`):

```tsx
// FINDS: target="_blank" without rel="noopener noreferrer"
function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a href={href} target="_blank">{children}</a>;
}
```

**True negative** (should produce NO finding):

```tsx
// OK: rel="noopener noreferrer" present
function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
```

---

### `a11y/missing-prefers-reduced-motion`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent (or agent-run grep) scans CSS files, CSS-in-JS, and Tailwind animate-*
utilities for animations or transitions and checks whether a `prefers-reduced-motion` media
query guard is present in the same file or in the global stylesheet.

Grep pattern for locating animation usage:

```
grep -rn 'animation\|transition\|animate-\|motion\.' \
  --include='*.css' --include='*.scss' --include='*.tsx' --include='*.ts' \
  --include='*.js' --include='*.jsx'
```

The agent then inspects whether `@media (prefers-reduced-motion` (or a framework-equivalent
guard) exists in the same project's CSS files or in the files that define the animations.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

Scan CSS, SCSS, and CSS-in-JS files for animations or transitions that lack a
prefers-reduced-motion guard. Also scan TSX/JSX files that use motion libraries (Framer
Motion, react-spring, GSAP) or Tailwind animate-* utilities.

Detection approach: run the grep below to find candidate files, then check each for a
corresponding prefers-reduced-motion guard in the same file or a global stylesheet.

  grep -rn '@keyframes\|animation:\|transition:\|animate-\|motion\.div\|<motion\.' \
    --include='*.css' --include='*.scss' --include='*.tsx' --include='*.ts' \
    --include='*.js' --include='*.jsx'

Flag as a finding if a file defines or uses animations/transitions AND:
- No @media (prefers-reduced-motion: reduce) block reduces or eliminates the animation
- The project has no global prefers-reduced-motion reset in any CSS file under src/ or styles/

Do NOT flag:
- Instantaneous CSS transitions (transition-duration: 0) — these are already motion-safe
- Opacity-only transitions without movement (fade-in/out without transform) — lower risk,
  but flag if the project has no prefers-reduced-motion guard at all
- Tailwind animate-* utilities when the project's global CSS already has a
  prefers-reduced-motion media query that sets animation: none
- Auto-generated or vendored files

For each finding report: file path, line number, the animation or transition definition,
and whether a project-level guard exists. Mark auto_fixable: false (requires design
judgment about what the reduced-motion experience should look like).
```

#### Spine Wiring

```yaml
check_id: a11y/missing-prefers-reduced-motion
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Users with vestibular disorders can experience nausea, vertigo, or
seizures from animations. Missing `prefers-reduced-motion` guards fail WCAG 2.1 Level AA
Success Criterion 2.3.3. Low severity: affects a small user population, but the fix
(one media query block) is inexpensive.

**Confidence rationale:** Detecting animation/transition declarations is straightforward
via grep. However, determining whether a project-level guard already handles this (e.g. a
global CSS reset) requires inspecting multiple files. Medium confidence.

**Rubric entry:** `a11y/missing-prefers-reduced-motion`

#### Fixture

**True positive** (`src/styles/animations.css`):

```css
/* FINDS: animation defined with no prefers-reduced-motion guard */
@keyframes slide-in {
  from { transform: translateX(-100%); }
  to   { transform: translateX(0); }
}

.panel-enter {
  animation: slide-in 300ms ease-out;
}
```

**True negative** (should produce NO finding):

```css
/* OK: prefers-reduced-motion guard present */
@keyframes slide-in {
  from { transform: translateX(-100%); }
  to   { transform: translateX(0); }
}

.panel-enter {
  animation: slide-in 300ms ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .panel-enter {
    animation: none;
  }
}
```

---

### `a11y/tailwind-cursor-pointer`

**Severity:** `low`
**Confidence:** `medium`
**Detection:** `llm`

#### Detection

The LLM agent (or agent-run grep) scans for Tailwind v4 projects and checks whether
interactive elements (`<button>`, elements with `role="button"`, `<a>`) are either:
(a) given the `cursor-pointer` Tailwind utility class, or
(b) the project has a global CSS base layer that adds `cursor: pointer` to interactive
elements.

This is the accessibility-surfacing of the known Tailwind v4 gap documented in
`modules/tailwind/rules/frontend-css.md`.

Grep pattern for locating potentially affected interactive elements:

```
grep -rn '<button\|role="button"\|<a ' \
  --include='*.tsx' --include='*.jsx'
```

The agent then checks whether `cursor-pointer` appears in the element's className, or
whether the project's global CSS contains a `@layer base` block that adds `cursor: pointer`
to buttons.

**Tool (if detection = tool or hybrid):**
n/a

Rule / rule-id: n/a

Fallback when tool absent: llm

**LLM instruction (if detection = llm or hybrid):**

```
READ AND APPLY: ~/.claude/skills/audit/reference/fix-patterns.md
Use the Fix Type Reference table from that file to assign fix_type and fix_confidence to
each finding. Do not rely on memory — open and apply the file.

This check applies ONLY to Tailwind v4 projects. Tailwind v4's preflight does NOT set
cursor: pointer on <button> elements globally — browsers default to cursor: default.

Step 1: Determine if this is a Tailwind v4 project. Look for:
- A package.json that has "tailwindcss": "^4" or "@tailwindcss/vite", "@tailwindcss/postcss"
  in dependencies/devDependencies.
- An import "@tailwindcss/..." pattern in CSS files (v4 uses CSS-first config).
If this is NOT a Tailwind v4 project, emit NO findings and stop.

Step 2: Check if a global fix is already in place. Look for a @layer base block in any
.css file under src/, styles/, or app/ that sets cursor: pointer on button, [role="button"],
or a[href]. If a comprehensive global fix exists, emit NO findings.

Step 3: If Tailwind v4 and no global fix: scan JSX/TSX files for interactive elements that
are missing the cursor-pointer utility.

Flag as findings: <button> elements and elements with role="button" in className strings
that do NOT include cursor-pointer (and are not covered by a global CSS base layer fix).

Do NOT flag:
- Disabled elements ([disabled], aria-disabled="true") — these should use cursor-not-allowed
- Elements in vendored or auto-generated files
- Non-Tailwind v4 projects

For each finding report: file path, the element, and whether the missing fix should be a
global CSS base layer addition or a per-element cursor-pointer class. Mark auto_fixable:
true for adding cursor-pointer to individual elements; mark auto_fixable: false when the
recommended fix is a global @layer base block (requires file creation or edit).
```

#### Spine Wiring

```yaml
check_id: a11y/tailwind-cursor-pointer
detection: llm
```

#### Severity / Confidence

**Severity rationale:** Missing `cursor: pointer` on interactive elements breaks the
affordance contract — desktop users with a mouse cannot tell what is clickable. This is a
usability and implicit accessibility defect. Low severity: does not break functionality and
only affects mouse users, but is trivially fixed.

**Confidence rationale:** Detecting Tailwind v4 is deterministic (package.json version
check). However, the agent must also check for a pre-existing global CSS fix, which
requires inspecting multiple files. Medium confidence overall.

**Rubric entry:** `a11y/tailwind-cursor-pointer`

#### Fixture

**True positive** (`src/components/SubmitButton.tsx`, Tailwind v4 project without global fix):

```tsx
// FINDS: button in Tailwind v4 project without cursor-pointer utility
function SubmitButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="bg-primary-500 text-white px-4 py-2 rounded-md"
      onClick={onClick}
    >
      Submit
    </button>
  );
}
```

**True negative** (should produce NO finding):

```tsx
// OK: cursor-pointer utility class present
function SubmitButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="bg-primary-500 text-white px-4 py-2 rounded-md cursor-pointer"
      onClick={onClick}
    >
      Submit
    </button>
  );
}
```

---

## Quality Checklist

- [x] Each check-id in this file exactly matches `pack.json`'s `checks[].id`
- [x] Every check with `detection: tool` or `detection: hybrid` names a real spine tool
- [x] Every check with `detection: llm` or `detection: hybrid` has a filled-in LLM instruction
- [x] Each fixture has both a true positive AND a true negative
- [x] Severity / confidence rationale is present for every check
- [x] `applies_when` rationale table is complete
- [x] `scripts/lint-pack.py` passes on this pack
