# Parallel Work Preference

When a task involves multiple independent issues or work items, prefer spawning parallel agents to complete them simultaneously. **On a single machine, isolate each agent in its own git worktree by default** (`isolation: "worktree"`): created per unit of work, torn down when that unit merges. Do **not** provision extra permanent clones just to get parallelism. Worktrees share the parent `.git` (no re-fetch), reclaim disk on teardown, and each has its own index and HEAD, so parallel builds and commits never collide. This is the default isolation for parallel sub-agent delegation — see the `git-worktrees` skill and `subagent-patterns.md`.

**Reserve separate clones** for the cases a worktree cannot serve:
- Multiple long-lived independent agents each owning the repo for days
- Per-branch dev-server ports (worktrees share `.env`; clones get per-clone `.env.clone` with pre-computed `FRONTEND_PORT`/`BACKEND_PORT`)
- Hook-driven per-branch `tracking.csv` issue tracking that the multi-clone setup provides
- Cross-machine / cloud dispatch (a worktree cannot span machines)

**When to parallelize:**
- Multiple independent GitHub issues need to be completed
- A project has issues that do not block each other

**How (default, worktrees):** Launch agents with `isolation: "worktree"`; each works on its own feature branch off `origin/main` in an isolated worktree. Remove each worktree when its PR merges, and run `/worktree-sweep` as the orphan backstop.

**How (clones):** When one of the reserved cases applies and a multi-clone setup exists (workspace model: `~/code/{repo}-workspaces/`, or flat model: `~/code/{repo}-repos/`), launch agents pointed at different clone directories. Each agent claims its own issue via the tracking CSV (auto-registered by hooks on branch creation) and works independently. See `~/.claude/multi-agent-system.md` for the full coordination guide.

**Teardown is mandatory, not best-effort.** A worktree an agent built in does **not** auto-remove — remove each unit's worktree the moment its PR merges, and run `/worktree-sweep` to reclaim any orphans (including built-in `isolation:"worktree"` worktrees the harness could not auto-reclaim). Leaving built worktrees behind is exactly what filled 237 GB on one repo on 2026-07-13. See the `git-worktrees` skill.

**Issue tracking**: Uses `~/code/{log-repo-name}/{repo}/tracking.csv`. Hooks auto-update tracking on branch creation, commits, PR creation, merge, and issue close. See `~/.claude/multi-agent-system.md` for details.

**Workspace model** (the heavier clone-based alternative, for the reserved cases above): Use `/workspace-setup {repo}` to create isolated workspace groups. Each workspace has 4 clones. Point a coordinator agent at a workspace directory - it discovers its clones and delegates. Prefer worktrees for ordinary single-machine parallel delegation; reach for the workspace model when you genuinely need persistent per-clone ports, per-branch `tracking.csv`, or long-lived independent agents.

**Cap peak concurrency.** Keep simultaneous heavy agents to 4 and launch in waves; the defaults, the 429 error, and the recovery procedure are in `subagent-patterns.md` under Concurrency and Rate Limits.

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
