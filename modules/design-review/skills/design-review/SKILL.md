---
name: design-review
description: Visual design review for web pages. Takes screenshots at multiple viewports, analyzes CSS/HTML source, and runs 6 parallel analysis passes covering spacing, typography, responsive design, visual hierarchy, accessibility, and component consistency. Produces a prioritized list of actionable fixes.
disable-model-invocation: true
---

# Design Review

A comprehensive frontend design review. Collects page data (screenshots, DOM, CSS), runs 6 parallel analysis passes, and produces a scored, prioritized list of actionable fixes.

## Usage

```
/design-review                                    # Reviews the current dev server page
/design-review http://localhost:3000/some/page     # Reviews a specific URL
/design-review http://localhost:3000/some/page --fix  # Reviews AND applies fixes automatically
```

## Instructions

### Step 1: Identify the Target

If `$ARGUMENTS` contains a URL, use it. Otherwise ask the user what page to review.

If no dev server is running, start one and wait for it to be ready.

### Step 2: Collect Page Data

Use Chrome browser tools to gather all the data the analysis agents will need. This step is done by the main agent (you), not subagents.

#### 2a: Screenshots

Take screenshots at 3 viewport widths. For each, scroll through the entire page capturing each screenful:

| Viewport | Width | Label |
|----------|-------|-------|
| Desktop | 1440px | desktop |
| Tablet | 768px | tablet |
| Mobile | 375px | mobile |

Use `resize_window` to set each viewport, then `navigate` to reload the page, then `screenshot` while scrolling through. Keep all screenshot IDs for your own visual analysis in Step 4.

If the project supports dark mode, also take one full desktop screenshot in the alternate theme.

#### 2b: DOM Structure

Use `read_page` (with `filter: "all"`, reasonable `depth`) to capture the page's element tree. Focus on the main content area, not the nav chrome.

Extract the key structural elements:
- All heading levels (h1-h6) and their nesting
- Tables and their structure
- Custom chart/visualization containers
- Image containers and figures
- Lists (ordered and unordered)

#### 2c: CSS Source

Read the project's CSS source file(s) using the Read tool. For Tailwind projects, also read the generated output CSS if available (usually in `dist/`). For the page's inline `<style>` blocks, extract them with `javascript_tool`:

```js
Array.from(document.querySelectorAll('style')).map(s => s.textContent).join('\n')
```

#### 2d: Computed Styles Extraction

Use `javascript_tool` to extract computed styles for key elements. Run this script:

```js
const selectors = [
  'h1', 'h2', 'h3', 'h4',
  'p', 'table', 'th', 'td',
  'figure', 'figcaption', 'img',
  '.chart-row', '.chart-bar', '.chart-label', '.chart-value', '.chart-note',
  '.audit-grid', '.audit-year',
  'blockquote', 'pre', 'code',
  'a', 'strong', 'em', 'small',
  '.main-content', 'article', 'main'
];

const results = {};
for (const sel of selectors) {
  const el = document.querySelector(sel);
  if (el) {
    const cs = getComputedStyle(el);
    results[sel] = {
      fontSize: cs.fontSize,
      lineHeight: cs.lineHeight,
      fontWeight: cs.fontWeight,
      fontFamily: cs.fontFamily.split(',')[0].trim(),
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      margin: `${cs.marginTop} ${cs.marginRight} ${cs.marginBottom} ${cs.marginLeft}`,
      padding: `${cs.paddingTop} ${cs.paddingRight} ${cs.paddingBottom} ${cs.paddingLeft}`,
      maxWidth: cs.maxWidth,
      width: cs.width,
      display: cs.display,
      gap: cs.gap,
      borderRadius: cs.borderRadius
    };
  }
}
JSON.stringify(results, null, 2)
```

### Step 3: Run Parallel Analysis Passes

Launch **6 Task agents in parallel** (single message, all `subagent_type: "Explore"`, `run_in_background: true`). Each agent receives the CSS source, computed styles JSON, and DOM structure extract. They analyze from one design lens.

Include the collected data directly in each agent's prompt (not file paths).

Every agent prompt must end with:

```
IMPORTANT:
- Return findings as the specified JSON array. If no issues found, return an empty array.
- Each finding must include the exact CSS selector or element description so the fix can be applied.
- Suggest specific CSS property changes (e.g., "margin-bottom: 1.5rem" not "add more space").
- Note which file the fix should be applied to (source CSS, inline style block, or HTML structure).
```

