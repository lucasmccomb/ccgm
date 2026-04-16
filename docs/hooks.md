# Hooks Reference

CCGM hooks are Python scripts that Claude Code executes at specific points in its workflow. They automate enforcement, provide warnings, and track state.

## How hooks work

Claude Code supports these hook types:

| Hook type | When it fires | Can block? |
|-----------|---------------|------------|
| **PreToolUse** | Before a tool call is executed | Yes - can approve, deny, or modify |
| **PostToolUse** | After a tool call completes | No - advisory only |
| **UserPromptSubmit** | When the user submits a message | No - can inject context |
| **SessionStart** | When a new session begins | No - can inject context |
| **PreCompact** | Before context compaction | No - can inject context |

Hooks are registered in `settings.json` under the `hooks` key. Each hook specifies its type, an optional matcher (e.g., `Bash` to only fire on Bash tool calls), and the command to run.

## Installed hooks

The **hooks** module installs 10 hooks, 2 Python libraries, and a settings partial. The **session-logging** module installs 1 additional hook. The **self-improving** module installs 2 additional hooks. Total: 13 hooks across 3 modules.

---

### enforce-git-workflow.py

**Type**: PreToolUse:Bash
**Module**: hooks
**Can block**: Yes

The most critical hook. Enforces branch protection and commit message formatting.

**What it blocks**:
- Commits directly to protected branches (main, master, develop, dev, staging, prod, production, release, trunk, stag)
- Commits without the `#N:` issue prefix format (e.g., `#42: add login form`)
- Pushes to protected branches

**Escape hatches**:
- `sync:` prefix in commit messages bypasses format check (for non-issue commits like syncing docs)
- `ALLOW_MAIN_COMMIT=1` environment variable disables all checks (emergency use)
- Repos listed in `DIRECT_TO_MAIN_REPOS` skip all checks (configured during install with your username)

**Custom protected branches**: During installation, you can specify additional branch names to protect. These are stored in `~/.claude/git-flow-protected-branches.json`.

---

### enforce-issue-workflow.py

**Type**: UserPromptSubmit
**Module**: hooks
**Can block**: No (context injection only)

Detects when the user asks Claude to do implementation work (keywords: update, fix, add, create, implement, build, etc.) and injects a workflow reminder into Claude's context.

**Injected reminder**:
- Check for an existing GitHub issue (or create one)
- Create a feature branch from the issue
- Implement the changes
- Commit with issue prefix
- Create a pull request

If the working directory has a `.claude/logs/` directory (indicating multi-agent setup), an additional coordination reminder is injected to read other agents' logs.

---

### auto-approve-bash.py

**Type**: PreToolUse:Bash
**Module**: hooks
**Can block**: Yes (approve or pass-through)

Enforces Bash command permissions from `settings.json`. This is a workaround for Claude Code bugs where the VS Code extension ignores configured permissions and piped commands bypass the allowlist.

**How it works**:
1. Reads `allow` and `deny` patterns for `Bash` from `settings.json`
2. Applies deny-first logic: if the command matches a deny pattern, it passes through (letting Claude Code handle the denial)
3. If the command matches an allow pattern, it auto-approves
4. Otherwise, passes through for Claude Code's default handling

**Pattern matching**: Supports prefix matching and `*` wildcard. For example, `git status*` matches `git status`, `git status --short`, etc.

---

### auto-approve-file-ops.py

**Type**: PreToolUse (matches Read, Edit, Write)
**Module**: hooks
**Can block**: Yes (approve or pass-through)

Enforces path-based permissions for file read/edit/write operations. Another workaround for Claude Code permission bugs.

**How it works**:
1. Reads `allow` patterns for Read, Edit, and Write tools from `settings.json`
2. Extracts the file path from the tool call input
3. If the path matches a glob pattern in the allow list, auto-approves
4. Otherwise, passes through for default handling

---

### ccgm-update-check.py

**Type**: PreToolUse (any tool, fires once per day)
**Module**: hooks
**Can block**: No (advisory only)

Checks once per day whether the CCGM repository has upstream updates.

**How it works**:
1. Reads the CCGM root directory from `~/.claude/.ccgm-manifest.json`
2. Checks a daily flag file in `/tmp` to avoid repeated checks
3. If not checked today: runs `git fetch` in the CCGM repo and compares HEAD to `origin/main`
4. If updates are available: prints a notification to stderr with the number of new commits
5. Creates the daily flag file to prevent further checks today

**Configuration**: Enabled/disabled via `CCGM_AUTO_UPDATE_CHECK` in `~/.claude/.ccgm.env`.

---

### port-check.py

**Type**: PreToolUse:Bash (dev server commands only)
**Module**: hooks
**Can block**: No (advisory only)

Detects dev server launch commands and warns about port conflicts.

**Commands detected**: `vite`, `wrangler dev`, `npm run dev`, `pnpm dev`, `next dev`, `npx vite`, and similar patterns.

**How it works**:
1. Reads port assignments from `~/.claude/port-registry.json` and `.env.clone`
2. Checks if the expected port is already in use via `lsof`
3. Warns if the command uses a port different from the clone's assigned port
4. Warns if another process is already listening on the expected port

This hook is advisory only - it never blocks commands. It exists to prevent port collisions when multiple agents run dev servers simultaneously.

---

### agent-tracking-pre.py

**Type**: PreToolUse:Bash
**Module**: hooks
**Can block**: No (advisory only)

