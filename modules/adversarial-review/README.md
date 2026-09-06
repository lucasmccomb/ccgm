# Adversarial Review

`/adrev` - run a single hostile lens against a plan or any entity: a file, doc, PR, issue, directory, or an idea stated inline. A separate `adrev-reviewer` agent (fresh context - the author session never grades its own work) attacks premises, hunts failure modes, steelmans the strongest case against, and checks falsifiability and reversal costs.

For plans, a **designated writer applies supported findings after an opposite-provider review and evidence-based critic exchange**. Reviewers stay read-only, and the coordinator preserves the report and evidence ledger. `--no-apply` or a natural-language opt-out returns findings without target changes. Headless mode applies only with explicit `--apply`; writable markdown documents can also opt in explicitly.

## How It Relates to Other Review Modules

| Surface | Scope | Modifies the target? |
|---|---|---|
| `/adrev` | One adversarial lens, **any entity** | Plans: designated writer by default; other markdown only with explicit --apply |
| `/document-review` | 7 lenses, docs headed to execution | Never - findings are presented |
| `/ce-review`, `pr-review-toolkit`, `/code-review` | Code diffs and PRs | Via review comments / fixes |
| `/editorial-critique` | Prose style | Optional `--fix` |

Use `/document-review` for the full pre-execution gate on a plan; use `/adrev` when you want the premise-challenge lens alone, on anything, with the plan updated when it is a plan.

## What This Module Provides

Files installed globally to `~/.claude/`:

| Source | Target | Purpose |
|--------|--------|---------|
| `skills/adrev/SKILL.md` | `skills/adrev/SKILL.md` | `/adrev` - target resolution + dispatch + verification |
| `agents/adrev-reviewer.md` | `agents/adrev-reviewer.md` | Read-only attack battery + evidence criteria |

## Usage

```
/adrev ~/code/plans/my-feature/plan.md       # review + incorporate findings into the plan
/adrev ~/code/plans/my-feature/plan.md --no-apply   # review only
/adrev my-feature                            # plan slug under ~/code/plans/
/adrev                                       # autodetect the in-progress plan (confirms first)
/adrev #42                                   # adversarial review of a GitHub issue
/adrev pr#117                                # adversarial review of a PR
/adrev src/auth/                             # attack a codebase area
/adrev "switching the store from JSONL to SQLite"   # attack a stated concept
/adrev docs/rfc.md --apply                   # force incorporation for a non-plan doc
/adrev plan.md --focus "the rollout sequencing"
/adrev plan.md mode:headless                 # skill-to-skill: JSON envelope, no prompts
```

## The Attack Battery

1. **Premise attack** - load-bearing assumptions the author has not realized they are making
2. **Falsification test** - claims with no articulated way to know if they are wrong
3. **Failure-mode hunt** - empty input, partial failure, concurrency, scale, clock edges, careless and malicious users
4. **Strongest opposing case** - steelman the alternative, including do-nothing
5. **Reversal-cost check** - expensive-to-undo decisions with thin justification
6. **Second-order effects** - assume it ships and works; who adapts to it, games it, or becomes load-bearing on it

Findings carry severity (P0-P3) and confidence (0.0-1.0), matching the document-review conventions. The report also lists what the target **survived** - a clean verdict is only credible when the attacks are shown.

## Plan Execution Tenets (plan targets)

Beyond the battery, a plan is a contract for *autonomous* execution, so `plan` targets get four additional checks that are **requirements, not judgment calls** - if the plan fails one, apply mode fixes it (adds/expands the section), it is not merely noted:

1. **Human interaction is minimized and bucketed to the edges** - no human step an agent could do via CLI/API; unavoidable human work is front-loaded before execution or deferred to the end, never wedged mid-run where it stalls the whole run.
2. **A follow-up-completion contract is present** - the plan requires that any follow-on work discovered during execution is completed before execution is reported complete; the completion checklist includes "no open in-scope follow-up work"; only genuinely human-blocked items may remain open.
3. **Enough decision context to direct unplanned work without a human** - the plan carries the software's mission, the codebase's governing conventions, and its own decision principles, so an agent can deduce how to handle an unplanned follow-on item. Missing context is expanded into the plan on apply.
4. **A comprehensive autonomous E2E test suite** - every testable surface maps to a real end-to-end test (not mocks), wired into CI as a blocking merge gate, so the suite (not the user) is the ready-to-merge oracle. For existing repos, coverage gaps in touched areas are filled optimistically. Thin coverage is expanded into Section 8 on apply.

The four reinforce each other: decision context (3) lets an agent finish follow-on work (2) without a human, which keeps execution human-free mid-run (1); the E2E suite (4) makes "done" verifiable without the user, so the whole run can certify itself green.

## The Apply Protocol (plans)

The opposite-provider reviewer is read-only. Findings are settled on a frozen artifact with an evidence-grounded critic, then one designated writer applies authorized changes. The policy checks current hashes, required checks, supported dispositions, both native provider acknowledgments and original-host reception. Confidence alone cannot close a finding. Preserve goal decisions and resource exhaustion as explicit unresolved states.

Plans apply supported fixes by default. `--no-apply`, report-only mode and natural-language opt-outs keep the target unchanged; headless applies only with explicit `--apply`. Report delivery with open findings is not consensus or execution readiness. See the [pilot workflow contract](../cross-agent-review/skills/cross-agent-review/references/workflow.md).

## Manual Installation

```bash
# From the CCGM repo root:
mkdir -p ~/.claude/skills/adrev ~/.claude/agents
cp modules/adversarial-review/skills/adrev/SKILL.md ~/.claude/skills/adrev/SKILL.md
cp modules/adversarial-review/agents/adrev-reviewer.md ~/.claude/agents/adrev-reviewer.md
```

## Dependencies

- `cross-agent-review` - restricted native providers and deterministic pilot workflow gates; install through the CCGM dependency resolver or follow its module README first
- `subagent-patterns` - dispatch uses pass-paths-not-contents, the four-state status protocol, and skill invocation modes

## When To Run

- After drafting a plan and before `/etp` executes it (lighter than the full `/document-review` gate)
- Before committing to a direction on an issue - `/adrev #N` pressure-tests the proposal in the issue body
- When a PR's approach (not its diff hygiene) deserves a hostile read
- Any time you catch yourself wanting the plan to be right more than wanting to know whether it is
