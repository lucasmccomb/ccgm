# Codebase Audit

Comprehensive codebase audit. Produces a findings document and creates GitHub issues. Prompts for configuration when invoked.

## Usage

```bash
# Interactive (prompts for configuration)
/audit                    # Asks: scope (read-only vs auto-fix) + execution strategy

# Direct flags (skip the prompt)
/audit --fix              # Audit WITH auto-fixes (uses worktrees, creates PR)
/audit --single           # Single-session audit (8 subagents, lightweight)
/audit --manual           # Set up tasks + output launch commands for manual orchestration
/audit --worker           # Worker mode (run from worktree/clone after --manual setup)
/audit --collect          # Compile results + create issues (after workers complete)
/audit --collect --force  # Collect even if some agents haven't completed
/audit --max-fixes 10     # Limit number of auto-fixes (only with --fix)
```

### Interactive Configuration

When `/audit` is called without flags, it prompts the user with two questions:

1. **Audit scope** - Read-only (just findings) or analyze + auto-fix (also make safe changes, create PR)
2. **Execution strategy** - Parallel worktrees, single session, multi-clone, or manual setup

This ensures the user always knows exactly what the audit will do before it starts.

### Execution Strategies

| Strategy | Agents | Isolation | Depth | Speed |
|----------|--------|-----------|-------|-------|
| **Parallel worktrees** | 4 Task agents | Git worktrees in `.audit/worktrees/` | Good | Fast |
| **Single session** | 8 Explore subagents | None (all read from same dir) | Light | Fastest |
| **Multi-clone** | 4 Task agents | Sibling clone dirs | Deep | Fast |
| **Manual setup** | 4 full Claude sessions | Worktrees (or clones) | Deepest | Slowest |

---

## CRITICAL: Isolation Rules

1. **Read-only by default** - The audit does NOT modify any files, create branches, or make commits unless the user explicitly chooses "Analyze + auto-fix".
2. **Worktree isolation (recommended)** - When worktrees or auto-fix are used, all work happens in git worktrees under `.audit/worktrees/`. The user's working directory is never touched.
3. **Multi-clone is opt-in only** - Sibling clones (supersam-1, supersam-2, etc.) are ONLY used when the user explicitly selects "Multi-clone" execution. Before using clones, ALL must be verified as clean (no uncommitted changes, no active feature branches). If any clone has active work, warn the user and suggest worktrees instead.
4. **Always prompt first** - When `/audit` is called without flags, always ask the user to configure scope and execution strategy before doing anything.

---

## Instructions

### Mode Detection & Routing

**If flags are passed, use them directly (skip the interactive prompt):**
- `--single` -> Single-Session Mode (Phases 1-7)
- `--worker` -> Worker Mode (Phases W1-W5)
- `--collect` -> Collector Mode (Phases C1-C4)
- `--force` -> sets FORCE_COLLECT=true (only used with --collect)
- `--fix` -> sets FIX_MODE=true
- `--max-fixes N` -> sets MAX_FIXES=N (only with --fix)
- `--manual` -> Coordinator-Only Mode (Phases M1-M4 + output launch commands)
- Remaining argument is the target path (default: entire repo)

**If NO flags are passed, prompt the user with `AskUserQuestion` to configure the audit:**

Use AskUserQuestion with TWO questions:

**Question 1** - header: "Audit scope", question: "What should the audit do?"
Options:
1. **Read-only (Recommended)** - description: "Analyze the codebase, produce a findings report, and create GitHub issues. No code changes."
2. **Analyze + auto-fix** - description: "Same as read-only, plus automatically fix high-confidence issues (unused imports, console.logs, formatting). Creates a PR with fixes for review."

**Question 2** - header: "Execution", question: "How should the audit run?"
Options:
1. **Parallel worktrees (Recommended)** - description: "4 Task agents in isolated git worktrees within this repo. Good balance of depth and speed. Your working directory is never touched."
2. **Single session** - description: "8 lightweight subagents in the current session. Fastest but least thorough - agents have limited context windows."
3. **Multi-clone** - description: "4 agents across sibling clone directories (supersam-0 through supersam-3). Deepest analysis with full context per agent. WARNING: Requires all clones to be on clean branches with no active work."
4. **Manual setup** - description: "Set up worktrees and task files, then output launch commands so you can run each agent yourself in separate terminals."

**Map user choices to configuration:**

