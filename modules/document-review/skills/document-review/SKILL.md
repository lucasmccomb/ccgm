---
name: document-review
description: >
  Seven-lens plan-quality gate. Before a plan, spec, or requirements doc ships to execution, dispatch 7 role-specific reviewer agents (coherence, feasibility, product-lens, scope-guardian, design-lens, security-lens, adversarial) and merge their structured findings with severity and confidence. Each lens has tight what-you-flag boundaries so findings do not overlap.
  Triggers: document-review, review this plan, review the spec, plan review, is this plan ready, falsification test, scope check, adversarial review of doc.
disable-model-invocation: true
---

# /document-review - Seven-Lens Plan Quality Gate

Review a plan, spec, or requirements document through 7 distinct lenses in parallel. Return a single merged report with findings tagged by severity (P0-P3) and confidence (0.0-1.0). The caller decides which findings to integrate.

This skill is for documents headed to execution - the output of `/xplan`, a design doc, a product spec, an RFC, a migration plan. It is NOT for reviewing code (use `/review` or `pr-review-toolkit`), prose style (use `editorial-critique`), or post-hoc retrospectives (use `/retro` if installed).

Each lens agent has a tight "what you flag / what you do not flag" boundary so the seven reviewers do not produce overlapping findings. The scope-guardian challenges unjustified complexity; the adversarial reviewer challenges premises and unstated assumptions; the feasibility reviewer challenges "can we actually build this." They are complementary, not redundant.

## When to Run

Run `/document-review` after:

- `/xplan` produces a plan and before execution begins
- A design doc, RFC, or spec is written and before stakeholders sign off
- A migration plan is drafted and before migrations run
- Any multi-step plan an agent is about to execute autonomously

Do NOT run for:

- Code diffs or PRs - use `/review` or `pr-review-toolkit`
- Prose style, tone, or grammar - use `editorial-critique`
- Throwaway scratch plans that the user will rewrite regardless
- Documents where you have not yet committed to the current draft being the one to ship

## Inputs

On invocation, parse `$ARGUMENTS` for:

- A path to the document under review. Required. Example: `docs/plan.md`, `~/code/plans/foo/plan.md`, or a URL to a gist or issue.
- An optional `mode` token (see Mode Selection below).
- Optional `skip:{lens}` tokens to disable specific lenses for this run (e.g., `skip:security-lens` for a plan that touches no security surface).
- Optional `only:{lens1,lens2}` token to run only a subset.

If no path is provided and exactly one document in the working tree is plausibly "the plan" (a single `plan.md`, the most recently edited `docs/*.md`, etc.), prompt once to confirm. Otherwise ask the user to specify.

Never invent a document to review. If the path does not resolve to a readable file, stop and return `NEEDS_CONTEXT` with the path that failed.

## Mode Selection

Parse `$ARGUMENTS` for a mode token:

- `mode:interactive` (default) - Run all lenses, present the merged report, pause for user review
- `mode:report-only` - Run all lenses, write the merged report to a file, do not prompt
- `mode:headless` - For skill-to-skill invocation, return structured JSON envelope, emit "Document review complete" terminal signal, do not prompt

In headless mode, suppress commentary and return only the structured output block (see Phase 3: Output).

## Phase 1: Preparation

1. Resolve the document path. Read it once. If the doc is longer than ~1500 lines, note that some lenses may return `needs_more_context` for sections they could not fully analyze; do not silently truncate.

2. Compute the review context. Extract:
   - `doc_path` - absolute path
   - `doc_type` - plan | spec | design-doc | rfc | migration-plan | other (best guess from filename and headings)
   - `scope_hint` - one paragraph summarizing what the doc proposes (for agents that need orientation without reading the whole thing)
   - `referenced_files` - list of code paths or modules mentioned in the doc

3. Determine which lenses run. Default is all 7. Honor `skip:{lens}` and `only:{lens,...}` tokens. Never auto-skip a lens based on content heuristics - the user decides.

## Phase 2: Dispatch Lenses

Dispatch the selected lens agents in parallel. Use the pass-paths-not-contents pattern (see `modules/subagent-patterns/rules/subagent-patterns.md`) - pass `doc_path` and the review context, let each agent Read the doc itself.

Each agent is installed under `~/.claude/agents/{lens}-reviewer.md`. Each agent returns JSON matching:

```json
{
  "lens": "coherence",
  "findings": [
    {
      "id": "coherence-001",
      "severity": "P1",
      "confidence": 0.85,
      "location": "section 3.2, paragraph 2",
      "what": "Step 4 references an API endpoint that Step 2 said would be deleted",
      "why": "Contradicts the earlier scope decision; one of the two must be wrong",
      "suggestion": "Either restore the endpoint or update Step 4 to use the replacement"
    }
  ],
  "status": "DONE"
}
```

Severity conventions:

