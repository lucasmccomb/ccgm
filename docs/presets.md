# Presets

Presets are named collections of modules for quick installation. Each preset is a JSON array in the `presets/` directory listing module names.

## Available presets

### minimal

**Best for**: Trying CCGM for the first time, or environments where you want light-touch guidance with no hooks or settings changes.

**Modules (3)**:
- `global-claude-md` - slim root config reference pointing to rules, commands, hooks, and settings
- `autonomy` - configures Claude as a fully autonomous engineer
- `git-workflow` - git conventions (sync, rebase, no AI attribution)

**What you get**: Three behavior rule files in `rules/` plus a root CLAUDE.md reference. No hooks, no commands, no settings.json changes.

### standard

**Best for**: Most individual developers. The recommended starting point.

**Modules (14)**:
- Everything in **minimal**, plus:
- `identity` - two foundational context files: soul.md and human-context.md
- `settings` - base `settings.json` with 800+ pre-configured tool permissions
- `hooks` - Python hooks for workflow enforcement (branch protection, commit format, auto-approval)
- `branch-guard` - hard PreToolUse gate: no edits or git mutations while HEAD is on the default branch
- `model-vetting` - security vetting gate for new AI models before they touch the harness
- `statusline` - custom status line for Claude Code sessions
- `commands-core` - essential slash commands (`/commit`, `/pr`, `/cpm`, `/gs`, `/ghi`)
- `commands-utility` - utility commands (`/cws-submit`, `/ccgm-sync`, `/user-test`)
- `self-improving` - reflection loop and learnings store (`/reflect`, `/consolidate`)
- `output-formatting` - copy-pasteable content goes in fenced code blocks, never blockquotes
- `writing-system` - Orwell's six rules as the prose standard, plus `/rewrite`

**What you get**: Rules, identity context, hooks, commands, and a permissions configuration that lets Claude operate effectively while keeping guardrails on destructive operations.

### team

**Best for**: Teams with shared repositories who want consistent practices across contributors.

**Modules (21)**:
- Everything in **standard** (minus `identity`, `commands-utility`, `model-vetting`, `self-improving`, and `statusline`), plus:
- `github-protocols` - issue-first workflow, PR conventions, label taxonomy, code review standards
- `code-quality` - code standards, testing requirements, error handling, security, build verification
- `systematic-debugging` - structured 4-phase debugging methodology
- `verification` - evidence-before-claims, fresh execution requirement
- `autoheal` - continuous self-improvement loop with multi-recipient digest support
- `ce-review`, `pr-feedback`, `document-review`, `compound-knowledge` - shared review skills and a team knowledge store (with their dependencies `pr-review-toolkit`, `skill-authoring`, `subagent-patterns`)

**What you get**: Everything in standard (with a team-focused selection), plus rules and review skills that enforce consistent development practices across a team. The autoheal module's multi-recipient digest (`digest_email: ["a@b", "c@d"]`) is particularly useful for sharing weekly insights with teammates.

### full

**Best for**: Power users who want the complete CCGM experience, including multi-agent coordination, brand research, and tech-specific guides.

**Modules (71)**: Every stable module — `full` is defined as the set of all modules whose `module.json` status is not `beta` or `deprecated`. This includes **autoheal** (continuous self-improvement; opt-in real-time alerts and auto-apply) and `cloud-dispatch`. The only modules omitted are the beta ones (`plugin-marketplace`, `relevance-injection`, `dreaming`) and the deprecated `agent-manager`; install those individually via the module selector if you need them.

**What you get**: The full suite. Includes multi-agent workflows, planning frameworks, tech-specific patterns (Cloudflare, Supabase, Tailwind, shadcn, MCP development), specialized commands, and the autoheal observability loop with three opt-in toggles (`/autoheal-toggle realtime|autoapply|webhook`).

### cloud-agent

**Best for**: Running CCGM on headless cloud VMs that dispatch parallel agents to work on GitHub issues. Includes the `cloud-dispatch` orchestration module plus the review and authoring skills agents lean on most.

**Modules (54)**: Curated for headless cloud agents — a headless-oriented selection drawn from the stable module set, including `cloud-dispatch` (Hetzner Cloud VM provisioning for parallel GitHub-issue work) and persona-relevant skills (`ce-review`, `pr-feedback`, `document-review`, `skill-authoring`, `rule-authoring`, `agent-native`, `git-worktrees`, `ship-readiness`, with their dependencies). The deprecated `agent-manager` (tmux-based dashboard) is not included; install it individually if you still need it.

**What you get**: The cloud-agent preset with cloud-dispatch commands (`/dispatch`, `/dispatch-status`, `/dispatch-stop`, `/vm-manage`). Intended for machines that provision cloud VMs and launch autonomous agents, not day-to-day laptop use.

## Dependency resolution

When you select a module that depends on other modules, the installer automatically includes the dependencies. For example:

- Selecting `xplan` automatically adds `multi-agent` and `adversarial-review`, plus their dependencies `startup-dashboard` and `subagent-patterns`
- Selecting `hooks` automatically adds `settings`

You don't need to manually track dependencies. The installer resolves them using topological sorting and reports any additions.

## Using presets from the command line

```bash
./start.sh --preset minimal
./start.sh --preset standard
./start.sh --preset full
./start.sh --preset team
./start.sh --preset cloud-agent
```

Combine with scope and link flags:

```bash
./start.sh --preset standard --scope global
./start.sh --preset full --link
```

## Custom module selection

If none of the presets match your needs, the installer offers a checkbox-style menu where you can select individual modules. This is the default when no `--preset` flag is provided.
