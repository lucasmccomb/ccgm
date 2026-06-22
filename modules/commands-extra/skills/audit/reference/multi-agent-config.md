# Multi-Agent Audit Configuration

Reference spec for distributed audit using git worktrees for isolation.

---

## Agent Assignments

9 audit categories are distributed across 4 agents. Agent 0 carries 3 categories because the
ToS & Compliance audit is often the most project-specific and benefits from sharing context
with the Security and Dependencies audits.

| Agent | Worktree Dir | Categories | Merge Priority |
|-------|-------------|------------|----------------|
| 0 | `.audit/worktrees/agent-0` | Security, Dependencies, ToS & Compliance | 1 (highest - wins conflicts) |
| 1 | `.audit/worktrees/agent-1` | Code Quality, TypeScript/React | 2 |
| 2 | `.audit/worktrees/agent-2` | Architecture, Performance | 3 |
| 3 | `.audit/worktrees/agent-3` | Testing, Documentation | 4 (lowest) |

**9 categories total**: Security, Dependencies, ToS & Compliance, Code Quality, TypeScript/React,
Architecture, Performance, Testing, Documentation.

**Merge priority**: When `--collect` merges branches and encounters a conflict, the process **halts and writes a conflict report** to `.audit/current/merge-conflicts.md`. Neither agent's changes are silently dropped. The human reviewer resolves the conflict and re-runs `--collect`. Agent 0 (Security/Dependencies/ToS) has the highest priority, but priority does NOT mean auto-resolution.

**Agent identity**: Derived from worktree directory name suffix. `agent-0` -> agent 0, `agent-3` -> agent 3.

**Concurrency cap — avoid the 429 throttle.** The 4-agent default is deliberately at the safe ceiling for *heavy* workers: each `general-purpose` worker loads its pack's checks plus a spine slice (large context) and, under `FIX_MODE=true`, also commits and pushes. **Never launch more than 4 of these at once.** If you raise the worker count (more non-empty assignments, or a custom split), launch them in sequential waves of ≤4 rather than one burst; if a launch reports `Server is temporarily limiting requests · Rate limited`, that is the server throttle, not a usage cap — wait 30–60s and re-dispatch only the unfinished workers. This matches the M5 launch step in `SKILL.md`. See `~/.claude/rules/concurrency-and-rate-limits.md`.

---

## CRITICAL: Worktree Isolation

**All parallel audit work MUST use git worktrees.** Worktrees are created inside `.audit/worktrees/` within the current repo. This ensures:

1. **No interference with the user's working directory** - The user's current branch is never checked out or modified
2. **No interference with sibling clones** - Other clone directories may have active agent work and are NEVER touched
3. **Complete isolation** - Each worktree has its own working tree, branch, and node_modules
4. **Shared git objects** - Worktrees share the same `.git` object database, so no redundant cloning

**NEVER use sibling clone directories for audit work.** They may be in use by other agents on different tasks.

---

## Directory Layout

The audit system creates this structure within the current repo:

```
<repo-root>/                    # The repo where /audit is invoked
├── .audit/                     # Audit coordination directory (gitignored)
│   ├── current/
│   │   ├── config.json         # Audit run configuration
│   │   ├── tasks/
│   │   │   ├── agent-0.json    # Task file for agent 0
│   │   │   ├── agent-1.json    # Task file for agent 1
│   │   │   ├── agent-2.json    # Task file for agent 2
│   │   │   └── agent-3.json    # Task file for agent 3
│   │   └── results/
│   │       ├── agent-0.json    # Results from agent 0
│   │       ├── agent-1.json    # Results from agent 1
│   │       ├── agent-2.json    # Results from agent 2
│   │       └── agent-3.json    # Results from agent 3
│   ├── worktrees/
│   │   ├── agent-0/            # Git worktree for agent 0 (full repo checkout)
│   │   ├── agent-1/            # Git worktree for agent 1
│   │   ├── agent-2/            # Git worktree for agent 2
│   │   ├── agent-3/            # Git worktree for agent 3
│   │   └── combined/           # Git worktree for merge/collection phase
│   └── history/
│       └── YYYYMMDD.json       # Archived combined results
├── .gitignore                  # Must contain `.audit/` entry
└── ... (rest of repo)
```

**Note:** `.audit/` MUST be in `.gitignore`. The coordinator (Phase M1) ensures this.

---

## JSON Schemas

### config.json

Written by coordinator during M2.

