# output-formatting

Formatting rules for user-facing output, starting with copy-pasteable content.

## What It Does

This module installs a rule that governs how Claude presents content the user intends to copy-paste somewhere else (emails, texts, social posts, bios, form answers, prompts for other tools, config snippets):

- Pasteable content goes in a **fenced code block** containing exactly the text that should land at the destination
- **Never** blockquotes (`>`), which render as a vertical line in the terminal and copy dirty
- No decorative quotation marks, indentation, or labels mixed into the content
- Commentary and option labels stay outside the block
- Plain text by default; markdown source only when the destination renders markdown

The result: the user selects, copies, and pastes — no reformatting pass at the destination.

## Manual Installation

Copy `rules/copy-paste-output.md` into your Claude configuration:

```bash
# Global (all projects)
cp rules/copy-paste-output.md ~/.claude/rules/copy-paste-output.md

# Project-level
cp rules/copy-paste-output.md .claude/rules/copy-paste-output.md
```

## Files

| File | Description |
|------|-------------|
| `rules/copy-paste-output.md` | Rule file: fenced code blocks for pasteable content, never blockquotes |