Warns when a `git checkout -b {N}-*` command is about to claim an issue that's already claimed by another agent.

**How it works**:
1. Only activates in multi-clone repos (checks for `.env.clone`)
2. Detects branch creation commands that follow the `{issue-number}-description` pattern
3. Reads the tracking CSV via `agent_tracking.py`
4. If the issue is already claimed by a different agent, prints a warning

Never blocks, never writes to tracking. The actual claim happens in the post-hook after the command succeeds.

---

### agent-tracking-post.py

**Type**: PostToolUse:Bash
**Module**: hooks
**Can block**: No (post-execution)

All tracking CSV writes happen in this hook, after commands succeed. This is the engine of the multi-agent issue tracking system.

**Commands intercepted**:

| Command pattern | Action | Status transition |
|----------------|--------|-------------------|
| `git checkout -b {N}-*` | `claim_issue()` | -> `claimed` |
| `git commit -m "#N: ..."` (first) | `update_status()` | `claimed` -> `in-progress` |
| `git commit -m "#N: ..."` (subsequent) | `update_heartbeat()` | Timestamp only (throttled to 30 min) |
| `gh pr create` | `update_status()` | -> `pr-created` |
| `gh pr merge` | `update_status()` | -> `merged` |
| `gh issue close N` | `update_status()` | -> `closed` |

**Concurrency model**: Uses git commit + `pull --rebase` + push for the tracking CSV. Different-row edits auto-resolve during rebase since each agent modifies only its own rows.

Only activates in multi-clone repos. Skips tracking for commits to the log repo itself.

---

### check-migration-timestamps.py

**Type**: PreToolUse
**Module**: hooks
**Can block**: Yes

Validates Supabase migration file timestamps before a commit is created, preventing duplicate timestamp issues that break `supabase db push`.

**What it checks**:
1. Scans `supabase/migrations/*.sql` files for the numeric timestamp prefix
2. Detects any duplicate prefixes (two files sharing the same timestamp)
3. Blocks the commit and reports which files have conflicting timestamps

**Why this matters**: Duplicate migration timestamps cause `supabase db push` to get confused - the CLI cannot distinguish the files and one gets permanently stuck as "local only." Catching this before commit prevents hard-to-debug migration state issues.

**Resolution**: When a duplicate is detected, rename one file to a unique timestamp (increment by 1 second) before committing.

---

### orphan-process-check.py

**Type**: SessionStart
**Module**: hooks
**Can block**: No (warning only)

Detects orphaned test worker processes (vitest, jest) left behind when a previous Claude Code session exited mid-test-run.

**How it works**:
1. Scans running processes for node processes with PPID 1 (re-parented to launchd/init)
2. Filters for test worker patterns: vitest, jest-worker, jest_worker, test-worker
3. If orphans are found, reports their PIDs and total RAM usage
4. Suggests a `kill` command to clean them up

**Why this matters**: Orphaned test workers run indefinitely after a session crash, consuming RAM and CPU. They accumulate over time and can slow down the machine. Catching them at session start prevents resource waste.

---

### auto-startup.py

**Type**: SessionStart
**Module**: session-logging
**Can block**: No (context injection)

Triggers the `/startup` command at the beginning of each new session.

**How it works**:
1. Only fires on fresh session starts (source == "startup"), not on resume or context compaction
2. Prints `<auto-startup>Run the /startup command now to initialize this session.</auto-startup>` to stdout
3. Claude Code picks up this output and Claude executes the `/startup` command

**Configuration**: Enabled/disabled via `CCGM_AUTO_STARTUP` in `~/.claude/.ccgm.env`.

---

### reflection-trigger.py

**Type**: PostToolUse:Bash
**Module**: self-improving
**Can block**: No

Injects a reflection reminder into Claude's context after significant git events.

**Detects**:
- `gh pr merge` - reminds Claude to run the post-merge reflection checklist
- `gh issue close` - reminds Claude to check for reusable patterns

**Does not fire**: On regular commits, in the log repo, or on non-git commands.

**Output**: XML-tagged instruction (e.g., `<reflection-trigger>PR merged. Run the post-merge reflection...</reflection-trigger>`) that Claude picks up as a context injection.

---

### precompact-reflection.py

**Type**: PreCompact
**Module**: self-improving
**Can block**: No

Reminds Claude to capture unwritten patterns before context compaction compresses the session.

**When it fires**: Before context compression begins. By the time PostCompact fires, session context is already compressed and learnings may be lost.

**Output**: `<precompact-reflection>` instruction prompting Claude to run the reflection checklist or invoke `/reflect`.

---

## Agent tracking library

The hooks module also installs `lib/agent_tracking.py`, a Python module and CLI tool used by the tracking hooks.

**Storage**: `~/code/{log-repo}/{repo}/tracking.csv`

**CSV fields**: `issue, agent, status, branch, pr, epic, title, claimed_at, updated_at`

**Status lifecycle**: `claimed` -> `in-progress` -> `pr-created` -> `merged` / `closed`

**CLI usage** (used by `/startup` command):

```bash
# List all tracked issues for a repo
python3 ~/.claude/lib/agent_tracking.py list --repo my-repo

# Garbage-collect stale claims (not updated in N days)
python3 ~/.claude/lib/agent_tracking.py gc --repo my-repo

# Import from label-based tracking (migration from legacy system)
python3 ~/.claude/lib/agent_tracking.py import --repo my-repo
```
