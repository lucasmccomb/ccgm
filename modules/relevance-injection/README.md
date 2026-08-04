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

## `/rules-scope`: generate a repo's `claudeMdExcludes` block

A third, independent piece: `lib/rules_scope.py` (driven by the
`/rules-scope` command) inspects a repo and proposes a `claudeMdExcludes`
array for that repo's `.claude/settings.json`, suppressing installed CCGM
rule files that are irrelevant to it (e.g. `tailwind`/`shadcn` rules in a
backend-only repo). Dry run by default; `--write` applies the proposal.
This is unrelated to the opt-in injection feature above and needs no flag
to use — see `commands/rules-scope.md` for the full contract.

```bash
python3 lib/rules_scope.py             # print the proposal for cwd; write nothing
python3 lib/rules_scope.py --write     # apply it to <cwd>/.claude/settings.json
```

**The generated file is machine-scoped.** `--write` puts this machine's
absolute, resolved rule-file paths into `claudeMdExcludes`. Commit it and
pull it on a different machine (a teammate, or the same operator with a
different `ccgmRoot`), and none of those paths match — every "excluded"
rule silently loads again there instead of staying suppressed. That is the
safe failure direction (nothing is ever wrongly dropped), but it does mean
the committed file only takes effect on the machine that generated it until
re-run with `--write` there. See `commands/rules-scope.md` for detail.

## Manual Installation

```bash
mkdir -p ~/.claude/rules ~/.claude/hooks ~/.claude/lib ~/.claude/commands
cp rules/relevance-injection.md        ~/.claude/rules/relevance-injection.md
cp hooks/relevance-inject.py           ~/.claude/hooks/relevance-inject.py
cp hooks/instructions-loaded-log.py    ~/.claude/hooks/instructions-loaded-log.py
cp lib/relevance_select.py             ~/.claude/lib/relevance_select.py
cp lib/loaded_log.py                   ~/.claude/lib/loaded_log.py
cp lib/rules_scope.py                  ~/.claude/lib/rules_scope.py
cp lib/applicability-schema.json       ~/.claude/lib/applicability-schema.json
cp commands/rules-scope.md             ~/.claude/commands/rules-scope.md
# then merge settings.partial.json into ~/.claude/settings.json
# (registers the SessionStart and InstructionsLoaded hooks)
```

## Files

| File | Description |
|------|-------------|
| `rules/relevance-injection.md` | Tiered safety-core precedence + how the opt-in feature works |
| `hooks/relevance-inject.py` | SessionStart hook; no-op unless the opt-in flag is set |
| `hooks/instructions-loaded-log.py` | `InstructionsLoaded` hook; appends one JSONL record per loaded instruction file to `~/.claude/rule-loading/loaded-{date}.jsonl` |
| `lib/relevance_select.py` | Pure, deterministic selection library (safety core + applicability matching) |
| `lib/loaded_log.py` | Reads the rule-loading log: `parse_log()` and `assert_loaded()` |
| `lib/rules_scope.py` | `/rules-scope` generator: `detect_repo_profile()`, `propose_excludes()`, `write_settings()` |
| `lib/applicability-schema.json` | JSON Schema for the optional `module.json` `applicability` field |
| `commands/rules-scope.md` | `/rules-scope` command: generate/apply a repo's `claudeMdExcludes` block |
| `settings.partial.json` | Registers the SessionStart and InstructionsLoaded hooks |
