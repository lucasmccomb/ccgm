# hooks

Python hooks that enforce git workflow rules: issue-first workflow, commit message format, branch protection, and auto-approval for file operations.

## What It Does

This module installs fifteen Python hooks, several Python libraries, and a settings partial:

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
| `sync-ccgm-canonical.py` | PostToolUse (Bash) | After `gh pr merge` succeeds in the CCGM repo, fast-forwards the canonical CCGM clone (the symlink source for `~/.claude/`) so it never drifts. Default canonical dir: `~/code/ccgm`; override with `CCGM_CANONICAL_DIR` env var. No-op if the dir doesn't exist or the merge wasn't in a CCGM clone |

The `settings.partial.json` wires these hooks into your `~/.claude/settings.json`.

> **PreToolUse:Bash is composed.** The six PreToolUse(Bash) checks above
> (`enforce-git-workflow`, `auto-approve-bash`, `port-check`,
> `agent-tracking-pre`, `check-migration-timestamps`, `check-careful`) run
> through a single in-process dispatcher
> (`hooks/pretooluse-bash-dispatch.py`) rather than six separate processes.
> Their behavior is unchanged — the dispatcher calls the same pure functions
> and the decision is equivalence-proven against the legacy chain. See
> [Hook Composition Dispatcher](#hook-composition-dispatcher-default) below.

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
cp hooks/sync-ccgm-canonical.py ~/.claude/hooks/sync-ccgm-canonical.py

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

## Hook Composition Dispatcher (default)

The PreToolUse:Bash event is handled by a **single-process composition
dispatcher** (`hooks/pretooluse-bash-dispatch.py`). It replaces what used to be
six separate Python processes (`enforce-git-workflow` → `auto-approve-bash` →
`port-check` → `agent-tracking-pre` → `check-migration-timestamps` →
`check-careful`), each re-importing `hook_utils` and re-parsing stdin, where
precedence was an emergent property of array order across several modules that
did not know about each other.

The dispatcher runs the same checks via a **declarative manifest** (priority +
tool-matcher + handler) with an explicit precedence contract:

```
hard_block (exit 2)  >  deny  >  allow  >  ask  >  advisory / pass
```

- The first `hard_block` wins and is emitted via `hook_utils.hard_block()`
  (exit 2) — the only signal that survives bypass mode (GitHub #39344).
- `deny` beats any `allow`; `allow` beats `ask`.
- The curated destructive set and the git-reset smart-rule are `short_circuit`
  checks: they emit the instant they fire, so nothing can soften them.
- Bypass-suppressible checks (pattern matching, the destructive-prompt `ask`,
  advisory warnings) declare `runs_in_bypass=False` and are skipped in bypass
  mode — exactly as the standalone hooks exit early when `is_bypass_mode()` is
  true.

The handlers (`lib/pretooluse_bash_checks.py`) call the **same pure functions**
the legacy hooks use, so the dispatched path and the legacy path share one
source of truth — the six standalone hook scripts are still installed and
remain individually runnable. `modules/hooks/tests/test-dispatcher.sh` proves
the dispatcher produces an identical final decision to the six-process chain
across an adversarial command battery × all four permission modes
(`equivalence_harness.py`): 224/224 (command × mode) pairs match, with a
non-trivial outcome distribution spanning `hard_block`, `deny`, `allow`, `ask`,
and pass.

**This is the default.** `settings.partial.json` wires the single dispatcher
entry for PreToolUse:Bash:

```json
{
  "matcher": "Bash",
  "hooks": [
    { "type": "command",
      "command": "python3 $HOME/.claude/hooks/pretooluse-bash-dispatch.py",
      "timeout": 5000 }
  ]
}
```

To revert to the legacy per-process chain, replace that single entry with the
six standalone hook entries (`enforce-git-workflow`, `auto-approve-bash`,
`port-check`, `agent-tracking-pre`, `check-migration-timestamps`,
`check-careful`) in `settings.json`. Both mechanisms remain supported.

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
| `hooks/sync-ccgm-canonical.py` | Auto-pull `~/code/ccgm` after CCGM PR merges so symlinked runtime never drifts (override path via `CCGM_CANONICAL_DIR`) |
| `hooks/pretooluse-bash-dispatch.py` | Default single-process composition dispatcher for the PreToolUse:Bash chain (declarative precedence; equivalence-proven against the six-process chain) |
| `lib/hook_dispatcher.py` | Composition engine: declarative `Manifest`/`Check`/`Result` model + `dispatch()` precedence resolution (hard_block > deny > allow > ask) |
| `lib/pretooluse_bash_checks.py` | Dispatcher handlers wrapping the legacy PreToolUse:Bash hooks' pure functions into the `Result` contract |
| `lib/agent_tracking.py` | Python library for tracking CSV operations |
| `lib/agent_sessions.py` | Python library for live session detection |
| `settings.partial.json` | Hook wiring configuration to merge into settings.json |
