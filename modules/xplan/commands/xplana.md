---
description: Autonomous xplan - full-depth research + planning + reviews with zero mid-flow prompts. Presents the completed plan as a single artifact at the end.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, WebSearch, WebFetch
argument-hint: <project concept or idea> [--repo <existing-repo-path>] [--deepen [<plan-dir>]]
---

# xplana - Autonomous xplan

Thin alias for `/xplan --autonomous`. Runs the full xplan pipeline (research + naming + tech stack + scope + multi-agent setup + full plan + full review + self-review) end-to-end without any mid-flow prompts, then presents the completed plan as a structured artifact for review at a single final gate.

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
| 0.5 (Discovery Interview) | Skipped. Defaults inferred per Phase 0.5 Inference Rules; recorded in `decisions.md`. |
| 1.0 (Research Config) | Locked to Full - all 7 research agents fire. |
| 1.5 (Research Review) | Skipped mid-flow; summary stashed for final walkthrough. |
| 2 (Naming Ideation) | Runs silently. Top pick auto-selected; top-5 surfaced in final walkthrough. |
| 2.5 (Tech Stack Sign-off) | Proposal built and auto-approved. No sign-off question. |
| 2.6 (Scope Sign-off) | Proposal built and auto-approved. No sign-off question. |
| 2.7 (Multi-Agent Setup) | Inferred from scope (9+ epics = workspace, 4-8 = flat, 1-3 = single). |
| 4.0 (Review Configuration) | Locked to Full - security + architecture + business logic. |
| 5.6 (Plan Quality Self-Review) | Unchanged - still loops until clean. |
| 6 (Walkthrough) | Runs the new **Phase 6.A Autonomous Plan Walkthrough** - structured plan-as-artifact presentation with explicit assumption callouts. |
| 6.5 (Final Execution Gate) | **Always fires**, same as any xplan run. Autonomous mode does NOT bypass this gate. |

## What This Command Does NOT Do

- It does NOT skip research, naming, reviews, or the self-review loop. Autonomous is the *deep* mode, not the fast one.
- It does NOT skip the final execution gate. 6.5 is non-bypassable.
- It does NOT automatically proceed to execution. The default recommendation at 6.5 in autonomous mode leans toward "save plan, don't execute yet" so the user can review before committing to multi-agent work.

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
