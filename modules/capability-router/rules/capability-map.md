# Capability Router

Several installed commands and skills overlap. When unsure which to use, run `/capabilities` for the full decision map. The most-confused picks:

- **Research:** `/research` (no deps, web/GitHub/Reddit) → `/deepresearch` (needs Exa MCP key).
- **Code review:** `/ce-review` (full orchestrated PR review) → `scope-drift` skill (intent-vs-diff check, run first).
- **Plan/spec review:** `document-review` (before execution). **Prose review:** `editorial-critique`. **Visual review:** `design-review`.
- **Plan then execute:** `/xplan` (interactive) or `/xplana` (autonomous) to PLAN → `/etp` to EXECUTE a ready plan/issue.
- **Debug a failure:** `/debug` (run the workflow). The `systematic-debugging` rule is the always-on methodology it follows.
- **Expensive session, delegate the work:** `/advisor` — standing orchestrator posture (hard-gated, ad-hoc work) → `/etp` for ready plans/issues (advisor mode routes those to it).
- **Knowledge:** `/reflect` (personal, this machine) vs `/compound` (team, committed to `docs/solutions/`).

Do not invent a command. If no installed capability fits, say so.
