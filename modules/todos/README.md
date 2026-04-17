# Todos

File-based review-finding tracker. Review findings, PR nitpicks, and tech debt that does not warrant a full GitHub issue go to `.claude/todos/NNN-{status}-{priority}-{slug}.md` in the repo being worked on.

## Why

CCGM already has two coordination surfaces:

| Surface | Scope | Commit to repo? |
|---|---|---|
| GitHub Issues + tracking.csv | cross-session, cross-agent, user-triaged work | no (GitHub + log repo) |
| `self-improving` / `compound-knowledge` | durable learnings and patterns | yes (per-repo and personal) |

Neither fits a p3 nitpick a reviewer leaves on line 42 of a PR. An issue is heavyweight. A learning is the wrong type. The item still deserves to be written down somewhere, or it gets lost between "review found it" and "cut an issue."

`todos` fills that gap. It is deliberately lightweight - three skills, a filename convention, a small frontmatter schema. No hooks, no hidden state, no external service.

## File Layout

```
.claude/todos/
  README.md                                    # per-repo convention reminder
  001-pending-p2-extract-auth-middleware.md    # freshly captured
  002-ready-p3-rename-foo-to-bar.md            # triaged, scoped, ready to fix
  003-complete-p1-fix-null-pointer.md          # done, kept for history
  .runs/                                       # optional autofix run artifacts
    20260416-1430.md
```

Filename encodes status and priority so a bare `ls` gives a visual scan without reading each file. Status changes rename the file in place.

See `skills/todo-create/references/schema.yaml` for the full frontmatter schema.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/todo-create/SKILL.md` | `skills/todo-create/SKILL.md` | `/todo-create` - canonical writer |
| `skills/todo-create/references/schema.yaml` | `skills/todo-create/references/schema.yaml` | YAML schema for frontmatter |
| `skills/todo-triage/SKILL.md` | `skills/todo-triage/SKILL.md` | `/todo-triage` - pending -> ready |
| `skills/todo-resolve/SKILL.md` | `skills/todo-resolve/SKILL.md` | `/todo-resolve` - batch-fix ready todos |

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/skills/todo-create/references
mkdir -p ~/.claude/skills/todo-triage
mkdir -p ~/.claude/skills/todo-resolve

cp modules/todos/skills/todo-create/SKILL.md \
   ~/.claude/skills/todo-create/SKILL.md

cp modules/todos/skills/todo-create/references/schema.yaml \
   ~/.claude/skills/todo-create/references/schema.yaml

cp modules/todos/skills/todo-triage/SKILL.md \
   ~/.claude/skills/todo-triage/SKILL.md

cp modules/todos/skills/todo-resolve/SKILL.md \
   ~/.claude/skills/todo-resolve/SKILL.md
```

## Per-Repo Bootstrap

`todos` writes to the repo being worked on, not CCGM or `~/.claude/`. Each consuming repo needs a small one-time setup:

1. `.claude/todos/` - the skill creates this on first use.
2. `.claude/todos/README.md` - the skill writes this on first use, explaining the convention.
3. A pointer block in the repo's `AGENTS.md` or `CLAUDE.md`:

   ```markdown
   ## Todos

   Review findings and PR nitpicks that do not warrant a GitHub issue live in
   `.claude/todos/` as `NNN-{status}-{priority}-{slug}.md` files. Run
   `/todo-triage` to promote pending todos to ready; run `/todo-resolve` to
   batch-fix ready todos.
   ```

The `/todo-create` skill runs a Discoverability Check on first use and offers to add the pointer and README if missing. Pre-seeding is optional.

## Usage

### Capture a finding

```
/todo-create extract the auth middleware out of the request handler, p2
/todo-create
```

With arguments, writes the todo directly. With no arguments, uses the most recent review finding or PR comment visible in the conversation.

### Triage the pending list

```
/todo-triage
/todo-triage mode:autofix
/todo-triage mode:report-only
```

Walks each pending todo and asks confirm / skip / modify / drop. Confirmed todos get a Proposed Change section and move to ready. `mode:autofix` only promotes todos with already-concrete bodies; vague ones stay pending.

### Batch-resolve ready todos

```
/todo-resolve
/todo-resolve priority:p3
/todo-resolve only:7,12,19
/todo-resolve mode:autofix
/todo-resolve mode:report-only
```

Dispatches parallel subagents, one per ready todo, with pass-paths-not-contents. Applies fixes, updates status to complete, posts inline PR replies for PR-sourced todos, and prints a run summary. Skips todos whose dependencies are not complete.

## Composition With Other CCGM Skills

`todo-create` is the canonical writer. Other skills invoke it rather than duplicating the filename and frontmatter rules:

- `ce-review` (future) - for each finding not fixed inline during review, call `/todo-create` instead of writing its own file.
- `resolve-pr-feedback` (future, CCGM #283) - for each PR comment that cannot be fixed in the same pass, call `/todo-create` with `source: pr-comment`.
- `/xplan` - for future-work items surfaced during planning that are not scope for the current plan.

All three resolver-style skills (`/todo-resolve`, `ce-review`, `/xplan`) share the pass-paths-not-contents dispatch and four-state subagent return contract documented in `modules/subagent-patterns/rules/subagent-patterns.md`.

## Dependencies

- `skill-authoring` - all three skills follow the skill-authoring discipline (reference files via backticks, imperative voice, mode token parsing, etc.)
- `subagent-patterns` - `/todo-resolve` uses the pass-paths-not-contents dispatch pattern and the four-state status protocol

No runtime dependencies beyond the module system.

## Non-Goals

This module does **not**:

- Replace GitHub Issues. Issues stay the source of truth for multi-session, cross-agent work.
- Replace `compound-knowledge`. Todos are short-lived work items; `docs/solutions/` is durable team knowledge.
- Ship a TUI or web UI. `ls .claude/todos/` and your editor are the UI.
- Install `.claude/todos/` in any repo. The skill bootstraps per-repo on first use.

## Source

Ported from EveryInc/compound-engineering-plugin (`skills/todo-create`, `skills/todo-triage`, `skills/todo-resolve`). The original ships under `.context/compound-engineering/todos/`; CCGM adopts the same three-skill structure at `.claude/todos/` to match CCGM's directory conventions.

Adaptations from the source:

- Directory path: `.claude/todos/` instead of `.context/compound-engineering/todos/`
- Mode token names match the CCGM skill-authoring convention (`mode:interactive`, `mode:autofix`, `mode:report-only`, `mode:headless`)
- Frontmatter schema is extracted to `skills/todo-create/references/schema.yaml` so the skill body does not carry it in every invocation
- `/todo-resolve` dispatch uses the pass-paths-not-contents pattern and the four-state subagent return contract (`DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, `NEEDS_CONTEXT`) from `modules/subagent-patterns`
