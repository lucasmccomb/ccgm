# output-styles

Delivers CCGM's always-on **tone** rules as Claude Code *output styles* — a system-prompt layer that is fixed at session start and prompt-cached — instead of always-loaded `rules/*.md`.

## What It Does

Installs two output styles:

**`CCGM Terse`** (`output-styles/ccgm-terse.md`) consolidates the three tone-shaping behaviors CCGM otherwise spreads across always-loaded rules, plus an Actionability layer (numbered steps, state restated each turn, one concrete next action, testable win reporting, concrete time estimates, 5-item list cap):

| Behavior | Source rule (still shipped) |
|----------|-----------------------------|
| Terse, action-first communication | `identity` → `rules/soul.md` (Communication Style) |
| Autonomous, end-to-end execution | `autonomy` → `rules/autonomy.md` |
| Clean copy-paste output (fenced blocks, never blockquotes) | `output-formatting` → `rules/copy-paste-output.md` |

**`CCGM ADHD`** (`output-styles/ccgm-adhd.md`) is the full-strength version of the actionability rules, shaped for a reader with ADHD: every response leads with the next doable action, multi-step work is numbered and its state restated every turn, wins are shown in testable terms, lists cap at 5, and a pre-send check strips announcing openers and recapping closers. Includes explicit override conditions (explanations, destructive actions, debug spirals, real ambiguity). Adapted from [`ayghri/i-have-adhd`](https://github.com/ayghri/i-have-adhd) (MIT), itself loosely based on *The Adult ADHD Tool Kit* (Ramsay & Rostain).

Activate either with `/config` (output style is fixed per session for prompt caching; the older `/output-style` command is deprecated).

## Why an Output Style Instead of a Rule

Claude Code loads every `rules/*.md` into context on every session and re-sends it every turn. Output styles are different: Claude Code applies them as a **system-prompt layer fixed at session start**, which means they are **prompt-cached** rather than re-sent as conversation context each turn.

For stable, always-on *tone* instructions — which never change mid-session — this is the cheaper home. The behavior is identical; the difference is where the tokens live and how often they are billed.

## The Tradeoff

This module **does not delete** the source rules in `identity`, `autonomy`, or `output-formatting`. It offers a styled alternative, so you choose between two delivery mechanisms:

| | Always-loaded rules (default) | Output style (this module) |
|---|---|---|
| **Token cost** | Re-sent every turn as context | Cached at session start |
| **Granularity** | Per-rule install / removal | One bundled style |
| **Edit-to-apply** | Takes effect next session | Fixed at session start; re-select via `/config` |
| **Project overrides** | Per-repo `rules/` supported | Global style |

**If you install this module, consider removing the redundant tone rules** to avoid sending the same guidance twice. The conservative default is to keep both and measure: the rules guarantee the behavior; the style is the token optimization. Do not assume the style alone is active until you have selected it via `/config`.

## Manual Installation

```bash
mkdir -p ~/.claude/output-styles
cp output-styles/ccgm-terse.md ~/.claude/output-styles/ccgm-terse.md
cp output-styles/ccgm-adhd.md ~/.claude/output-styles/ccgm-adhd.md
```

Then select **CCGM Terse** or **CCGM ADHD** via `/config` in Claude Code.

## Files

| File | Description |
|------|-------------|
| `output-styles/ccgm-terse.md` | Terse tone + autonomy + actionability + copy-paste formatting, with frontmatter (`name`, `description`, `keep-coding-instructions: true`). |
| `output-styles/ccgm-adhd.md` | Action-first output shaped for an ADHD reader: 10 rules, override conditions, and a pre-send check. Adapted from `ayghri/i-have-adhd` (MIT). |

## Dependencies

None. Standalone; complements (does not require) `identity`, `autonomy`, and `output-formatting`.
