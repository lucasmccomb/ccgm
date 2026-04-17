# Onboarding Generator

Generates a structured `ONBOARDING.md` for any repository from a language-aware code inventory. Ships a thin `/onboarding` slash command, a skill with strict voice rules, and the inventory script the skill depends on.

The output is orientation for contributors (human or agent), not end-user documentation. Always regenerates from scratch.

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `commands/onboarding.md` | `commands/onboarding.md` | `/onboarding` slash command entry point |
| `skills/onboarding/SKILL.md` | `skills/onboarding/SKILL.md` | Voice rules, section contract, sanity checklist |
| `scripts/inventory.mjs` | `scripts/inventory.mjs` | Node script producing JSON inventory (languages, frameworks, entry points, scripts, docs, infra, monorepo) |

## The Output: ONBOARDING.md

Six sections, in this exact order:

1. **Overview** - one paragraph, three sentences max.
2. **Architecture** - concrete files and directories, ASCII diagram when two or more pieces interact.
3. **Dev Setup** - prerequisites, install, env (link to `.env.example`), first-run command.
4. **Key Commands** - short table of the commands a working engineer actually types.
5. **Test Workflow** - unit / integration / e2e layout, commands, pre-push expectation.
6. **Glossary** - five to fifteen project-specific terms, one sentence each.

## Voice Rules

The skill enforces a specific voice. Output should read like a knowledgeable teammate explaining the repo over coffee:

- **Direct**, no hedges ("probably", "might", "should usually" are banned).
- **Concrete over abstract** - name files and directories, not "the middleware layer".
- **Match codebase formality** - read `CLAUDE.md` / `README.md` first, mirror the tone.
- **Never include secrets** - link to `.env.example`, never paste values.
- **Link instead of duplicate** - if an answer lives in `docs/architecture.md`, point there.
- **No preamble** ("Welcome!") or filler close ("That should get you started!").

Full list in `skills/onboarding/SKILL.md`.

## Usage

```bash
/onboarding                    # Inventory the current repo, write ONBOARDING.md at the root
/onboarding --dry-run          # Print the markdown to stdout, do not write the file
/onboarding path/to/repo       # Inventory a specific path
```

You can also run the inventory script directly to inspect the JSON:

```bash
node ~/.claude/scripts/inventory.mjs . --pretty
```

## Stack Coverage

The inventory script detects:

- **Languages**: TypeScript, JavaScript, Python, Go, Rust, Ruby, Java, PHP, Swift, C/C++, Shell.
- **JS frameworks**: Vite, Webpack, Next.js, Nuxt, Remix, SvelteKit, Astro, Angular, React, Vue, Svelte, Solid.
- **Styling / UI**: Tailwind, styled-components.
- **Backend / runtimes**: Express, Fastify, Hono, Cloudflare Workers.
- **Testing**: Vitest, Jest, Playwright, Cypress, pytest, RSpec, `go test`, `cargo test`.
- **Chrome extensions**: detects `manifest.json` with MV2/MV3 structure, surfaces background / content / popup / options entry points.
- **Monorepos**: npm/pnpm/yarn workspaces, turborepo, nx, lerna.
- **Package managers**: pnpm, npm, yarn, bun, poetry, pipenv, cargo, bundler.
- **Infrastructure**: Docker, docker-compose, Cloudflare Workers, Vercel, Netlify, GitHub Actions, CircleCI, Fly.io, Render, Heroku, Supabase, Terraform, Husky.

The script is bounded (depth 4, ignores `node_modules`, `.git`, `dist`, build output, caches). It never reads file contents beyond the manifests and config files it explicitly opens.

## Manual Installation

```bash
mkdir -p ~/.claude/commands
mkdir -p ~/.claude/skills/onboarding
mkdir -p ~/.claude/scripts

cp modules/onboarding/commands/onboarding.md \
   ~/.claude/commands/onboarding.md

cp modules/onboarding/skills/onboarding/SKILL.md \
   ~/.claude/skills/onboarding/SKILL.md

cp modules/onboarding/scripts/inventory.mjs \
   ~/.claude/scripts/inventory.mjs
```

Requires `node` on `$PATH`. No other dependencies.

## Design Notes

- **Always regenerates from scratch.** No diffing against a prior `ONBOARDING.md`. Regeneration keeps the voice consistent and avoids fossilized claims that survive a refactor.
- **Inventory first, then read.** The skill reads only the files the inventory surfaces - entry points, top-level docs, env example. It never globs the whole tree, never reads lockfiles, never opens `node_modules`.
- **Separation of concerns.** The command is a thin argument parser and runner. The skill holds the voice rules and section contract. The inventory script is pure structural analysis with no prose logic.
- **No overlap with `/docupdate`.** `/docupdate` audits existing documentation for drift. `/onboarding` writes a single new file from scratch. They are complementary.

## Source

Pattern adapted from EveryInc's compound-engineering plugin (`skills/onboarding/SKILL.md`, `skills/onboarding/scripts/inventory.mjs`). The original is Ruby-aware; this implementation adds explicit support for Vite, Next.js, Chrome extensions, and monorepo tooling (turborepo, nx, pnpm workspaces) that appear across the portfolio.