---

**Agent 1: Spacing & Layout**

```
You are a design systems engineer reviewing spacing and layout consistency. Analyze the CSS and computed styles for spacing issues.

For each issue found, report:
- The element(s) affected (CSS selector)
- What's wrong
- The specific CSS fix
- Severity

CHECK FOR:

Vertical rhythm:
- Inconsistent margins between same-level elements (e.g., h2 sections have different spacing)
- Missing or insufficient spacing between sections/components
- Margin collapse issues causing unexpected gaps
- Spacing between a heading and its first paragraph (should be tighter than between paragraphs)
- Spacing above headings vs below (above should be larger to associate heading with its content)

Horizontal alignment:
- Elements that should be aligned but aren't (labels, values in charts, table columns)
- Inconsistent left/right padding in nested containers
- Content that overflows its container on narrow viewports

Whitespace:
- Sections that feel cramped (insufficient padding inside containers)
- Sections that feel too sparse (excessive margins creating disconnection)
- Inconsistent gaps in flex/grid layouts

Charts and data visualizations:
- Bar chart labels misaligned with bars
- Inconsistent spacing between chart rows
- Chart containers with insufficient breathing room from surrounding content
- Source notes too close to or too far from their charts

Tables:
- Cell padding inconsistency
- Header row not visually distinguished enough via spacing
- Tables too close to surrounding paragraphs

Return findings as a JSON array:
[{"element": "CSS selector", "issue": "...", "fix": "property: value", "file": "source file", "severity": "high|medium|low"}]
```

---

**Agent 2: Typography & Readability**

```
You are a typographer reviewing text rendering and readability. Analyze computed styles and CSS for typography issues.

For each issue found, report:
- The element(s) affected
- What's wrong
- The specific CSS fix
- Severity

CHECK FOR:

Type scale:
- Heading sizes that don't form a clear hierarchy (h2 too close to h3, etc.)
- Body text too small for comfortable reading (below 16px on desktop, below 15px on mobile)
- Subheadings (h3, h4) that are hard to distinguish from body text
- Footnotes or small text below 12px (accessibility concern)

Line height and measure:
- Body text line-height below 1.5 (hard to read in long-form content)
- Heading line-height above 1.4 (headings should be tighter than body)
- Content width exceeding 75ch (optimal reading measure is 45-75ch)
- Content width below 45ch on desktop (too narrow, wastes space)

Font weight and emphasis:
- Bold text that doesn't stand out enough from regular weight
- Too many levels of emphasis competing (bold + italic + color + size)
- Table headers not bold enough to distinguish from data
- Chart labels with inappropriate font weight

Text color and contrast:
- Body text with insufficient contrast against background
- Secondary text (captions, notes) too faint to read comfortably
- Link colors that don't stand out from body text
- Visited vs unvisited link states indistinguishable

Spacing between text elements:
- Paragraphs too close together (need clear separation for scanning)
- List item spacing too tight or too loose
- Blockquote spacing and indentation

Return findings as a JSON array:
[{"element": "CSS selector", "issue": "...", "fix": "property: value", "file": "source file", "severity": "high|medium|low"}]
```

---

**Agent 3: Responsive Design**

```
You are a responsive design specialist. Analyze CSS for responsive behavior across desktop (1440px), tablet (768px), and mobile (375px) viewports.

For each issue found, report:
- The element(s) affected
- What's wrong at which viewport
- The specific CSS fix (including media query if needed)
- Severity

CHECK FOR:

Breakpoint coverage:
- Elements with fixed widths that will overflow on mobile
- Tables without horizontal scroll or responsive layout on small screens
- Charts that become unreadable on narrow viewports (labels overlap, bars too small)
- Images or figures without max-width: 100%

Mobile-specific issues:
- Touch targets smaller than 44x44px (buttons, links)
- Text that requires horizontal scrolling
- Side-by-side layouts that should stack on mobile
- Font sizes that need adjustment for mobile readability

Tablet-specific issues:
- Awkward layout in the 768-1024px range (too wide for single column, too narrow for desktop)
- Navigation that doesn't adapt to tablet width
- Charts/tables that work on desktop and mobile but break on tablet

Content reflow:
- Flex containers that don't wrap appropriately
- Grid layouts without responsive column adjustments
- Absolute or fixed positioning that breaks on resize
- Overflow hidden cutting off important content

Media query hygiene:
- Redundant or conflicting media queries
- Missing mobile-first or desktop-first consistency
- Breakpoints that don't match the project's design system

Return findings as a JSON array:
[{"element": "CSS selector", "viewport": "mobile|tablet|desktop", "issue": "...", "fix": "CSS including @media if needed", "file": "source file", "severity": "high|medium|low"}]
```

