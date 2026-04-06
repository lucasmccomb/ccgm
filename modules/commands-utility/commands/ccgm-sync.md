---
description: Sync local Claude Code config changes back to the CCGM repo and lem-deepresearch repo
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

Reverse-sync local `~/.claude/` changes back to source repos:
1. **CCGM repo** - the source of truth for all global Claude Code configs
2. **lem-deepresearch repo** - the source of truth for the /deepresearch command and CLI script

**CCGM root**: Read from `~/.claude/.ccgm-manifest.json` -> `ccgmRoot` field.
**lem-deepresearch root**: `~/code/lem-deepresearch` (if it exists).

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

### 3. Deepresearch Sync

Check if the local deepresearch files have changed compared to the lem-deepresearch repo:

```bash
DEEPRESEARCH_REPO="$HOME/code/lem-deepresearch"

if [ -d "$DEEPRESEARCH_REPO" ]; then
  CHANGED=false

  # Check command file
  if [ -f "$HOME/.claude/commands/deepresearch.md" ] && [ -f "$DEEPRESEARCH_REPO/deepresearch.md" ]; then
    if ! diff -q "$HOME/.claude/commands/deepresearch.md" "$DEEPRESEARCH_REPO/deepresearch.md" &>/dev/null; then
      echo "CHANGED: deepresearch.md (command file)"
      CHANGED=true
    fi
  fi

  # Check CLI script
  if [ -f "$HOME/.claude/bin/deepresearch-cli.py" ] && [ -f "$DEEPRESEARCH_REPO/bin/deepresearch-cli.py" ]; then
    if ! diff -q "$HOME/.claude/bin/deepresearch-cli.py" "$DEEPRESEARCH_REPO/bin/deepresearch-cli.py" &>/dev/null; then
      echo "CHANGED: bin/deepresearch-cli.py (CLI script)"
      CHANGED=true
    fi
  fi

  if [ "$CHANGED" = true ]; then
    echo "Syncing deepresearch changes to lem-deepresearch repo..."
  else
    echo "lem-deepresearch is in sync."
  fi
fi
```

If changes were detected:

1. Copy the changed files from `~/.claude/` to the lem-deepresearch repo:
   - `~/.claude/commands/deepresearch.md` -> `$DEEPRESEARCH_REPO/deepresearch.md`
   - `~/.claude/bin/deepresearch-cli.py` -> `$DEEPRESEARCH_REPO/bin/deepresearch-cli.py`
2. **Fix the shebang** in the copied CLI script - replace any user-specific venv path with the portable `#!/usr/bin/env python3`:
   ```bash
   if head -1 "$DEEPRESEARCH_REPO/bin/deepresearch-cli.py" | grep -q "research-tools-venv"; then
     sed -i '' '1s|^#!.*|#!/usr/bin/env python3|' "$DEEPRESEARCH_REPO/bin/deepresearch-cli.py"
   fi
   ```
3. Commit and push:
   ```bash
   cd "$DEEPRESEARCH_REPO"
   git add -A
   if ! git diff --cached --quiet; then
     ALLOW_MAIN_COMMIT=1 git commit -m "sync: update deepresearch from local config ($(date +%Y-%m-%d))"
     ALLOW_MAIN_COMMIT=1 git push origin main
   fi
   ```

If `~/code/lem-deepresearch` does not exist, skip this step silently (the user may not have the repo cloned).

### 4. Report Results

Tell the user:
- Which broken symlinks were found and fixed (if any)
- Which CCGM module files were updated (if any)
- Which deepresearch files were updated (if any)
- Which files are unmanaged (not tracked by any CCGM module)
- Whether changes were committed and pushed to each repo
- The current sync status

### 5. Run /docupdate (if CCGM files changed)

If any files were synced back to CCGM (step 2 made changes), run `/docupdate` to catch any documentation drift introduced by those changes.

This ensures module counts, command references, and feature descriptions in README, docs/, and module READMEs stay accurate after every sync.
