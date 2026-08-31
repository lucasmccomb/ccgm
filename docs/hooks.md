# Hooks Reference

CCGM hooks are Python scripts that Claude Code executes at specific points in its workflow. They automate enforcement, provide warnings, and track state.

## How hooks work

Claude Code supports these hook types:

| Hook type | When it fires | Can block? |
|-----------|---------------|------------|
| **PreToolUse** | Before a tool call is executed | Yes - can approve, deny, or modify |
| **PostToolUse** | After a tool call completes | No - advisory only |
| **PostToolUseFailure** | After a tool call fails | No - advisory only |
| **PermissionRequest** | When Claude Code asks the user for a permission decision | Yes - can auto-allow |
| **UserPromptSubmit** | When the user submits a message | No - can inject context |
| **SessionStart** | When a new session begins | No - can inject context |
| **PreCompact** | Before context compaction | No - can inject context |
| **InstructionsLoaded** | Once per instruction file Claude Code loads | No - observational only |
| **Stop** | When Claude finishes responding | No - can emit a suggestion |
| **SubagentStop** | When a subagent finishes responding | Yes - one narrow empty-message case |
| **TaskCompleted** | When a delegated task completes | No - always allows |

Hooks are registered in `settings.json` under the `hooks` key. Each hook specifies its type, an optional matcher (e.g., `Bash` to only fire on Bash tool calls), and the command to run.

## Installed hooks

