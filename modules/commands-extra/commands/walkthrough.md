# /walkthrough - Step-by-Step Guide Mode

Enter guided walkthrough mode where Claude presents one step at a time and waits for confirmation before advancing.

## Trigger

Activate when the user says "walk me through", "guide me through", "step me through", or uses `/walkthrough`.

## Behavior

1. **Identify the task** - Understand what the user wants to accomplish
2. **Break it down** - Divide the task into discrete, sequential steps
3. **Present one step at a time** with clear instructions
4. **Show progress** - Display "**Step N/Total**" at the start of each step
5. **STOP and wait** for the user to confirm completion, ask questions, or provide information
6. **Never skip ahead** or present multiple steps at once - one step, one confirmation, then next
7. **Adapt** - If the user provides info (API keys, account IDs, URLs), incorporate it into subsequent steps
8. **Resolve blockers** - If the user is stuck on a step, help resolve the issue before moving on
9. **Only advance when confirmed** - Do not proceed until the user explicitly signals they are ready

## Step Format

Each step should follow this format:

```
**Step N/Total: [Brief title]**

[Clear instructions for this step]

[Any code blocks, commands, or configuration needed]

[What to expect / how to verify this step succeeded]

---
Ready to continue? Let me know when this step is done, or ask if you have questions.
```

## Guidelines

- Keep each step focused on ONE action or decision
- Provide enough context so the user understands WHY they are doing this step
- Include verification criteria so the user knows the step succeeded
- If a step requires the user to perform an action in a third-party UI (dashboard, browser), describe exactly where to click and what to look for
- If a step has prerequisites, state them clearly at the top
- Estimate complexity: mark steps as quick (< 1 min), moderate (1-5 min), or involved (5+ min)

## Usage

```
/walkthrough deploy to cloudflare    # Guided deployment walkthrough
/walkthrough setup supabase auth     # Guided auth configuration
/walkthrough migrate database        # Guided migration process
```
