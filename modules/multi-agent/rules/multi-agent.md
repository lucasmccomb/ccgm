# Parallel Work Preference

When a task involves multiple independent issues or work items, prefer spawning parallel agents in separate clones to complete them simultaneously. Use the Task tool to launch agents, each working in its own clone directory.

**When to parallelize:**
- Multiple independent GitHub issues need to be completed
- A project has issues that do not block each other
- The repo has a multi-clone setup (`~/code/{repo}-repos/` with multiple clones)

**How:** Launch Task agents pointed at different clone directories. Each agent claims its own issue via GitHub labels and works independently. See `~/.claude/multi-agent-system.md` for the full coordination guide.

---

# Dev Server Port Allocation (Multi-Clone)

**Each clone gets isolated ports to prevent collisions.** Ports are offset by clone number:

| Service | Formula | Clone 0 | Clone 1 | Clone 2 | Clone 3 |
|---------|---------|---------|---------|---------|---------|
| Frontend (Vite) | 5173 + N | 5173 | 5174 | 5175 | 5176 |
| Backend (Wrangler/API) | 8787 + N | 8787 | 8788 | 8789 | 8790 |

**How it works:**
- Each clone has a `.env.clone` file with `CLONE_NUMBER=N` (written during clone setup)
- Projects should configure `vite.config.ts` and dev scripts to read `.env.clone` and offset ports automatically
- If the project has not been configured yet, pass the port manually:
  ```bash
  CLONE_N=$(grep -oP 'CLONE_NUMBER=\K\d+' .env.clone 2>/dev/null || echo 0)
  pnpm dev -- --port $((5173 + CLONE_N))
  ```

**NEVER run `pnpm dev` or `wrangler dev` without clone-aware ports in a multi-clone repo.** Port collisions kill other agents' dev servers.

See `~/.claude/multi-agent-system.md` for full details on dev server port allocation.