| Scope | Execution | Result |
|-------|-----------|--------|
| Read-only | Parallel worktrees | Default autonomous mode (M1-M7, FIX_MODE=false) - agents read from worktrees |
| Read-only | Single session | Single-session mode (Phases 1-7) |
| Read-only | Multi-clone | Clone-based autonomous mode (M1-M7, FIX_MODE=false, USE_CLONES=true) |
| Read-only | Manual setup | Manual mode (M1-M4 + launch commands) |
| Analyze + auto-fix | Parallel worktrees | Autonomous mode with fixes (M1-M7, FIX_MODE=true) |
| Analyze + auto-fix | Single session | Single-session mode with fixes (Phases 1-7, FIX_MODE=true) |
| Analyze + auto-fix | Multi-clone | Clone-based mode with fixes (M1-M7, FIX_MODE=true, USE_CLONES=true) |
| Analyze + auto-fix | Manual setup | Manual mode with fixes (M1-M4 + launch commands, FIX_MODE=true) |

**Multi-clone mode additional validation (when selected):**
Before proceeding, the coordinator MUST:
1. Discover sibling clones: `ls -d "$REPOS_DIR"/supersam-*/` (or equivalent pattern)
2. Verify ALL clones have clean git state (`git status --porcelain` returns empty)
3. Verify NO clone has active feature branches checked out (all should be on `development` or `main`)
4. If any clone is dirty or has active work, WARN the user and suggest "Parallel worktrees" instead
5. Only proceed after explicit user confirmation

**Derive environment variables:**
```bash
# Repo root (the current working directory where /audit is invoked)
REPO_DIR=$(git rev-parse --show-toplevel)

# Audit coordination directory (inside the repo, gitignored)
AUDIT_DIR="$REPO_DIR/.audit"

# Today's date
AUDIT_DATE=$(date +%Y%m%d)

# Base branch (read from config.json if exists, otherwise default)
BASE_BRANCH="development"

# Number of agents (always 4 - one per category pair)
AGENT_COUNT=4
```

---

## Autonomous Mode (DEFAULT) (Phases M1-M7)

Run from any clone. The default is **read-only** - no code changes unless `--fix` is passed.

### Phase M1: Pre-Flight

1. **Verify this is a git repo** and identify the repo root:
   ```bash
   REPO_DIR=$(git rev-parse --show-toplevel)
   ```

2. **Ensure `.audit` is gitignored**: Check if `.audit` or `.audit/` is in `.gitignore`. If not, add it:
   ```bash
   grep -qxF '.audit/' .gitignore 2>/dev/null || echo '.audit/' >> .gitignore
   ```
   Do NOT commit this change - it's a local-only addition.

3. **Check for existing audit run**: Look for `$AUDIT_DIR/current/config.json`.
   - If exists, ask the user:
     ```
     An existing audit run was found from [date].
     1. Resume (keep existing task files, only recreate missing ones)
     2. Clean start (move .audit/current/ to .audit/archived-YYYYMMDD/ and start fresh)
     3. Cancel
     ```

4. **Check for open audit PRs** (informational):
   ```bash
   gh pr list --search "Audit:" --state open
   ```
   Warn if existing audit PRs are open.

5. **If --fix mode**: Verify clean git state and check for existing worktrees (see Fix Mode Addendum below).

### Phase M2: Create Coordination Directory

```bash
mkdir -p "$AUDIT_DIR/current/tasks"
mkdir -p "$AUDIT_DIR/current/results"
mkdir -p "$AUDIT_DIR/history"
```

Write `config.json`:
```json
{
  "audit_date": "YYYYMMDD",
  "started_at": "ISO-8601",
  "base_branch": "development",
  "agent_count": 4,
  "scope": "entire repo",
  "fix_mode": false,
  "repo_dir": "<absolute path to repo root>",
  "epic_issue": null
}
```

### Phase M2.5: Create Epic Issue

Create a GitHub epic issue to serve as the parent tracker for this audit run. All downstream category issues (created during collection) will reference this epic.

```bash
gh issue create \
  --title "Audit: YYYY-MM-DD - Codebase Audit" \
  --label "audit" \
  --body "$(cat <<'EOF'
## Codebase Audit - YYYY-MM-DD

Tracking issue for the YYYY-MM-DD codebase audit.

### Categories
- [ ] Security
- [ ] Dependencies
- [ ] Code Quality
- [ ] TypeScript/React
- [ ] Architecture
- [ ] Performance
- [ ] Testing
- [ ] Documentation

### Status
- **Started**: YYYY-MM-DD
- **Agents**: 4
- **Mode**: Read-only audit

### Downstream Issues
Category-specific findings issues will be linked here as they are created.

---
*Generated by `/audit` skill*
EOF
)"
```

