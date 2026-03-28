# Session Logging System

This document defines the session logging system for Claude Code, providing continuity between sessions, cross-agent visibility, and work tracking with git-backed history.

## Purpose

- **Session continuity**: Pick up exactly where the previous session left off
- **Cross-agent visibility**: See what other agents are working on in real time
- **Context preservation**: Capture details that do not fit in git commits or issues
- **Work tracking**: Record completed work, blockers, and decisions made
- **Remote backup**: All logs are git-tracked with a GitHub remote

## Log Repository

All session logs live in a centralized git repo shared by all agents across all projects:

**Location**: `~/code/{log-repo-name}/`
**GitHub**: `{your-username}/{log-repo-name}` (private)
**Branch**: Always `main` (no branching)

## Directory Structure

```
~/code/{log-repo-name}/
├── {repo-name}/
│   └── YYYYMMDD/
│       ├── agent-0.md
│       ├── agent-1.md
│       └── agent-2.md
└── README.md
```

Each project has its own directory. Within each project, logs are organized by date subdirectories (use your local timezone consistently). Each agent writes exclusively to its own file.

## Agent Identity Derivation

Agent identity is derived automatically from the working directory name. Two models are supported:

### Workspace Model (preferred)

Directory names follow `{repo}-w{X}-c{Y}` pattern:

```bash
WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')
if [ -n "$WC_MATCH" ]; then
  AGENT_ID="agent-${WC_MATCH}"
fi
```

| Directory | Agent ID |
|-----------|----------|
| `habitpro-ai-w0-c0` | agent-w0-c0 |
| `habitpro-ai-w1-c2` | agent-w1-c2 |
| `habitpro-ai-w2-c3` | agent-w2-c3 |

### Flat Clone Model (legacy)

Directory names follow `{repo}-{N}` pattern:

```bash
AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' || echo "0")
AGENT_ID="agent-${AGENT_NUM}"
```

| Directory | Agent ID |
|-----------|----------|
| `my-repo-0` or `my-repo` | agent-0 |
| `my-repo-1` | agent-1 |

### Unified Derivation

Use this to auto-detect the model:

```bash
WC_MATCH=$(basename "$PWD" | grep -oP 'w\d+-c\d+$')
if [ -n "$WC_MATCH" ]; then
  AGENT_ID="agent-${WC_MATCH}"
elif [ -f .env.clone ] && grep -q 'AGENT_ID=' .env.clone 2>/dev/null; then
  AGENT_ID=$(grep 'AGENT_ID=' .env.clone | cut -d= -f2)
else
  AGENT_NUM=$(basename "$PWD" | grep -oE '[0-9]+$' || echo "0")
  AGENT_ID="agent-${AGENT_NUM}"
fi
```

## Repo Name Derivation

The project name for log paths is derived from the git remote:

```bash
REPO_NAME=$(git remote get-url origin 2>/dev/null | xargs basename | sed 's/\.git$//')
```

This ensures consistency regardless of the local directory name.

## Log File Path

The full path to an agent's log file:

```
~/code/{log-repo-name}/{repo-name}/YYYYMMDD/{agent-id}.md
```

- Workspace model: `~/code/{log-repo-name}/my-project/20260207/agent-w1-c2.md`
- Flat clone model: `~/code/{log-repo-name}/my-project/20260207/agent-0.md`

## File Naming Convention

- **Date format**: `YYYYMMDD` (no dashes, no hyphens)
- **Timezone**: Use your local timezone consistently across all sessions
- **Agent file**: `{agent-id}.md` (e.g., `agent-w1-c2.md` or `agent-0.md`)

## Log File Title Format

Each log file starts with:

```markdown
# {agent-id} - YYYYMMDD - {repo-name}
```

- Workspace example: `# agent-w1-c2 - 20260207 - my-project`
- Flat clone example: `# agent-0 - 20260207 - my-project`

## Session Startup Protocol

When starting a new session (via `/startup` command):

1. **Pull latest logs**: `cd ~/code/{log-repo-name} && git pull --rebase`
2. **Derive identity**: Determine agent number and repo name
3. **Check for today's log**: Look for `~/code/{log-repo-name}/{repo-name}/YYYYMMDD/{agent-id}.md`
4. **Read context**:
   - If today's log exists for this agent, read it
   - If not, find most recent log for this agent in the repo directory
   - Also read other agents' logs from today for cross-agent awareness