```json
{
  "audit_date": "YYYYMMDD",
  "started_at": "ISO-8601 timestamp",
  "base_branch": "<detected from git symbolic-ref refs/remotes/origin/HEAD, fallback: main>",
  "agent_count": 4,
  "scope": "entire repo",
  "fix_mode": true,
  "repo_dir": "/absolute/path/to/repo-root",
  "epic_issue": 123,
  "worktrees": [
    { "agent": 0, "dir": ".audit/worktrees/agent-0", "branch": "audit/agent-0-YYYYMMDD" },
    { "agent": 1, "dir": ".audit/worktrees/agent-1", "branch": "audit/agent-1-YYYYMMDD" },
    { "agent": 2, "dir": ".audit/worktrees/agent-2", "branch": "audit/agent-2-YYYYMMDD" },
    { "agent": 3, "dir": ".audit/worktrees/agent-3", "branch": "audit/agent-3-YYYYMMDD" }
  ]
}
```

### tasks/agent-N.json

Written by coordinator during M4. Each task file is self-contained so workers don't need to read other files.

```json
{
  "agent": 0,
  "audit_date": "YYYYMMDD",
  "base_branch": "<detected base branch>",
  "branch": "audit/agent-0-YYYYMMDD",
  "fix_mode": true,
  "merge_priority": 1,
  "categories": [
    {
      "name": "Security",
      "instructions": "Full category audit instructions embedded here...",
      "patterns_reference": "Embedded content from security-patterns.md..."
    },
    {
      "name": "Dependencies",
      "instructions": "Full category audit instructions embedded here..."
    },
    {
      "name": "ToS & Compliance",
      "instructions": "Full category audit instructions embedded here (Agent 9 prompt from SKILL.md)..."
    }
  ],
  "fix_reference": "Embedded content from fix-patterns.md...",
  "verification_commands": {
    "lint": "<detected from package.json scripts; e.g. 'npm run lint' or 'pnpm run lint'>",
    "type_check": "<detected from package.json scripts; e.g. 'npm run type-check'>",
    "build": "<detected from package.json scripts; e.g. 'npm run build'>"
  },
  "finding_format": {
    "id": "agent-N-category-NNN",
    "severity": "critical|high|medium|low",
    "title": "Brief title",
    "file": "path/to/file.ts",
    "line": 123,
    "description": "What's wrong",
    "auto_fixable": true,
    "fix_confidence": "high|medium|low",
    "fix_type": "eslint_fix|remove_line|add_type|custom",
    "fix_command": "Command or description of fix",
    "reason_not_fixable": "Why human review needed (if not auto_fixable)"
  },
  "commit_format": "audit({category}): {brief title}",
  "project_claude_md": "/absolute/path/to/repo-root/CLAUDE.md"
}
```

### results/agent-N.json

Written by worker during W2 (initial) and W5 (final).

```json
{
  "agent": 0,
  "status": "in_progress|completed|completed_local|failed",
  "started_at": "ISO-8601 timestamp",
  "completed_at": "ISO-8601 timestamp or null",
  "branch": "audit/agent-0-YYYYMMDD",
  "categories_audited": ["Security", "Dependencies", "ToS & Compliance"],
  "findings": [
    {
      "id": "agent-0-security-001",
      "category": "Security",
      "severity": "high",
      "title": "Console.log exposes user PII",
      "file": "src/hooks/useAuth.ts",
      "line": 45,
      "description": "Console.log statement outputs full user object including email and phone",
      "auto_fixable": true,
      "fix_confidence": "high",
      "fix_type": "remove_line",
      "fix_command": "Remove console.log on line 45"
    }
  ],
  "cross_category_findings": [
    {
      "id": "agent-0-xcat-001",
      "target_category": "Code Quality",
      "severity": "medium",
      "title": "Unused import in auth module",
      "file": "src/hooks/useAuth.ts",
      "line": 3,
      "description": "Discovered while auditing security - unused lodash import",
      "note": "Not fixed by this agent - belongs to Code Quality category"
    }
  ],
  "fixes_applied": [
    {
      "finding_id": "agent-0-security-001",
      "commit_hash": "abc1234",
      "commit_message": "audit(security): remove PII-leaking console.log",
      "files_changed": ["src/hooks/useAuth.ts"]
    }
  ],
  "fixes_failed": [
    {
      "finding_id": "agent-0-security-003",
      "reason": "Type error after removing console.log - variable only used in log statement",
      "verification_output": "error TS6133: 'debugData' is declared but never used"
    }
  ],
  "summary": {
    "total_findings": 12,
    "by_severity": { "critical": 1, "high": 4, "medium": 5, "low": 2 },
    "fixes_attempted": 6,
    "fixes_succeeded": 5,
    "fixes_failed": 1,
    "human_review_needed": 6
  }
}
```

### history/YYYYMMDD.json

