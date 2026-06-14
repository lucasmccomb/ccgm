# Capability Router

CCGM ships many commands and skills, and several clusters overlap (three research entry points, half a dozen review tools, four planning/execution commands). This module answers the recurring question: **which one do I use?**

## What it installs

- A tight always-on rule (`rules/capability-map.md`) with the most-confused one-liners and a pointer to the full map. Kept deliberately small so it costs almost nothing when idle.
- `/capabilities` - an on-demand command that prints the full decision map. The bulky map lives here, not in an always-loaded rule, so the token cost is paid only when you ask.

## `/capabilities [cluster]`

Prints a decision map for the overlapping clusters. Pass a cluster name to print just that section:

```
/capabilities
/capabilities research
/capabilities review
/capabilities plan
/capabilities debug
/capabilities knowledge
```

## Clusters covered

| Cluster | Picks |
|---------|-------|
| Research | `/research` (no deps) vs `/deepresearch` (Exa MCP) |
| Review | `scope-drift`, `/ce-review`, `pr-review-toolkit`, `document-review`, `editorial-critique`, `design-review`, `adrev`, `/resolve-pr-feedback`, built-in `/review` |
| Planning & execution | `/xplan`, `/xplana`, `/etp`, `/mawf` |
| Debugging | `/debug` vs the `systematic-debugging` methodology rule |
| Knowledge & memory | `/reflect` (personal) vs `/compound` (team) vs `session-history` |

The map notes which entries depend on external tooling and skips anything not installed in your setup.

## Manual Installation

```bash
cp commands/capabilities.md ~/.claude/commands/capabilities.md
cp rules/capability-map.md ~/.claude/rules/capability-map.md
```

## Dependencies

None. The router documents other modules but does not require them - it tells you to skip entries you have not installed.
