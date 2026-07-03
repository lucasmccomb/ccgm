# /dream-scorecard - Weekly Observability Scorecard

Render a deterministic weekly scorecard over the memory system's read-path
signals — the honest answer to "how do I know the memory system is working?"

## Usage

```
/dream-scorecard             # last 7 days, ending today (UTC)
/dream-scorecard 2026-06-30  # the 7 days ending 2026-06-30 (inclusive)
```

## What it does

1. Resolve the week-ending date. With no argument, use today (UTC). With an
   argument, validate the `YYYY-MM-DD` shape. The window is the 7 calendar
   days ending on (and including) that date.
2. Run `bash ~/.claude/bin/dream-scorecard.sh {week-ending}`, which aggregates
   the existing on-disk read-path telemetry (read-only) and writes
   `~/.claude/dreaming/scorecards/{week-ending}.md`.
3. Print the rendered scorecard.

## Sections

- **Captured** — new learnings added in the window (store JSONL `add`/legacy
  op-events), grouped by type + project. In-window `supersede` refinements are
  surfaced as a separate sub-line (they are refinements, not new captures).
- **Injected** — sessions that received injected memory (#782 injection-log
  telemetry): session count, total learnings injected, top injected learnings.
- **Reused** — `verify` op-events in the window. This is the key value signal:
  a reuse means a stored learning paid off across sessions.
- **Applied** — proposals applied to the store in the window (apply-audit +
  proposals-dir funnel), by kind.
- **Store health** — total active learnings, effective-confidence bands, and
  deprecated/superseded counts.

## When to invoke

- A weekly check on whether the durable-memory system is capturing, injecting,
  and (most importantly) reusing learnings.
- Before deciding whether to enable an opt-in (auto-apply, injection): the
  scorecard shows whether there is enough signal yet to trust it.

## When NOT to invoke

- To act on a specific proposal — use `/dream-apply <id>`.
- For a per-day proposal digest — use `/dream-digest [date]`.
- For dates older than the retention window — older injection-log/proposals
  artifacts are swept by `dream-daily.sh`'s retention step, so an old window
  will under-count.

## How it interacts with state

Strictly **read-only** over the learnings store, proposals, apply-audit, and
injection-log. The one write is the rendered markdown at
`~/.claude/dreaming/scorecards/{week-ending}.md`. All counting lives in
`lib/scorecard.py` (deterministic, unit-tested); the `.sh` only resolves the
window + wall clock. The library never reads the wall clock itself.

## Cross-references

- Generator: `~/.claude/bin/dream-scorecard.sh` → `lib/scorecard.py`
- `/dream-digest [date]` — per-day proposal digest.
- `/dream-apply [id|list]` — the human-gated write path for proposals.
- Injection telemetry: `~/.claude/dreaming/injection-log/*.jsonl` (#782).
