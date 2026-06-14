# relevance-injection

Opt-in, backward-compatible relevance-scoped rule injection plus a tiered
always-on safety core.

**Off by default.** With the opt-in flag unset, all rules load exactly as
before — this module changes nothing about the default install. When enabled,
a `SessionStart` hook surfaces a pointer to the task-relevant subset of rules
while always including the safety core.

## What It Does

CCGM auto-loads every installed module's rules on every session. This module
offers a way to scope *attention* (not access) to the rules relevant to the
current task, addressing the always-on rule-token load — without ever removing
a rule file or changing default behavior.

Two pieces:

1. **Tiered safety core** (`rules/relevance-injection.md`): an authoritative
   precedence for the always-on Iron Laws (safety/permissions > confusion
   protocol > TDD/verification > the rest), so they are tiered rather than
   nine-way flat. This is documentation + metadata, not a behavior change.

2. **Opt-in injection** (`hooks/relevance-inject.py` + `lib/relevance_select.py`):
   when `CCGM_RELEVANCE_INJECTION=true` is set in `~/.claude/.ccgm.env`, the
   hook emits an `additionalContext` pointer naming the safety core plus the
   profile-relevant modules. Selection is deterministic and lives in the pure,
   tested `relevance_select` library. When the flag is unset, the hook no-ops.

## The `applicability` field

Modules may add an optional `applicability` field to their `module.json`
(schema: `lib/applicability-schema.json`). Absent or `{"always": true}` ==
always applicable (preserves pre-feature behavior). Otherwise `{"langs": [...]}`
and/or `{"taskTypes": [...]}` scope the module to a profile.

## Enabling

```bash
# ~/.claude/.ccgm.env
CCGM_RELEVANCE_INJECTION=true
CCGM_RELEVANCE_LANGS=python,typescript        # optional
CCGM_RELEVANCE_TASKTYPES=backend,testing      # optional
```

## Manual Installation

```bash
cp rules/relevance-injection.md   ~/.claude/rules/relevance-injection.md
cp hooks/relevance-inject.py      ~/.claude/hooks/relevance-inject.py
cp lib/relevance_select.py        ~/.claude/lib/relevance_select.py
cp lib/applicability-schema.json  ~/.claude/lib/applicability-schema.json
# then merge settings.partial.json into ~/.claude/settings.json (SessionStart hook)
```

## Files

| File | Description |
|------|-------------|
| `rules/relevance-injection.md` | Tiered safety-core precedence + how the opt-in feature works |
| `hooks/relevance-inject.py` | SessionStart hook; no-op unless the opt-in flag is set |
| `lib/relevance_select.py` | Pure, deterministic selection library (safety core + applicability matching) |
| `lib/applicability-schema.json` | JSON Schema for the optional `module.json` `applicability` field |
| `settings.partial.json` | Registers the SessionStart hook |
