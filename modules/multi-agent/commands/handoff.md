# /handoff — Write a handoff note for peer clones

Write a short markdown handoff so sibling clones on this machine can orient quickly on startup. Handoffs are the lightweight level between "nothing" and a full `/recall` transcript dive.

## Usage

```
/handoff                        Prompt yourself to fill in the three sections
/handoff {one-line description} Pre-seed the title; still fill in the sections
```

## When to use

- **After `gh pr merge`** on non-trivial work. The post-merge reflection hook already reminds you.
- **Before ending a session** that touched shared code another agent might need to pick up.
- **When you hand off a blocker** — name it explicitly so the next agent does not rediscover it.

Skip for trivial one-liner commits (typo fixes, dependency bumps) and for work entirely inside throwaway experiments.

## What to write

A handoff answers three questions, in order:

1. **What I did** — one paragraph. Shipped PR / functionality. Name files or modules touched. Link the PR if there is one.
2. **What's next** — immediate follow-ups. Open questions that block the next step. Ideally concrete enough that the next agent can act without re-deriving context.
3. **Blockers / context for the next agent** — known landmines, decisions made and their reason, anything that would surprise someone who did not sit through this session. Say nothing if nothing applies.

Keep the whole thing under ~200 words. If it needs more, you are writing docs, not a handoff.

## How it gets consumed

`auto-startup.py` reads `~/.claude/handoffs/{repo}/*.md` on SessionStart, filters out the current agent's own handoffs and anything older than 7 days, and injects a compact block into the fresh session. Peer agents see your handoff at the top of their next session's context.

Handoffs older than 30 days are pruned on startup.

## Implementation

Invoke the helper:

```bash
python3 ~/.claude/lib/handoff.py --repo "$(git remote get-url origin | sed 's#.*[:/]##;s#\.git$##')"
```

Or invoke the CLI shim installed alongside the lib. The helper reads `.env.clone` / cwd to derive agent identity, introspects git for branch/PR/issue, and writes the file.

## Conventions

- One handoff per "unit of handed-off work" (typically one PR). Multiple handoffs in the same session is fine.
- Do not overwrite — each handoff is timestamped; editing is done by writing a new one.
- No secrets. Handoffs live on-disk unencrypted under `~/.claude/handoffs/`.
