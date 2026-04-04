# Design Review

Comprehensive frontend design review. Collects page data (screenshots, DOM, CSS), runs 6 parallel analysis passes, and produces a scored, prioritized list of actionable CSS/HTML fixes.

## `/design-review [url] [--fix]`

Takes screenshots at desktop (1440px), tablet (768px), and mobile (375px), extracts DOM structure and computed styles, then runs 6 parallel analysis passes:

| Pass | What It Checks |
|------|---------------|
| Spacing & Layout | Vertical rhythm, alignment, whitespace, chart/table spacing |
| Typography | Type scale, readability, line height, measure, contrast |
| Responsive Design | Breakpoint coverage, mobile/tablet issues, content reflow |
| Visual Hierarchy | Heading structure, section separation, scan-ability |
| Accessibility | WCAG AA contrast, semantic structure, focus styles, touch targets |
| Component Consistency | Table/chart/card uniformity, link styling, interactive states |

Produces a scorecard (6 dimensions, 60 points max) and a prioritized findings list with exact CSS selectors and property values. Optionally applies fixes with `--fix`.

Requires Chrome browser automation tools (Claude-in-Chrome extension).

**Usage:**
```
/design-review
/design-review http://localhost:3000/page
/design-review http://localhost:3000/page --fix
```

## Manual Installation

```bash
mkdir -p ~/.claude/skills/design-review
cp skills/design-review/SKILL.md ~/.claude/skills/design-review/SKILL.md
```