The **hooks** module installs 15 hooks, 6 Python libraries, and a settings partial. Eight other modules add the rest: **advisor-mode** 4, **self-improving** 3, **subagent-patterns** 2, **relevance-injection** 2, and one each from **branch-guard**, **ask-context**, **startup-dashboard**, and **commands-preamble**. Total: 30 hooks across 9 modules (the **autoheal** module's 6 observational hooks are documented in their own section below, bringing the installed total to 36).

This count excludes `hooks/plugin-rule-inject.py`, which brings the true `"type": "hook"` file total to 37. It is the **plugin-marketplace** module's own hook, copied into every other rules-bearing module's `hooks/` directory so each module's generated Claude Code plugin manifest can register it independently - see [plugin-marketplace](../modules/plugin-marketplace/README.md) for what it does.

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

**Type**: UserPromptSubmit (fires once per day)
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

**Type**: Not a hook - invoked by `/startup` (`startup-dashboard`'s `startup-gather.sh`)
**Module**: hooks
**Can block**: No (warning only)

Detects orphaned test worker processes (vitest, jest) left behind when a previous Claude Code session exited mid-test-run. It carries no `settings.partial.json` registration in any module - it runs only when `/startup` runs, not on any Claude Code hook event.

**How it works**:
1. Scans running processes for node processes with PPID 1 (re-parented to launchd/init)
2. Filters for test worker patterns: vitest, jest-worker, jest_worker, test-worker
3. If orphans are found, reports their PIDs and total RAM usage
4. Suggests a `kill` command to clean them up

**Why this matters**: Orphaned test workers run indefinitely after a session crash, consuming RAM and CPU. They accumulate over time and can slow down the machine. Catching them at session start prevents resource waste.

---

### reflection-trigger.py

**Type**: PostToolUse:Bash
**Module**: self-improving
**Can block**: No

Injects a reflection reminder into Claude's context after significant git events.

**Detects**:
- `gh pr merge` - reminds Claude to run the post-merge reflection checklist
- `gh issue close` - reminds Claude to check for reusable patterns

**Does not fire**: On regular commits or on non-git commands.

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

### learnings-inject.py

**Type**: SessionStart (matcher: `startup`)
**Module**: self-improving
**Can block**: No (context injection only)

Opt-in, prefix-cache-safe injection of the current project's top-ranked durable learnings at fresh session start. Strict no-op unless `CCGM_LEARNINGS_INJECT` is truthy AND the event fires with `source == "startup"` (never on resume/compaction — re-ranking and re-rendering per turn is the exact per-turn re-injection pattern this hook exists to avoid).

**Resolution**: Project slug via `learnings_store.detect_project_slug()` (never `session-history`'s `repo_detect.py` — the two compute different strings for the same repo). Selection reuses `learnings_store.search()`'s own ranking/decay/token-budget; conflicted rows (`conflict: true`, competing supersedes) are suppressed before rendering rather than handed to an agent as settled truth.

**Output**: `<ccgm-learnings-injection>` block, each entry rendered with the same age/verification wrapper `ccgm-learnings-search`'s preamble output uses.

**Opt in**: Set `CCGM_LEARNINGS_INJECT=true` in your environment.

---

### check-careful.py

**Type**: PreToolUse:Bash
**Module**: hooks
**Can block**: Yes (returns `permissionDecision: "ask"`)

Pauses destructive Bash commands for confirmation. Catches `rm -rf`, SQL `DROP`/`TRUNCATE`, `git push --force`, `git reset --hard`, `git checkout .`, `kubectl delete`, and `docker rm -f` / `docker system prune`.

**Smart allow-list**: Build-artifact directories (`node_modules`, `dist`, `.next`, `build`, `__pycache__`, `.cache`, `.turbo`, `coverage`) bypass the prompt for `rm -rf`.

---

### check-freeze.py

**Type**: PreToolUse:Edit/Write
**Module**: hooks
**Can block**: Yes

Scope-locks file edits to a frozen directory. When `~/.claude/freeze-dir.txt` contains a directory path, any Edit or Write outside that directory is denied. Paths are normalised (symlinks resolved, `..` collapsed) before the containment check.

**Activation**: `/freeze <dir>` to set, `/unfreeze` to clear.

---

### branch-guard.py

**Type**: PreToolUse:Edit/MultiEdit/Write/NotebookEdit/filesystem-MCP writes + PreToolUse:Bash
**Module**: branch-guard
**Can block**: Yes (exit 2 — survives bypass mode)

Hard gate against work on a repo's default branch (main/master, per `origin/HEAD` with fallbacks). Blocks file edits whose target file lives in a repo checked out on its default branch (symlinks resolved; the file's repo is checked, not the session cwd), and mutating git commands — `git commit`/`add`/`stage`/`apply` — in any `&&`/`;`/`|` segment, honoring `git -C <path>`. Fires before the first edit so uncommitted work can never be stranded on main and destroyed by a later origin sync. The denial teaches the fix: `git fetch origin && git checkout -b <type>/<short-desc> origin/<default>` (type: feature/fix/chore/docs).

**Exemptions**: `ALLOW_MAIN_COMMIT=1` (env or inline), in-progress rebase/merge/cherry-pick/revert/bisect, unborn HEAD, repos with no origin remote, `~/.claude/git-flow-direct-to-main-repos.json` entries, and gitignored target paths (file tools only; `git check-ignore`-verified, fails closed on git errors — gitignored files can never be committed to main, e.g. `.audit/` coordination state).

---

### advisor-guard.py

**Type**: PreToolUse:Edit/MultiEdit/Write/NotebookEdit/filesystem-MCP writes + PreToolUse:Bash
**Module**: advisor-mode
**Can block**: Yes (exit 2 — survives bypass mode)

Hard gate for advisor mode: while this session's flag `~/.claude/advisor-mode/<session_id>` exists, the MAIN agent cannot implement — file edits are confined to orchestrator work-product paths (`~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`, worktree checkouts, plan-mode plan files) and Bash is default-deny outside read-only inspection plus orchestration verbs (read-only git; `checkout`/`switch`/`pull`/`fetch`/`worktree` lifecycle; `gh` PR/issue/run/label management including merge; redirection and scratch file-ops scoped to the allowed write roots). Subagent tool calls pass untouched — their hook input carries `agent_id`/`agent_type`, the main agent's does not. Discriminator drift is asymmetric: main-agent inputs gaining the fields makes the guard inert (fails open, visibly); subagent inputs losing them would deny subagents too — loud, and recoverable with `/advisor off`. Dev-tool version and identity probes (`node -v`, `wrangler whoami`) are allowed, grouping tokens are structure, and `$(...)`/backtick substitution is allowed when every inner command is itself allowlisted (checked recursively, depth-capped, backtick bodies unescaped first as the shell does), with the result usable only as an argument to a read-only command — `sed $(echo -i) …` is denied. An argument that begins with a variable the guard cannot resolve is denied the same way (`A=-i; sed $A f`), while a read-only first word still takes one and a resolvable one is checked as its expansion (`rm -rf $TMPDIR/x`). Process substitution, shells, interpreters, and wrapper commands are denied outright. Every denial names the delegation recipe.

State is per session: the flag is keyed by the hook input's `session_id` (`CLAUDE_CODE_SESSION_ID` as the fallback), so one session's mode never binds another's.

**Exemptions**: this session's flag absent (mode off), subagent calls, `ADVISOR_DIRECT=1` (env or inline), unparseable input, missing paths, and input with no resolvable session id (all fail open).

---

### advisor-posture.py

**Type**: UserPromptSubmit
**Module**: advisor-mode
**Can block**: No

While this session's advisor-mode flag (`~/.claude/advisor-mode/<session_id>`) exists, injects a short per-turn posture reminder (`additionalContext`): the session is an orchestrator — spec, delegate to implementers, review via separate agents, triage, merge; trivial or conversational turns are answered directly; a guard denial means delegate, never shell-trick around it. The injection also names this session's id and flag path, which is what `/advisor` reads when `CLAUDE_CODE_SESSION_ID` is not in the environment. One JSON parse and one `stat()` per prompt when the mode is off. The guard enforces; this injection is what keeps the model delegating instead of fighting denials.

---

### advisor-session-start.py

**Type**: SessionStart (startup, resume, clear)
**Module**: advisor-mode
**Can block**: No (state only — writes no context)

Creates this session's advisor-mode flag (`~/.claude/advisor-mode/<session_id>`, content `on <UTC timestamp>`), so every session starts in the delegation posture. An existing flag keeps its original timestamp. Also migrates the legacy machine-global state (a regular file at `~/.claude/advisor-mode`) away on first run, and garbage-collects flags whose session is gone: no transcript under `~/.claude/projects/*/<session_id>.jsonl` and the flag older than an hour (the grace period spares a session that has not written its transcript yet), or a transcript untouched for more than three days. The current session's flag is never swept.

**Opt out of the auto-on**: `CCGM_ADVISOR_AUTO=false` in the environment or `~/.claude/.ccgm.env` (environment wins; unset means on). Garbage collection still runs. `source == "compact"` also skips the auto-on, so compaction never re-enables a mode the session turned off with `/advisor off`.

---

### advisor-session-end.py

**Type**: SessionEnd
**Module**: advisor-mode
**Can block**: No

Removes this session's advisor-mode flag when the session ends, so the state directory does not fill with dead sessions. A session that dies without firing SessionEnd is swept later by `advisor-session-start.py`.

---

### ask-context-gate.py

**Type**: PreToolUse:AskUserQuestion
**Module**: ask-context
**Can block**: Yes (exit 2)

Hard gate ensuring every AskUserQuestion carries visible decision context. The user's screen shows only the question payload and plain assistant text emitted since their last message — thinking and collapsed tool output are invisible, so an agent that "analyzed it" has not necessarily shown it. Three gates: **deictic references** in the question text or option descriptions to context outside the payload ("with that context", "as described above", "see above"); **identical re-asks** of a question set the user answered in free text (Other), dismissed, or never answered — re-asks after a picked option label stay allowed for recurring approval loops; and **invisible context** — asking mid-workstream (≥1 tool call since the user's last real message) with fewer than 200 visible characters of text this turn (`ASK_CONTEXT_MIN_CHARS` overrides). Every denial message contains the recovery recipe: emit a visible context brief as plain text, then re-call with a self-contained question. Transcript-based gates fail open when the transcript is unreadable; the payload gate always runs.

**Escape hatch**: `CCGM_ASK_CONTEXT_OFF=1` (debugging only).

---

### session-start-enforce.py

**Type**: SessionStart
**Module**: hooks
**Can block**: No (context injection only)

Experimental (OFF by default). Injects a rule-enforcement meta-instruction at fresh session start, reminding the agent to route through the discipline rules (TDD, systematic-debugging, verification) as real gates.

**Opt in**: Set `CCGM_RULE_ENFORCEMENT=true` in `~/.claude/.ccgm.env`. Fires only on `source == "startup"`, not on resume or compaction.

---

### pretooluse-bash-dispatch.py

**Type**: PreToolUse:Bash
**Module**: hooks
**Can block**: Yes (hard block, deny, allow, or ask)

The default PreToolUse:Bash handler, and the single process every Bash command passes through. It replaces what used to be a six-process chain (`enforce-git-workflow` → `auto-approve-bash` → `port-check` → `agent-tracking-pre` → `check-migration-timestamps` → `check-careful`) with one process that runs the same checks in-process, by priority.

Two things this buys over the old chain. Each command previously spawned six Python interpreters in sequence, each re-importing `hook_utils` and re-parsing stdin. And precedence was an emergent property of array order in `settings.json` across modules that knew nothing about each other; it is now declared.

**Declarative manifest** (priority order mirrors the legacy registration order):

| Priority | Check | Decisions | Runs in bypass | Short-circuit |
|----------|-------|-----------|----------------|---------------|
| 10 | `git_workflow_check` | hard_block / advisory | Yes | No |
| 20 | `destructive_check` | hard_block | Yes | Yes |
| 30 | `smart_rules_check` | hard_block / allow | Yes | Yes |
| 40 | `port_advisory_check` | advisory | No | No |
| 50 | `agent_tracking_check` | advisory | No | No |
| 60 | `migration_timestamp_check` | hard_block | Yes | No |
| 70 | `force_push_main_check` | hard_block | Yes | No |
| 80 | `careful_check` | ask | No | No |
| 90 | `pattern_check` | deny / allow | No | No |

**Precedence**: `hard_block` > `deny` > `allow` > `ask`. The first `hard_block` wins and exits 2, the only signal Claude Code honors regardless of permission mode. Advisory output never affects the decision and is flushed for every check that produced it.

**Bypass mode**: a check declaring `runs_in_bypass=False` is skipped in bypass mode, matching the legacy hooks that exited early there. The destructive set, data-integrity blocks, and protected-branch enforcement declare `runs_in_bypass=True` and run above that short-circuit.

**Reverting**: the six standalone hooks stay installed and individually runnable. Restoring their six PreToolUse:Bash entries in `settings.json` returns the legacy path.

**Equivalence**: `modules/hooks/tests/test-dispatcher.sh` runs both paths over an adversarial command battery across all four permission modes and asserts identical decisions on all 224 (command × mode) pairs. Run it through that script, not `equivalence_harness.py` directly - the harness needs the fixture `HOME` the script builds.

---

### sync-ccgm-canonical.py

**Type**: PostToolUse:Bash
**Module**: hooks
**Can block**: No

Keeps the canonical CCGM checkout current after a CCGM PR merges. `~/.claude/` symlinks point at one canonical clone; when PRs merge from workspace clones, that checkout drifts until something pulls it.

**Fires when all three hold**:
- The Bash command invokes `gh pr merge` in any segment (it is usually chained after a `cd`, so the hook scans segments rather than the first token)
- The cwd's git remote points at a repo named `ccgm`, any owner
- The canonical clone exists at `$CCGM_CANONICAL_DIR` (default `~/code/ccgm`)

Runs `git fetch origin main && git pull --ff-only origin main` there, logs the result to stderr, and always exits 0. A failed sync never blocks the merge.

---

### auto-startup.py

**Type**: SessionStart (matcher `startup|resume`)
**Module**: startup-dashboard
**Can block**: No (context injection only)

Prompts Claude to run `/startup` on fresh sessions and surfaces recent handoffs left by other clones of the same repo.

Fires only when `source == "startup"`. It stays silent on `resume` on purpose, so a resumed session picks up mid-task instead of being pushed into a dashboard render.

**Also does**: prunes handoffs older than 30 days for the current repo, opportunistically.

**Gated by**: `CCGM_AUTO_STARTUP` in `~/.claude/.ccgm.env`. Disable by setting it to `false` or removing it.

---

### inject-preamble.py

**Type**: UserPromptSubmit
**Module**: commands-preamble
**Can block**: No (context injection only)

Experimental, opt-in, off by default. Prepends a compact preamble of iron-law principles to slash-command prompts.

Rules in `~/.claude/rules/` cover the main conversation thread, but a slash command expands into its own context and can drift from principles that should be active from the first token rather than whenever the agent next rereads `CLAUDE.md`. This hook puts a distilled version in front of the command at invocation time.

**Enable**: `touch ~/.claude/preamble.enabled`. Remove that file to disable; without it the hook exits silently and the prompt is unchanged. Content lives at `~/.claude/preamble/preamble.md` and is read at runtime, so edits take effect with no rebuild.

---

### relevance-inject.py

**Type**: SessionStart (matcher `startup`)
**Module**: relevance-injection
**Can block**: No (context injection only)

Opt-in and off by default. CCGM installs every selected module's rules to `~/.claude/rules/`, where Claude Code auto-loads all of them every session. This hook offers an alternative: surface a pointer to the subset relevant to the current task profile, with a safety core that is always included.

**Safety properties**, in the order they matter:
- With `CCGM_RELEVANCE_INJECTION` unset in `~/.claude/.ccgm.env` — the default on every install — the hook reads stdin, finds no flag, and returns without emitting anything. The normal all-rules-loaded behavior is untouched.
- It only ever adds a pointer. It never deletes a rule file and never suppresses the auto-load path.
- The pointer is `additionalContext`, not authority. Every rule file stays on disk and stays loadable; the pointer biases attention, it does not gate access.
- Fires only on `source == "startup"`, not resume or compaction.

---

### instructions-loaded-log.py

**Type**: InstructionsLoaded (no matcher)
**Module**: relevance-injection
**Can block**: No (observational only)

Deterministic measurement oracle for the rest of the dynamic rule-loading work: turns "did the right rule load?" from a model judgment into a fact recorded on disk. Claude Code invokes this hook once per loaded instruction file (not once per session with a batched list), so it appends one JSONL record per invocation to `~/.claude/rule-loading/loaded-{date}.jsonl`.

**Record shape**: `hook_event_name`, `timestamp`, `session_id`, `cwd`, `file_path`, `memory_type`, and `load_reason` extracted directly from the payload, plus the full redacted raw payload under `raw` as a forward-compat safety net.

**Safety properties**: always exits 0, even on malformed or empty stdin. Redacts the payload via `hook_utils.redact_secrets()` before writing, and uses `hook_utils.file_locked_append()` so concurrent clones or invocations cannot interleave or tear a write.

---

### subagent-stop-check.py

**Type**: SubagentStop
**Module**: subagent-patterns
**Can block**: Yes (one narrow case)

Blocks only when a subagent's last assistant message is empty or whitespace-only. Allows everything else, and allows immediately when `stop_hook_active` is set, for loop protection.

An earlier version called Haiku on every subagent stop to judge whether the agent had finished its task. It over-blocked, because the hook input carries too little transcript context for that judgment, and it added up to 15 seconds per stop event. Completion discipline belongs upstream, in the subagent-patterns rules (the DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT protocol) and in the reviewer agents — not in static analysis of a single message.

---

### task-completed-check.py

**Type**: TaskCompleted
**Module**: subagent-patterns
**Can block**: No (always allows)

Always allows completion. Writes a stderr warning when the task description is empty or placeholder-like (`todo`, `tbd`, `wip`, and similar), but never blocks on it.

The slot is kept registered so deterministic logic can be added later — telemetry, description linting — without a new registration. Like `subagent-stop-check.py`, this replaced a Haiku-backed version that blocked legitimate completions from inputs (`task_subject`, `task_description`) that cannot support the judgment.

---

## Autoheal hooks

Installed by the **autoheal** module. They are registered alongside the core hooks but emit/log only — they do NOT enforce. Three opt-in surfaces (real-time alerts, auto-apply, webhook publisher) are gated by config flags in `~/.claude/autoheal/config.json` and default OFF.

### permission-event-logger.py

**Type**: PostToolUse + PostToolUseFailure + PermissionRequest (no matcher)
**Module**: autoheal
**Can block**: No (observational)

Appends one JSONL record per event to `~/.claude/autoheal/events/{date}.jsonl`, cross-clone safe via `hook_utils.file_locked_append`. Commands are redacted via the 17-pattern set BEFORE truncation, so secrets never enter the log even when the truncation point falls mid-token.

### failure-logger.py

**Type**: PostToolUse + PostToolUseFailure (no matcher)
**Module**: autoheal
**Can block**: No

Specialization of the event logger for tool failures — captures `exit_code` and a redacted `stderr_excerpt` (≤200 chars) for analyzer context. Registered on both surfaces so a client that omits `hook_event_name` is still caught: on `PostToolUseFailure` it always logs, and on plain `PostToolUse` it logs only if `exit_code` is a nonzero int; otherwise it exits silently and leaves the success record to `permission-event-logger.py`.

### user-correction-detector.py

**Type**: UserPromptSubmit (no matcher)
**Module**: autoheal
**Can block**: No

Pattern-matches 9 user-correction phrases ("no, not like that", "stop doing", "actually", "wait, no", etc.) in the submitted prompt. On match: logs a `user_correction` event with the last 3 tool-use event IDs as context. Never modifies the prompt.

### permission-request-suppress.py

**Type**: PermissionRequest (no matcher)
**Module**: autoheal
**Can block**: Yes (auto-allow only)

Conservative auto-allow gate: fires only when ALL hold — `is_bypass_mode()` is True, the `(tool, command-prefix)` signature has ≥3 prior approvals across ≥2 distinct sessions, and the signature is not in `~/.claude/autoheal/snoozed.json`. Otherwise exits silently.

### post-prompt-introspect.py

**Type**: Stop
**Module**: autoheal
**Can block**: No (emits suggestion to stderr)

Session-level dedup'd Stop hook. When ≥2 same-signature `permission_request` or `tool_failure` events fire in the current session, emits an `<autoheal-suggestion>` block on stderr suggesting `/permission-fix latest`. One suggestion per signature per session.

### realtime-security-scanner.py

**Type**: PostToolUse with `async: true, asyncRewake: true` (no matcher)
**Module**: autoheal
**Can block**: Yes (`exit 2` wakes Claude mid-session)

Strictly opt-in. Reads `~/.claude/autoheal/config.json` → if `realtime_alerts_enabled` is false or missing, exits 0 immediately without touching the patterns file. When enabled: applies 7 regexes (GitHub/AWS/Anthropic tokens in commit/echo; force-push-to-main without `ALLOW_MAIN_COMMIT`; `rm -rf /…`; `sudo` destructive; `DROP TABLE` against prod-tagged connection strings). On match: logs `realtime_security_alert` event and `exit 2` with an `<autoheal-security-alert>` envelope.

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
