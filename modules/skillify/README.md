# skillify

Slash command that promotes an ad-hoc session capability into a durable skill.

## What It Does

Installs a `/skillify` command that walks the agent through turning "this just worked" into permanent, tested infrastructure:

1. Identify the capability and its trigger
2. Classify each step as latent (judgment) vs deterministic (script)
3. Check for name collisions against existing commands
4. Write the skill contract (command file with triggers and rules)
5. Extract deterministic steps into a helper script
6. Write a pinning test for the script
7. Register a pointer in the learnings store
8. Report what was created

Inspired by the skillify pattern: every repeated failure becomes structurally unreachable by being turned into a tested skill.

## Manual Installation

```bash
# Global (all projects)
cp commands/skillify.md ~/.claude/commands/skillify.md
cp bin/ccgm-skillify-check ~/.claude/bin/ccgm-skillify-check
chmod +x ~/.claude/bin/ccgm-skillify-check

# Project-level
cp commands/skillify.md .claude/commands/skillify.md
```

Make sure `~/.claude/bin` is on `$PATH` so the collision-check helper is discoverable.

## Related Modules

- `skill-authoring` — rules governing how skills are written (reference-file inclusion, voice, tool selection)
- `code-quality` (`rules/latent-vs-deterministic.md`) — the classification the `/skillify` workflow leans on in Phase 1
- `self-improving` — provides `ccgm-learnings-log` which `/skillify` uses in Phase 7 to register the new skill

## Files

| File | Description |
|------|-------------|
| `commands/skillify.md` | The `/skillify` slash command — 8-phase workflow from capability to durable skill |
| `bin/ccgm-skillify-check` | Deterministic helper: scans `~/.claude/commands/` and `.claude/commands/` for exact and fuzzy name collisions |

## `ccgm-skillify-check`

```
ccgm-skillify-check <skill-name>

Exit codes:
  0  no collisions
  1  exact collision — pick another name
  2  fuzzy match — review before creating
  3  invalid usage (non-kebab-case or wrong arg count)
```

Fuzzy matching splits the proposed name on hyphens and flags other commands that contain any token ≥ 4 characters. Short tokens are ignored to keep noise down.
