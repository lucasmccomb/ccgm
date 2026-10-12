# output-formatting

Formatting rules for output addressed to the operator: copy-pasteable content, and a ladder that picks the lowest medium that carries the content.

## What It Does

### Copy-paste output

A rule governs content the user intends to paste somewhere else (emails, texts, social posts, bios, form answers, prompts for other tools, config snippets):

- Pasteable content goes in a **fenced code block** containing exactly the text that should land at the destination
- **Never** blockquotes (`>`), which render as a vertical line in the terminal and copy dirty
- No decorative quotation marks, indentation, or labels mixed into the content
- Commentary and option labels stay outside the block
- Plain text by default; markdown source only when the destination renders markdown

### Medium ladder

A short always-loaded rule (`output-medium.md`) tells the agent to pick the lowest medium that carries the content:

| Content shape | Medium |
|---|---|
| Status, result, decision, short explanation | Prose |
| Flow, sequence, dependency, state machine, architecture, before/after | Diagram: ASCII (terminal), Mermaid (GitHub), inline SVG (page) |
| More than 5 items on more than 3 attributes, a long report, data to chart | Page: the Artifact tool when present, else `ccgm-md-page` |
| A new concept the operator asked to learn | Video, only on request (the `explainer-video` module) |

The prose answer leads. A diagram or page adds to it. The rule applies to text addressed to the operator, not to a subagent reporting to its caller. The `output-medium` skill holds the conventions for each medium.

### `/explain <topic> [as prose|diagram|page|video]`

Reads what it needs, picks the medium (or honours `as`), checks the result, and ends with a summary of 5 lines or fewer plus the path or link. `as video` without `explainer-video` says so and offers a page.

### `ccgm-md-page IN.md [-o OUT.html] [--title T]`

Turns markdown into one self-contained HTML page for installs without the harness Artifact tool. Stdlib Python. It writes the file, prints the path, and never opens it.

- Renders in the browser with pinned `marked` and `DOMPurify` (exact versions, SRI hashes, `crossorigin="anonymous"`). Hostile markdown cannot run code.
- Loads `mermaid` only when the markdown has a `mermaid` block.
- Shows the markdown source when JavaScript is off (`<noscript>`) or a CDN file fails to load.
- Light and dark themes, a readable column, a table of contents above 4 `##` headings, no horizontal scroll at 390 px.
- The pinned versions and hashes are constants at the top of the script.

Callers run it as `"${CCGM_BIN:-$HOME/.claude/bin}/ccgm-md-page"` because `~/.claude/bin` is not on `PATH`.

## Tests

```bash
python3 -m pytest modules/output-formatting/tests -q
bash modules/output-formatting/tests/test-output-formatting.sh
bash modules/output-formatting/tests/test-md-page-e2e.sh   # headless Chromium via orrery's toolchain
```

The browser test skips with a note when orrery's Playwright toolchain is absent. Set `CCGM_E2E_REQUIRED=1` to fail instead.

## Manual Installation

```bash
mkdir -p ~/.claude/rules ~/.claude/skills/output-medium ~/.claude/commands ~/.claude/bin
cp rules/copy-paste-output.md ~/.claude/rules/copy-paste-output.md
cp rules/output-medium.md ~/.claude/rules/output-medium.md
cp skills/output-medium/SKILL.md ~/.claude/skills/output-medium/SKILL.md
cp commands/explain.md ~/.claude/commands/explain.md
cp bin/ccgm-md-page ~/.claude/bin/ccgm-md-page
chmod +x ~/.claude/bin/ccgm-md-page
```

## Files

| File | Description |
|------|-------------|
| `rules/copy-paste-output.md` | Rule file: fenced code blocks for pasteable content, never blockquotes |
| `rules/output-medium.md` | Rule file (20 lines or fewer): pick the lowest medium that carries the content |
| `skills/output-medium/SKILL.md` | Conventions for ASCII and Mermaid diagrams and for pages |
| `commands/explain.md` | `/explain`: explain a topic in the right medium |
| `bin/ccgm-md-page` | Markdown to a self-contained HTML page |
