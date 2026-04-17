# Document Review

Seven-lens plan-quality gate. Before a plan, spec, or design doc ships to execution, `/document-review` fans out to 7 role-specific reviewer agents and merges their structured findings. Each lens has tight what-you-flag boundaries so the reviewers do not produce overlapping findings.

This module fills a gap in CCGM's review surfaces: existing review commands (`/review`, `pr-review-toolkit`, `security-review`) operate on code. `document-review` operates on the plan before the code is written - the cheapest moment to catch a scope bloat, an unstated assumption, or a missing auth check.

## The Seven Lenses

| Lens | What it flags |
|---|---|
| **coherence** | Internal contradictions, dangling cross-references, undefined terms, step-ordering errors, scope/detail mismatches |
| **feasibility** | Missing prerequisites, technology misuse, unavailable dependencies, unrealistic sequencing, environment gaps |
| **product-lens** | Missing user stories, unclear success criteria, undefined metrics, outcome/implementation mismatch, UX state gaps |
| **scope-guardian** | Premature abstractions, speculative configuration, while-we're-here expansions, new surfaces duplicating existing ones (YAGNI at plan time) |
| **design-lens** | Fragile coupling, leaky abstractions, mixed responsibilities, awkward data flow, unnecessary state, bolt-on integrations |
| **security-lens** | Auth/authz gaps, input validation gaps, secret handling, data exposure, missing RLS/ACL, insecure defaults |
| **adversarial-document** | Unstated premises, unfalsifiable claims, high-reversal-cost decisions with thin justification, decision-scope mismatches, abstraction audits |

Each lens has a "what you do NOT flag" section in its agent file to keep findings from overlapping. The orchestrator dedupes when two lenses still hit the same location.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/document-review/SKILL.md` | `skills/document-review/SKILL.md` | `/document-review` - orchestrator skill |
| `agents/coherence-reviewer.md` | `agents/coherence-reviewer.md` | Internal consistency lens |
| `agents/feasibility-reviewer.md` | `agents/feasibility-reviewer.md` | Buildability lens |
| `agents/product-lens-reviewer.md` | `agents/product-lens-reviewer.md` | Product judgment lens |
| `agents/scope-guardian-reviewer.md` | `agents/scope-guardian-reviewer.md` | YAGNI lens |
| `agents/design-lens-reviewer.md` | `agents/design-lens-reviewer.md` | Design quality lens |
| `agents/security-lens-reviewer.md` | `agents/security-lens-reviewer.md` | Plan-stage security lens |
| `agents/adversarial-document-reviewer.md` | `agents/adversarial-document-reviewer.md` | Premise-challenge lens |

## Manual Installation

```bash
# From the CCGM repo root:

mkdir -p ~/.claude/skills/document-review
mkdir -p ~/.claude/agents

cp modules/document-review/skills/document-review/SKILL.md \
   ~/.claude/skills/document-review/SKILL.md

for agent in coherence feasibility product-lens scope-guardian design-lens security-lens adversarial-document; do
  cp "modules/document-review/agents/${agent}-reviewer.md" \
     "~/.claude/agents/${agent}-reviewer.md"
done
```

## Usage

### Review a plan

```
/document-review docs/plan.md
/document-review ~/code/plans/my-feature/plan.md
```

The skill dispatches all 7 lenses in parallel, merges their findings by severity (P0-P3) and confidence (0.0-1.0), dedupes overlaps, and presents a merged report.

### Modes

```
/document-review docs/plan.md mode:report-only
/document-review docs/plan.md mode:headless
```

- `mode:interactive` (default) - present the report in the transcript, pause for user decision
- `mode:report-only` - write the merged report to `{doc_path}.review.md`, no prompts
- `mode:headless` - structured JSON envelope for skill-to-skill invocation

### Lens selection

```
/document-review docs/plan.md skip:security-lens
/document-review docs/plan.md only:scope-guardian,adversarial-document
```

Default is all 7. Use `skip:` or `only:` tokens to adjust for a specific run.

## Severity and Confidence

Every finding carries a severity and a confidence. The orchestrator suppresses findings below 0.50 confidence by default so the report stays signal-dense.

**Severity:**

- **P0** - Blocks shipping
- **P1** - Must fix before execution
- **P2** - Should fix
- **P3** - Nice to have

**Confidence:**

- **HIGH** (>= 0.80) - lens is sure
- **MODERATE** (0.60 - 0.79) - lens suspects but acknowledges interpretation
- **LOW** (< 0.60) - suppressed by default; available in verbose mode

## Dependencies

- `skill-authoring` - orchestrator and lens agents follow the skill-authoring discipline
- `subagent-patterns` - lens dispatch uses the pass-paths-not-contents pattern

No runtime dependencies beyond the module system.

## Non-Goals

This module does **not**:

- Review code diffs or PRs. Use `/review`, `pr-review-toolkit`, or `security-review` for code.
- Auto-wire itself into `/xplan`. That integration is a follow-up; see CCGM's xplan enhancements backlog.
- Edit the reviewed document. Findings are presented; the author (or a later explicit pass) integrates them.
- Replace `editorial-critique` for prose-style review, or `design-review` for UI-design review. Those remain separate surfaces.

## When To Run

Run `/document-review` when:

- `/xplan` produces a plan and before execution starts
- A design doc, RFC, or spec is drafted and before stakeholders sign off
- A migration plan is written and before migrations run
- Any multi-step plan is about to be executed autonomously

Do not run for throwaway scratch plans or for documents you know you will rewrite regardless of findings - the lenses are well-behaved but not free.

## Source

Ported from EveryInc/compound-engineering-plugin's `document-review` skill and its 7 lens agents at `plugins/compound-engineering/agents/document-review/`.

CCGM adaptations:

- Lens agents live under `agents/` (per CCGM #273 directory convention) rather than inside the skill directory.
- Mode tokens match CCGM skill-authoring convention (`mode:interactive`, `mode:report-only`, `mode:headless`).
- The pass-paths-not-contents pattern is applied to lens dispatch so the orchestrator does not inline the doc body into each agent's context.
- No wiring into `/xplan` ships with this PR. That integration is a follow-up.
- The security-lens explicitly delineates its boundary with the adversarial-document lens (checklist-style vs premise-challenge).
