# /handoff — Write a session handoff with copy-paste kickoff prompt

Write a structured markdown handoff to disk AND emit a copy-paste-ready kickoff prompt the next session can paste into a fresh Claude Code conversation. Solves the problem of context bloat: end a session before it degrades, paste the prompt into a new session, the next agent reads the handoff and picks up cleanly.

## Usage

```
/handoff                          Build the handoff from current session context
/handoff {one-line description}   Same, but seed the title
```

The skill is **always interactive**: you (the agent) gather the six sections from session context, write the file, and print the kickoff prompt verbatim. Do not skip sections — every one has a purpose. If a section genuinely has no content, write `(none)` and move on.

## When to use

- **End of a working session** that you don't want to resume via `claude --continue` (session is bloated, you're switching machines, you're going headless, etc.)
- **Mid-task context checkpoint** when `/compact` would lose too much. Write the handoff, `/clear`, paste the kickoff prompt back in.
- **Before a risky operation** — handoff acts as a known-good restore point.
- **End-of-day pause**. Resume tomorrow with the kickoff prompt.

Skip for trivial one-liner commits or work entirely inside throwaway experiments. For the peer-clone broadcast use case, the same `handoff.py` lib also feeds `/startup` auto-injection — you do not need a separate command.

## The six sections (in priority order)

A good handoff is one a fresh agent can read in under 2 minutes and act on within 5. Target 200-400 words total, never more. Use file:line anchors instead of pasted file contents.

1. **Current state** — One paragraph snapshot of where things are right now. Not a journal of what you did; a state read.
2. **Next steps** — Numbered, immediate, actionable. Item #1 is what the next agent should do first.
3. **Decisions & rationale** — What you chose AND why. Without rationale, the next agent can't judge edge cases.
4. **Files in progress** — `path:lineStart-lineEnd — state — one-line note`. States: `editing`, `partial`, `needs_review`, `ready`.
5. **Gotchas** — Anti-patterns you discovered, surprises, things that look right but aren't. The "if I forgot to tell you this, you'd waste an hour" section.
6. **Blockers** — What's stopping forward progress and what would unblock it. `(none)` if nothing.

## Implementation

Gather the six sections, then invoke the helper. Prefer the `--body` heredoc form for multi-line content (file lists, numbered next steps with sub-bullets):

```bash
python3 ~/.claude/lib/handoff.py write --body "$(cat <<'EOF'
# Handoff — <one-line description>

## Current state

<one paragraph>

## Next steps

1. <action>
2. <action>

## Decisions & rationale

- **<decision>**: <why> (`file:line` if relevant)

## Files in progress

- `path/to/file.ts:40-80` — editing — <note>

## Gotchas

<anti-patterns, surprises>

## Blockers

<what's stuck, or (none)>
EOF
)"
```

For single-line sections (a quick checkpoint), the per-section flags work too:

```bash
python3 ~/.claude/lib/handoff.py write \
  --title "Fix auth bug" \
  --state "..." --next "..." --decisions "..." \
  --files "..." --gotchas "..." --blockers "..."
```

The lib auto-detects repo, branch, agent (from `.env.clone`), PR, and issue. Pass `--repo`/`--agent` explicitly only when detection fails.

## Output contract

The CLI prints two things, in this order:

1. **Line 1**: absolute path to the new handoff file (script-safe, capturable via `head -n1`)
2. **Below the divider**: the copy-paste kickoff prompt — three sentences plus an optional `[USER DIRECTIVE]` slot

You (the agent) must show the user the **full output verbatim**, including the divider, so they can grab the prompt with a single triple-click or drag-select. Do not paraphrase, reformat, or wrap it in extra markdown.

Example:

```
~/.claude/handoffs/myrepo/2026-05-21T16-46-25-agent-w0-c0.md

Copy the prompt below into your next session:
----------------------------------------------------------------
Continue from session handoff at ~/.claude/handoffs/myrepo/2026-05-21T16-46-25-agent-w0-c0.md.

Read it completely before doing anything else. Trust the context it gives you — do not re-explore the codebase unless the handoff is wrong or incomplete. Then start with item #1 in "Next steps".

[USER DIRECTIVE: leave blank to let the agent propose the next action, or fill in to override]
----------------------------------------------------------------
```

Pass `--no-kickoff` only if you have a specific script-side reason; the default is always on.

## How it gets consumed

Two paths, both supported:

- **Copy-paste path (primary):** the user takes the kickoff prompt and pastes it as the first message in a fresh Claude Code session (same repo, different machine, or `claude -p` headless). The receiving agent reads the absolute path, opens the doc, and starts with item #1.
- **Auto-injection path (secondary):** if the user runs `/startup` in a new session in this clone, `startup-gather.sh` calls `handoff.py summary --include-self --max 3 --days 3` and surfaces recent handoffs (including peers') in the dashboard. This is the same lib feeding the same files; no second mechanism.

Handoffs older than 30 days are pruned on startup. Each handoff is timestamped — never overwrite; write a new one if you need to revise.

## Conventions

- One handoff per "unit of handed-off work" (typically one session-end). Multiple handoffs in the same session is fine.
- No secrets. Handoffs live unencrypted under `~/.claude/handoffs/`. Never include env vars, API keys, or API response bodies. File paths only.
- Keep it terse. Two sentences in a section beats six. The next agent has fresh context — they don't need a tutorial, they need a state read.
