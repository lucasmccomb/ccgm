---
name: onboarding
description: >
  Generate a structured ONBOARDING.md for the current repository. Runs an inventory script to build a language-aware structural map (languages, frameworks, entry points, scripts, docs, infrastructure, monorepo layout), reads only the files the inventory surfaces, then writes prose that reads like a knowledgeable teammate over coffee - not generated documentation. Always regenerates from scratch; no diffing against the previous file.
  Triggers: onboarding doc, write ONBOARDING.md, generate project onboarding, new engineer guide, fresh session primer.
---

# onboarding - Structured ONBOARDING.md Generator

Produce a single file at the repo root: `ONBOARDING.md`. The file is the deliverable. The skill does not modify any other documentation.

## When to Run

- A new engineer (or a fresh Claude session) will read this repo for the first time.
- The repo has grown enough that `README.md` alone no longer answers "how do I ship a change here today?"
- The project just crossed a refactor boundary and the old onboarding notes are stale.
- The user asks for "the five-minute tour" or an orientation doc.

Do NOT run for:

- Single-file utilities, one-off scripts, or projects without a meaningful internal structure.
- Private forks of well-documented upstreams (point the user at the upstream docs instead).
- Monorepo workspaces that already have per-package READMEs covering the same ground.

## Phase 0: Run the Inventory

Always start with the inventory script. It is cheap and the writer depends on its output.

```bash
node ~/.claude/scripts/inventory.mjs "$PWD" --pretty
```

If the command errors or returns a shallow inventory (no languages, no frameworks, no scripts), STOP and ask the user what kind of repo this is. Do not guess. A wrong onboarding doc is worse than no onboarding doc.

The inventory JSON contains:

- `name`, `description`, `languages`, `frameworks`, `packageManager`
- `monorepo` (isMonorepo, tool, workspaces)
- `entryPoints` (web, node-main, bin, ext-background, ext-content, python, go, rust)
- `scripts` (package.json scripts plus Makefile targets)
- `docs` (README, CLAUDE.md, docs/*, ARCHITECTURE.md, etc.)
- `infrastructure` (docker, cloudflare-workers, github-actions, husky, ...)
- `testRunners`, `envExample`, `topLevelDirs`, `notes`

## Phase 1: Read Only What the Inventory Surfaces

Read the specific files the inventory points at:

- Every doc in `docs[]` (they often already contain the answer; link, do not duplicate).
- `package.json` (or equivalent manifest) for the `scripts` and dependency context.
- `CLAUDE.md` and/or `AGENTS.md` at the repo root (the tone and project conventions live there).
- One or two entry points so architecture claims are grounded in real code.
- The env example file if present (for the "Setup" section).

Do NOT glob-read every source file. Do NOT read lockfiles. Do NOT read generated build output.

If the inventory lists a monorepo, pick the two or three workspace packages that look like the primary entry points (by scripts, entry points, or dependency surface) and sketch them. Do not enumerate every package.

## Phase 2: Write ONBOARDING.md

Always regenerate from scratch. Never diff against a prior ONBOARDING.md - regeneration keeps the voice consistent and avoids fossilized claims. If a prior ONBOARDING.md exists, overwrite it.

The output has six sections in this exact order:

1. **Overview** - one paragraph: what this repo is, who uses it, what it ships. Three sentences maximum.
2. **Architecture** - key components and how they connect. Use a small ASCII diagram when more than two pieces interact. Name concrete files and directories.
3. **Dev Setup** - prerequisites (languages, runtime versions), install command, env vars (link to `.env.example` - never paste values), first-run command.
4. **Key Commands** - a short table of the scripts a working engineer actually types. Trim noise (leave out `postinstall`, `prepare`, `lint:fix` unless meaningful). If a command has an obvious gotcha, note it in one clause.
5. **Test Workflow** - how tests are organized (unit / integration / e2e), how to run each tier, what counts as "tests pass before push."
6. **Glossary** - five to fifteen project-specific terms. Definitions in one sentence each. No generic terminology (do not define "TypeScript"). Lucas-specific portfolio terms like `clone`, `workspace`, `agent-id` go here when the repo uses them.

Link to files with relative paths. Use `file.ts:42` when pointing at a specific line.

## Voice Rules

These are non-negotiable. The output should read like a knowledgeable teammate explaining the repo over coffee.

- **Direct**: "Run `npm run dev`" not "You can run `npm run dev` to start the development server."
- **Cut hedges**: no "probably", "might", "should", "in most cases." If the claim needs a hedge, it is not confident enough to include.
- **Concrete over abstract**: "The auth middleware sets `req.user` from the JWT in `Authorization`" not "Authentication is handled by the middleware layer."
- **Match codebase formality**: if `CLAUDE.md` is terse and jokey, match it. If it is formal, match that. Read the existing tone before writing.
- **Never include secrets**: no example keys, no sample tokens, no production URLs. Link to `.env.example` and move on.
- **Link instead of duplicate**: if the answer lives in `docs/architecture.md`, point there. The goal is orientation, not a second copy of the docs.
- **No preamble**: the file opens with `# Onboarding` (or `# {name} Onboarding`) and goes straight to the Overview. No "Welcome!" No "This document will help you..."
- **No filler summaries**: do not close with "That should get you started!" End on the last useful sentence.

## Anti-Patterns to Refuse

Refuse to produce output in these shapes, even if the user asks. Say what you are doing differently and continue.

- A bulleted list of every file in the repo. Onboarding is orientation, not inventory.
- A rewrite of the README. If the README covers the answer, link to it.
- Step-by-step tutorials for how to use the product. Onboarding is for contributors, not end users.
- Marketing prose ("our cutting-edge platform"). This is an internal doc for engineers.
- Duplicate `.env` values. Ever. Link to the example file.

## Phase 3: Sanity Check

After writing, re-read the file once before finalizing:

- [ ] Every section is present in the required order.
- [ ] No secrets, keys, or real URLs appear.
- [ ] No hedges slipped in ("probably", "might", "should usually").
- [ ] Every file path referenced actually exists (cross-check against inventory `docs[]` / `entryPoints[]`).
- [ ] The doc is under ~300 lines. If longer, cut the Architecture diagram or the Glossary.
- [ ] Opening sentence does not start with "Welcome" or "This document."

Then write to `ONBOARDING.md` at the repo root. Report file path and line count. Done.

## Notes for the Calling Agent

- The skill is idempotent. Running it twice regenerates the same shape.
- The inventory script is deliberately bounded (depth 4, ignores build output). For a very large monorepo (dozens of workspaces), let the inventory finish, then pick a small, interesting subset rather than re-expanding the scan.
- If the user wants a preview, pass `--dry-run` to the containing command - the skill prints the draft to stdout and skips the write.
