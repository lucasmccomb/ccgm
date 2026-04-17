# commands-preamble (Experimental)

Inject a compact preamble of iron-law principles at the start of every slash-command invocation.

## Status

**Experimental. Disabled by default.** Pilot this before committing to it across all commands.

## What It Does

CCGM rules live at `~/.claude/rules/*.md` and load from `CLAUDE.md` references. That covers the main conversation. But slash-commands expand into their own context and can drift from principles like:

- **Confusion Protocol** (stop and ask at architectural forks)
- **Completeness** (Boil the Lake - ship the whole job, not 90%)
- **Evidence Before Claims** (no completion claims without fresh output)
- **Root Cause Before Fix** (no fixes without investigation)
- **Completion Status** (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT)

This module installs a `UserPromptSubmit` hook that detects slash-command prompts and prepends a tagged `<command-preamble>` block containing those principles. The principles fire at invocation time, not "whenever the agent rereads CLAUDE.md."

## Why a Hook Instead of a Template

Three options were considered (see issue #298):

| Option | Tradeoff |
|--------|----------|
| **(a) Runtime hook** | Zero build step, runtime-dynamic, experimental-friendly. **Chosen.** |
| (b) Build-time template generator | Contradicts CCGM's zero-build simplicity. Requires TS/bun tooling. |
| (c) Convention: every command's first H2 is a preamble | Cheapest but drifts. Has to be maintained per-command by hand. |

The hook wins on reversibility - flip one file to disable, no rebuild needed.

## Enable / Disable

Disabled by default. To turn on:

```bash
touch ~/.claude/preamble.enabled
```

To turn off:

```bash
rm ~/.claude/preamble.enabled
```

The hook is always installed, but exits silently unless the sentinel file exists.

## How It Works

1. User submits a prompt.
2. `inject-preamble.py` runs (UserPromptSubmit hook).
3. If `~/.claude/preamble.enabled` is missing, exit silently.
4. If the prompt does not look like a slash-command (first token starts with `/` and isn't a filesystem path), exit silently.
5. Otherwise, read `~/.claude/preamble/preamble.md`, wrap it in a `<command-preamble>` block, and print to stdout. Claude Code appends stdout to the model's context before the prompt runs.

## Tuning the Preamble

Edit `~/.claude/preamble/preamble.md` to change what gets injected. Keep it compact - this prepends to every slash-command invocation, so bloat costs tokens on every call.

## Manual Installation

```bash
# Copy the hook
cp hooks/inject-preamble.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/inject-preamble.py

# Copy the preamble content
mkdir -p ~/.claude/preamble
cp preamble/preamble.md ~/.claude/preamble/

# Register the hook (merge settings.partial.json into ~/.claude/settings.json)
# See settings.partial.json for the hook entry to add under hooks.UserPromptSubmit.

# Enable (opt-in)
touch ~/.claude/preamble.enabled
```

## Files

| File | Description |
|------|-------------|
| `hooks/inject-preamble.py` | UserPromptSubmit hook. Prepends preamble block to slash-command prompts when enabled. |
| `preamble/preamble.md` | The preamble content (edit to tune). |
| `settings.partial.json` | Hook registration for `~/.claude/settings.json`. |
| `tests/test_inject_preamble.py` | Unit tests for the hook (slash-command detection, enable flag, injection format). |

## Testing

```bash
python3 -m unittest modules/commands-preamble/tests/test_inject_preamble.py -v
```

## Relationship to Other Modules

- `autonomy/rules/confusion-protocol.md` - source of the Confusion Protocol section in the preamble.
- `code-quality/rules/completeness.md` - source of the Completeness section.
- `verification/rules/verification.md` - source of Evidence Before Claims.
- `systematic-debugging/rules/systematic-debugging.md` - source of Root Cause Before Fix.
- `subagent-patterns/rules/subagent-patterns.md` - source of the four-state Completion Status Protocol.

The preamble does not replace those rule files - it surfaces their iron laws at command start. The full rules still govern behavior.

## Known Limitations

- Only fires on slash-command invocations. Regular conversational prompts are untouched (they already run under the full `CLAUDE.md` context).
- Preamble detection heuristic: first token starts with `/`, is >= 2 chars, and contains at most one slash. Edge cases like pasted absolute paths starting with `/tmp` would be misclassified; the `> 1 slash` guard rules out the common case. File an issue if you hit a false positive.
- The hook runs on every prompt. It exits immediately (~1ms) when disabled or when the prompt is not a command, so the cost is negligible.

## When to Disable

- When debugging a command and need to see the raw prompt context.
- When you are the kind of agent that re-reads rules on every response and doesn't need reinforcement.
- When the preamble is causing token bloat on long-running command sessions.