---

**Agent 4: Visual Hierarchy & Content Flow**

```
You are a visual design director reviewing information hierarchy and content flow. Analyze the DOM structure and computed styles.

For each issue found, report:
- The section or element affected
- What's wrong with the hierarchy
- The specific fix (CSS or HTML structure change)
- Severity

CHECK FOR:

Heading hierarchy:
- Skipped heading levels (h1 followed by h3, no h2)
- Headings that don't visually communicate their level (h3 looks like h2)
- Too many heading levels (h4, h5, h6 rarely needed - flatten the hierarchy)
- Subheadings (h3 under h2) that visually compete with their parent heading

Section separation:
- Horizontal rules that are too prominent or too subtle
- Section breaks that need more or less visual weight
- Sections that run together without clear boundaries
- Inconsistent section separation methods (some use hr, some use spacing)

Data presentation hierarchy:
- Tables where the most important column isn't visually emphasized
- Charts where the key takeaway isn't the most visually prominent element
- Source citations that compete with the data they reference
- Footnotes or annotations that break the reading flow

Content emphasis:
- Bold, italic, and link styles that create too many competing focal points
- Callouts or highlights that don't stand out from body text
- Important numbers or statistics not visually distinguished
- Inline code or technical terms that disrupt reading flow

Scan-ability:
- Long unbroken text blocks without visual anchors (subheadings, bold, lists)
- Sections where a reader scanning headings would miss the key point
- Dense paragraphs that would benefit from being broken into a list or table

Return findings as a JSON array:
[{"section": "...", "issue": "...", "fix": "...", "file": "source file", "severity": "high|medium|low"}]
```

---

**Agent 5: Accessibility**

```
You are a WCAG accessibility auditor. Analyze the DOM structure, computed styles, and CSS for accessibility issues.

For each issue found, report:
- The element(s) affected
- Which WCAG guideline is violated
- The specific fix
- Severity

CHECK FOR:

Color contrast (WCAG 2.1 AA):
- Body text contrast ratio must be at least 4.5:1 against its background
- Large text (18px+ or 14px+ bold) needs at least 3:1
- UI component boundaries need at least 3:1 against adjacent colors
- Check both light and dark theme if applicable

Text sizing:
- Text below 12px anywhere on the page
- Text that doesn't scale with browser zoom (using px instead of rem/em for font-size)
- Line heights specified in fixed units (should be unitless or relative)

Interactive elements:
- Links distinguishable only by color (need underline or other non-color indicator)
- Focus styles missing or insufficient (all interactive elements need visible focus)
- Click/touch targets smaller than 44x44 CSS pixels

Semantic structure:
- Missing landmark roles (main, nav, article, aside)
- Images without alt text
- Tables without proper th/scope attributes
- Heading hierarchy violations (non-sequential levels)
- Lists of items not using ul/ol elements

Motion and animation:
- Animations that can't be disabled (check for prefers-reduced-motion)
- Auto-playing content without pause controls

Return findings as a JSON array:
[{"element": "CSS selector or description", "wcag": "guideline number", "issue": "...", "fix": "...", "file": "source file", "severity": "high|medium|low"}]
```

---

**Agent 6: Component Consistency**

```
You are a design system reviewer checking that similar elements are styled consistently. Analyze the CSS and computed styles for inconsistencies.

For each issue found, report:
- The inconsistent elements
- What's inconsistent
- The specific CSS fix to unify them
- Severity

CHECK FOR:

Table consistency:
- Different tables using different cell padding, font sizes, or header styles
- Some tables with borders, others without
- Inconsistent text alignment across tables (some left, some centered)
- Table header styling varies between tables

Chart/visualization consistency:
- Bar chart styling inconsistent across instances (height, border-radius, spacing)
- Chart labels using different font sizes or weights
- Source notes styled differently under different charts
- Color usage inconsistent (same category using different colors in different charts)

Card/container consistency:
- Similar containers with different padding, border-radius, or shadow
- Callout boxes or highlighted sections with inconsistent styling

Link styling:
- Links styled differently in different contexts without clear reason
- Inconsistent hover/active states

Spacing patterns:
- Similar components using different margin/padding values
- Section spacing that varies without clear hierarchy reason

Number and data formatting:
- Currency values formatted inconsistently ($1.2T vs $1,200B)
- Percentages styled differently in different tables
- Inconsistent use of bold for emphasis in data

Interactive states:
- Hover effects present on some interactive elements but not others
- Focus rings inconsistent across interactive elements

Return findings as a JSON array:
[{"elements": "what's inconsistent", "issue": "...", "fix": "CSS to unify", "file": "source file", "severity": "high|medium|low"}]
```

