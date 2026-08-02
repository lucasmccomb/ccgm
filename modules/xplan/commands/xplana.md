---
description: Autonomous xplan - full-depth research + planning + reviews with zero mid-flow prompts. Presents the completed plan as a single artifact at the end.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <project concept or idea> [--repo <existing-repo-path>] [--deepen [<plan-dir>]]
---

# xplana - Autonomous xplan

Thin alias for `/xplan --autonomous`. Runs the full xplan pipeline (research + naming + tech stack + scope + multi-agent setup + full plan + full standard review + self-review + **3 sequential adversarial reviews**) end-to-end without any mid-flow prompts, then presents the completed plan as a structured artifact for review at a single final gate.

Pick `/xplana` when:
- You know exactly what you want to plan and don't want the 7-question discovery interview
- You prefer reviewing a finished plan over answering questions during its creation
- You want maximum-depth output (full research, full review) without interruption

Pick `/xplan` (default) when:
- You want the guided, section-by-section interactive experience
- You want to refine the concept during research
- You want to approve the tech stack and scope before the full plan is written

Pick `/xplan --light` when:
- You want a quick pass (reduced research, internal defaults, section-by-section walkthrough at the end)

## Input

```
$ARGUMENTS
```

## Behavior

Delegate immediately to the main `/xplan` command with the `--autonomous` flag set. Read `~/.claude/commands/xplan.md` and execute its full workflow, treating the following flag as set:

```
--autonomous
```

Preserve every other argument the user passed (e.g., `--repo <path>`, `--deepen [<plan-dir>]`). Do NOT strip or transform the concept text.

Autonomous mode affects these xplan phases:

| Phase | What changes in autonomous mode |
|-------|--------------------------------|
| 0.4.0 (Source Freshness Guard) | Runs automatically with NO prompt when `--repo` is set: fetch, pin the origin default-branch anchor, expose a temp anchor worktree, and verify every repo fact against it. Never fast-forwards the user's clone. Skipped entirely for greenfield (no `--repo`). |
| 0.5 (Discovery Interview) | Skipped. Defaults inferred per Phase 0.5 Inference Rules; recorded in `decisions.md`. **Except Q8 (live-testing authorization)**, which cannot be inferred: plan §8.6 records `NOT AUTHORIZED` and 6.A surfaces it. |
| 1.0 (Research Config) | Locked to Full - all 7 research agents fire. |
| 1.5 (Research Review) | Skipped mid-flow; summary stashed for final walkthrough. |
| 2 (Naming Ideation) | Runs silently. Top pick auto-selected; top-5 surfaced in final walkthrough. |
| 2.5 (Tech Stack Sign-off) | Proposal built and auto-approved. No sign-off question. |
| 2.6 (Scope Sign-off) | Proposal built and auto-approved. No sign-off question. |
| 2.7 (Multi-Agent Setup) | Inferred from scope (9+ epics = workspace, 4-8 = flat, 1-3 = single). |
| 4.0 (Review Configuration) | Locked to Full - security + architecture + business logic. |
| 5.6 (Plan Quality Self-Review) | Unchanged - still loops until clean. |
| 5.7 (Adversarial Review Sequence) | **Locked ON.** Runs 3 sequential `adrev-reviewer` passes (Opus 4.8, max effort) against the finished plan — each pass attacks after the previous pass's fixes are incorporated; the third is the final review. No mid-flow prompt - any P0/P1 the final pass leaves unresolved are recorded and surfaced at the 6.A walkthrough + 6.5 gate instead of asking. |
| 6 (Walkthrough) | Runs the new **Phase 6.A Autonomous Plan Walkthrough** - structured plan-as-artifact presentation with explicit assumption callouts. |
| 6.5 (Final Execution Gate) | **Always fires**, same as any xplan run. Autonomous mode does NOT bypass this gate. |

## Built-In Execution Tenets (matter most here)