5. **Create today's log** if it does not exist:
   - Create the date subdirectory: `mkdir -p ~/code/{log-repo-name}/{repo-name}/YYYYMMDD`
   - Create agent file with Session Start entry (filename: `{agent-id}.md`)
6. **Freshness check**: If log repo has uncommitted changes older than 1 hour, auto-commit and push

## Cross-Agent Visibility

At session start, check what other agents have done today:

```bash
ls ~/code/{log-repo-name}/{repo-name}/YYYYMMDD/
# Workspace model output: agent-w0-c0.md  agent-w0-c1.md  agent-w1-c0.md
# Flat clone model output: agent-0.md  agent-1.md  agent-2.md
```

Read other agents' files to understand:
- What issues they are working on (avoid conflicts)
- What branches they have created
- Any blockers or decisions that affect your work

## During Session Protocol

Update your agent's log file throughout the session with:

- Work completed (issue numbers, PRs, branches)
- Decisions made and rationale
- Blockers encountered
- Files modified or created
- **Insights**: Codebase-specific knowledge surfaced during the work (see below)
- Context that would help future sessions
- Next steps / recommendations

### Logging Insights

When you generate insights during a conversation - architecture patterns, gotchas, design decisions, non-obvious relationships - capture them in the current work log entry.

**What to capture**:
- Codebase architecture knowledge (e.g., "CSS prefix system uses build-time transformation for CSS files but runtime context for React")
- Non-obvious relationships between files/packages
- Gotchas or footguns discovered during implementation
- Design decisions and their rationale

**What NOT to capture**:
- General programming concepts
- Obvious observations that any developer would know from reading the code
- Insights that duplicate information already in CLAUDE.md or memory files

**Format**: Condense into 1-2 bullet points under an `- **Insights**:` field in the work log entry.

```markdown
### Issue #XX: [Title] #completed
- **Branch**: `XX-branch-name`
- **PR**: #YY
- **Insights**:
  - Monorepo has duplicate feature strings across shared and per-product configs; all must be updated together
  - Component exists in both shared and suite packages because suite adds multi-product routing
```

## Log Repo Commit Protocol

After updating your log file, commit and push to the log repo:

```bash
cd ~/code/{log-repo-name}
git add -A
git commit -m "{agent-id}: {repo-name} update"
git pull --rebase
git push
```

**When to commit the log repo:**
- After major workflow milestones (PR merge, issue close)
- Before ending a session
- Periodically during long sessions (every ~30 minutes of active work)
- The startup freshness check handles stale uncommitted changes

**Conflict handling**: Since each agent writes only to its own file, `git pull --rebase` always resolves cleanly.

## Midnight Crossover Protocol

If a session continues past midnight in your timezone:

1. Create a new date subdirectory and agent file
2. Add a continuation note at the top
3. Reference the previous day's log
4. Continue logging in the new file

## Log File Template

```markdown
# {agent-id} - YYYYMMDD - {repo-name}

> [Optional: Continued from previous session (YYYYMMDD)]

## Session Start
- **Time**: HH:MM
- **Branch**: `main`
- **State**: Clean / dirty / in-progress on #XX

## Work

### Issue #XX: [Title] #status
- **Branch**: `XX-branch-name`
- **PR**: #YY
- **Status**: completed / in-progress / blocked
- **Summary**: [what was done]
- **Files**: [key files changed]
- **Insights**: [codebase knowledge surfaced during this work - omit if none]

## Session End
- **Time**: HH:MM
- **Next steps**: [recommendations]
```

## Tags (Optional)

Use inline tags for easy scanning:
- `#completed` - Work finished
- `#in-progress` - Work ongoing
- `#blocked` - Waiting on something
- `#decision` - Important decision made
- `#todo` - Task identified for future

## GitHub Issue Status Table (Optional)

For complex projects, include a status table:

```markdown
## GitHub Issue Status
| Issue | Title | Status | Notes |
|-------|-------|--------|-------|
| #14 | Initialize monorepo | PR #89 | Awaiting review |
| #15 | Set up CI/CD | In progress | CI done, deploy needed |
```

## Automated Logging at Workflow Events

**IMPORTANT**: Claude Code must automatically update the session log at these workflow trigger points. This ensures work is captured before moving to subsequent tasks.

**Log file location**: `~/code/{log-repo-name}/{repo-name}/YYYYMMDD/{agent-id}.md`

### Pre-Commit Log Update