Save the epic issue number in `config.json` as `"epic_issue"`.

### Phase M3: Prepare Agent Environment

The preparation depends on the execution strategy chosen by the user:

**Worktree mode (parallel worktrees):**
Create worktrees for agent isolation:
```bash
git fetch origin
mkdir -p "$AUDIT_DIR/worktrees"
for i in 0 1 2 3; do
  git worktree add "$AUDIT_DIR/worktrees/agent-$i" -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done
```
If FIX_MODE is true, also install dependencies in each worktree:
```bash
for i in 0 1 2 3; do
  (cd "$AUDIT_DIR/worktrees/agent-$i" && bun install --frozen-lockfile 2>&1 | tail -1) &
done
wait
```

**Multi-clone mode:**
Discover and prepare sibling clones:
```bash
REPOS_DIR=$(dirname "$REPO_DIR")
for dir in "$REPOS_DIR"/supersam-*/; do
  echo "=== $(basename $dir) ==="
  git -C "$dir" status --porcelain
done
```
Verify all clones are clean (no uncommitted changes, no active feature branches). If any are dirty, STOP and warn the user.
Then create audit branches in each clone:
```bash
for i in 0 1 2 3; do
  git -C "$REPOS_DIR/supersam-$i" fetch origin
  git -C "$REPOS_DIR/supersam-$i" checkout -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done
```
If FIX_MODE is true, install dependencies in each clone.

**Single-session mode:**
No preparation needed. Skip to M4.

**Read-only worktree-less mode (fallback):**
No worktrees needed. All agents read from the main repo directory. Skip to M4.

### Phase M4: Write Task Files

For each agent, write `tasks/agent-N.json`. **Embed all needed reference material directly** so workers are self-contained.

Reference the agent assignment table from `~/.claude/skills/audit/reference/multi-agent-config.md`:

| Agent | Categories | Merge Priority |
|-------|-----------|----------------|
| 0 | Security, Dependencies | 1 (highest) |
| 1 | Code Quality, TypeScript/React | 2 |
| 2 | Architecture, Performance | 3 |
| 3 | Testing, Documentation | 4 (lowest) |

For each agent's task file:
1. Read the category instructions from the Category Prompts section below (Agent 1-8 prompts)
2. Read `~/.claude/skills/audit/reference/fix-patterns.md` for the fix reference (even in read-only mode, used to classify fix_confidence)
3. Read category-specific reference files if they exist (e.g., `reference/security-patterns.md`)
4. Discover verification commands from the project's `package.json`
5. Embed all of this into the task JSON per the schema in `reference/multi-agent-config.md`

**Category-to-Agent mapping for task file creation:**
- Agent 0: Embed Agent 1 (Security) + Agent 2 (Dependencies) instructions
- Agent 1: Embed Agent 3 (Code Quality) + Agent 5 (TypeScript/React) instructions
- Agent 2: Embed Agent 4 (Architecture) + Agent 8 (Performance) instructions
- Agent 3: Embed Agent 6 (Testing) + Agent 7 (Documentation) instructions

### Phase M5: Launch Audit Agents

**CRITICAL**: Launch all 4 Task agents in a SINGLE message with 4 parallel Task tool calls. Each agent uses `subagent_type: "general-purpose"` and `run_in_background: true`.

Display progress summary before launching:
```
## Launching Audit Agents

| Agent | Categories | Working Dir | Mode |
|-------|-----------|------------|------|
| 0 | Security, Dependencies | {agent_dir} | {mode} |
| 1 | Code Quality, TypeScript/React | {agent_dir} | {mode} |
| 2 | Architecture, Performance | {agent_dir} | {mode} |
| 3 | Testing, Documentation | {agent_dir} | {mode} |

Running 4 audit agents in parallel...
```

Where `{agent_dir}` is:
- **Worktree mode**: `$AUDIT_DIR/worktrees/agent-N`
- **Multi-clone mode**: `$REPOS_DIR/supersam-N`
- **Plain read-only**: `$REPO_DIR` (all agents read from same directory)

And `{mode}` is "Read-only" or "Read + auto-fix".

**Prompt template for each Task agent (read-only mode):**

