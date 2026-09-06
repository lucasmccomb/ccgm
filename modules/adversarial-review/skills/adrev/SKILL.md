---
name: adrev
description: >
  Adversarial review of a plan or any entity - file, doc, PR, issue, directory, or stated concept. Routes a fresh reviewer opposite the actual producing provider, then resolves concrete findings with evidence. A designated writer incorporates supported plan changes unless report-only was requested.
  Triggers: adrev, adversarial review, red-team this, attack this plan, poke holes in, tear this apart, devil's advocate review.
disable-model-invocation: true
---

# /adrev - Adversarial Review

Run a single hostile lens against anything: a plan, a doc, a PR, an issue, a codebase area, or an idea stated in the prompt. The review runs in a **separate agent** with fresh context so the author session never grades its own work.

Two behaviors by target class:

- **Plan** - the designated writer incorporates supported findings by default after the frozen review/critic exchange, with the coordinator preserving the full review and evidence ledger.
- **Other targets** - findings are reported without changes, unless `--apply` explicitly authorizes a writable markdown document.

Not this skill's job: the full 7-lens plan gate (`/document-review`), code-correctness review of a diff (`/code-review`, `pr-review-toolkit`), prose style (`/editorial-critique`).

## Inputs

Parse `$ARGUMENTS`:

- **Target** (positional) - path, `#N` / issue URL, PR number/URL, plan slug, or free text describing the entity. Empty → autodetect (below).
- **`--no-apply`** - review only; never modify the plan. Any natural-language opt-out in the invocation ("don't change the plan", "report only", "just review") counts as `--no-apply`.
- **`--apply`** - force incorporation for a writable markdown target that did not auto-classify as a plan.
- **`--focus "..."`** - narrow the attack surface (e.g., `--focus "the migration sequencing"`).
- **`mode:report-only`** - same as `--no-apply`, plus write the report to a file instead of prompting.
- **`mode:headless`** - skill-to-skill invocation: no prompts, return the findings JSON envelope, end with "Adversarial review complete". Headless never applies unless `--apply` is explicitly present.

## Phase 1: Resolve and Classify the Target

Resolve deterministically, in order:

1. **Existing path** (file or dir) → that entity. A directory: prefer `plan.md` / `PLAN.md` inside it; otherwise treat as a `dir` (code) target.
2. **`#N`, bare number, or GitHub issue URL** → `issue`. A PR URL or `pr#N` → `pr`. Verify with `gh issue view` / `gh pr view`; a ref that resolves to neither is a blocker - report it, do not guess.
3. **Plan slug** - token matching a directory under `~/code/plans/{token}/` → that plan.
4. **Empty** → autodetect: most recently modified `~/code/plans/*/plan.md` whose sibling `progress.md` is not complete, falling back to a `plan.md`/obvious plan doc in the working tree. Confirm the autodetected target with the user before dispatching. If nothing plausible, ask.
5. **Anything else** → `concept`: the argument text itself is the entity under review.

**Plan classification** (controls auto-apply): the target is a `plan` if it is a `plan.md`/`PLAN.md`, lives under a `plans/` directory, or is unambiguously an execution plan (phased steps intended to be built). Ambiguous docs classify as `doc` (report-only) - the user can rerun with `--apply`. Never auto-apply to anything but a plan.

## Phase 2: Cross-Agent Review and Evidence Resolution

Read `~/.claude/skills/cross-agent-review/references/workflow.md`. Use the policy's **adrev** mode with one pass and the `adrev-reviewer` attack battery as review criteria. Record the actual producing provider/session from dispatch metadata: reviewer selection is opposite that provider, not whichever model happens to orchestrate this command. If authorship is unknown or materially mixed, obtain both perspectives. Do not relabel user-authored or unattributed files as Claude/Codex work.

Resolve `apply` explicitly: plans default to apply unless `--no-apply`, natural-language report-only, or `mode:report-only` applies. `mode:headless` is report-only unless `--apply` is present. Explicit `--apply` may authorize a writable markdown document; report-only always wins conflicting instructions. Other targets remain unchanged. Select one writer and keep reviewer tools read-only.

Build a narrow frozen bundle from the target, specification/goal, attack criteria and relevant source evidence. Resolve PR/issue URLs before review and snapshot the relevant content; a no-tools reviewer cannot fetch a GitHub URL. A concept becomes an explicit UTF-8 artifact containing the user's text. Do not include the author's persuasive self-report. If required context exceeds the supported bundle, request/narrow the precise evidence instead of silently truncating it.

Run `review`, then the other provider's `critic` on material findings. Every plan review checks premises, falsification, failure modes, opposing case, reversal costs, second-order effects and the four existing plan-execution tenets: minimal edge-bucketed human work, in-scope follow-up completion, sufficient decision context, and real autonomous E2E/CI coverage. Clean independent reviews are valid; do not invent objections.

Freeze the artifact during disputes; use requirement/source/test evidence and the three critic verdicts. For an apply-authorized target, use the policy's accepted disposition and `fix` admission before the designated writer edits. Then refresh, run affected checks and obtain opposite-provider material-change validation. Confidence alone never authorizes a fix, refutes evidence, or establishes agreement. The initiating host coordinates, receives the final evidence, and respects the policy's unresolved limits.

For report-only targets, return the findings and evidence without edits or a fix dispatch. Report delivery can complete while findings remain open; do not label such a report `CONSENSUS` or execution-ready. Never turn a requested audit into an implementation loop merely to achieve a green status.

## Phase 3: Verify and Report

The returned prose is a claim, not evidence. Read the policy result and structured reports:

- **Applied:** verify actual diff and recorded checks, current hashes, supported dispositions, both providers' final acknowledgments and original-host reception. Show the findings, changes, remaining limitations and run/report paths. Required findings that remain unresolved block an execution-ready result.
- **Report-only:** verify target bytes are unchanged, then present the findings and survived attacks with their status/evidence. Open findings are valid report content. Do not infer consensus or merge permission. For a PR/issue, offer to post only when explicitly requested; this skill does not auto-post.
- **Missing evidence/provider, exhausted limits or unresolved dispute:** preserve the run and explicit status/next action. Do not substitute a same-provider reviewer or invent a clean result.

In `mode:headless`, emit the structured findings and policy status/ledger, followed by "Adversarial review complete" only when report delivery completed; otherwise return the explicit incomplete status. Auto-apply remains disabled unless explicitly requested in that mode.
