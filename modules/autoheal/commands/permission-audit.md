---
description: Audit CCGM hooks + settings.json deny list for permission-mode alignment.
---

# /permission-audit

Read-only audit that reports the alignment between:

- Each `~/.claude/hooks/*.py` hook's classification (bypass-suppressible vs.
  bypass-retained vs. legacy), derived from static inspection of the source —
  does it `import hook_utils`? does it call `is_bypass_mode()`? does it call
  `hard_block()`?
- `~/.claude/settings.json` deny list entries — are any redundant with a
  hook-level `hard_block()` smart rule? are any obvious force-push variants
  duplicated?
- Misalignments — e.g., a hook documented as "bypass-suppressible" that does
  not actually short-circuit; a deny entry that overlaps a hook hard-block;
  a hook that imports `hook_utils` but uses neither helper.

The command shells out to `bin/permission-audit.sh`, which performs the
classification and rendering. It modifies no files.

## What it does

1. Resolves the hooks directory and settings file (with overrides — see below).
2. For each `*.py` file in the hooks directory, statically inspects the file
   to set three flags:
   - `has-hook_utils` — does the source contain `import hook_utils`?
   - `bypass-aware` — does the source reference `is_bypass_mode`?
   - `has-hard-block` — does the source reference `hard_block`?
3. Classifies each hook:
   - **bypass-suppressible** — `bypass-aware=YES` (with or without `hard_block`).
     The hook respects bypass mode and may also have always-on safety rails.
   - **bypass-retained** — `bypass-aware=NO`, `has-hard-block=YES`. The hook is
     always-on safety, intentionally bypass-proof.
   - **legacy** — `bypass-aware=NO`, `has-hard-block=NO`. Pre-Epic-1 hook that
     has not been migrated yet (informational; not necessarily wrong).
4. Counts `.permissions.deny` entries in the settings file.
5. For each deny entry, flags whether it appears redundant with a hook
   `hard_block` (e.g., `Bash(rm -rf:*)` overlaps with `check-careful.py`'s
   destructive-rm hard_block).
6. Renders a text report (default) or a JSON envelope (`--format json`).

## Output sections (text mode)

```
=== CCGM permission-audit ===
hooks-dir:     <path>
settings-file: <path>

--- Hook classification ---
HOOK_NAME                       CLASSIFICATION       NOTES
check-careful.py                bypass-suppressible  uses both helpers
port-check.py                   bypass-suppressible  hook_utils-aware, no hard_block
enforce-git-workflow.py         bypass-retained      hard_block, no is_bypass_mode
check-migration-timestamps.py   bypass-retained      hard_block, no is_bypass_mode
agent-tracking-pre.py           legacy               not yet migrated to hook_utils

--- Deny list ---
count: 13

--- Misalignments ---
- deny entry `Bash(rm -rf:*)` overlaps with check-careful.py destructive-rm rule
- deny entry `Bash(git reset --hard:*)` overlaps with auto-approve-bash.py destructive-reset hard_block
- deny entry `Bash(git push --force origin main:*)` overlaps with check-careful.py force-push-to-main hard_block

--- Summary ---
bypass-suppressible: 3
bypass-retained:     2
legacy:              9
deny entries:        13
misalignments:       3
```

## How to invoke

Default invocation (operates on the installed CCGM state):

```bash
/permission-audit
```

This calls `bin/permission-audit.sh` with the defaults:

- `--hooks-dir ~/.claude/hooks`
- `--settings-file ~/.claude/settings.json`

When run from a CCGM checkout (development context), defaults shift to the
in-tree paths:

- `--hooks-dir modules/hooks/hooks`
- `--settings-file modules/settings/settings.base.json`

### Overrides (for testing on fixture trees)

```bash
bash modules/autoheal/bin/permission-audit.sh \
  --hooks-dir modules/autoheal/tests/fixtures/audit-hooks \
  --settings-file modules/autoheal/tests/fixtures/audit-settings.json
```

### JSON output

```bash
bash modules/autoheal/bin/permission-audit.sh --format json | jq .
```

The JSON envelope has the shape:

```json
{
  "hooks_dir": "<absolute path>",
  "settings_file": "<absolute path>",
  "hooks": [
    {
      "name": "check-careful.py",
      "classification": "bypass-suppressible",
      "has_hook_utils": true,
      "bypass_aware": true,
      "has_hard_block": true,
      "notes": "uses both helpers"
    }
  ],
  "deny_count": 13,
  "misalignments": [
    {
      "kind": "deny_overlaps_hard_block",
      "deny_entry": "Bash(rm -rf:*)",
      "hook": "check-careful.py",
      "note": "destructive-rm rule"
    }
  ],
  "summary": {
    "bypass_suppressible": 3,
    "bypass_retained": 2,
    "legacy": 9,
    "deny_entries": 13,
    "misalignments": 3
  }
}
```

## Read-only contract

`permission-audit.sh` never modifies any file. It is safe to run repeatedly
and concurrently with other CCGM operations. Use `/permission-fix` (Epic 4)
when a remediation proposal is wanted.
