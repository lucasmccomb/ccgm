# CE Review Orchestrator

A unified code-review skill that composes CCGM's review surface into one structured pipeline. Dispatches tiered reviewer personas (correctness, testing, maintainability, project-standards plus conditional security, performance, reliability, api-contract, data-migrations) in parallel, runs an adversarial/red-team lens AFTER the specialists with access to their findings, and routes the merged findings by a confidence score and an `autofix_class` (`safe_auto` / `gated_auto` / `manual` / `advisory`).

## Why This Exists

CCGM already has four review entry points:

- Claude Code's built-in `/review`
- `code-review:code-review` (external plugin)
- `pr-review-toolkit:review-pr` (external plugin)
- `/security-review`

None of them compose. None have confidence gating, severity-based autofix routing, or a structured JSON merge. None include an adversarial lens that reads other reviewers' output. `/ce-review` is the one pipeline that pulls prior learnings, runs scope-drift first, fans out tiered reviewers, closes with a red-team pass, and emits Fix-First output with a machine-parseable envelope.

The legacy entry points remain installed. Use them when the stakes are low or when you specifically want one lens. Use `/ce-review` when the PR is non-trivial, cross-cutting, or high-risk.

## What This Module Provides

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/ce-review/SKILL.md` | `skills/ce-review/SKILL.md` | `/ce-review` - orchestrator skill |
| `skills/ce-review/references/finding.schema.yaml` | `skills/ce-review/references/finding.schema.yaml` | JSON schema every reviewer returns |
| `agents/reviewers/correctness-reviewer.md` | `agents/reviewers/correctness-reviewer.md` | Logic errors, off-by-ones, control-flow |
| `agents/reviewers/testing-reviewer.md` | `agents/reviewers/testing-reviewer.md` | Missing tests, flaky patterns, over-mocking |
| `agents/reviewers/maintainability-reviewer.md` | `agents/reviewers/maintainability-reviewer.md` | Duplication, naming, complexity |
| `agents/reviewers/project-standards-reviewer.md` | `agents/reviewers/project-standards-reviewer.md` | Conformance to repo conventions |
| `agents/reviewers/security-reviewer.md` | `agents/reviewers/security-reviewer.md` | Auth, injection, secrets, RLS (conditional) |
| `agents/reviewers/performance-reviewer.md` | `agents/reviewers/performance-reviewer.md` | N+1, complexity, bundle, memoization (conditional) |
| `agents/reviewers/reliability-reviewer.md` | `agents/reviewers/reliability-reviewer.md` | Retries, timeouts, idempotency, recovery (conditional) |
| `agents/reviewers/api-contract-reviewer.md` | `agents/reviewers/api-contract-reviewer.md` | Breaking route / type / schema changes (conditional) |
| `agents/reviewers/data-migrations-reviewer.md` | `agents/reviewers/data-migrations-reviewer.md` | Reserved keywords, RLS, unsafe backfills (conditional) |
| `agents/reviewers/adversarial-reviewer.md` | `agents/reviewers/adversarial-reviewer.md` | Red-team lens, runs last, reads other findings |

## The Pipeline

1. **Phase 0 - Inputs**: collect diff, PR body, commit messages, issue body
2. **Phase 1 - Priors**: dispatch `learnings-researcher` (from `compound-knowledge`) with the diff summary; include returned blocks as grounding for every downstream reviewer
3. **Phase 2 - Scope-drift**: invoke the `scope-drift` skill (from `pr-review-toolkit`); in interactive mode, a HIGH gating "block" stops the pipeline
4. **Phase 3 - Tiered fan-out**: dispatch always-on reviewers in parallel, plus conditional reviewers selected from the diff content
5. **Phase 4 - Adversarial**: dispatch `adversarial-reviewer` with every Phase 3 reviewer's output; five lenses (attack happy path, silent failures, trust assumptions, edge cases, integration boundaries)
6. **Phase 5 - Merge / Dedupe / Route**: confidence-gate at 0.50, dedupe on `(file, line ±3, category)`, route by `autofix_class`
7. **Phase 6 - Output**: Fix-First format (AUTO-FIXED / NEEDS INPUT / RED-TEAM LENS), plus a full JSON envelope at `.context/ce-review/{timestamp}-{base}-{head}.json`

## Modes

`/ce-review mode:{interactive|autofix|report-only|headless}`

| Mode | Asks question? | Applies fixes? | Writes envelope? | Stdout |
|------|----------------|----------------|------------------|--------|
| `interactive` (default) | Yes, one batched | `safe_auto` applied | Yes | Full Summary |
| `autofix` | No | `safe_auto` applied; `gated_auto` -> todo | Yes | Full Summary |
| `report-only` | No | No | Yes | Full Summary |
| `headless` | No | No | Yes | Envelope path + `Review complete.` |

## Confidence and Severity

Every reviewer prompt enforces the same calibration:

- **Confidence**: HIGH >= 0.80, MODERATE 0.60-0.79, LOW 0.50-0.59 (surfaced only for safety-critical categories), SUPPRESSED < 0.50
- **Severity**: P0 (blocking), P1 (must fix), P2 (should fix), P3 (nice to fix)
- **Orthogonal**: a P0 finding at confidence 0.55 is still suppressed - you cannot block a merge on a suspicion

## Autofix Classes

- `safe_auto` - applied in interactive and autofix modes; mechanical, one correct fix, no behavior change
- `gated_auto` - batched into NEEDS INPUT in interactive mode; listed as a todo in autofix mode
- `manual` - no auto-fix; reported with a recommended direction
- `advisory` - informational only

Hard ceiling: scope-drift and adversarial findings are at most `gated_auto`. Never `safe_auto`.

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/skills/ce-review/references
mkdir -p ~/.claude/agents/reviewers

cp modules/ce-review/skills/ce-review/SKILL.md \
   ~/.claude/skills/ce-review/SKILL.md

cp modules/ce-review/skills/ce-review/references/finding.schema.yaml \
   ~/.claude/skills/ce-review/references/finding.schema.yaml

cp modules/ce-review/agents/reviewers/*.md \
   ~/.claude/agents/reviewers/
```

