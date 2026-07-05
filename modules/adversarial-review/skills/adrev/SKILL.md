---
name: adrev
description: >
  Adversarial review of a plan or any entity - file, doc, PR, issue, directory, or stated concept. Dispatches a separate adrev-reviewer agent that attacks premises, hunts failure modes, and steelmans the case against. When the target is a plan, the reviewing agent incorporates its findings into the plan automatically unless told not to.
  Triggers: adrev, adversarial review, red-team this, attack this plan, poke holes in, tear this apart, devil's advocate review.
disable-model-invocation: true
---

# /adrev - Adversarial Review

Run a single hostile lens against anything: a plan, a doc, a PR, an issue, a codebase area, or an idea stated in the prompt. The review runs in a **separate agent** with fresh context so the author session never grades its own work.

Two behaviors by target class:

- **Plan** - the reviewing agent incorporates its findings into the plan automatically (the default), writing the full review to the plan's `reviews/` directory as the audit trail.
- **Anything else** - findings are reported; the target is never modified.

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

## Phase 2: Dispatch the Reviewer

Compute the date deterministically: `date +%F`. Decide `apply`: target is a plan AND no opt-out present.

Dispatch one `adrev-reviewer` agent (installed at `~/.claude/agents/adrev-reviewer.md`). Pass paths, not contents:

```
Target: {path-or-ref}
target_kind: {plan|doc|pr|issue|code|dir|concept}
apply: {true|false}
review_date: {YYYY-MM-DD}
review_artifact_path: {plan-dir}/reviews/adversarial-{review_date}.md   # plans in a directory; omit otherwise
focus: {focus text, if any}
Reference files (read as needed): {siblings: research.md, decisions.md, progress.md; or repo paths the target cites}
```

For a `concept` target, include the full concept text in the prompt (it has no path) plus any repo context the user's phrasing points at.

The agent runs the full attack battery (premises, falsification, failure modes, strongest opposing case, reversal cost, second-order effects) and - when `apply` - incorporates findings into the plan per its apply protocol, returning a ledger of what changed.

**For `plan` targets, the agent additionally enforces three plan-execution tenets** (requirements, not judgment calls — it adds or expands sections when the plan is missing them):

1. **Human interaction is minimized and bucketed to the edges** — no human step an agent could do via CLI/API; any unavoidable human work is front-loaded before execution or deferred to the end, never mid-run.
2. **A follow-up-completion contract is present** — the plan requires that any follow-on work discovered during execution is completed before execution is reported complete; only genuinely human-blocked work may remain open.
3. **Enough decision context to direct unplanned work without a human** — the plan carries the software's mission, the codebase's governing conventions, and its own decision principles, so an agent can deduce how to handle unplanned follow-on work. If that context is missing, the agent expands the plan to add it.

## Phase 3: Verify and Report

The agent's DONE is a claim, not evidence:

- **Applied (plan)**: run `git diff` on the plan (or re-read the edited sections if untracked). Confirm the review artifact exists and every `incorporated` ledger entry corresponds to a real edit. Confirm the three plan-execution tenets are satisfied in the edited plan — human work is minimized and bucketed to the edges, the follow-up-completion contract is present and clearly located, and the mission / codebase-context / decision-principles content is concrete enough to direct unplanned work. If the reviewer parked a tenet in the Risk Register instead of fixing it, verify it named a genuine reason (a decision only the author can make). Then present: findings table (id, test, severity, confidence, one-line what), the ledger (incorporated / deferred-to-risks / artifact-only), what the target survived, and the artifact path.
- **Report-only**: present the findings table and survived list. For an `issue` or `pr` target, offer - do not auto-post - `gh issue comment` / `gh pr review --comment` with the findings.
- **BLOCKED / NEEDS_CONTEXT**: relay the missing piece verbatim and stop. Do not invent a target or substitute your own review in the main context - that breaks the separation that makes the review trustworthy.

In `mode:headless`, skip the prose: emit the findings JSON envelope plus the ledger, then "Adversarial review complete".