```
You are audit agent {N} performing a READ-ONLY codebase audit.

CODEBASE ROOT: {AGENT_WORKING_DIR}
TASK FILE: {AUDIT_DIR}/current/tasks/agent-{N}.json
RESULTS FILE: {AUDIT_DIR}/current/results/agent-{N}.json

IMPORTANT: This is a READ-ONLY audit. Do NOT modify any source files. Do NOT create branches or make commits.
Use ABSOLUTE PATHS for ALL file operations. Your codebase root is {AGENT_WORKING_DIR}.

## Instructions

1. Read your task file to get your assigned categories and instructions.

2. Write an initial results file to signal you've started:
   Write to {AUDIT_DIR}/current/results/agent-{N}.json:
   {"agent": {N}, "status": "in_progress", "started_at": "<current ISO timestamp>"}

3. For each assigned category:
   - Systematically search the codebase using Grep, Glob, and Read with absolute paths
   - Record findings in the standard format from the task file
   - Assign finding IDs as agent-{N}-{category}-NNN
   - For each finding, assess whether it COULD be auto-fixed and with what confidence
     (this classification helps prioritize issue creation, but DO NOT make any changes)

4. Write final results with all findings and summary to {AUDIT_DIR}/current/results/agent-{N}.json with status "completed".

Be thorough. Read entire files when needed. Trace patterns across the codebase. This is a deep audit, not a surface scan.
```

After launching all 4 agents, display:
```
All 4 audit agents launched. Waiting for completion...
```

**Poll for completion** using TaskOutput to check each agent. Once all 4 have returned results (or after a reasonable timeout), proceed to Phase M6.

### Phase M6: Compile Audit Document

After all agents complete:

1. **Read all result files** from `$AUDIT_DIR/current/results/agent-*.json`

2. **Deduplicate findings**: Match by `file` + approximate `line` (within 5 lines) + `category`. Keep the finding with more detail.

3. **Sort**: By severity (critical > high > medium > low), then by category.

4. **Write the compiled audit document** to `$AUDIT_DIR/current/audit-report.md`:

```markdown
# Codebase Audit Report - YYYY-MM-DD

## Summary

| Metric | Count |
|--------|-------|
| Total Findings | X |
| Critical | X |
| High | X |
| Medium | X |
| Low | X |
| Positive Observations | X |
| Auto-fixable (high confidence) | X |
| Needs Human Review | X |

## Findings by Category

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Security | X | X | X | X | X |
| Dependencies | X | X | X | X | X |
| Code Quality | X | X | X | X | X |
| TypeScript/React | X | X | X | X | X |
| Architecture | X | X | X | X | X |
| Performance | X | X | X | X | X |
| Testing | X | X | X | X | X |
| Documentation | X | X | X | X | X |

## Critical & High Severity Findings

### Security
- **[agent-0-security-001]** (HIGH) Title - `file:line`
  Description of the finding...

### Code Quality
...

## Medium Severity Findings
...

## Low Severity Findings
...

## Positive Observations
...

---
*Generated by `/audit` skill on YYYY-MM-DD*
*Agents: 4 | Duration: Xm*
```

5. **Display the summary** to the user (the summary table and critical/high findings - NOT the full document).

### Phase M7: Issue Creation

Ask the user:
```
The audit found {N} findings (Critical: X, High: Y, Medium: Z, Low: W).
Full report: .audit/current/audit-report.md

Would you like me to create GitHub issues for these?
1. Create issues for Critical + High severity only
2. Create issues for all findings
3. Create issues for Critical + High, plus one umbrella issue for Medium + Low
4. Skip issue creation
```

**If creating issues:**

1. Check for existing audit issues: `gh issue list --label "audit" --state open`

2. Create labels if needed:
   ```bash
   gh label create "audit" --color "d4c5f9" 2>/dev/null || true
   gh label create "needs-human-review" --color "fbca04" 2>/dev/null || true
   ```

3. Group findings by category and create one issue per category (for selected severity levels).

4. Use the issue template from `reference/output-template.md`.

5. **Link each issue to the epic**: Add `Parent: #<epic_issue>` in the issue body.

6. **Update the epic issue** with downstream issue links.

7. **Optionally clean up**: Ask user if they want to keep `.audit/current/` (for reference) or archive it.

---

### Phase M5-manual: Output Launch Instructions (--manual mode only)

**This phase only runs when `--manual` flag is provided.** It replaces M5-M7 above.

