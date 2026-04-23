# hooks

Python hooks that enforce git workflow rules: issue-first workflow, commit message format, branch protection, and auto-approval for file operations.

## What It Does

This module installs thirteen Python hooks, two Python libraries, and a settings partial:

| Hook | Event | Purpose |
|------|-------|---------|
| `enforce-git-workflow.py` | PreToolUse (Bash) | Blocks commits on protected branches and enforces `#issue: description` commit message format |
| `enforce-issue-workflow.py` | UserPromptSubmit | Injects a workflow reminder when Claude detects a work request (create issue first, create branch, then implement) |
| `auto-approve-bash.py` | PreToolUse (Bash) | Reads allow/deny patterns from settings.json and auto-approves matching Bash commands |
| `auto-approve-file-ops.py` | PreToolUse (Read/Edit/Write) | Reads path patterns from settings.json and auto-approves file operations on allowed paths |
| `ccgm-update-check.py` | PreToolUse | Daily check for CCGM upstream updates |
| `port-check.py` | PreToolUse (Bash) | Warns about dev server port conflicts in multi-clone setups |
| `agent-tracking-pre.py` | PreToolUse (Bash) | Warns when claiming an issue already claimed by another agent |
| `agent-tracking-post.py` | PostToolUse (Bash) | Records issue claims and status transitions in tracking CSV |
| `check-migration-timestamps.py` | PreToolUse | Validates Supabase migration file timestamps for duplicates before commit |
| `orphan-process-check.py` | PreToolUse (Bash) | Detects and warns about orphaned background processes (stale dev servers, zombie workers) before running commands that would conflict with them |
| `check-careful.py` | PreToolUse (Bash) | Prompts before destructive Bash commands (rm -rf, SQL DROP/TRUNCATE, force push, hard reset, kubectl delete, docker prune). Build-artifact directories (node_modules, dist, .next, build, __pycache__, .cache, .turbo, coverage) are whitelisted for `rm -rf` |
| `check-freeze.py` | PreToolUse (Edit/Write) | Denies Edit/Write outside the frozen directory when `~/.claude/freeze-dir.txt` is set. Pair with `/freeze`, `/unfreeze`, `/guard` from `commands-extra` |
| `session-start-enforce.py` | SessionStart (startup) | Experimental. Injects an Iron-Law rule-enforcement meta-instruction at fresh session start so discipline rules activate under pressure. OFF by default; opt in via `CCGM_RULE_ENFORCEMENT=true` in `~/.claude/.ccgm.env` |

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
mkdir -p ~/.claude/hooks
cp hooks/enforce-git-workflow.py ~/.claude/hooks/enforce-git-workflow.py
cp hooks/enforce-issue-workflow.py ~/.claude/hooks/enforce-issue-workflow.py
cp hooks/auto-approve-bash.py ~/.claude/hooks/auto-approve-bash.py
cp hooks/auto-approve-file-ops.py ~/.claude/hooks/auto-approve-file-ops.py
cp hooks/ccgm-update-check.py ~/.claude/hooks/ccgm-update-check.py
cp hooks/port-check.py ~/.claude/hooks/port-check.py
cp hooks/agent-tracking-pre.py ~/.claude/hooks/agent-tracking-pre.py
cp hooks/agent-tracking-post.py ~/.claude/hooks/agent-tracking-post.py
cp hooks/check-migration-timestamps.py ~/.claude/hooks/check-migration-timestamps.py
cp hooks/orphan-process-check.py ~/.claude/hooks/orphan-process-check.py
cp hooks/check-careful.py ~/.claude/hooks/check-careful.py
cp hooks/check-freeze.py ~/.claude/hooks/check-freeze.py
cp hooks/session-start-enforce.py ~/.claude/hooks/session-start-enforce.py

# 2. Copy libraries
mkdir -p ~/.claude/lib
cp lib/agent_tracking.py ~/.claude/lib/agent_tracking.py
cp lib/agent_sessions.py ~/.claude/lib/agent_sessions.py

# 3. Make hooks executable
chmod +x ~/.claude/hooks/*.py

# 4. Replace template variable in enforce-git-workflow.py
# Edit the DIRECT_TO_MAIN_REPOS list to use your GitHub username

# 5. Merge settings.partial.json into ~/.claude/settings.json
# Add the "hooks" section from settings.partial.json
```

## Configuration

You can add additional protected branches by creating `~/.claude/git-flow-protected-branches.json`:

```json
["staging", "develop", "release"]
```

The default protected branches are: main, master, production, prod, staging, stag, develop, dev, release, trunk.

### Experimental: rule-enforcement meta-instruction

`session-start-enforce.py` is OFF by default. To pilot it, add this to `~/.claude/.ccgm.env`:

```
CCGM_RULE_ENFORCEMENT=true
```

On fresh session start, the hook injects a short reminder that routes tasks through loaded Iron-Law rules (TDD, systematic-debugging, verification, subagent-patterns, confusion-protocol). Remove or set to `false` to disable.

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
| `hooks/orphan-process-check.py` | Orphaned background process detection before conflicting Bash commands |
| `hooks/check-careful.py` | Destructive-command warning (careful safety hook) |
| `hooks/check-freeze.py` | Scope-lock Edit/Write to `~/.claude/freeze-dir.txt` (freeze safety hook) |
| `hooks/session-start-enforce.py` | Experimental Iron-Law rule-enforcement meta-instruction at session start (opt in via `CCGM_RULE_ENFORCEMENT=true`) |
| `lib/agent_tracking.py` | Python library for tracking CSV operations |
| `lib/agent_sessions.py` | Python library for live session detection |
| `settings.partial.json` | Hook wiring configuration to merge into settings.json |
