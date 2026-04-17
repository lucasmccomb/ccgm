# Agent-Native Architecture

Principles and tooling for designing applications where an LLM agent is a first-class user. Ship it when you are building or auditing a product that an agent will drive on behalf of a human.

The module installs three things: a rule file with the four principles, a `/agent-native-audit` skill that scores a codebase against them, and a reviewer persona for the unified review orchestrator (CCGM #277).

## The Four Principles

1. **Parity** - Whatever the user can do in the UI, the agent can do via a tool.
2. **Granularity** - Prefer atomic primitives. Features are outcomes achieved by an agent composing primitives in a loop.
3. **Composability** - New features become new prompts, not new code.
4. **Emergent Capability** - The agent accomplishes things the product team did not explicitly design for.

Full discussion with design-time guidance, runtime guidance, anti-patterns, and scope guidance in `rules/agent-native.md`.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `rules/agent-native.md` | `rules/agent-native.md` | Four principles with one section each plus design, runtime, and audit guidance |
| `skills/agent-native-audit/SKILL.md` | `skills/agent-native-audit/SKILL.md` | `/agent-native-audit` - score a codebase with specific counts and concrete fixes |
| `agents/reviewers/agent-native-reviewer.md` | `agents/reviewers/agent-native-reviewer.md` | Reviewer persona for `/ce-review` and standalone diff review |

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/rules
mkdir -p ~/.claude/skills/agent-native-audit
mkdir -p ~/.claude/agents/reviewers

cp modules/agent-native/rules/agent-native.md \
   ~/.claude/rules/agent-native.md

cp modules/agent-native/skills/agent-native-audit/SKILL.md \
   ~/.claude/skills/agent-native-audit/SKILL.md

cp modules/agent-native/agents/reviewers/agent-native-reviewer.md \
   ~/.claude/agents/reviewers/agent-native-reviewer.md
```

## Usage

### Audit a codebase

```
/agent-native-audit
/agent-native-audit apps/web
/agent-native-audit focus:parity
/agent-native-audit mode:report-only
/agent-native-audit mode:headless
```

The skill dispatches eight parallel subagents - two per principle, one measuring and one critiquing. It returns a scorecard out of 100 with bands (absent / emerging / solid / exemplary), a Top-5 Findings section with file:line evidence, and probe prompts that surface whether emergent capability exists.

Full mode writes the report to `.agent-native-audit/{timestamp}.md` so you can diff future runs. Report-only mode writes nothing. Headless mode returns a structured JSON envelope for skill-to-skill invocation.

### Review a diff

Dispatch the `agent-native-reviewer` agent directly, or invoke it as one lens inside the unified review orchestrator (CCGM #277):

```
Dispatch agent-native-reviewer with:
- diff: <unified diff or file list>
- repo_path: <absolute path>
- focus: parity | granularity | composability | emergent | all
```

The reviewer returns a structured critique with a verdict (approve / approve-with-concerns / request-changes), principle-level deltas versus a prior audit if provided, and a Findings list with file:line evidence and suggested changes.

### Use the rule as design guidance

Reference `rules/agent-native.md` when writing a system prompt for an AI assistant layer, when RFC-ing a new product surface, or when sketching the tool signature for a new feature. The design-time, runtime, and anti-patterns sections are structured for that use.

## Dependencies

- `subagent-patterns` - the audit skill uses the pass-paths-not-contents pattern and the mode token convention from `modules/subagent-patterns/rules/subagent-patterns.md`.

No runtime dependencies beyond the module system.

## Non-Goals

This module does **not**:

- Ship a reference agent-native application. The rules and audit target existing codebases.
- Auto-fix violations. The audit produces findings and proposed PRs; humans decide which to land.
- Replace general code review. Parity, granularity, composability, and emergent capability are one lens among many (security, tests, prose, accessibility). The reviewer persona is scoped to this lens only.
- Wire itself into `/ce-review`. The reviewer persona is available; the orchestrator invocation is tracked in CCGM #277.

## Source

Adapted from EveryInc/compound-engineering-plugin. The original ships `skills/agent-native-architecture/SKILL.md` (principle doc as a skill), `skills/agent-native-audit/SKILL.md`, and `agents/review/agent-native-reviewer.md` as part of a larger review orchestrator.

Adaptations from the source:

- The principle document is a rule file (installs to `~/.claude/rules/`) rather than a skill, so other rules and commands can reference it without invoking a skill.
- The audit skill uses the CCGM mode token convention (`mode:full`, `mode:report-only`, `mode:headless`) and the pass-paths-not-contents subagent dispatch pattern.
- The reviewer persona lives under `agents/reviewers/` per the `agents/` convention added in CCGM #273, so the unified review orchestrator (CCGM #277) can discover it.
- The fan-out is eight agents (two per principle - one measures, one critiques) rather than four, matching the density of evidence each principle needs.