For `--manual` mode, worktrees are always created (even in read-only mode) so each Claude Code session has its own working directory:

```bash
for i in 0 1 2 3; do
  git worktree add "$AUDIT_DIR/worktrees/agent-$i" -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done
```

Display a clear summary and launch commands:

```
## Multi-Agent Audit Setup Complete

### Agent Assignments
| Agent | Worktree | Categories | Branch |
|-------|----------|-----------|--------|
| 0 | .audit/worktrees/agent-0 | Security, Dependencies | audit/agent-0-YYYYMMDD |
| 1 | .audit/worktrees/agent-1 | Code Quality, TypeScript/React | audit/agent-1-YYYYMMDD |
| 2 | .audit/worktrees/agent-2 | Architecture, Performance | audit/agent-2-YYYYMMDD |
| 3 | .audit/worktrees/agent-3 | Testing, Documentation | audit/agent-3-YYYYMMDD |

### Launch Commands

Run each in a separate terminal/tmux pane:

  cd {AUDIT_DIR}/worktrees/agent-0 && claude "/audit --worker"
  cd {AUDIT_DIR}/worktrees/agent-1 && claude "/audit --worker"
  cd {AUDIT_DIR}/worktrees/agent-2 && claude "/audit --worker"
  cd {AUDIT_DIR}/worktrees/agent-3 && claude "/audit --worker"

### Monitor Progress

  watch -n 10 'for i in 0 1 2 3; do echo "Agent $i: $(jq -r ".status // \"pending\"" {AUDIT_DIR}/current/results/agent-$i.json 2>/dev/null || echo "waiting")"; done'

### After All Complete

  cd {REPO_DIR} && claude "/audit --collect"
```

---

## Worker Mode: `--worker` (Phases W1-W5)

Run from a worktree (manual mode) or invoked as a Task agent (autonomous mode). Reads its task file and performs audit of assigned categories.

### Phase W1: Self-ID & Task Load

1. **Derive agent number** from current directory:
   ```bash
   AGENT_NUMBER=$(basename "$PWD" | grep -oP '\d+$')
   ```

2. **Derive AUDIT_DIR** from git common directory:
   ```bash
   GIT_COMMON=$(git rev-parse --git-common-dir)
   REPO_ROOT=$(dirname "$GIT_COMMON")
   AUDIT_DIR="$REPO_ROOT/.audit"
   ```

3. **Read task file**:
   ```bash
   cat "$AUDIT_DIR/current/tasks/agent-$AGENT_NUMBER.json"
   ```
   If task file doesn't exist, error out with a message pointing to `/audit`.

4. **Load project CLAUDE.md** from the path specified in the task file for project-specific context.

### Phase W2: Init Results File

Write initial results file to signal this agent has started:
```json
{
  "agent": N,
  "status": "in_progress",
  "started_at": "ISO-8601",
  "completed_at": null,
  "branch": "audit/agent-N-YYYYMMDD",
  "categories_audited": [],
  "findings": [],
  "cross_category_findings": [],
  "fixes_applied": [],
  "fixes_failed": [],
  "summary": null
}
```

Write to `$AUDIT_DIR/current/results/agent-$AGENT_NUMBER.json`.

### Phase W3: Deep Audit

For each assigned category from the task file:

1. **Read the embedded category instructions** from the task JSON
2. **Systematically explore the codebase** using full tool access (Grep, Glob, Read):
   - Trace data flows across files
   - Cross-reference imports and exports
   - Read entire files when needed, not just snippets
   - Follow call chains through hooks, components, and utilities
   - Check database queries against RLS policies
   - Verify edge function auth patterns
3. **Record each finding** in the standard JSON format from the task file
4. **Assign finding IDs** as `agent-N-{category}-NNN` (e.g., `agent-0-security-001`)
5. **For findings in other categories**, add to `cross_category_findings` with a note
6. **Classify each finding's fixability**: auto_fixable, fix_confidence, fix_type (for prioritization, NOT for making changes)

### Phase W4: Fix Cycle (--fix mode only)

**Skip entirely unless FIX_MODE is true (from task file).**

See "Fix Mode Addendum" below for the full fix cycle.

### Phase W5: Write Final Results & Signal

Update the results JSON with:
- All findings (including cross-category)
- All fixes applied (empty array in read-only mode)
- Summary counts
- `"status": "completed"`
- `"completed_at": "ISO-8601"`

