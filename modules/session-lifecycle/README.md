# session-lifecycle

`/sds` (Shutdown Sequence) — autonomous end-of-session wrap-up. Commits dirty work, updates referenced issues, runs `/reflect`, writes a handoff, and broadcasts to sibling clones.

Pairs with `/startup` at the other end of the session: where `/startup` orients you on session entry, `/sds` captures and disseminates context on session exit.

## What This Module Does

- **`/sds` command**: runs a fixed sequence of wrap-up phases without prompting unless something genuinely cannot proceed
- **`sds-broadcast.sh` helper**: deterministic sibling detection + tracking.csv signal writer (kept out of the LLM)

## The Sequence

`/sds` runs these phases in order. Each is a step the agent would otherwise have to remember to do separately:

1. **Background work check** — enumerate active background tasks; report and wait/kill as appropriate
2. **Working tree** — commit dirty changes (WIP commit + push on feature branches; ask on main)
3. **Issue updates** — comment on referenced issues with session summary; auto-close only when commit body has `closes/fixes #N` AND PR merged
4. **Reflect** — invoke the `/reflect` workflow inline to capture non-obvious learnings to the JSONL store
5. **Handoff** — write a structured handoff via `handoff.py write` to `~/.claude/handoffs/{repo}/`, where `auto-startup.py` will auto-inject it into the next session
6. **Sibling broadcast** — append a `session-ended` marker to `tracking.csv` so sibling clones in the same workspace see this clone has wrapped

## Files

| File | Type | Description |
|------|------|-------------|
| `commands/sds.md` | command | `/sds` shutdown sequence command |
| `lib/sds-broadcast.sh` | lib | Detects sibling clones from tracking.csv and writes the session-ended marker |

## Dependencies

- **multi-agent**: provides `~/.claude/lib/handoff.py` (used in phase 5)
- **self-improving**: provides `/reflect` and the learnings store (used in phase 4)
- **git-workflow**: provides commit/PR conventions used in phases 2-3

## Manual Installation

```bash
# Copy the command
mkdir -p ~/.claude/commands
cp commands/sds.md ~/.claude/commands/sds.md

# Copy the helper
mkdir -p ~/.claude/lib
cp lib/sds-broadcast.sh ~/.claude/lib/sds-broadcast.sh
chmod +x ~/.claude/lib/sds-broadcast.sh
```

## Usage

```
/sds              Run the full shutdown sequence autonomously
/sds --dry-run    Show what would happen without doing anything
```

## Design Notes

- **Autonomous by default.** Asking five questions during shutdown defeats the point. The agent only prompts when it cannot proceed (e.g., merge conflict on the WIP commit).
- **Composes existing primitives.** This module does not duplicate the handoff, reflection, or tracking infrastructure — it orchestrates them.
- **Passive sibling coordination.** Sibling clones are not directly invoked; they see a `session-ended` row in tracking.csv on their next interaction. Active push (e.g., `tmux send-keys`) is intentionally deferred.
- **Conservative issue closing.** Only auto-closes issues when the commit body explicitly says `closes #N` or `fixes #N` AND the PR has merged. GitHub already does this on merge; the phase is a safety net.
