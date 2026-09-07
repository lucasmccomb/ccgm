---
name: adrev
description: >
  Adversarial review of a plan or any entity - file, doc, PR, issue, directory, or stated concept. The lead reviews personally by default; explicit cross-provider opt-in requests a fresh opposite-provider reviewer. Resolve concrete findings with evidence. A designated writer incorporates supported plan changes unless report-only was requested.
  Triggers: adrev, adversarial review, red-team this, attack this plan, poke holes in, tear this apart, devil's advocate review.
disable-model-invocation: true
---

# /adrev - Adversarial Review

Run a single hostile lens against anything: a plan, a doc, a PR, an issue, a codebase area, or an idea stated in the prompt. The lead performs the review personally by default. `--cross-provider` or an explicit natural-language request opts into a fresh opposite-provider reviewer; a request for adversarial review alone does not.

Two behaviors by target class:

- **Plan** - the designated writer incorporates supported findings by default after evidence-backed lead triage, preserving findings and their dispositions.
- **Other targets** - findings are reported without changes, unless `--apply` explicitly authorizes a writable markdown document.

Not this skill's job: the full 7-lens plan gate (`/document-review`), code-correctness review of a diff (`/code-review`, `pr-review-toolkit`), prose style (`/editorial-critique`).

## Inputs

Parse `$ARGUMENTS`:

- **Target** (positional) - path, `#N` / issue URL, PR number/URL, plan slug, or free text describing the entity. Empty → autodetect (below).
- **`--no-apply`** - review only; never modify the plan. Any natural-language opt-out in the invocation ("don't change the plan", "report only", "just review") counts as `--no-apply`.
- **`--apply`** - force incorporation for a writable markdown target that did not auto-classify as a plan.
- **`--cross-provider`** - explicitly request the optional native Claude/Codex workflow. Before preparing the target, run `python3 ~/.claude/lib/cross_agent_review_policy.py preflight`; require `AVAILABLE` from both binary/login checks for that path. `NEEDS_PROVIDER` stops the optional path. Default lead review needs no provider preflight or native run.
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

## Phase 2: Review and Evidence Resolution

The lead personally applies the `adrev-reviewer` attack battery to the target, goal/specification and actual relevant source/check evidence. Judge the artifact, not the author's defense. Keep concrete findings, evidence, remedies and dispositions; never describe personal review as an independent provider session.

Resolve `apply` explicitly: plans default to apply unless `--no-apply`, natural-language report-only, or `mode:report-only` applies. `mode:headless` is report-only unless `--apply` is present. Explicit `--apply` may authorize a writable markdown document; report-only always wins conflicting instructions. Other targets remain unchanged. Select one writer and keep reviewer tools read-only.

For optional native review, build a narrow frozen bundle from the target, specification/goal, attack criteria and relevant source evidence. Resolve PR/issue URLs before review and snapshot the relevant content; a no-tools reviewer cannot fetch a GitHub URL. A concept becomes an explicit UTF-8 artifact containing the user's text. Do not include the author's persuasive self-report. If required context exceeds the supported bundle, request/narrow the precise evidence instead of silently truncating it.

Every plan review checks premises, falsification, failure modes, opposing case, reversal costs, second-order effects and the four existing plan-execution tenets: minimal edge-bucketed human work, in-scope follow-up completion, sufficient decision context, and real autonomous E2E/CI coverage. Clean independent reviews are valid; do not invent objections.

The lead evaluates supported findings against the goal and evidence, regardless of who raised them. For apply-authorized targets, assign accepted changes to one writer, inspect the actual diff, run affected checks and review the changed artifact. Advisor mode still delegates edits and check execution. Confidence alone cannot refute evidence or authorize unrelated work.

**Only when explicitly opted in**, read `~/.claude/skills/cross-agent-review/references/workflow.md` and use `init --cross-provider --mode adrev` with one pass, required request/check/writer options, and `--report-only` when applicable. Use `~/.claude/cross-agent-review/<run-id>/`. Record actual producer/session; route opposite that producer, with both perspectives for unknown or materially mixed work. Standalone adrev uses `workflow: work`, even for a plan target.

Follow the optional policy's review/critic, frozen dispute, designated-writer, revalidation and acknowledgment contract. A provider error stops that optional run; preserve reports/findings and use `stop` with a reason when abandoning it. The lead may separately evaluate and complete the authorized delivery using personal review and normal checks, without relabeling the stopped run approved. Coordinator repairs never require recursive provider consensus.

For report-only targets, return the findings and evidence without edits or a fix dispatch. Report delivery can complete while findings remain open; do not label such a report `CONSENSUS` or execution-ready. Never turn a requested audit into an implementation loop merely to achieve a green status.

## Phase 3: Verify and Report

The returned prose is a claim, not evidence. Read the actual artifact, checks and review record; inspect policy reports/status only if an optional run exists:

- **Applied:** verify actual diff, fresh checks and supported dispositions personally. Claim optional policy completion only if its current hashes, both native acknowledgments and recorded host receipt pass its gate. Show the findings, changes, remaining limitations and available report/run paths. Required findings that remain unresolved block an execution-ready result.
- **Report-only:** verify target bytes are unchanged, then present the findings and survived attacks with their status/evidence. Open findings are valid report content. Do not infer consensus or merge permission. For a PR/issue, offer to post only when explicitly requested; this skill does not auto-post.
- **Missing evidence/provider, exhausted limits or unresolved dispute:** stop the optional run and preserve its explicit status, reports and next action. A separate lead decision does not erase the failure or invent native success.

In `mode:headless`, emit the structured findings and lead review status, plus any optional policy status/ledger, followed by "Adversarial review complete" only when report delivery completed; otherwise return the explicit incomplete status. Auto-apply remains disabled unless explicitly requested in that mode.
