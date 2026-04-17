---
description: Generate a structured ONBOARDING.md for the current repo from a code inventory. Architecture, dev setup, key commands, test workflow, glossary. Always regenerates from scratch.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
argument-hint: [path] [--dry-run]
---

# /onboarding - Structured ONBOARDING.md Generator

Analyze the current repository and write `ONBOARDING.md` at the repo root. The file covers architecture, dev setup, key commands, test workflow, and a project glossary - sized for a new engineer (or a fresh Claude session) to get productive in under ten minutes.

Always regenerates from scratch. Never diffs against an existing ONBOARDING.md.

Follow the detailed instructions in `~/.claude/skills/onboarding/SKILL.md`. This command is the thin entry point; the skill holds the voice rules and the section contract.

---

## Phase 0: Parse Arguments

Extract from `$ARGUMENTS`:

- **Positional path** (optional): target repo root. Defaults to `$PWD`.
- **`--dry-run`**: print the generated markdown to stdout; do not write `ONBOARDING.md`.

If a path argument is present and is not a directory, stop and tell the user.

---

## Phase 1: Run the Inventory

Run the inventory script and capture the JSON output:

```bash
node ~/.claude/scripts/inventory.mjs "$TARGET_ROOT" --pretty
```

Read the returned JSON. If the script errors, or the output shows `languages: []` and `frameworks: []` and `scripts: {}`, STOP. Tell the user the repo looks too sparse for a meaningful onboarding doc and ask what they want covered instead.

Highlight inventory `notes[]` to the user if any are non-empty (for example "No README detected at repo root").

---

## Phase 2: Read What the Inventory Surfaces

Read only the files the inventory points at. The target set is:

- Every entry in `docs[]` (READMEs, architecture notes, CLAUDE.md, AGENTS.md, subdocs).
- The first one or two `entryPoints[]` that look like a human would start there.
- The `package.json` (or Cargo.toml / pyproject.toml / go.mod) for the scripts and dependency context already summarized in the inventory.
- The `envExample` file if present.

Do NOT glob the whole tree. Do NOT read lockfiles, generated output, node_modules, or .git.

For a monorepo, pick two or three representative workspace packages to sketch in Architecture. Do not enumerate every package.

---

## Phase 3: Write the Six Sections

Follow the section contract in the skill exactly. The output has six sections in this order:

1. **Overview** - one paragraph, three sentences max.
2. **Architecture** - concrete files and directories, ASCII diagram when two or more pieces interact.
3. **Dev Setup** - prerequisites, install, env (link to `.env.example`), first-run command.
4. **Key Commands** - short table of the commands a working engineer actually types.
5. **Test Workflow** - unit / integration / e2e layout, commands, pre-push expectation.
6. **Glossary** - five to fifteen project-specific terms, one sentence each.

Honor every voice rule from `~/.claude/skills/onboarding/SKILL.md`:

- Direct, no hedges, concrete over abstract.
- Match the formality of the existing `CLAUDE.md` / `README.md` tone.
- Never paste secrets, keys, or production URLs. Link to the env example.
- Link to existing docs instead of duplicating their content.
- No "Welcome!" preamble, no "That should get you started!" closer.

---

## Phase 4: Sanity Check

Before writing the file:

- [ ] Six sections present in the required order.
- [ ] No secrets or real URLs.
- [ ] No hedge words ("probably", "might", "should usually", "in most cases").
- [ ] File paths referenced exist in `entryPoints[]` or `docs[]` from the inventory.
- [ ] Under ~300 lines.
- [ ] Opens with `# Onboarding` or `# {name} Onboarding`, not "Welcome" or "This document...".

If any check fails, edit the draft before writing.

---

## Phase 5: Write or Print

If `--dry-run` was passed, print the markdown to stdout and stop.

Otherwise:

```bash
# Overwrite; regeneration is always from scratch.
# (Write tool, not bash heredoc - preserves exact content.)
```

Write the content to `${TARGET_ROOT}/ONBOARDING.md` using the Write tool.

Report to the user:

- File written (absolute path).
- Line count.
- Any inventory `notes[]` that were non-empty (gaps the user should know about).

Stop. Do not follow up with "Would you like me to..." - the file is the deliverable.
