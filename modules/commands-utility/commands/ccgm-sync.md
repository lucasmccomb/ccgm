---
description: Sync local Claude Code config changes back to the CCGM repo
allowed-tools: Agent
---

# Sync Local Config (/ccgm-sync)

Use the Agent tool to execute this entire workflow on a cheaper model:

- **model**: sonnet
- **description**: ccgm-sync

Pass the agent all workflow instructions below.

After the agent completes, relay its report to the user exactly as received.

---

## Workflow Instructions

Reverse-sync local `~/.claude/` changes back to the **CCGM repo** - the source of truth for all global Claude Code configs.

**CCGM root**: Read from `~/.claude/.ccgm-manifest.json` -> `ccgmRoot` field.

### 0. Broken Symlink Check

Check for broken symlinks in `~/.claude/`. These happen when modules are renamed or removed while the install is in link mode.

```bash
find ~/.claude/commands ~/.claude/rules ~/.claude/hooks ~/.claude/bin ~/.claude/skills -type l ! -exec test -e {} \; -print 2>/dev/null
```

If any broken symlinks are found:
1. List each one with its dead target (`ls -la` on each)
2. Report them to the user
3. For each broken symlink, check if the target file moved to a new location in the CCGM repo (e.g., module was renamed). If found, fix the symlink to point to the new location. If not found, remove the broken symlink and note it.

Continue with the rest of the sync after resolving broken symlinks.

### 1. CCGM Sync - Run Dry First (Preview Changes)

```bash
bash ~/.claude/scripts/ccgm-sync.sh --dry
```

Show what drifted files and unmanaged files were found.

### 2. CCGM Sync - Apply

If there are drifted files, run:

```bash
bash ~/.claude/scripts/ccgm-sync.sh
```

This copies local changes back to CCGM module directories, commits, and pushes.

### 3. Report Results

Tell the user:
- Which broken symlinks were found and fixed (if any)
- Which CCGM module files were updated (if any)
- Which files are unmanaged (not tracked by any CCGM module)
- Whether changes were committed and pushed
- The current sync status

### 4. Run /docupdate (if CCGM files changed)

If any files were synced back to CCGM (step 2 made changes), run `/docupdate` to catch any documentation drift introduced by those changes.

This ensures module counts, command references, and feature descriptions in README, docs/, and module READMEs stay accurate after every sync.
