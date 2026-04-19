---
description: Session startup - repo-aware intelligent summary
allowed-tools: Bash
---

# /startup - Session Startup

Run the summary script and display its output verbatim:

```bash
bash ~/.claude/lib/startup-summary.sh $ARGUMENTS
```

The script runs the gather pipeline, feeds the output to a headless Sonnet
model via `claude -p`, and emits a short markdown summary with sections for
Where we are / Recent activity / Open PRs / Top open issues / Live sessions /
Next up. Display the output as-is, then **stop and wait** for the user's next
instruction. Do NOT add commentary, do NOT continue into other work.

## Flags

- `/startup --raw` — skip the model pipeline; emit the deterministic plain-text
  dashboard produced by `startup-dashboard.sh`. Useful for debugging or when
  offline.

## How it works

1. `startup-gather.sh` collects structured data (git state, merges, PRs,
   tracking, sessions, priority issues, etc.) in parallel — deterministic,
   zero model tokens.
2. `startup-summary.sh` pipes the gather output plus a fixed prompt into
   `claude --model sonnet --no-session-persistence -p`. Summarization is a
   judgment task, so a model call is warranted.
3. If `claude` is missing, returns empty, or any step fails, the script falls
   back to `startup-dashboard.sh` automatically.

To debug the raw data the summary is working from:

```bash
bash ~/.claude/lib/startup-gather.sh
```
