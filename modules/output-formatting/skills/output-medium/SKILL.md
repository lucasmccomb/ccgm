---
name: output-medium
description: Conventions for each output medium above prose - ASCII and Mermaid diagrams, and HTML pages (Artifact tool or the ccgm-md-page fallback). Load before drawing a diagram or writing a page for the operator.
disable-model-invocation: false
---

# Output Medium Conventions

The `output-medium` rule picks the medium. This skill holds the conventions for each one. The prose answer still leads the final message; the diagram or page adds to it.

Every rung degrades. A missing tool means a skipped check and a one-line note, never a failed task. Write files and print their paths. Never open a page.

## Diagrams

Use a diagram for a flow, sequence, dependency, state machine, architecture, or before/after structure. One idea per diagram. End with a one-line caption.

### ASCII (terminal, question previews)

- Put it in a fenced code block.
- Use box-drawing characters: `┌ ─ ┐ │ └ ┘ ▶ ▼`.
- Keep every line at 100 columns or fewer.
- Put labels inside boxes. Make arrows show direction.
- In `AskUserQuestion`, put the diagram in the option's `preview` field, which renders monospace beside the options. Never put it in the question text.

Check the width before you send it. Save the diagram to a file, then run:

```bash
python3 -c 'import sys; [print(f"line {n} is {len(l.rstrip(chr(10)))} columns") for n, l in enumerate(open(sys.argv[1], encoding="utf-8"), 1) if len(l.rstrip(chr(10))) > 100]' diagram.txt
```

No output means every line fits. Do not use `awk 'length($0) > 100'` here: macOS `awk` counts bytes, so a box-drawing character counts as 3. In advisor mode the guard denies `python3 -c`; skip the width check there and keep each line short by hand.

### Mermaid (GitHub destinations: PR bodies, issues, READMEs)

- Use `flowchart`, `sequenceDiagram`, or `stateDiagram-v2`.
- Use at most 12 nodes. Split larger diagrams.
- Use short IDs and quoted labels: `A["Request"] --> B["Handler"]`.
- Check the syntax when `npx` exists:

```bash
npx -y @mermaid-js/mermaid-cli -i diagram.mmd -o diagram.svg
```

When `npx` is missing, skip the check and say so in one line. Do not use Mermaid in the terminal; the operator sees raw text there.

## Pages

Use a page for more than 5 items on more than 3 attributes, a long report the operator will scan or revisit, data worth charting, or anything that needs filters. The first screen holds the answer.

### With the Artifact tool

Load `artifact-design`, plus `artifact-diagramming` or `dataviz` when the page has diagrams or charts. Follow the tool's own publish guidance. Print the link.

### Without the Artifact tool

Write the content as markdown, then render it:

```bash
test -x "$HOME/.claude/bin/ccgm-md-page"
```

If that exits non-zero, `ccgm-md-page` is missing: print a one-line "not installed" note, give the markdown file path, and continue. Otherwise run it as its own command:

```bash
"$HOME/.claude/bin/ccgm-md-page" /abs/path/report.md -o /abs/path/report.html --title "Report title"
```

Use absolute paths; in advisor mode relative paths are denied. The output path must end in `.html`.

The command prints the page path. Print that path to the operator. Keep each step a separate command; do not join them with `if` or `&&`, and do not assign variables.

What the page tool does:

- Renders in the browser with pinned `marked` and `DOMPurify`, so hostile markdown cannot run code.
- Loads `mermaid` only when the markdown has a `mermaid` block, so put diagrams in that fence.
- Shows the markdown source when offline or when JavaScript is off.
- Adds a table of contents above 4 `##` headings and fits a 390 px screen.
- Needs network access to the CDN to render. Offline, the operator reads the source text.

## Video

Video is never chosen unprompted. The `explainer-video` module owns it. `/explain <topic> as video` uses it when installed.
