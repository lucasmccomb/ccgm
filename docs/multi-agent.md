# Multi-Agent System

The multi-agent system enables running multiple Claude Code instances in parallel on the same repository. Each instance works in its own clone of the repo, claims issues to avoid duplicate work, and uses assigned ports to prevent dev server collisions.

## When to use multi-agent

Multi-agent is useful when:
- You have multiple independent GitHub issues to complete
- Issues don't block each other (no sequential dependencies)
- You want to parallelize development work
- You're working on a project with a large backlog

## Clone organization models

CCGM supports two directory layouts for multi-clone repos.

### Workspace model (recommended)

```
~/code/my-repo-workspaces/
├── my-repo-w0/                    # Workspace 0
│   ├── my-repo-w0-c0/             # Clone 0 (agent-w0-c0)
│   ├── my-repo-w0-c1/             # Clone 1 (agent-w0-c1)
│   ├── my-repo-w0-c2/             # Clone 2 (agent-w0-c2)
│   └── my-repo-w0-c3/             # Clone 3 (agent-w0-c3)
├── my-repo-w1/                    # Workspace 1
│   ├── my-repo-w1-c0/
│   └── ...
```

Each workspace is an isolated group of 4 clones. A coordinator agent runs in the workspace directory and delegates tasks to sub-agents in its clones.

Create workspaces with `/workspace-setup`:
```
/workspace-setup my-repo
```

### Flat clone model (simpler)

```
~/code/my-repo-repos/
├── my-repo-0/                     # Clone 0 (agent-0)
├── my-repo-1/                     # Clone 1 (agent-1)
├── my-repo-2/                     # Clone 2 (agent-2)
└── my-repo-3/                     # Clone 3 (agent-3)
```

All clones are siblings in one directory. Simpler to set up but no isolation between agents.

## Agent identity

Each clone has a unique agent ID derived from its directory name:

| Directory | Agent ID |
|-----------|----------|
| `my-repo-w0-c2` | `agent-w0-c2` |
| `my-repo-3` | `agent-3` |
| `my-repo` (no number) | `agent-0` |

The agent ID is also stored in `.env.clone`:

```bash
AGENT_ID=agent-w0-c2
WORKSPACE_NUMBER=0
CLONE_NUMBER=2
PORT_OFFSET=2
FRONTEND_PORT=5175
BACKEND_PORT=8789
```

## Port allocation

Each clone gets unique ports to prevent dev server collisions.

### How ports are assigned

Ports are managed in `~/.claude/port-registry.json`. Each repo has separate base ports for its frontend and backend services:

```json
{
  "repos": {
    "my-repo": {
      "frontend": 5173,
      "backend": 8787
    }
  }
}
```

Each clone receives a `PORT_OFFSET` (workspace-mode: `workspace_number * clones_per_workspace + clone_number`; flat-clone mode: `clone_number`). The clone's ports are computed by adding `PORT_OFFSET` to each base:

| Clone | `PORT_OFFSET` | Frontend | Backend |
|-------|---------------|----------|---------|
| Clone 0 | 0 | frontend + 0 | backend + 0 |
| Clone 1 | 1 | frontend + 1 | backend + 1 |
| Clone 2 | 2 | frontend + 2 | backend + 2 |
| Clone 3 | 3 | frontend + 3 | backend + 3 |

Each repo gets a 16-port block per service to support up to 16 clones.

### Using ports

Always read ports from `.env.clone` before starting a dev server:

```bash
FRONTEND_PORT=$(grep 'FRONTEND_PORT=' .env.clone | cut -d= -f2)
pnpm dev -- --port ${FRONTEND_PORT}
```

The `port-check.py` hook warns if you start a dev server on the wrong port or if the port is already in use.

## Issue tracking

The multi-agent system uses a CSV-based tracking system to coordinate which agent is working on which issue.

### Tracking file

Located at `~/code/{log-repo}/{repo}/tracking.csv` with fields:

```
issue,agent,status,branch,pr,epic,title,claimed_at,updated_at
42,agent-w0-c1,in-progress,42-add-login,,,"Add login form",2026-03-29T10:00:00,2026-03-29T11:30:00
43,agent-w0-c2,pr-created,43-dark-mode,#87,,"Add dark mode",2026-03-29T10:05:00,2026-03-29T11:45:00
```

### Status lifecycle

```
claimed -> in-progress -> pr-created -> merged
                                     -> closed
```

### Automatic tracking

Hooks automatically update the tracking CSV:

1. **`git checkout -b 42-add-login`** -> Issue #42 claimed by this agent
2. **`git commit -m "#42: initial scaffold"`** -> Status transitions to `in-progress`
3. **Subsequent commits** -> Heartbeat updated (throttled to every 30 minutes)
4. **`gh pr create`** -> Status transitions to `pr-created`
5. **`gh pr merge`** -> Status transitions to `merged`
6. **`gh issue close 42`** -> Status transitions to `closed`

No manual tracking updates are needed. The hooks handle everything.

### Viewing tracking state

The `/startup` command shows the tracking dashboard. You can also query it directly:

```bash
python3 ~/.claude/lib/agent_tracking.py list --repo my-repo
```

### Stale claim cleanup

If an agent abandons work without updating tracking:

```bash
python3 ~/.claude/lib/agent_tracking.py gc --repo my-repo
```

This finds claims not updated in the last 24 hours and flags them as stale.

## Session logging

Each agent maintains its own session log in the log repo:

```
~/code/{log-repo}/
└── my-repo/
    └── 20260329/
        ├── agent-w0-c0.md
        ├── agent-w0-c1.md
        └── agent-w0-c2.md
```

At session start, agents read each other's logs to understand:
- Which issues other agents have claimed
- What branches they created
- Blockers or decisions that might affect shared work

## Workflows

### /mawf - Multi-Agent Workflow

Takes unstructured feedback, splits it into GitHub issues, and spawns parallel agents:

```
/mawf "Fix the login bug, add dark mode, update API docs"
```

This creates issues, plans dependency waves, spawns agents in separate clones, monitors progress, and reports results.

### /workspace-setup - Create workspace structure

Creates the directory structure, clones, `.env.clone` files, and GitHub labels:

```
/workspace-setup my-repo
```

### /xplan - Planning and execution

For larger projects, `/xplan` handles the full lifecycle from research through parallel execution:

```
/xplan "Build a SaaS dashboard with auth and billing"
```

## Concurrency safety

The tracking CSV uses git's merge mechanism for concurrency:

1. Agent modifies only its own rows
2. After writing, runs `git commit && git pull --rebase && git push`
3. Different-row edits auto-resolve during rebase
4. Same-row conflicts (rare) require manual resolution

This is safe for typical multi-agent workflows where each agent works on different issues.
