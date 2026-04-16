# hooks

Python hooks that enforce git workflow rules: issue-first workflow, commit message format, branch protection, and auto-approval for file operations.

## What It Does

This module installs eleven Python hooks, one shell script, two Python libraries, and a settings partial:

| Hook | Event | Purpose |
|------|-------|---------|
| `halt-gate.py` | PreToolUse (universal) | Blocks all tool calls when `~/.claude/halt.flag` exists with a future reset timestamp (usage-halt system) |
| `enforce-git-workflow.py` | PreToolUse (Bash) | Blocks commits on protected branches and enforces `#issue: description` commit message format |
| `enforce-issue-workflow.py` | UserPromptSubmit | Injects a workflow reminder when Claude detects a work request (create issue first, create branch, then implement) |
| `auto-approve-bash.py` | PreToolUse (Bash) | Reads allow/deny patterns from settings.json and auto-approves matching Bash commands |
| `auto-approve-file-ops.py` | PreToolUse (Read/Edit/Write) | Reads path patterns from settings.json and auto-approves file operations on allowed paths |
| `ccgm-update-check.py` | PreToolUse | Daily check for CCGM upstream updates |
| `port-check.py` | PreToolUse (Bash) | Warns about dev server port conflicts in multi-clone setups |
| `agent-tracking-pre.py` | PreToolUse (Bash) | Warns when claiming an issue already claimed by another agent |
| `agent-tracking-post.py` | PostToolUse (Bash) | Records issue claims and status transitions in tracking CSV |
| `check-migration-timestamps.py` | PreToolUse | Validates Supabase migration file timestamps for duplicates before commit |
| `orphan-process-check.py` | SessionStart | Detects orphaned test worker processes left behind from crashed sessions |
| `usage-monitor.sh` | (launchd) | Polls `ccusage` every 60s and writes `~/.claude/halt.flag` at ≥99% usage; sends macOS notifications on halt and resume |

The `settings.partial.json` wires these hooks into your `~/.claude/settings.json`.

**Libraries**: `lib/agent_tracking.py` (tracking CSV operations), `lib/agent_sessions.py` (live session detection)

## Dependencies

This module depends on the **settings** module. The auto-approve hooks read permission patterns from `settings.json`, so the settings module must be installed first.

## Template Variables

`enforce-git-workflow.py` contains one template variable:

| Variable | Description | Example |
|----------|-------------|---------|
| `__USERNAME__` | Your GitHub username | `myuser` |

During installation, `__USERNAME__/ccgm` in the `DIRECT_TO_MAIN_REPOS` list will be replaced with your actual GitHub username. This allows the ccgm config repo itself to use direct-to-main commits.

## Manual Installation

```bash
# 1. Copy hooks
cp hooks/enforce-git-workflow.py ~/.claude/hooks/enforce-git-workflow.py
cp hooks/enforce-issue-workflow.py ~/.claude/hooks/enforce-issue-workflow.py
cp hooks/auto-approve-bash.py ~/.claude/hooks/auto-approve-bash.py
cp hooks/auto-approve-file-ops.py ~/.claude/hooks/auto-approve-file-ops.py

# 2. Make executable
chmod +x ~/.claude/hooks/enforce-git-workflow.py
chmod +x ~/.claude/hooks/enforce-issue-workflow.py
chmod +x ~/.claude/hooks/auto-approve-bash.py
chmod +x ~/.claude/hooks/auto-approve-file-ops.py

# 3. Replace template variable in enforce-git-workflow.py
# Edit the DIRECT_TO_MAIN_REPOS list to use your GitHub username

# 4. Merge settings.partial.json into ~/.claude/settings.json
# Add the "hooks" section from settings.partial.json
```

## Configuration

You can add additional protected branches by creating `~/.claude/git-flow-protected-branches.json`:

```json
["staging", "develop", "release"]
```

The default protected branches are: main, master, production, prod, staging, stag, develop, dev, release, trunk.

## Files

| File | Description |
|------|-------------|
| `hooks/enforce-git-workflow.py` | Branch protection and commit message format enforcement (template) |
| `hooks/enforce-issue-workflow.py` | Issue-first workflow reminder injection |
| `hooks/auto-approve-bash.py` | Bash command auto-approval based on settings.json patterns |
| `hooks/auto-approve-file-ops.py` | File operation auto-approval based on settings.json path patterns |
| `hooks/ccgm-update-check.py` | Daily CCGM update check |
| `hooks/port-check.py` | Dev server port conflict detection |
| `hooks/agent-tracking-pre.py` | Pre-execution issue claim warning |
| `hooks/agent-tracking-post.py` | Post-execution tracking CSV updates |
| `hooks/check-migration-timestamps.py` | Supabase migration timestamp validation |
| `hooks/orphan-process-check.py` | Orphaned test worker process detection |
| `hooks/halt-gate.py` | Universal PreToolUse gate that enforces usage-halt flag |
| `hooks/usage-monitor.sh` | launchd-driven poller that writes the halt flag at ≥99% usage |
| `lib/agent_tracking.py` | Python library for tracking CSV operations |
| `lib/agent_sessions.py` | Python library for live session detection |
| `settings.partial.json` | Hook wiring configuration to merge into settings.json |