Written by `--collect` during C6. Combines all agent results for trend tracking.

```json
{
  "audit_date": "YYYYMMDD",
  "completed_at": "ISO-8601 timestamp",
  "base_branch": "<detected base branch>",
  "combined_branch": "audit/YYYYMMDD",
  "pr_number": 123,
  "pr_url": "https://github.com/org/repo/pull/123",
  "epic_issue": 456,
  "agents": [
    { "agent": 0, "status": "completed", "findings": 12, "fixes": 5 },
    { "agent": 1, "status": "completed", "findings": 28, "fixes": 8 },
    { "agent": 2, "status": "completed", "findings": 15, "fixes": 0 },
    { "agent": 3, "status": "completed", "findings": 9, "fixes": 2 }
  ],
  "totals": {
    "findings": 64,
    "by_severity": { "critical": 2, "high": 15, "medium": 30, "low": 17 },
    "fixes_applied": 15,
    "fixes_failed": 3,
    "human_review": 46,
    "issues_created": 5
  },
  "downstream_issues": [457, 458, 459, 460, 461]
}
```

---

## Coordination Protocol

### Phase Flow

```
Coordinator (/audit)             Workers (/audit --worker)        Collector (/audit --collect)
        |                            |                            |
   M1: Pre-flight                    |                            |
   M2: Create .audit/               |                            |
   M2.5: Create epic issue          |                            |
   M3: Create worktrees             |                            |
   M4: Write task files              |                            |
   M5: Launch agents (or output cmds)|                            |
        |                       W1: Read task                     |
        |                       W2: Init results                  |
        |                       W3: Deep audit                    |
        |                       W4: Fix cycle                     |
        |                       W5: Write results                 |
        |                       W6: Push & signal                 |
        |                            |                       C1: Verify completion
        |                            |                       C2: Collect & dedup
        |                            |                       C3: Merge (in collector worktree)
        |                            |                       C4: Create PR
        |                            |                       C5: Create issues
        |                            |                       C6: Cleanup worktrees & archive
```

### Status Lifecycle

```
(not started) -> in_progress -> completed
                             -> completed_local  (push failed, results available locally)
                             -> failed           (agent crashed or errored)
```

### Conflict Resolution During Merge (C3)

1. Attempt `git merge` for each agent branch in priority order (0 first, 3 last)
2. If a merge conflict occurs: **HALT immediately**. Write a conflict report to `.audit/current/merge-conflicts.md` listing the conflicted files and both agents involved. Abort the merge with `git merge --abort`. Stop processing further agent branches.
3. **NEVER use `git checkout --ours`** to auto-resolve conflicts. Both agents may have applied valid fixes; silently dropping either agent's work is incorrect and falsely records it as applied.
4. Report the halt to the user: "Merge conflict on agent-N branch. See `.audit/current/merge-conflicts.md`. Resolve manually and re-run `--collect`."
5. After the human resolves conflicts and re-runs `--collect`, continue with remaining merges.
6. After all merges, run full verification using the detected commands (`lint`, `type-check`, `build`)
7. If verification fails, incrementally test by reverting the last merge and re-verifying to identify the breaking agent

### Cross-Category Findings

When an agent discovers an issue that belongs to another agent's category:
- **Record it** in `cross_category_findings` in the results JSON
- **Do NOT fix it** - the owning agent is responsible for fixes in their categories
- The collector merges cross-category findings into the appropriate category during C2

---

## Branch Naming

| Branch | Purpose | Created By |
|--------|---------|------------|
| `audit/agent-0-YYYYMMDD` | Agent 0's work branch | Coordinator (M3, via worktree) |
| `audit/agent-1-YYYYMMDD` | Agent 1's work branch | Coordinator (M3, via worktree) |
| `audit/agent-2-YYYYMMDD` | Agent 2's work branch | Coordinator (M3, via worktree) |
| `audit/agent-3-YYYYMMDD` | Agent 3's work branch | Coordinator (M3, via worktree) |
| `audit/YYYYMMDD` | Combined branch for PR | Collector (C3, via collector worktree) |

---

## Monitoring

While workers run, the coordinator or user can monitor progress:

```bash
# Check which agents have completed
for i in 0 1 2 3; do
  echo "Agent $i: $(jq -r '.status // "not started"' .audit/current/results/agent-$i.json 2>/dev/null || echo 'no results file')"
done

# Watch for completion
watch -n 10 'for i in 0 1 2 3; do echo "Agent $i: $(jq -r ".status // \"pending\"" .audit/current/results/agent-$i.json 2>/dev/null || echo "waiting")"; done'

# List active worktrees
git worktree list
```