**If in a worktree (manual mode) and fix mode:**
```bash
git push origin "audit/agent-$AGENT_NUMBER-$AUDIT_DATE"
```

Display completion summary:
```
## Agent N Audit Complete

Categories: [list]
Findings: X (Critical: X, High: X, Medium: X, Low: X)
Human review needed: X
```

---

## Collector Mode: `--collect` (Phases C1-C4)

Run from the repo root (NOT from a worktree) after all workers complete. Compiles results and creates issues.

### Phase C1: Verify Completion

Check all result files:
```bash
for i in 0 1 2 3; do
  STATUS=$(jq -r '.status // "missing"' "$AUDIT_DIR/current/results/agent-$i.json" 2>/dev/null || echo "no file")
  echo "Agent $i: $STATUS"
done
```

- If all show `"completed"`, proceed.
- If any show `"in_progress"` or `"missing"`:
  - Without `--force`: Report status and wait.
  - With `--force`: Warn and proceed with available results.

### Phase C2: Compile Audit Document

Same as Phase M6 above - read all results, deduplicate, sort, write `audit-report.md`.

### Phase C3: Issue Creation

Same as Phase M7 above - present the report, ask about issue creation.

### Phase C4: Archive & Cleanup

1. **Archive results**: Write `history/YYYYMMDD.json` per the schema in `reference/multi-agent-config.md`.

2. **If worktrees exist**, clean them up:
   ```bash
   for i in 0 1 2 3; do
     git worktree remove "$AUDIT_DIR/worktrees/agent-$i" --force 2>/dev/null || true
   done
   git worktree remove "$AUDIT_DIR/worktrees/combined" --force 2>/dev/null || true
   git worktree prune
   ```

3. **If multi-clone mode was used**, reset clones to base branch:
   ```bash
   for i in 0 1 2 3; do
     git -C "$REPOS_DIR/supersam-$i" checkout "$BASE_BRANCH"
     git -C "$REPOS_DIR/supersam-$i" pull origin "$BASE_BRANCH"
   done
   ```

4. **Delete remote agent branches** (if they were pushed in fix mode):
   ```bash
   for i in 0 1 2 3; do
     git push origin --delete "audit/agent-$i-$AUDIT_DATE" 2>/dev/null || true
   done
   ```

5. **Ask about cleanup**: Keep or archive `.audit/current/`.

---

## Fix Mode Addendum (--fix)

When `--fix` is passed, these additional steps are added to the default workflow:

### M3-fix: Create Worktrees

```bash
git fetch origin
for i in 0 1 2 3; do
  git worktree add "$AUDIT_DIR/worktrees/agent-$i" -b "audit/agent-$i-$AUDIT_DATE" "origin/$BASE_BRANCH"
done

# Install dependencies in each worktree (parallel)
for i in 0 1 2 3; do
  (cd "$AUDIT_DIR/worktrees/agent-$i" && bun install --frozen-lockfile 2>&1 | tail -1) &
done
wait
```

### M5-fix: Agent Prompts Include Fix Instructions

The Task agent prompts are extended with:
```
WORKING DIRECTORY: {AUDIT_DIR}/worktrees/agent-{N}
Use `git -C {AUDIT_DIR}/worktrees/agent-{N}` for all git commands.

For auto-fixable findings:
- Implement fixes using Edit tool with absolute paths
- Run verification: cd {AUDIT_DIR}/worktrees/agent-{N} && bun run lint
- If verification passes: git add <files> && git commit -m "audit({category}): {title}"
- If verification fails: git checkout -- . && git clean -fd
- Record fix success/failure in results

Push when done: git push origin audit/agent-{N}-{AUDIT_DATE}
```

### W4-fix: Fix Cycle

For each auto-fixable finding, ordered by fix_confidence (high first, then medium):

1. **Verify this is YOUR category** - never fix cross-category findings
2. **Implement the fix** using Edit/Write tools
3. **Run verification**:
   ```bash
   bun run lint 2>&1 || echo "LINT_FAILED"
   bun run type-check 2>&1 || echo "TYPECHECK_FAILED"
   ```
4. **If verification passes**: Commit:
   ```bash
   git add <affected_files>
   git commit -m "audit({category}): {brief title}"
   ```
5. **If verification fails**: Revert:
   ```bash
   git checkout -- .
   git clean -fd
   ```
6. **Continue** to next finding. Stop if MAX_FIXES reached.

### M6-fix: Merge & Create PR

After collecting results, merge the fix branches:

