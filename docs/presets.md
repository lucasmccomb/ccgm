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

**Modules (8)**:
- Everything in **minimal**, plus:
- `identity` - two foundational context files: soul.md and human-context.md
- `settings` - base `settings.json` with 800+ pre-configured tool permissions
- `hooks` - Python hooks for workflow enforcement (branch protection, commit format, auto-approval)
- `commands-core` - essential slash commands (`/commit`, `/pr`, `/cpm`, `/gs`, `/ghi`)
- `commands-utility` - utility commands (`/cws-submit`, `/ccgm-sync`, `/user-test`)

**What you get**: Rules, identity context, hooks, commands, and a permissions configuration that lets Claude operate effectively while keeping guardrails on destructive operations.

### team

**Best for**: Teams with shared repositories who want consistent practices across contributors.

**Modules (10)**:
- Everything in **standard** (minus `identity` and `commands-utility`), plus:
- `github-protocols` - issue-first workflow, PR conventions, label taxonomy, code review standards
- `code-quality` - code standards, testing requirements, error handling, security, build verification
- `systematic-debugging` - structured 4-phase debugging methodology
- `verification` - evidence-before-claims, fresh execution requirement

**What you get**: Everything in standard (with a team-focused selection), plus rules that enforce consistent development practices across a team.

### full

**Best for**: Power users who want the complete CCGM experience, including multi-agent coordination, brand research, and tech-specific guides.

**Modules (35)**: All modules.

**What you get**: The full suite. Includes multi-agent workflows, planning frameworks, tech-specific patterns (Cloudflare, Supabase, Tailwind, shadcn, MCP development), and specialized commands.

## Dependency resolution

When you select a module that depends on other modules, the installer automatically includes the dependencies. For example:

- Selecting `xplan` automatically adds `multi-agent` and `session-logging`
- Selecting `hooks` automatically adds `settings`

You don't need to manually track dependencies. The installer resolves them using topological sorting and reports any additions.

## Using presets from the command line

```bash
./start.sh --preset minimal
./start.sh --preset standard
./start.sh --preset full
./start.sh --preset team
```

Combine with scope and link flags:

```bash
./start.sh --preset standard --scope global
./start.sh --preset full --link
```

## Custom module selection

If none of the presets match your needs, the installer offers a checkbox-style menu where you can select individual modules. This is the default when no `--preset` flag is provided.
