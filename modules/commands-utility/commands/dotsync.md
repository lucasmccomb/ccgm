---
description: Sync local Claude Code config changes back to the CCGM repo (source of truth)
allowed-tools: Agent
---

# Sync Local Config to CCGM (/dotsync)

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: haiku
- **description**: dotsync to CCGM

Pass the agent all workflow instructions below.

After the agent completes, relay its report to the user exactly as received.

---

## Workflow Instructions

Reverse-sync local `~/.claude/` changes back to the CCGM repo (the single source of truth for all global Claude Code configs).

**CCGM root**: Read from `~/.claude/.ccgm-manifest.json` -> `ccgmRoot` field.

### 1. Run Dry First (Preview Changes)

```bash
bash ~/.claude/scripts/ccgm-sync.sh --dry
```

Show what drifted files and unmanaged files were found.

### 2. Run the Sync

If there are drifted files, run:

```bash
bash ~/.claude/scripts/ccgm-sync.sh
```

This copies local changes back to CCGM module directories, commits, and pushes.

### 3. Report Results

Tell the user:
- Which CCGM module files were updated (if any)
- Which files are unmanaged (not tracked by any CCGM module)
- Whether changes were committed and pushed
- The current sync status

### 4. Run /docupdate (if files changed)

If any files were synced back to CCGM (step 2 made changes), run `/docupdate` to catch any documentation drift introduced by those changes.

This ensures module counts, command references, and feature descriptions in README, docs/, and module READMEs stay accurate after every sync.