**Trigger**: Before committing code (after running verification, before `git commit`)

**What to log**:
```markdown
### Issue #XX: [Brief description] #in-progress
- **Branch**: `XX-branch-name`
- **Commit**: [commit message summary]
- **Files changed**: [list key files]
- **Verification**: [passed/failed - lint, types, tests, build]
```

**Action**: Update the agent log file, then proceed with the commit.

### Pre-Push Log Update

**Trigger**: Before pushing to remote (after commit, before `git push`)

**What to log**:
```markdown
### Issue #XX: [Brief description] #in-progress
- **Branch**: `XX-branch-name`
- **Commits**: [number of commits being pushed]
- **Status**: Ready for PR / Pushing updates
- **Verification**: All checks passed
```

**Action**: Update the agent log file, then proceed with the push.

### Post-PR Creation Log Update

**Trigger**: Immediately after creating a pull request

**What to log**:
```markdown
### Issue #XX: [Title] #in-review
- **Branch**: `XX-branch-name`
- **PR**: #YY (URL)
- **Status**: PR created, awaiting review
- **Summary**: [what the PR accomplishes]
- **Key files**: [main files changed]
- **Insights**: [codebase knowledge surfaced during this work - omit if none]
```

**Action**: Update the agent log, update the GitHub Issue Status table if present, then inform user.

### Post-PR Merge Log Update

**Trigger**: After a PR is merged (either by user or via `gh pr merge`)

**What to log**:
```markdown
### Issue #XX: [Title] #completed
- **Branch**: `XX-branch-name`
- **PR**: #YY - MERGED
- **Merged at**: [timestamp if available]
- **Summary**: [final summary of what was delivered]
```

**Action**:
1. Update the issue entry to `#completed`
2. Update the GitHub Issue Status table
3. Commit and push the log repo

### Post-Issue Close Log Update

**Trigger**: After closing a GitHub issue (via `gh issue close` or PR auto-close)

**What to log**:
```markdown
### Issue #XX: [Title] #completed
- **Closed**: [how - PR merge / manual / will not fix]
- **Resolution**: [brief summary]
```

**Action**:
1. Mark issue as `#completed` in agent log
2. Update GitHub Issue Status table
3. Identify and log next available issue to work on
4. Commit and push the log repo

### Workflow Event Checklist

Before moving to any new issue, verify these log updates are complete:

- [ ] Current issue status updated in agent log
- [ ] Any PRs created/merged noted
- [ ] Any issues closed noted
- [ ] GitHub Issue Status table updated (if present)
- [ ] Next steps documented
- [ ] Log repo committed and pushed (if major milestone)
- [ ] **Dev-env check**: If any global config, MCP, plugin, or tooling changes were made, log to `dev-env`

## Best Practices

1. **Be specific**: Include issue numbers, PR numbers, branch names
2. **Capture rationale**: Document *why* decisions were made, not just what
3. **Note blockers early**: If something is blocking progress, document it
4. **Update at workflow events**: Follow the automated logging triggers above
5. **Link to files**: Mention specific files that are relevant for context
6. **Keep it scannable**: Use headers, bullet points, and tables
7. **Never skip log updates**: Always update before moving to next task
8. **Check other agents' logs**: Read today's date subdirectory at session start

## Safeguards and Enforcement

### Self-Check Questions

Before ANY git operation in the project repo, ask yourself:
1. **"Have I updated my agent log?"** - If no, update it first
2. **"Does the log reflect my current work?"** - If not, fix it
3. **"When did I last update the log?"** - If >30 min ago during active work, update it

### Red Flags (Stop and Fix)

If any of these are true, STOP and update the agent log before continuing:
- About to commit but log does not mention the work
- About to push but log does not have push details
- PR was just created but log does not have PR number
- Issue was just closed but log still shows it as in-progress
- Starting new issue but previous issue is not logged as complete
- Session has been active 30+ minutes with no log updates

### Recovery Protocol

If you realize logging was skipped:
1. **Do not panic** - It is fixable
2. **Reconstruct from git** - Use `git log`, `gh pr list`, `gh issue list` to see what happened
3. **Update the agent log retroactively** - Add entries for missed work with approximate times
4. **Add a note**: `> Note: Reconstructed from git history - logging was briefly interrupted`
5. **Resume normal logging** - Continue with proper workflow from here

## Dev Environment Log (`dev-env`)

