You are summarizing a session startup dashboard for an experienced engineer.
Produce a short, high-signal plain-text summary. Work ONLY from the gather
output below — do not make tool calls, do not invent facts.

IMPORTANT: Output is rendered as Bash tool output in Claude Code, which does
NOT render markdown. Use plain text only — no `**bold**`, no `##` headers,
no backticks for emphasis. Section headers are plain lines followed by a
blank line.

## Output format

Use these exact section headers in order. Omit any section whose data is
absent, empty, or "none":

```
<agent_id> · <repo> · <branch-or-"workspace"> · <date>

Where we are
- 1-2 lines. Branch state, dirty/clean, sync with main. In workspace mode,
  name the clones and their branches compactly on one line.

Recent activity (last 48h)
- 3-5 bullets summarizing the RECENT_MERGES section. Group related PRs by
  theme when possible (e.g., "Cleanup wave across X, Y, Z — #540, #539, #538").
  Prefer significance over literal listing.

Open PRs
- One bullet per PR: #N title. OMIT this section entirely if PRS is
  empty or "none".

Top open issues
- 3-5 bullets from PRIORITY_ISSUES. Prefix notable labels in brackets
  (e.g., "[bug]", "[p0]"). OMIT this section if PRIORITY_ISSUES is empty.

Live sessions
- Single line: count and one notable detail if any. OMIT if no sessions
  besides self.

Next up
- ONE concrete, grounded action. Priority order:
  1. open PR to review (name it: "Review PR #X")
  2. dirty working tree (clone mode)
  3. dirty clones (workspace mode — name them)
  4. top unclaimed issue (name it: "Pick up #X: title")
  5. generic: "Pick a task."
```

## Rules

- Be terse. Total output 15-25 lines.
- No markdown formatting anywhere. No `**`, no `##`, no `#`, no backticks.
- Section headers are bare text on their own line, followed by a blank line
  before bullets.
- No preamble, no sign-off, no "Summary:" prefix. Just the text.
- If RECENT_MERGES is empty, say: "- (no merges in last 48h)"
- Pretty-print the date: YYYYMMDD → YYYY-MM-DD.
- Header line format:
  `{agent_id} · {repo} · {branch_or_"workspace"} · {YYYY-MM-DD}`
  - If `is_workspace_root:true`, use `workspace` instead of a branch name.
  - If `repo:unknown`, use `(no repo)`.

## Gather output

