# Make Interfaces Feel Better

Design-engineering details that compound into polished interfaces. Model-invoked skill that fires when Claude works on UI polish, animations, shadows, borders, typography, enter/exit transitions, or anything whose success depends on getting small visual details right.

## What it covers

The skill ships a top-level `SKILL.md` plus four reference files that the skill pulls in on demand:

| Reference | When it applies |
|-----------|-----------------|
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

Vendored from [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better) (MIT). Content is based on Jakub Krehel's article [Details that make interfaces feel better](https://jakub.kr/writing/details-that-make-interfaces-feel-better). Skill files are copied verbatim; attribution belongs to the upstream author.

To refresh from upstream:

```bash
git clone --depth 1 https://github.com/jakubkrehel/make-interfaces-feel-better /tmp/mifb
cp /tmp/mifb/skills/make-interfaces-feel-better/*.md modules/make-interfaces-feel-better/skills/make-interfaces-feel-better/
```
