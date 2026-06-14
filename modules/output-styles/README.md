# output-styles

Delivers CCGM's always-on **tone** rules as a Claude Code *output style* — a system-prompt layer that is fixed at session start and prompt-cached — instead of always-loaded `rules/*.md`.

## What It Does

Installs one output style, `CCGM Terse` (`output-styles/ccgm-terse.md`), that consolidates the three tone-shaping behaviors CCGM otherwise spreads across always-loaded rules:

| Behavior | Source rule (still shipped) |
|----------|-----------------------------|
| Terse, action-first communication | `identity` → `rules/soul.md` (Communication Style) |
| Autonomous, end-to-end execution | `autonomy` → `rules/autonomy.md` |
| Clean copy-paste output (fenced blocks, never blockquotes) | `output-formatting` → `rules/copy-paste-output.md` |

Activate it with `/config` (output style is fixed per session for prompt caching; the older `/output-style` command is deprecated).

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
```

Then select **CCGM Terse** via `/config` in Claude Code.

## Files

| File | Description |
|------|-------------|
| `output-styles/ccgm-terse.md` | The output style: terse tone + autonomy + copy-paste formatting, with frontmatter (`name`, `description`, `keep-coding-instructions: true`). |

## Dependencies

None. Standalone; complements (does not require) `identity`, `autonomy`, and `output-formatting`.