Requires the `compound-knowledge` and `pr-review-toolkit` modules to be installed for the full pipeline. If they are not present, the orchestrator skips Phase 1 (priors) and runs an inline 10-item scope check in place of Phase 2.

## Dependencies

- **`compound-knowledge`** - supplies the `learnings-researcher` agent used in Phase 1. If absent, Phase 1 is a no-op.
- **`pr-review-toolkit`** - supplies the `scope-drift` skill used in Phase 2 and the `fix-first-review` rule used in Phase 6. If absent, a degraded in-line path is used.
- **`subagent-patterns`** - supplies the pass-paths-not-contents dispatch pattern used throughout.

## Relationship to Legacy Review Commands

The legacy entry points remain installed and functional:

- `/review` (Claude Code built-in) - quick single-pass review
- `code-review:code-review` - plugin specialist agents, no orchestration
- `pr-review-toolkit:review-pr` - plugin specialist agents, scope-drift + Fix-First format via the `pr-review-toolkit` CCGM module
- `/security-review` - security-only pass

Use the legacy commands for narrow or low-stakes reviews. Use `/ce-review` when:

- The PR touches cross-cutting concerns (security + performance + migrations)
- You want the adversarial lens to check what the specialists missed
- You want a machine-readable envelope for downstream tooling (ship dashboard, auto-todo creation)
- You want `safe_auto` fixes applied without ceremony and `gated_auto` fixes batched into one question

The orchestrator never shells out to the legacy commands. It dispatches agent personas directly. This avoids double-reviews and keeps the output format consistent.

## Non-Goals

This module does **not**:

- Replace or unregister the legacy review commands
- Ship Rails-specific reviewers (omitted by design; see Source)
- Bundle stack-specific personas (TypeScript, Frontend, etc.) - add those under `agents/reviewers/stack/` in a follow-up when the second caller appears
- Wire itself into any existing command. `/ce-review` is opt-in. Auto-dispatch on `gh pr create` would be a separate module.
- Publish findings outside the current repo. No external services, no plugin catalogs, no telemetry.

## Source

Ported from EveryInc/compound-engineering's `skills/ce-review/SKILL.md` (orchestrator, 743 lines) and its `agents/review/` directory (27 reviewer files). Adversarial lens adapted from garrytan/gstack's `review/specialists/red-team.md` (five lenses).

CCGM adaptations:

- Mode tokens match CCGM skill-authoring convention (`mode:interactive` / `mode:autofix` / `mode:report-only` / `mode:headless`)
- Reviewers live under `agents/reviewers/` per CCGM's `agents/` convention (issue #273)
- Phase 1 uses the CCGM `learnings-researcher` agent (compound-knowledge, issue #276) instead of a CE-specific retriever
- Phase 2 uses the CCGM `scope-drift` skill (pr-review-toolkit, issue #293) instead of an inline version
- Phase 6 output obeys the Fix-First rule (pr-review-toolkit) instead of CE's severity-tiered format
- Rails-specific reviewers from CE are dropped; stack-specific personas are a follow-up (none ship in this PR)
- The adversarial reviewer has a hard `gated_auto` ceiling on autofix class; CE allowed `safe_auto` in edge cases
- Finding schema is extracted to `references/finding.schema.yaml` so the skill body does not carry it on every invocation