The `dev-env` log captures changes to the shared development environment - tooling, configs, workflows, and optimizations that span all projects. Unlike project logs (tied to a specific repo), `dev-env` entries track cross-cutting infrastructure changes.

**Location**: `~/code/{log-repo-name}/dev-env/YYYYMMDD/{agent-id}.md`

### Auto-Detection: When to Log to `dev-env`

Whenever you make changes that match ANY of the categories below, automatically create or update a `dev-env` log entry. Do not wait to be asked.

**Trigger categories**:

| Category | Examples | Detection Signal |
|----------|----------|-----------------|
| MCP server changes | Adding/removing/updating servers in MCP config | You edited MCP configuration |
| Global instructions updates | New workflow sections, updated tool preferences | You edited global CLAUDE.md |
| Browser/extension tooling | New extensions, flags, automation capabilities | Chrome flag changes, extension installs |
| CLI tool installs | New global npm packages, brew installs | `npm install -g`, `brew install` for tooling |
| Shell config changes | zshrc updates, aliases, PATH changes | You edited shell config files |
| Hook system changes | New hooks, updated hook scripts | You edited hook files or config |
| Plugin changes | Installing/removing Claude Code plugins | Plugin install/uninstall commands |
| Memory system updates | New memory files, significant memory changes | You edited memory files |
| Skill/command updates | New skills, updated skill configs | You edited skill definitions |
| Multi-agent system changes | Clone setup, coordination rules | You edited multi-agent config |
| New standards/protocols | Adopting new APIs, spec-driven changes | Research + config changes |

### Log Entry Template (dev-env)

```markdown
### [Optimization Title] #completed
- **Category**: [from table above]
- **What changed**:
  - [Bullet list of specific changes]
- **Files modified**:
  - [List of config/system files changed]
- **Why**: [Motivation - what problem this solves or what capability it adds]
- **Insights**: [Non-obvious learnings from the research/implementation]
- **References**: [Links to docs, issues, specs]
- **Next steps**: [Follow-up work if any]
```

### What NOT to Log in `dev-env`

- Project-specific config changes (those go in the project's log)
- Temporary debugging changes that will be reverted
- Reading/researching without making changes

## Issue Tracking

Each repo with multi-agent work has a `tracking.csv` file in the log repo at `{repo}/tracking.csv`. This file tracks which agent is working on which issue.

**Format**: CSV with fields: issue, agent, status, branch, pr, epic, title, claimed_at, updated_at

**Automatic updates**: Claude Code hooks update tracking.csv at these workflow points:
- `git checkout -b {N}-*` -> claim issue N
- `git commit -m "#N: ..."` -> heartbeat update (throttled to 30 min)
- `gh pr create` -> status: pr-created
- `gh pr merge` -> status: merged
- `gh issue close` -> status: closed

**Manual operations**: `python3 ~/.claude/lib/agent_tracking.py <command>`
- `list --repo {repo}` - show all claims
- `check {repo} {issue}` - check if an issue is claimed
- `gc` - find stale claims (>24h with active status)
- `import {repo}` - import existing GitHub-labeled issues

**Concurrency**: Standard git flow. All agents read/write the same tracking.csv. Different-row edits auto-resolve via `git pull --rebase`.

## Adding a New Project

To start logging for a new project:

1. Create the project directory in the log repo:
   ```bash
   mkdir -p ~/code/{log-repo-name}/{new-repo-name}
   ```

2. Commit and push:
   ```bash
   cd ~/code/{log-repo-name}
   git add -A && git commit -m "Add {new-repo-name} directory" && git push
   ```

3. The startup command will automatically create date subdirectories and agent files as needed.

## Freshness Check

The `/startup` command runs a freshness check on the log repo:

```bash
LOG_REPO="$HOME/code/{log-repo-name}"
LAST_COMMIT=$(cd "$LOG_REPO" && git log -1 --format="%ct" 2>/dev/null || echo "0")
NOW=$(date +%s)
DIFF_MINUTES=$(( (NOW - LAST_COMMIT) / 60 ))

# Pull latest from other agents
cd "$LOG_REPO" && git pull --rebase

# Auto-commit and push if stale (>60 min with uncommitted changes)
if [ "$DIFF_MINUTES" -gt 60 ]; then
  cd "$LOG_REPO" && git add -A
  if ! git diff --cached --quiet; then
    git commit -m "${AGENT_ID}: auto-sync" && git pull --rebase && git push
  fi
fi
```
