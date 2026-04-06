---
description: Session startup - check logs, git status, open issues, and orient
allowed-tools: Agent
---

# /startup - Session Startup

Use the Agent tool to execute this workflow on a cheaper model:

- **model**: haiku
- **description**: session startup

Pass the agent all workflow instructions below.

After the agent completes, relay its session summary dashboard to the user exactly as received. Then wait for the user's next instruction.

---

## Workflow Instructions

### Step 1: Gather Data

Run the gather script. It collects all session data in parallel and outputs structured `=== SECTION ===` blocks:

```bash
bash ~/.claude/lib/startup-gather.sh
```

**IMPORTANT**: The gather output is raw internal data. Do NOT display it to the user. Parse it silently and only output the formatted dashboard in Step 4.

### Step 2: Read Previous Log

From the `=== LOG ===` section:
- If `status:existing`, the `=== PREV_LOG_TAIL ===` section already has the last 20 lines of context.
- If `status:new` and `prev:` is not "none", read that file with the Read tool for previous session context.

### Step 3: Create Today's Log (if needed)

Only if `status:new` in the LOG section:

1. Run `mkdir -p {dir}` (from LOG section's `dir:` value). Run this as its own bash call, not grouped with other commands.
2. Create the log file at `file:` path:

```markdown
# {agent_id} - {date} - {repo}

## Session Start
- **Time**: {time from IDENTITY section}
- **Branch**: `{branch from GIT section}`
- **State**: {Clean if GIT STATUS section is empty, dirty otherwise}
```

### Step 4: Present Dashboard

Format the gathered data for terminal display. Use **bold** for labels, `backticks` for values, and `---` for separators. Do NOT use markdown headers (`#`, `##`, `###`). Omit sections with no content.

Output this exact structure (replace placeholders, keep formatting):

```
**{agent_id}** | `{repo}` | {date}
**Branch:** `{branch}` | **Status:** {clean/dirty} | **Sync:** {ahead_behind or "up to date"}

---

**Previous** — {One-line summary from PREV_LOG_TAIL, or "No prior session found"}
```

Then add only sections that have content, each separated by a blank line with a bold label:

```
**Live Sessions**
  {each session on its own line, indented}

**Open PRs** ({count})
  {each PR on its own line, indented}

**Tracking**
  {active claims and unclaimed issues, indented}

**Cross-Agent**
  {CROSS_AGENT content, indented}

**Siblings**
  {SIBLINGS content, indented}
```

End with the recommendation after a separator:

```
---
**Next:** {recommended action per table below}
```

If RELEASE section contains `UPDATE_AVAILABLE`, add before Next:
```
**Update:** v{current} -> v{latest} (`npm i -g @anthropic-ai/claude-code@latest`)
```

If ORPHANS section has output, include its warning.

**STOP after presenting the dashboard.** Do not continue work. Wait for user instruction.

| State | Recommendation |
|-------|---------------|
| PR open from previous session | Report PR URL and CI status |
| In-progress issue | Report issue and branch |
| Uncommitted changes | Report what's uncommitted |
| No active work | Report available issues |
| All issues done | Ask what to work on next |
| Update available | Suggest upgrading first |
