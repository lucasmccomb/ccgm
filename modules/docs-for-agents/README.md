# docs-for-agents

Rule and template for shipping machine-readable docs alongside human docs. Any project an agent will install, build, test, deploy, or debug should have an `AGENTS.md` with copy-pasteable command blocks.

The rule enforces what Karpathy called out in the Sequoia vibe-coding interview: docs written for humans tell an agent what to do in prose. Docs written for agents give the agent one command to run. `AGENTS.md` is the agent-readable contract.

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `rules/docs-for-agents.md` | `~/.claude/rules/docs-for-agents.md` | When to ship AGENTS.md, what it contains, format conventions, anti-patterns |
| `templates/AGENTS.md` | (use in your project) | Skeleton with labeled sections and example commands |

The rule file is installed globally so Claude applies it to every project. The template is a copy-paste starting point — it is not installed anywhere automatically.

## Manual Installation

```bash
# From the CCGM repo root:
mkdir -p ~/.claude/rules
cp modules/docs-for-agents/rules/docs-for-agents.md ~/.claude/rules/docs-for-agents.md
```

To start an `AGENTS.md` in a project:

```bash
cp modules/docs-for-agents/templates/AGENTS.md /path/to/your/project/AGENTS.md
# Edit to replace example commands with the real ones for your project
```

## Usage

Once the rule is installed, Claude will:

- Prompt you to create `AGENTS.md` when starting work on a project that does not have one and that an agent would reasonably need to operate
- Enforce the labeled-block format (Install, Build, Test, Deploy, Debug) when authoring or reviewing `AGENTS.md`
- Flag anti-patterns: dashboard navigation instructions, missing env vars, vague debug steps

To author an `AGENTS.md` from scratch, copy the template and fill in the labeled sections with the real commands for your project. Remove the comment blocks before committing.

## What AGENTS.md Is Not

- Not a replacement for `README.md` — README explains what the project is; AGENTS.md tells the agent how to operate it
- Not a replacement for `CLAUDE.md` — CLAUDE.md carries repo conventions and workflow rules; AGENTS.md carries operational commands
- Not a changelog or a design doc — one command per operation, nothing more

See `rules/docs-for-agents.md` for the full distinction table and format rules.