1. **Create collector worktree**:
   ```bash
   git worktree add "$AUDIT_DIR/worktrees/combined" -b "audit/$AUDIT_DATE" "origin/$BASE_BRANCH"
   ```

2. **Merge each agent branch** in priority order (0 first, 3 last):
   ```bash
   cd "$AUDIT_DIR/worktrees/combined"
   for i in 0 1 2 3; do
     git merge "origin/audit/agent-$i-$AUDIT_DATE" --no-edit || {
       git checkout --ours .
       git add .
       git commit --no-edit
     }
   done
   ```

3. **Install deps and verify**:
   ```bash
   bun install --frozen-lockfile
   bun run lint && bun run type-check && bun run build
   ```

4. **Push and create PR**:
   ```bash
   git push origin "audit/$AUDIT_DATE"
   gh pr create --base "$BASE_BRANCH" --head "audit/$AUDIT_DATE" \
     --title "Audit: $(date +%Y-%m-%d) - Codebase Audit Fixes" \
     --label "audit,ai-generated" --body "..."
   ```

---

## Single-Session Mode: `--single` (Phases 1-7)

Lightweight single-session audit using 8 subagents within the current Claude Code session. Always read-only (no fixes in single-session mode).

### Phase 1: Pre-Flight Checks

**Parse arguments first:**
- Remaining argument is the target path (default: entire repo)

### Phase 2: Discovery

1. **Check for monorepo structure**:
   - Look for `apps/`, `packages/`, `libs/`, `modules/` directories
   - Check `package.json` for `workspaces` field

2. **Identify tech stack**:
   - Check for `tsconfig.json`, React, Node.js patterns
   - Note the package manager

3. **Find existing rules**:
   - Read any `CLAUDE.md` files
   - Note ESLint configurations

4. **Determine scope**: Use path argument or audit entire repo.

### Phase 3: Parallel Audit (8 Agents)

Launch **8 Task agents in parallel** (in a single message with multiple tool calls). Each agent should use `subagent_type: "Explore"` and `run_in_background: true`.

**CRITICAL**: Send all 8 Task tool calls in ONE message to run them truly in parallel.

**Each agent must report findings in this format:**
```json
{
  "category": "category_name",
  "findings": [
    {
      "id": "unique-id",
      "severity": "critical|high|medium|low",
      "title": "Brief title",
      "file": "path/to/file.ts",
      "line": 123,
      "description": "What's wrong",
      "auto_fixable": true|false,
      "fix_confidence": "high|medium|low",
      "fix_type": "eslint_fix|remove_line|add_type|custom",
      "reason_not_fixable": "Why human review needed (if not auto_fixable)"
    }
  ]
}
```

See "Category Prompts" section below for each agent's instructions.

### Phase 4: Collect & Compile

After all agents complete:

1. **Read each agent's output**
2. **Compile all findings** into a master list
3. **Deduplicate** overlapping issues
4. **Write audit report** to `.audit/current/audit-report.md`

### Phase 5: Summary

Display the summary table and critical/high findings to the user.

### Phase 6: Issue Creation

Same as Phase M7 - ask the user what issues to create.

### Phase 7: Cleanup

Archive results and optionally clean up `.audit/current/`.

---

## Category Prompts

These prompts are used by both single-session mode (directly) and multi-agent mode (embedded in task files).

### Agent 1: Security Audit
```
Audit for security vulnerabilities. For each finding, classify its fixability.

Check for:
- Hardcoded secrets, API keys, tokens (NOT auto-fixable - needs env var setup)
- Console.logs with sensitive data (auto-fixable: remove line)
- SQL injection risks (NOT auto-fixable - needs refactor)
- XSS vulnerabilities (NOT auto-fixable - needs sanitization)
- Missing security headers (auto-fixable if config file exists)
- Edge function auth bypasses (NOT auto-fixable)

Report with severity, file:line, and auto_fixable classification.
Reference: ~/.claude/skills/audit/reference/security-patterns.md
```

### Agent 2: Dependencies Audit
```
Audit dependencies. For each finding, classify its fixability.

Check for:
- npm audit vulnerabilities (auto-fixable: npm audit fix for non-breaking)
- Outdated packages - minor versions (auto-fixable: npm update)
- Outdated packages - major versions (NOT auto-fixable - breaking changes)
- Unused dependencies (auto-fixable: npm uninstall)
- Duplicate dependencies (NOT auto-fixable - needs investigation)

Run: npm audit --json, npm outdated --json
Report with severity and auto_fixable classification.
```