---

### Step 4: Visual Analysis (Main Agent)

While agents are running, review your own screenshots from Step 2. Look for issues that code analysis alone can't catch:

- Elements that look visually "off" even if CSS is technically correct
- Optical alignment issues (mathematical alignment vs visual alignment)
- Overall page "feel" - does it look polished and intentional or rough?
- Color balance - do the chart colors work together?
- Dark mode issues (if applicable)

Add any visual-only findings to your own list.

### Step 5: Score the Page

After all agents complete, compute a scorecard across 6 dimensions (1-10 each, 60 max):

| Dimension | What It Measures | Agent Source |
|-----------|-----------------|--------------|
| **Spacing** | Vertical rhythm, alignment, whitespace, breathing room | Agent 1 |
| **Typography** | Type scale, readability, line height, measure | Agent 2 |
| **Responsive** | Mobile/tablet behavior, reflow, breakpoints | Agent 3 |
| **Hierarchy** | Visual weight, heading structure, scan-ability | Agent 4 |
| **Accessibility** | WCAG compliance, contrast, semantics, focus | Agent 5 |
| **Consistency** | Component uniformity, pattern adherence | Agent 6 |

**Scoring guidelines:**
- 9-10: Production-ready. No meaningful improvements possible.
- 7-8: Strong. A few fixable issues, but solid overall.
- 5-6: Adequate. Noticeable issues that affect the experience.
- 3-4: Weak. Significant problems that undermine quality.
- 1-2: Needs fundamental rework in this dimension.

### Step 6: Compile Results

Compile all findings into a single **numbered, prioritized list** ordered from highest to lowest priority.

**Deduplication**: If multiple agents flag the same element, merge into a single finding and note which lenses caught it.

**Prioritization rules** (apply in order):

1. **Severity tier** is the primary sort: Critical > Important > Polish
   - **Critical** - Accessibility violations (WCAG AA), broken layouts, text unreadable, content overflow
   - **Important** - Spacing inconsistencies, typography issues, responsive problems, hierarchy gaps
   - **Polish** - Minor inconsistencies, micro-adjustments, optical alignment, nice-to-haves

2. **Within each tier**, rank by impact:
   - Issues visible on every viewport rank above viewport-specific issues
   - Issues affecting multiple components rank above single-element issues
   - Issues in the above-the-fold content rank above below-the-fold
   - Accessibility issues rank above aesthetic issues at the same severity

Each item in the list includes:
- A number (sequential across all tiers)
- The severity tier tag: `[Critical]`, `[Important]`, or `[Polish]`
- A concise description of the issue
- The exact CSS selector or element affected
- The specific fix (CSS property: value, or HTML change)
- Which file to edit
- Which design lens(es) caught it

### Step 7: Present to User

Display the scorecard first:

```
DESIGN REVIEW SCORECARD (XX/60)

Spacing:       X/10  ████████░░
Typography:    X/10  ██████░░░░
Responsive:    X/10  █████████░
Hierarchy:     X/10  ███████░░░
Accessibility: X/10  █████████░
Consistency:   X/10  ████████░░
```

Then display the full numbered list from Step 6.

After the list, use `AskUserQuestion` to ask how the user wants to proceed:

1. **Implement all** - Apply every fix from the list
2. **Pick and choose** - Let me select which items to implement by number
3. **None** - Keep the report as reference, make no changes

If `--fix` was passed, skip the question and apply all Critical-level fixes automatically, then ask about the remaining items.

If the user chooses **"Pick and choose"**, ask them to provide the item numbers they want implemented (e.g., "1, 3, 5-8, 12"). Then apply only those.

### Step 8: Apply Fixes (if requested)

Apply approved CSS/HTML changes using the Edit tool. Work through edits grouped by file.

After all edits:
1. Rebuild if applicable (`npm run build` or equivalent)
2. Reload the page in the browser
3. Take a new screenshot to verify the fixes look correct
4. Report before/after comparison
