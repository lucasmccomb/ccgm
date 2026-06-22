# Parallel Work Preference

When a task involves multiple independent issues or work items, prefer spawning parallel agents in separate clones to complete them simultaneously. Use the Agent tool to launch agents, each working in its own clone directory.

**When to parallelize:**
- Multiple independent GitHub issues need to be completed
- A project has issues that do not block each other
- The repo has a multi-clone setup (workspace model: `~/code/{repo}-workspaces/` or flat model: `~/code/{repo}-repos/`)

**How:** Launch agents pointed at different clone directories. Each agent claims its own issue via the tracking CSV (auto-registered by hooks on branch creation) and works independently. See `~/.claude/multi-agent-system.md` for the full coordination guide.

**Issue tracking**: Uses `~/code/{log-repo-name}/{repo}/tracking.csv`. Hooks auto-update tracking on branch creation, commits, PR creation, merge, and issue close. See `~/.claude/multi-agent-system.md` for details.

**Workspace model** (preferred for delegated work): Use `/workspace-setup {repo}` to create isolated workspace groups. Each workspace has 4 clones. Point a coordinator agent at a workspace directory - it discovers its clones and delegates.

**Cap peak concurrency.** Preferring parallelism does NOT mean launching everything at once. Too many heavy agents firing simultaneously - whether via the Workflow tool's `parallel()`/`pipeline()` or many Agent calls in one message - trips a server-side 429 throttle (`Server is temporarily limiting requests · Rate limited`) that fails the *entire* burst, not just the marginal agent. Keep simultaneous **heavy** agents (Opus, high/max effort, or large-context) to **4** (never exceed 5), launch in waves, and default fan-out agents to cheaper models / lower effort unless thoroughness is explicitly requested. If you have `subagent-patterns` installed, `concurrency-and-rate-limits.md` carries the full defaults table and the throttled-mid-run recovery procedure.

---

# Dev Server Port Allocation (Multi-Clone)

**Each clone gets isolated ports to prevent collisions.** Ports are assigned per-repo via `~/.claude/port-registry.json`, ensuring no collisions between different repos.

**How it works:**
- Each repo has a unique base port block (16 ports) in the registry
- Each clone's `.env.clone` has pre-computed `FRONTEND_PORT` and `BACKEND_PORT`
- A PreToolUse hook (`~/.claude/hooks/port-check.py`) warns about port mismatches and conflicts
- Read ports from `.env.clone`:
  ```bash
  FRONTEND_PORT=$(grep 'FRONTEND_PORT=' .env.clone | cut -d= -f2)
  BACKEND_PORT=$(grep 'BACKEND_PORT=' .env.clone | cut -d= -f2)
  pnpm dev -- --port ${FRONTEND_PORT}
  ```

**NEVER run `pnpm dev` or `wrangler dev` without clone-aware ports in a multi-clone repo.** Port collisions kill other agents' dev servers.

See `~/.claude/multi-agent-system.md` for full details.
