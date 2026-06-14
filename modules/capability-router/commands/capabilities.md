---
description: Print the CCGM capability map - which command/skill to use among overlapping clusters (research, review, planning/execution, debugging, knowledge).
allowed-tools: Read, Glob, Grep
argument-hint: [cluster: research | review | plan | debug | knowledge]
---

# /capabilities - Which Command Do I Use?

CCGM ships overlapping capabilities. This is the decision map. If `$ARGUMENTS` names a cluster, print only that section; otherwise print the whole map. Some entries below may not be installed in this setup - check `~/.claude/commands/` and `~/.claude/skills/` and skip anything missing.

## Research

| Use | When | Notes |
|-----|------|-------|
| `/research` | Default. Broad web research with no setup. | Parallel agents over WebSearch, WebFetch, GitHub CLI, Reddit. **Zero external dependencies.** |
| `/deepresearch` | You want semantic/neural search depth and have an Exa key. | Fans queries out via the **Exa MCP server** (requires `claude mcp add` + Exa API key). Synthesizes from full page contents, not snippets. |

Decision: no API key or want it to just work → `/research`. Need higher-quality semantic retrieval and have Exa set up → `/deepresearch`.

## Review

| Use | When | Scope |
|-----|------|-------|
| `scope-drift` (skill) | At the **start** of any PR review or before claiming a task done. | Compares stated intent (PR body, plan, TODOs) against the actual diff. Run this first, then a quality review. |
| `/ce-review` | Full code-quality review of a PR/diff. | Orchestrates tiered reviewer personas (correctness, testing, maintainability + conditional security/performance/reliability/api-contract/migrations) plus an adversarial lens. Confidence-gated autofix. Modes: interactive/autofix/report-only/headless. |
| `pr-review-toolkit` | You use the external pr-review-toolkit plugin. | Adds scope-drift + Fix-First output (AUTO-FIXED vs NEEDS INPUT) on top of that plugin. |
| `document-review` | Reviewing a **plan/spec/requirements doc** before it ships to execution. | 7 lenses: coherence, feasibility, product, scope-guardian, design, security, adversarial. Not for code. |
| `editorial-critique` | Reviewing **long-form prose** (essays, blog posts, reports). | 8 passes: prose craft, AI-tell detection, argument, conciseness, data, structure, impact, grammar. |
| `design-review` | Reviewing the **visual design of a web page**. | Screenshots at 3 viewports; passes on spacing, typography, responsive, hierarchy, a11y, consistency. |
| `adrev` (skill) | You want to **attack** a plan/doc/PR/idea, not grade it. | Separate agent steelmans the case against, hunts failure modes. Plan targets get findings folded in automatically. |
| `/resolve-pr-feedback` | Existing PR has **review comments to resolve**. | Fetches unresolved threads, clusters them, applies unambiguous fixes, replies + resolves; batches taste questions. |
| built-in `/review` | Quick built-in code review when none of the above is installed. | Claude Code's native command; no CCGM orchestration. |

Decision: code → `/ce-review` (after `scope-drift`). Plan/spec → `document-review`. Prose → `editorial-critique`. UI → `design-review`. Want adversarial pressure → `adrev`. Resolving existing PR comments → `/resolve-pr-feedback`.

## Planning & Execution

| Use | When |
|-----|------|
| `/xplan` | Interactive, human-in-the-loop planning of a new project/feature. Interview → research → tech-stack/scope sign-off → plan → reviews → execute. |
| `/xplana` | Same pipeline as `/xplan --autonomous`: full depth, **no mid-flow prompts**, presents the finished plan at one final gate. |
| `/etp` | You already have a **ready plan or GitHub issue(s)** and want to drive it to done with parallel agents, adversarial PR review, and follow-ups. `etp` executes; it does not research or write the plan. |
| `/mawf` | You have **unstructured feedback** to turn into discrete GitHub issues, then spin up parallel agents to implement them. |

Decision: still figuring out *what* to build → `/xplan` (guided) or `/xplana` (hands-off). Plan/issue ready to build → `/etp`. Pile of raw feedback to triage into issues → `/mawf`.

## Debugging

| Use | When |
|-----|------|
| `/debug` | You are actually fixing a bug/error/failure. Runs a structured reproduce → hypothesize → instrument → diagnose → fix → verify workflow (delegates to a more capable model). |
| `systematic-debugging` (rule) | Always-on methodology, not a command. It is the discipline `/debug` follows; you do not invoke it directly. |

Decision: fixing something → `/debug`. The rule just enforces root-cause-first behavior in every session.

## Knowledge & Memory

| Use | When |
|-----|------|
| `/reflect` | Capture a **personal** learning after a task. Writes the JSONL learnings store on this machine (confidence-scored, decaying). Never leaves your machine. |
| `/compound` | Capture a **team-shared** learning. Writes a structured doc to `docs/solutions/` in the repo, committed and reviewed; `/xplan` and reviews later re-inject it as grounding. |
| `session-history` (skill) | Search **prior session transcripts** for what was tried/failed/decided. Usually invoked by `/compound`, `/xplan`, `/debug` - not run standalone. |
| memory MCP (if configured) | Cross-session structured memory via an MCP server, separate from CCGM's learnings store. |

Decision: just for me → `/reflect`. For the team/repo → `/compound`. "What did a past session do here?" → `session-history`.