### Agent 3: Code Quality Audit
```
Audit code quality. For each finding, classify its fixability.

Check for:
- ESLint violations (auto-fixable: eslint --fix)
- Prettier violations (auto-fixable: prettier --write)
- Unused imports/variables (auto-fixable: eslint --fix)
- Long methods >50 lines (NOT auto-fixable - needs refactor)
- Large files >500 lines (NOT auto-fixable - needs split)
- Empty catch blocks (NOT auto-fixable - needs error handling)

Report with severity, file:line, and auto_fixable classification.
Reference: ~/.claude/skills/audit/reference/code-quality.md
```

### Agent 4: Architecture Audit
```
Audit architecture patterns. Most findings need human review.

Check for:
- Circular dependencies (NOT auto-fixable)
- God objects (NOT auto-fixable)
- Improper layering (NOT auto-fixable)
- Import from wrong layer (MAYBE auto-fixable with verification)

Report with severity and file references.
Reference: ~/.claude/skills/audit/reference/architecture.md
```

### Agent 5: TypeScript/React Audit
```
Audit TypeScript and React patterns.

Check for:
- Excessive `any` types (auto-fixable if type is inferable)
- Missing return types (auto-fixable: add inferred type)
- React hooks violations (NOT auto-fixable)
- Fast Refresh violations (NOT auto-fixable)
- Missing key props (auto-fixable: add index as key, but flag for review)

Report with severity, file:line, and auto_fixable classification.
```

### Agent 6: Testing Audit
```
Audit test coverage and quality. Most findings need human review.

Check for:
- Missing test files for components (NOT auto-fixable)
- Test files without assertions (NOT auto-fixable)
- Missing edge case tests (NOT auto-fixable)

Report with severity and specific test gaps.
```

### Agent 7: Documentation Audit
```
Audit documentation.

Check for:
- Missing JSDoc on exports (auto-fixable: generate from types)
- Stale comments (NOT auto-fixable)
- README completeness (NOT auto-fixable)

Report with severity and file references.
```

### Agent 8: Performance Audit
```
Audit performance patterns. Most findings need human review.

Check for:
- N+1 query patterns (NOT auto-fixable)
- Missing React.memo (auto-fixable: add memo wrapper)
- Large bundle imports (NOT auto-fixable - needs tree shaking)

Report with severity and file:line references.
```

---

## Auto-Fix Confidence Reference

### HIGH Confidence (auto-fix with --fix)
- `eslint --fix` for fixable rules
- `prettier --write` for formatting
- `npm audit fix` (non-breaking only)
- Remove unused imports/variables
- Add missing semicolons

### MEDIUM Confidence (fix with extra care)
- Add explicit return types (verify inference is correct)
- Replace simple `any` with inferred type
- Add React.memo wrapper

### LOW Confidence (human review always)
- Refactor long methods
- Resolve circular dependencies
- Add error boundaries
- Write test implementations
- Major dependency upgrades

---

## Error Handling

| Scenario | Response |
|----------|----------|
| Agent crashes mid-audit | Results show `"in_progress"`. `--collect` reports incomplete agents. `--force` collects available. |
| Fix breaks the build (--fix) | Fix is reverted, recorded in `fixes_failed`, agent continues. |
| Merge conflict (--fix) | Higher-priority agent wins. Falls back to cherry-pick. |
| `.audit/current/` already exists | Coordinator asks: clean start, resume, or cancel. |
| Worktree already exists | Remove stale worktree first, then create fresh. |
| Task file missing | Worker errors with message to run `/audit` first. |
| Task agent times out | Collect proceeds with completed agents, reports incomplete ones. |
| All Task agents fail | Report failure, suggest `--manual` mode. |

---

## Notes

- **Always prompt the user** when `/audit` is called without flags - let them choose scope and execution strategy
- **Default mode is read-only** - no code changes, no branches, no PR
- Auto-fix is opt-in (user selects "Analyze + auto-fix" or passes `--fix`)
- **Three execution strategies**: Parallel worktrees (recommended), single session, or multi-clone
- Multi-clone is opt-in and requires explicit verification that all clones are clean
- Worktrees are the safest isolation method - they never touch the user's working directory or sibling clones
- The output is always an audit report document + optional GitHub issues
- The `reference/multi-agent-config.md` file has full JSON schemas for coordination files
