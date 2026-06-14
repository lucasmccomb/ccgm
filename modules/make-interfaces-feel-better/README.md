# Make Interfaces Feel Better

Design-engineering details that compound into polished interfaces. Model-invoked skill that fires when Claude works on UI polish, animations, shadows, borders, typography, enter/exit transitions, or anything whose success depends on getting small visual details right.

## What it covers

The skill ships a top-level `SKILL.md` plus reference files that the skill pulls in on demand:

| Reference | When it applies |
|-----------|-----------------|
| `design-direction.md` | Aesthetic identity (minimal/brutalist/editorial/…), typeface and color-palette selection, spacing scale, motion philosophy, avoiding generic AI-generated aesthetics. **CCGM addition, not upstream.** |
| `typography.md` | `text-wrap: balance` / `pretty`, font smoothing on macOS, tabular numbers for dynamic values |
| `surfaces.md` | Concentric border radius, optical vs geometric alignment, shadows instead of borders, image outlines, hit areas |
| `animations.md` | Interruptible animations (transitions vs keyframes), enter/exit transitions, icon micro-interactions, scale on press |
| `performance.md` | Transition specificity, `will-change` usage |

Trigger words (from the skill's frontmatter): UI polish, design details, "make it feel better", "feels off", stagger animations, border radius, optical alignment, font smoothing, tabular numbers, image outlines, box shadows.

## Usage

Model-invoked: Claude loads the skill automatically when the conversation is about visual polish or UI details. No slash command required.

## Manual Installation

```bash
mkdir -p ~/.claude/skills/make-interfaces-feel-better
cp skills/make-interfaces-feel-better/*.md ~/.claude/skills/make-interfaces-feel-better/
```

## Upstream

`SKILL.md`, `typography.md`, `surfaces.md`, `animations.md`, and `performance.md` are vendored from [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better) (MIT). Content is based on Jakub Krehel's article [Details that make interfaces feel better](https://jakub.kr/writing/details-that-make-interfaces-feel-better). Those skill files are copied verbatim; attribution belongs to the upstream author.

`design-direction.md` is a **CCGM addition** (folded in from the former `frontend-design` module) and is **not** part of the upstream repo. `SKILL.md` carries a one-line pointer to it.

To refresh the upstream files (this deliberately excludes `design-direction.md`, which has no upstream counterpart):

```bash
git clone --depth 1 https://github.com/jakubkrehel/make-interfaces-feel-better /tmp/mifb
# Copy only the upstream files; do NOT touch design-direction.md
for f in SKILL typography surfaces animations performance; do
  cp "/tmp/mifb/skills/make-interfaces-feel-better/$f.md" \
     modules/make-interfaces-feel-better/skills/make-interfaces-feel-better/
done
# Re-add the design-direction pointer to SKILL.md if the refresh overwrote it.
```