Autonomous mode is where these four plan tenets matter most: there is no human in the loop during creation *or* execution, so the plan must stand entirely on its own. They apply in every xplan mode, but `/xplana` leans on them hardest. The Phase 5.7 adversarial reviewer enforces all four (T1–T4), expanding the plan when any is thin:

1. **Human interaction is minimized and bucketed to the edges** (T1). No human step an agent could do via CLI/API; unavoidable human work is front-loaded before Wave 1 or deferred to the end, never wedged mid-run. Once execution starts, it runs to done without pausing for a person.
2. **Follow-up-completion contract** (T2, plan §9.5). Any follow-on work discovered during execution is tracked, triaged, and — if in-scope — completed before execution is reported complete. Only genuinely human-blocked work may remain open, surfaced with its exact ask.
3. **Autonomous decision context** (T3, plan §1.4). The plan carries the software's mission, the codebase's governing context, and its decision principles, so an execution agent deduces the direction for unplanned follow-on work *itself* — critical in autonomous mode, where there is no user to ask mid-run. If that context is thin, the adversarial review expands the plan to add it.
4. **Comprehensive autonomous E2E testing** (T4, plan §8). Every plan ships a full autonomous E2E suite over all testable surfaces, wired into CI as a blocking merge gate — the certainty oracle so the user never tests manually. New projects build it in from the ground up; existing repos get **optimistic gap-fill** for touched areas that lack coverage (added by default on the assumption the user wants more coverage — surfaced in the final walkthrough, not gated behind a mid-flow question, which fits autonomous mode). The plan provisions whatever infra certainty needs (testing agents, RunPod, cloud Mac, real devices); there is no resource constraint on testing. The adversarial review expands §8 when coverage is thin.

## What This Command Does NOT Do

- It does NOT skip research, naming, the standard reviews, the self-review loop, or the Phase 5.7 adversarial review sequence. Autonomous is the *deep* mode, not the fast one — the finished plan has survived 6 reviews (3 standard + 3 sequential adversarial) before you see it.
- It does NOT skip the four execution tenets above. The adversarial review enforces minimal edge-bucketed human work (T1), a follow-up-completion contract (T2), enough decision context to direct unplanned work without a human (T3), and a comprehensive autonomous E2E suite over all testable surfaces (T4) — expanding the plan when any is missing.
- It does NOT skip the final execution gate. 6.5 is non-bypassable.
- It does NOT grant live-testing permission. Autonomous planning can infer a tech stack; it cannot approve running app launches, dictation, synthetic input, focus changes, machine-global input/audio overrides, or mic capture on the user's behalf. Plan §8.6 records `NOT AUTHORIZED`, the 6.A walkthrough shows the affected steps, and `/etp` or `/xplan-resume` holds each one and asks before running it. See `~/.claude/rules/live-testing-guard.md`.
- It does NOT automatically proceed to execution. The default recommendation at 6.5 in autonomous mode leans toward "save plan, don't execute yet" so the user can review before committing to multi-agent work.
- It does NOT leave a worktree behind on that gate-stop path. When `--repo` is set, Phase 0.4.0 creates a temp anchor worktree; because autonomous mode usually stops at the 6.5 gate *without* executing, run the Phase 8.7 worktree teardown on exit anyway (it is explicitly early-exit-safe). If any execution worktrees were created, `/worktree-sweep` reclaims the leaks. Nothing worktree-shaped outlives the run — see `git-worktrees.md`.

For the fast path (reduced depth, minimal interaction), use `/xplan --light` instead.

## Correcting Inferred Assumptions

If the final walkthrough surfaces an assumption the user wants to correct, the recommended path is:

```
/xplan --deepen ~/code/plans/{concept-name}
```

`--deepen` mode loads the existing plan and runs targeted passes on under-specified sections without re-running the full pipeline. This is faster than `--autonomous` again with adjusted inputs.

## Companion Commands

- `/xplan` - Full interactive version
- `/xplan-status` - Check progress on a running or completed plan
- `/xplan-resume` - Resume an interrupted plan execution
