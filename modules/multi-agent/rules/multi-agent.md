# Parallel Work Preference

When a task involves multiple independent issues or work items, spawn parallel agents. On a single machine, isolate each agent in its own git worktree (`isolation: "worktree"`): created per unit of work, torn down when that unit merges. Worktrees share the parent `.git`, reclaim disk on teardown, and each has its own index and HEAD, so parallel builds and commits never collide. See the `git-worktrees` skill and `subagent-patterns.md`.

Reserve separate clones for the cases a worktree cannot serve: several long-lived independent agents each owning the repo for days, per-branch dev-server ports (worktrees share `.env`; clones get a per-clone `.env.clone` with pre-computed `FRONTEND_PORT` and `BACKEND_PORT`), hook-driven per-branch `tracking.csv` issue tracking, and cross-machine or cloud dispatch.

- **Parallelize** when multiple independent GitHub issues need completion or a project's issues do not block each other.
- **With worktrees**: launch agents with `isolation: "worktree"`, each on its own feature branch off `origin/main`. Remove each worktree when its PR merges and run `/worktree-sweep` for orphans; a worktree an agent built in does not auto-remove.
- **With clones**: when a reserved case applies and a multi-clone setup exists (workspace model `~/code/{repo}-workspaces/`, flat model `~/code/{repo}-repos/`), point agents at different clone directories. Each claims its issue via the tracking CSV, auto-registered by hooks on branch creation. `~/.claude/multi-agent-system.md` has the coordination guide; `/workspace-setup {repo}` creates a workspace of four clones.
- **Issue tracking** uses `~/code/{log-repo-name}/{repo}/tracking.csv`, updated by hooks on branch creation, commits, PR creation, merge, and issue close.
- **Cap peak concurrency**: keep simultaneous heavy agents to 4 and launch in waves; the defaults, the 429 error, and the recovery procedure are in `subagent-patterns.md` under Concurrency and Rate Limits.

# Dev Server Port Allocation (Multi-Clone)

Each clone gets isolated ports so agents' dev servers never collide. Ports are assigned per repo in `~/.claude/port-registry.json` (a unique 16-port block per repo), and each clone's `.env.clone` carries its pre-computed `FRONTEND_PORT` and `BACKEND_PORT`. A PreToolUse hook (`~/.claude/hooks/port-check.py`) warns about mismatches and conflicts. Never run `pnpm dev` or `wrangler dev` in a multi-clone repo without the clone's ports:

```bash
FRONTEND_PORT=$(grep 'FRONTEND_PORT=' .env.clone | cut -d= -f2)
BACKEND_PORT=$(grep 'BACKEND_PORT=' .env.clone | cut -d= -f2)
pnpm dev -- --port ${FRONTEND_PORT}
```
