---
description: Session startup - check logs, git status, open issues, and orient
allowed-tools: Bash
---

# /startup - Session Startup

Run the dashboard script and display its output verbatim:

```bash
bash ~/.claude/lib/startup-dashboard.sh
```

The script runs the data-gather pipeline, creates today's log if missing, and emits the formatted dashboard to stdout. Display the output as-is to the user, then **stop and wait for the user's next instruction**.

Do NOT add commentary, reformat the output, or continue into other work after the dashboard appears.

---

## Why this is a single bash call

The formatting is deterministic (section extraction + string interpolation), so there is no benefit to running it through a model. The previous implementation delegated to a Sonnet sub-agent and routinely burned ~48k tokens per startup while sometimes failing to surface the dashboard at all. The current implementation costs ~0 model tokens for formatting and is fail-fast visible (stderr messages appear directly if anything breaks).

If you need to debug what the dashboard is seeing, run the gather script directly:

```bash
bash ~/.claude/lib/startup-gather.sh
```

That produces the raw `=== SECTION ===` blocks the dashboard parses.