- **P0** - Blocks shipping. Internal contradiction, impossible constraint, fundamental misread of the problem
- **P1** - Must fix before execution. Missing critical detail, likely-wrong assumption, scope bloat that will derail the plan
- **P2** - Should fix. Risky choice, unclear section, omitted consideration
- **P3** - Nice to have. Small improvement, optional clarification

Confidence conventions:

- **HIGH (>= 0.80)** - Lens is confident the finding is real
- **MODERATE (0.60 - 0.79)** - Lens suspects the finding but acknowledges ambiguity
- **LOW (< 0.60)** - Lens would suppress the finding from the default report but include it in verbose output

Agents that cannot complete (missing file, malformed doc) return `status: BLOCKED` with a reason. Agents that need more context return `status: NEEDS_CONTEXT`.

## Phase 3: Merge and Report

Collect all lens outputs. Merge:

1. **Dedupe** - If two lenses flag the same location with the same root cause, keep the higher-confidence finding and note the second lens in `also_flagged_by`. Do not average confidences.

2. **Sort** - By severity (P0 first), then by confidence (high first), then by lens order (coherence, feasibility, product, scope, design, security, adversarial).

3. **Suppress** - In interactive and report-only modes, suppress any finding with confidence below 0.50 from the default report. Keep a `suppressed_count` per lens at the end so the user knows the filter fired.

4. **Structure** - Produce the merged report.

### Interactive Mode Output

```markdown
# Document Review: {doc_path}

**Lenses run:** {list}
**Findings:** {P0 count} P0, {P1 count} P1, {P2 count} P2, {P3 count} P3
**Suppressed (confidence < 0.50):** {count}

## P0 - Blocking

{findings}

## P1 - Must Fix

{findings}

## P2 - Should Fix

{findings}

## P3 - Nice to Have

{findings}

## Lens Summary

| Lens | Status | Findings | Suppressed |
|------|--------|----------|------------|
| coherence | DONE | 3 | 1 |
| feasibility | DONE | 2 | 0 |
| ...

## Next Steps

1. Address P0 items before execution
2. Decide on P1 items - fix in place or document the tradeoff
3. P2 and P3 can ship as follow-ups if the plan is otherwise ready
```

End with the question: "Integrate these findings into the plan, or ship as-is?"

### Report-Only Mode Output

Write the merged report to `{doc_path}.review.md` next to the source document. Emit one line summary. Do not prompt.

### Headless Mode Output

Return structured envelope:

```json
{
  "status": "DONE" | "DONE_WITH_CONCERNS" | "BLOCKED",
  "doc_path": "...",
  "lenses_run": ["coherence", "..."],
  "findings": [...],
  "counts": { "P0": 0, "P1": 2, "P2": 5, "P3": 3, "suppressed": 4 },
  "suggestions_for_caller": "..."
}
```

`DONE_WITH_CONCERNS` fires when any P1 or higher finding landed. `BLOCKED` fires only if a lens returned BLOCKED and no other lens produced actionable findings. Terminate with the line `Document review complete.` so caller skills can detect completion.

## Phase 4: Integration (Interactive Mode Only)

After presenting the report, offer:

- **Apply safe edits** - For findings marked `autofix_safe: true` by their lens (simple wording, broken cross-references, obvious typos). Dispatch a narrow edit agent; do not auto-apply anything that changes meaning.
- **Open as todos** - Create a checklist block at the end of the reviewed doc or in `docs/TODO.md` if that is the repo convention.
- **Ship as-is** - Record the decision in a footer block noting which findings were acknowledged but not integrated.

Do not silently edit the doc. Every write requires an explicit confirmation in interactive mode.

## Guardrails

- Every lens reads the doc itself via Read. The orchestrator never passes the doc body inline.
- Never merge two lenses into one agent call "for efficiency" - the distinct perspectives are the whole point.
- Never run fewer than 7 lenses silently. If a user passes `skip:` tokens, honor them but surface the skipped list in the report header.
- Never claim a plan is "ready" on behalf of the user. The skill produces findings; the user ships.
- Do not write `{doc_path}.review.md` in interactive mode unless the user asks for it. The report lives in the transcript by default.
- If the doc itself is missing or unreadable, stop in Phase 1 and return `BLOCKED`. Do not dispatch lens agents against nothing.

## Source

Ported from EveryInc/compound-engineering-plugin's `document-review` skill and its 7 lens agents. The original fans out to the same 7 lenses with the same what-you-flag boundaries. CCGM adaptations:

- Lens agents live under `agents/` (per CCGM #273 convention) rather than inside the skill directory
- Mode tokens match CCGM skill-authoring convention (`mode:interactive`, `mode:report-only`, `mode:headless`)
- The pass-paths-not-contents pattern is applied to lens dispatch
- No wiring into `/xplan` ships with this PR - that integration is tracked as a follow-up
