# CCGM Project Story & Knowledge Base

A living knowledge document for the CCGM (Claude Code God Mode) repository: what it is, why it was built, how it evolved, the systems inside it, the decisions behind them, and the lessons learned along the way. This document is maintained alongside the code — update it when a merged PR changes the story (new system, notable decision, interesting root cause, methodology change).

For user-facing documentation, see the [README](../README.md) and the rest of [`docs/`](./). This document is the narrative and rationale layer those docs deliberately leave out.

---

## What CCGM Is

CCGM is a modular configuration system for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Instead of hand-crafting rules, hooks, slash commands, and permissions from scratch, users pick from a catalog of 80 self-contained modules and install them with a single command. Each module packages one coherent capability — a behavioral discipline, a workflow command, an enforcement hook, an entire subsystem — with its own manifest, README, tests, and manual-install path.

At a higher level, CCGM is an answer to a question: **what does a fully-configured, safety-railed, self-improving AI coding environment look like when you treat the configuration itself as a serious software project?** It applies production engineering practice — issue-first workflow, CI, adversarial review, append-only data models, deterministic gates, incident postmortems — to the layer most people treat as dotfiles.

## Project Facts at a Glance

| Fact | Value |
|------|-------|
| First commit | 2026-03-19 |
| Modules | 80 installable (5 categories: core, commands, workflow, patterns, tech-specific) |
| Slash commands | 92 |
| Hooks | 36 Python hooks across 11 Claude Code events |
| Presets | 5 (minimal, standard 16 modules, team, cloud-agent 55, full 76) |
| Commits / issues | 430+ commits, 870+ issues and PRs in the first 4 months |
| Base permission policy | 800+ allow entries, curated deny list, bypass-proof destructive-command blocks |
| Audit engine | 21 audit packs over a deterministic tool spine + LLM triage |
| Test infrastructure | 15 structural test scripts, per-module pytest/bash suites, 5 CI workflows, dual-OS (ubuntu + macos) |
| Documentation | 12-file `docs/` directory (~5,800 lines) with CI-guarded counts |
| Distribution | Interactive bash installer (canonical), non-interactive agent mode, native Claude Code plugin marketplace (generated projection), per-module manual copy |
| License | MIT, public repo with a CI-enforced no-personal-data scan |

Development pace by month: March 36 commits (bootstrap), April 177 (peak build-out), May 68, June 90, July 82, August 36, September 4 through the 2nd — sustained by a solo maintainer orchestrating parallel Claude Code agents, using CCGM itself as the development environment.

---

## Motivation

CCGM grew out of a practical problem: a working Claude Code setup accumulates enormous tacit value — rules that prevent repeated mistakes, hooks that enforce workflow, commands that compress hours into minutes — but that value lives in an unversioned dotfile directory. It can't be shared, can't be selectively adopted, can't be tested, and silently drifts.

The founding moves:

1. **Modularize the configuration.** Every capability becomes a self-contained module with a JSON manifest, so a newcomer can install three modules or seventy, and a power user can diff exactly what changed.
2. **Treat configuration as code.** Manifest schema validation, dependency resolution, CI, per-module unit tests, doc-drift guards, an uninstaller that un-merges rather than deletes.
3. **Encode lessons as enforcement, not advice.** When something goes wrong once, it becomes a rule; when it goes wrong twice, it becomes a deterministic hook that makes the failure structurally impossible.
4. **Close the loop.** The system observes its own friction (autoheal), mines its own session history (dreaming), and proposes its own improvements — behind human gates and hard safety rails.

The result is as much a methodology artifact as a config repo: a worked example of running an autonomous-agent development practice with real guardrails.

## Design Philosophy

A few principles show up everywhere in the codebase:

- **Minimize dependencies.** The installer TUI is pure bash with ANSI escapes (an early external TUI dependency was removed the same day a flag-parsing bug surfaced). Hooks are Python stdlib only. The hard requirements are git, python3, jq, and Claude Code itself.
- **Deterministic where possible, latent where necessary.** Anything a script can compute exactly (counts, timestamps, parsing, gating decisions) is done by a script; the model is reserved for judgment. This is codified as a rule (`latent-vs-deterministic`) and practiced structurally: the memory miner is pure stdlib, the eligibility gate that decides automated memory writes contains no LLM call at all, and background analyzers call the Anthropic API directly rather than spawning nested agent runtimes.
- **Default-off for anything that writes, alerts, or spends money.** Autoheal's real-time alerts, auto-apply, and email; dreaming's optimistic integration and its composite gate — all ship disabled, each behind a deliberate activation flow, never a buried JSON edit.
- **Fail-open vs fail-closed is a per-gate decision, made explicitly.** Safety hooks fail open on broken git state (a broken repo must never brick the session) — except the one check whose failure would *widen* a gate, which fails closed. Eval gates and circuit breakers fail closed. Every choice is documented with its reason.
- **Separate the judge from the implementer.** Reviewers get the spec and the diff, never the implementer's rationale; the visual judge in Argus never sees the code change; subagent self-reports are claims, not evidence. Coupled self-grading inflates grades, so the architecture prevents it.
- **Docs drift is a bug.** Module and command counts in docs are derived from the repo and CI-guarded; a `/docupdate` pass is mandatory after every merge; stale claims fail the build.
- **Safety must not depend on a report being read.** Prevention (caps, gates, breakers, decay) works with zero human reads; reading is only ever required for *undo*.

---

## Architecture

### The module system

Every module is a directory under `modules/{name}/` with:

- `module.json` — manifest: name, description, category, scope (global/project), dependencies, file map (each file typed as `copy`, `link`, or `merge`, optionally template-expanded), tags, and interactive `configPrompts`.
- `README.md` — docs including manual copy-paste installation, so the installer is never mandatory.
- Content directories mirroring install targets: `rules/` (auto-loaded behavior), `commands/` (slash commands), `agents/` (reusable subagent prompts), `skills/` (SKILL.md packages), `hooks/` (Python event hooks), `lib/`, `scripts/`, and `settings.partial.json` fragments.

Dependencies resolve via depth-first topological sort with cycle detection — selecting `xplan` automatically pulls `multi-agent`, `adversarial-review`, `cross-agent-review`, and their transitive deps.

### The installer

`start.sh` runs a 15-step flow: prerequisite check (with package-manager auto-install offers), config collection (GitHub username via `gh`, code dir, timezone), scope selection, module/preset selection, dependency resolution, per-module config prompts, preview, confirm, timestamped backup, install, manifest write, verification (files exist, no unexpanded `__PLACEHOLDER__` tokens, `settings.json` parses), optional shell aliases, next steps.

Notable mechanics:

- **Settings deep-merge.** Multiple modules contribute to one `settings.json`; a custom `jq` merge concatenates and dedupes `allow`/`deny` arrays, concatenates hook-event arrays, and deep-merges the rest — so modules compose without clobbering each other. The uninstaller *un-merges* CCGM's keys instead of deleting the file.
- **Template variables** (`__HOME__`, `__USERNAME__`, `__CODE_DIR__`, `__TIMEZONE__`, `__DEFAULT_MODE__`) expand in config files only — rule files stay generic prose.
- **Three install modes**: copy (default), symlink (`--link`, for developing CCGM against a live install), and non-interactive (`CCGM_NON_INTERACTIVE=1` + env vars, for agents and CI).
- **`--add <module>`** — an idempotent fast path that installs additional modules into an existing setup, inheriting scope and link mode from the recorded manifest.
- A **manifest** (`.ccgm-manifest.json`) records exactly what was installed, enabling surgical update, drift detection, and uninstall.

### Distribution surfaces

1. **Bash installer** — canonical.
2. **Agent-paste install** — a copy-paste block in the README that a fresh Claude Code session executes: detect environment, clone, recommend a preset, install non-interactively, verify, report. The install instructions are themselves written for an AI operator.
3. **Native plugin marketplace** — CCGM projects its modules into a Claude Code plugin marketplace (`.claude-plugin/marketplace.json` + per-module `plugin.json`), fully *generated* from the module manifests by a Python generator with a CI check. The bash installer remains canonical because plugins can't perform the deep settings merge or install the always-loaded global context.
4. **Manual copy** — every module README documents raw `cp` commands.

### Presets

Named module collections for different personas: `minimal` (get started), `standard` (most users — includes the safety hooks, identity, memory read path), `team` (adds review tooling and shared-knowledge modules), `cloud-agent` (55 modules for autonomous/headless VM agents), `full` (every stable module). Preset membership is CI-checked: a stable module in zero presets fails the build unless allowlisted.

---

## Development Timeline

### March 2026 — Bootstrap (36 commits)

Day one shipped a working system: 15 modules, 4 presets, the installer core (TUI, template expansion, settings merge, backup/restore), and a test suite with CI. The first week's iterations were installer UX: prerequisite auto-install, labeled prompts, protected-branch defaults, an opt-in daily update-check hook — and the removal of the external `gum` TUI dependency in favor of pure bash after a flag-parsing bug, an early enactment of the minimize-dependencies principle against the project's own tooling. By month end: nine new modules adapted from community skill collections, the brand-naming research pipeline, the workspace-based multi-agent system with port registry and CSV issue tracking, and an 8-file docs directory.

### April 2026 — Peak build-out (177 commits)

The busiest month, in several waves:

- **Session tooling**: the statusline monitor; `/startup` (which would be rewritten four times — see Iteration Case Studies); live-session discovery so parallel agents see each other; the identity module (`soul.md` + `human-context.md`); the slim global CLAUDE.md.
- **Planning**: `/xplan` overhauled into an interactive interview-driven research-plan-execute framework; `/docupdate` born and immediately made a post-merge ritual.
- **Infrastructure week**: the Go/tmux agent-manager TUI (later deprecated) and cloud-dispatch — a full Hetzner Cloud pipeline with Terraform infrastructure, a Packer golden-image build, VM lifecycle scripts, secret injection, workspace provisioning, tmux agent launchers with jitter and auto-shutdown, and cost/budget controls.
- **The discipline wave (April 16–17)**: existing rules hardened into a house style — Iron Law header, rationalization table, red flags, four-state completion status — and roughly twenty modules landed in 48 hours: skill-authoring, rule-authoring, git-worktrees, compound-knowledge, agent-native, session-history, document-review (7-lens plan gate), ce-review, brainstorm, pr-feedback, todos, onboarding, ship-readiness, the careful/freeze/guard safety hooks, config-change-detection, and the first structured JSONL learnings store with confidence decay.
- **Late April**: supersede chains and the compaction guard for the learnings store; `/xplana` (fully autonomous planning); the `latent-vs-deterministic` rule; `/skillify`; per-module unit test runner; `ccgm-doctor` (install auditor with a command-overlap "dry" detector); xplan's highlight-and-comment web review UI.

### May 2026 — Autoheal and philosophy (68 commits)

- **A philosophy wave** (May 2): rules distilled from studying how top practitioners work — "outsource thinking, not understanding," verifiable-domain self-classification, spec-is-the-artifact, an intake check for apps that shouldn't exist, a mental model for agent supervision — plus `/launch` (one-page spec → deployed site) and the YouTube transcript-and-implications pipeline.
- **Autoheal** (May 18, one day, epics 3–12): the self-healing observability loop. Five hooks capture permission events, tool failures, and user corrections to locked, redacted JSONL; a daily analyzer clusters events and calls the Anthropic API directly (no nested agent runtime — a deliberate attack-surface decision) under a cost cap; a digest proposes configuration fixes; opt-in layers add real-time security alerts, confidence-gated auto-apply on feature branches, Resend email, and a webhook publisher. Follow-ups scoped API keys to a mode-0600 env file (never shell rc — both a billing and an exposure decision) and aligned the chain on UTC dates.
- Also: the canonical-clone auto-sync hook, `/sds` (autonomous session shutdown sequence), the richer `/handoff` with a copy-paste kickoff prompt, **Argus** (the visual-ATDD convergence loop), the `--add` installer flag, and `/etp` (execute-the-plan).

### June 2026 — The audit engine and hardening (90 commits)

- **The audit engine rebuild** (June 9–10): `/audit` went from nine category prompts to a pack-based architecture — 21 packs (security, secrets, dependencies/supply-chain, correctness, architecture, TS/React, testing, docs, performance, privacy, observability, reliability, CI/CD, data-migrations, infra-IaC, accessibility, API-contract, TOS-compliance, two CCGM-specific packs, and code quality) with JSON schemas for packs and findings, a Phase-0 ecosystem detector gating which packs apply, a **deterministic tool spine** (eslint, gitleaks, squawk, sqlfluff, checkov behind injection-safe, secret-redacting normalizers), spine→LLM triage and merge, stable finding fingerprints, baseline/delta classification, a suppression system (`.auditignore.yaml` + inline comments), provenance headers with CODEOWNERS routing, diff-scoped mode, and bash-3.2 portability.
- **Security hardening of the permission layer**: dangerous `sudo`/`eval`/`exec` auto-allows removed; per-segment deny matching with a bypass-proof destructive-command hard block; matcher-bypass auto-allows removed; the personal-data scan rewritten in Python after a macOS BSD-grep segfault and extended with generic secret/PII shapes.
- **Meta-infrastructure**: derived, CI-guarded module/preset counts; the hook composition dispatcher (declarative precedence for multiple hooks on one event, equivalence-gated rollout); the generated plugin marketplace; capability-router (a decision map for overlapping command clusters); relevance-scoped rule injection (opt-in) with a tiered always-on safety core; fresh-context reviewer phases with results-in-files return paths.
- **xplan's earlier adversarial review loop** (historically 3 constructive + 3+ adversarial passes; current counts are selected upfront) and, after a production 429 incident, the **subagent concurrency rule** — heavy-agent fan-out capped at 4, waves not bursts — propagated into all 19 fan-out skills.

### July 2026 — Memory, worktrees, and vetting (61 commits)

- **Branch-guard** (July 1): a hard PreToolUse gate blocking edits/staging/commits while HEAD is on the default branch — firing *before the first edit*, because uncommitted work on main had actually been destroyed by a sync.
- **The durable memory system** (July 2, eight epics in one day): learnings store v2 (append-only op-events, per-agent shards, CAS, transcript-verified origin binding, promotion guard), the deterministic transcript miner, SessionStart injection, the git sync substrate, the map-reduce dreaming analyzer, the apply path with `/dream-*` commands and a nightly launchd scheduler, a with/without-memory A/B eval harness, and read-only reconciliation against the harness's own auto-memory.
- **Optimistic auto-integration** (July 5, eight more epics): per-op-kind postures, the 24-hour dwell window, per-slug blast-radius caps, batch-anomaly detection, a windowed self-healing circuit breaker, poisoning negative-controls in the eval gate, the daily integrated-memories report, `/dream-review` + one-command rollback, and the activation forcing-function.
- **The composite eligibility gate** (July 7–8): a deterministic, no-LLM admission waterfall for automated memory writes — static floor, legacy escape, non-compensatory origin gate, and a four-signal weighted score re-derived from transcripts at apply time — shipped with an adversarial poisoning analysis and red-team test suite. A field-level structural canary replaced version allowlists for transcript-schema drift.
- **Worktrees as default parallel isolation** (July 13): after a 237 GB disk incident from orphaned build trees, git worktrees became the standard per-unit isolation with *enforced* teardown and a safe janitor (`/worktree-sweep`) that classifies precisely which worktrees are safe to remove.
- **Model-vetting** (July 19): a security gate for integrating any new AI model — weights provenance, file-format safety, license/data terms, serving-path supply chain, and staged agentic access — written after observing an "announced ≠ released ≠ verified" gap in a flagship open-weights launch.

### Late July – early August 2026 — Docs hygiene, orrery, and install-time hardening (48 commits, July 20 – August 4)

- **Docs and small modules** (July 20–22): a new `CCGM ADHD` output style (adapted from an MIT-licensed community skill) plus an Actionability section folded into the default `CCGM Terse` style; the `writing-system` module (Orwell's six rules as the always-on prose standard, `/rewrite`); `ask-context` — a hard PreToolUse gate blocking `AskUserQuestion` calls whose context the user cannot actually see, closing the recurring failure of a question asked from context that lived only in a thinking block or collapsed tool output.
- **README catalog and orrery** (July 28–30): the module catalog gained a per-module commands column and an alphabetical-order guard, and the 12 stable commands and hooks it was missing got documented; `orrery` shipped in six epics over two days — parallel read-only scout agents deep-dive a codebase and render a zoomable, embeddable system-design map as one self-contained HTML file, four zoom tiers, file links pinned to an anchor SHA, with an incremental `/orrery update` path — the same one-day-many-epics delivery shape as July's durable memory system.
- **Install-time and shell-parsing hardening** (August 2–4): three separate bugs sharing one root shape — a piped consumer SIGPIPE-killing a still-writing producer under `set -o pipefail`, bash's builtin `echo` silently swallowing a literal `-n`, and `grep -c` exiting 1 on a zero count under `set -e` — were traced across the structural suite and all 33 bundled audit-skill suites and fixed with herestrings, `printf '%s'`, and `|| true` guards (full detail in Incidents & Lessons, below); the README install-block guard grew a directory-bootstrap check and a disk-resolved over-copy check after both blind spots let a from-scratch-install regression and an over-broad `cp -R` ship green; and `live-testing-guard` shipped after a July 30 incident where a plan-mandated dictation preflight silently swapped every microphone dictation for a canned fixture on the dev machine mid-run — the rule confines live/UI/app testing to a dedicated runner behind a plan-recorded grant, because the incident it answers corrupted input with no crash and no failed assertion.
- Also: `code-quality`'s simplest-implementation and no-backward-compat-shims rules; the interactive installer's preset menu and its backup set both re-derived from `presets/` and module manifests instead of hand-maintained lists.

### August 2026 (mid-to-late) — Presets contract, ccgm-site, and advisor-mode (8 commits, August 12–31)

- **A machine-readable preset contract** (August 12): `docs/preset-descriptions.json`, seeded from `docs/presets.md`'s prose and key-set-checked against the live preset list, gives the (then-upcoming) ccgm-site something to render — presets had never had a machine-readable description before.
- **ccgm-site's deploy hook** (August 13): a companion site repo got a guest CI workflow in this repo — on every push to main, POST the site's Cloudflare deploy hook, then poll its live `modules.json` for an advanced `generatedAt`/`sourceSha` before calling the rebuild real; skip-with-notice when the secret is unset, `continue-on-error` throughout, and a stale deploy opens an issue on this repo rather than touching the site's own credentials.
- **advisor-mode** (August 20, then 30–31; the 79th module): a per-session posture that turns an expensive orchestrator (Fable/Opus) into a pure delegator, held to it by a hard PreToolUse gate rather than a prompt (see Major Systems, below). The follow-ups moved state from one machine-global flag file to one per session — a single session's `/advisor off` had been silently dropping the gate for the other nine of ten sessions running in parallel — added auto-on at SessionStart with an opt-out and idle-session garbage collection, and opened the guard to read-only recon (tool version probes, shell grouping tokens, allowlisted command substitution) it had been wrongly blocking.

### September 2026 (through September 2) — Cloudflare reversal and the advisor-guard's shell-parsing model (4 commits)

- **Cloudflare Pages is API-creatable.** A live run in a sibling project overturned the standing assumption — baked into the `cloudflare` rule, `common-mistakes` #8, and `/launch` — that the dashboard's Connect-to-Git flow was the only way to create a Git-connected Pages project: `POST .../pages/projects` with `source.type: "github"` does it, followed by a separate deployment-trigger call and its own poll step. The rewrite went through three adversarial review rounds after a reviewer caught the source research and the live transcript disagreeing on trigger behavior.
- **advisor-guard's argument model closed its last shell-parsing gap.** Every flag and predicate check had read an argument's literal text, so a quoted, ANSI-C-quoted, or expansion-carried flag reached real bash unseen. A differential harness — spell every way of disguising a mutating flag against every command that acts on one, run each through the guard and real `bash -c` in a throwaway sandbox, assert that whatever mutated the sandbox was denied — found the gap and, across two review rounds, closed it from 27 live bypasses to zero (the full incident is below, in Incidents & Lessons).

---

## Major Systems

### The memory system (`self-improving` + `dreaming`)

The flagship subsystem: durable, cross-session memory with a hard split between a free, always-safe **read path** and an opt-in, token-spending **write path**.

**Read path.** Learnings (patterns, pitfalls, preferences, architecture facts, tool gotchas, ops facts) live in an **append-only op-event log** — five op kinds (`add`, `verify`, `contradict`, `deprecate`, `supersede`), one JSON line each, per-agent shards so concurrent writers never touch the same file. Current state is *reconstructed* by a deterministic two-phase fold at read time (dedupe by op id → total-order by timestamp+id → seed heads → apply counter-ops, deferring and surfacing orphans rather than dropping them). Effective confidence is computed on read: `clamp(confidence + min(uses×0.25, 2) − contradictions×1.5, 0, 10) × 0.5^(age/90d)` — reuse boosts but caps, contradiction cuts hard, age halves. Staleness is a separate axis. A SessionStart hook injects the current project's top-ranked learnings (token-budgeted, max 8) into each fresh session; a `verify` op when a learning pays off again is the system's key success signal.

**Integrity layers.** A write-time prompt-injection sanitizer neutralizes instruction-shaped content (wrapped, not stripped — readable but defanged); read-time validation re-runs on *every* projection and quarantines failing rows by id without ever mutating another writer's line (the load-bearing property — it catches every ingestion path, including raw git operations that bypass the sync tool); a compaction guard rejects rewrites that drop more than 5% of fact-bearing tokens.

**Cross-machine sync.** The store is a git repo with `merge=union` shards. `pull` is merge-only — never rebase, after an empirical finding that a rebase-abort recovery path silently destroyed a concurrently-appended line. `revert` is a computed line-set-difference rather than `git revert`, because the union merge driver's whole job ("never let a line disappear") silently defeats a plain revert. Both are sound *because of* the append-only invariant.

**Write path (dreaming).** A nightly, cost-capped launchd pipeline: a pure-stdlib miner extracts friction events, user corrections, and token economics from session transcripts (watermarked, redacted secrets-then-PII, budget that never fully drops a friction cluster, and a structural canary that fails loud on real schema drift while passing benign version bumps); a map-reduce analyzer (direct API calls, per-slug map, cross-slug reduce, preflight cost plan under a daily cap) emits evidence-tagged **per-change proposals**, never whole-store swaps. Human-gated apply (`/dream-apply`) is the default. The opt-in optimistic engine writes immediately but holds rows behind a 24h dwell window before any read path can see them, bounded by per-slug caps, an eviction-concentration anomaly check, a cross-night accumulation signal (the one control that catches a patient one-add-per-night attacker), a windowed self-healing circuit breaker, and a nightly A/B eval gate that fails closed. Global promotion is human-only through exactly one code path, with writer identity derived from the transcript's own recorded cwd — never a spoofable env var.

**Honest engineering note**: the eval gate deliberately keeps optimistic integration closed until mined memory demonstrably beats a full-context baseline — the capability is wired, tested, red-teamed, and *off*, which is itself the point.

### Autoheal (self-healing observability)

The same capture-analyze-propose shape as dreaming, pointed at permission events instead of transcripts. Hooks log every permission decision, tool failure, and detected user correction (redacted, fcntl-locked, append-only); a contextual auto-allow suppresses prompts for signatures approved ≥3 times across ≥2 sessions; a daily analyzer clusters the log and proposes settings/hook fixes; `/permission-fix` does in-session root-cause analysis of the latest friction. Auto-apply (opt-in) is gated on confidence ≥9, blast-radius ≤1, a fixed proposal kind, *and* a deterministic eval/regression gate that replays proposed allow-rules against fixture scenarios — a proposal must fix a friction case with zero silently-auto-allowed deny cases. It creates feature branches and never pushes.

### The audit engine

`/audit` is a pack-based codebase auditor: 21 packs, each a manifest + checks with severity/confidence rubrics, gated by a Phase-0 project-shape detector so only applicable packs run. Findings are schema-validated JSONL with stable fingerprints, enabling baseline/delta runs ("what did this PR introduce?"), suppression files, and CODEOWNERS-routed provenance. The two-stage detection model — a deterministic tool spine (eslint, gitleaks, squawk, sqlfluff, checkov, wrapped in injection-safe, secret-redacting normalizers) feeding LLM triage for what static tools can't judge — keeps deterministic work out of latent space and LLM effort focused on judgment.

### Multi-agent development

CCGM assumes parallel agents as the normal working mode and provides the coordination substrate:

- **Worktree isolation (default)**: each delegated unit of work gets an ephemeral git worktree on a feature branch, torn down on merge, with `/worktree-sweep` as the janitor — it removes only provably-safe worktrees (clean, on a branch, or detached-but-reachable) and preserves anything with uncommitted work, in-progress operations, or ref-orphan commits.
- **Workspace/clone model (for the cases worktrees can't serve)**: `{repo}-workspaces/{repo}-wX/{repo}-wX-cY` clone groups with per-clone identity (`.env.clone`), a port registry preventing dev-server collisions, and hook-driven CSV issue tracking (claims on branch creation, updates on commit/PR/merge/close).
- **Dispatch methodology** (`subagent-patterns`): spec-driven delegation (objective/context/constraints/deliverable), pass-paths-not-contents, a four-state completion protocol (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT), and a two-stage review where spec-compliance gates code-quality and reviewers never see the implementer's rationale.
- **Concurrency limits**: heavy-agent fan-out capped at 4 concurrent (waves, not bursts) after a measured incident where ~10 simultaneous max-effort agents attempted ~1.4M tokens in 27 seconds and tripped a server-side throttle that failed the entire burst.
- **Cross-provider review** (`cross-agent-review`): a local native Claude/Codex coordinator supplies frozen evidence, validates attributable findings, and retains bounded counters. Explicit cross-provider opt-in adds provider-aware workflow gates for X-Plan/adrev/ETP; personal lead review is the default, and provider failure stops only the optional run; `REVIEWED` transport output alone never authorizes execution or merge.
- **Cloud dispatch**: the Hetzner pipeline (Terraform + Packer golden image + lifecycle/secret/provisioning scripts) for delegating issues to VMs entirely off the local machine.

### Planning and execution

A graduated stack from idea to shipped code:

- `/ideate` (Socratic refinement) → `/brainstorm` (design-before-code gate) → `/xplan` (interview-driven deep research + plan + parallel-wave execution, with a source-freshness guard, a no-placeholder self-review, a web-based highlight-and-comment review UI, and a review gauntlet: personal lead constructive review plus upfront-selected 1–3 adversarial passes (default one), with native provider alternation only when explicitly opted in) → `/etp` (execute a ready plan or GitHub issues end-to-end with a bounded post-PR CI-fix loop) → `/xplana` (the autonomous variant after its one review-count setup choice).
- Plans are held to four autonomous-execution tenets, enforced by the adversarial reviewer: minimal and edge-bucketed human involvement, a follow-up-completion contract, enough decision context that unplanned work doesn't need a human, and a comprehensive autonomous E2E test suite over every testable surface.
- `/adrev` generalizes adversarial review to any entity — plan, doc, PR, directory, or a stated concept — attacking premises, hunting failure modes, and steelmanning the strongest counter-case.
- `/document-review` fans a plan out to seven role-specific reviewers (coherence, feasibility, product, scope, design, security, adversarial) with structured JSON findings.

### The safety-hook layer

Deterministic Python hooks that make classes of mistakes structurally impossible rather than advised-against:

| Hook | Gate |
|------|------|
| `branch-guard` | Hard-blocks edits/staging/commits on the default branch, *before the first edit*; resolves symlinks and `git -C` targets; exempts rebase/merge states, unborn HEAD, no-origin repos, and gitignored paths (that one check fails closed — it widens the gate) |
| `enforce-git-workflow` | Commit-message format, protected-branch commit/push blocks |
| `enforce-issue-workflow` | Advisory issue-first reminder on work-request prompts |
| `auto-approve-*` | Safe read-only operations skip permission prompts |
| `check-careful` / `check-freeze` | Session-scoped modes: extra confirmation on risky ops; scope-lock edits to a directory |
| `hook dispatcher` | Declarative precedence composition when multiple hooks claim one event, rolled out behind an equivalence gate |
| `sync-ccgm-canonical` | Auto-pulls the canonical clone after CCGM PR merges so symlinked installs update immediately |
| `port-check`, `agent-tracking-*`, `orphan-process-check` | Multi-agent coordination and cleanup |
| `reflection-trigger`, `precompact-reflection`, `learnings-inject` | The memory loop's capture nudges and injection |
| `advisor-guard` | PreToolUse exit-2 hard block on the main agent's file edits and non-orchestration Bash while advisor mode's per-session flag exists; subagent calls and orchestrator work-product paths pass, `ADVISOR_DIRECT=1` is the one-off hatch |
| `advisor-posture` | UserPromptSubmit: injects the delegate-don't-implement posture (and the session id) every turn the flag exists |
| `advisor-session-start` | SessionStart: creates this session's advisor-mode flag unless opted out, migrates the legacy single-file flag, and garbage-collects flags whose session has no transcript or has sat idle 3+ days |
| `advisor-session-end` | SessionEnd: removes this session's advisor-mode flag |

A single escape hatch (`ALLOW_MAIN_COMMIT=1`) opens the related gates consistently for intentional main-only operations.

### Advisor mode

**What it is.** A per-session posture for expensive orchestrator models (Fable/Opus): `/advisor on` turns the main agent into a pure delegator — it writes specs, dispatches cheaper implementer agents, personally reviews their diffs for spec compliance then quality, triages findings, delegates fixes, and merges, but never edits source itself. `/etp` already runs this loop for plan- and issue-shaped work; advisor mode routes ad-hoc requests through the same discipline instead of letting the orchestrator implement inline. Optional X-Plan/adrev/ETP native runs allow at most two correction cycles within bounded calls/time/input bytes and cannot extend automatically. Provider failure preserves the optional run’s evidence; the lead can separately judge delivery with normal checks without calling that run approved.

**Enforcement.** A PreToolUse hook hard-blocks the main agent's file edits outside a short list of orchestrator work-product paths (`~/.claude/`, temp/scratchpad roots, `~/code/plans/`, `~/code/docs/`, worktree checkouts, plan-mode files) and default-denies Bash to a read-only-plus-orchestration allowlist (read-only git; branch/worktree lifecycle; `gh` PR/issue/run/label management including merge). Denials use exit 2 — the same bypass-surviving convention as branch-guard, because a JSON `permissionDecision: deny` does not survive bypass mode — and a hook-input discriminator (`agent_id`/`agent_type`, present on subagent calls, absent on the main agent's) lets delegated implementers pass untouched; The opt-in pilot adds one narrow orchestration exception for the installed cross-agent-review policy shim, whose allowed actions record evidence and dispatch restricted reviewers. Source edits and test execution remain delegated; `/advisor off` and the one-off `ADVISOR_DIRECT=1` hatch still control direct implementation.

**Session lifecycle.** State lives at `~/.claude/advisor-mode/<session_id>`, one flag per session rather than one machine-global file — the fix for an incident where a single session's `/advisor off` had silently dropped the gate for the other nine of ten sessions running in parallel. Every session now starts in the mode (`CCGM_ADVISOR_AUTO=false` opts out); a SessionStart hook creates the flag, migrates the old single-file layout, and garbage-collects flags whose session has no transcript or has sat idle more than three days, while a SessionEnd hook removes the flag when the session ends. Only compaction is exempt from the auto-on, so a deliberate `/advisor off` survives it but a resume or `/clear` re-arms the mode.

**The argument-reading model.** Bash turns a typed command line into `argv` through seven steps; the guard's normalizer reproduces three of them — quote removal, backslash-escape removal, and substitution of a variable the hook process can itself resolve — so a flag spelled `'-i'`, `\-i`, `$'-i'`, or `$"-i"` all reach the same check as `-i`. It refuses the other four outright, for any command that is not read-only: brace expansion, `$IFS` word splitting, pathname globbing, and an undecodable `$'...'` escape each turn one typed word into several `argv` words that no per-word check can represent, so rather than model them the guard denies. Getting there took three follow-up PRs — one closing holes an earlier review reproduced by hand, one closing two gaps that PR had left named but unfixed (`$VAR` and `$'...'` carriers) — and finally this normalizer, proven by a differential test harness built for the job: it spells every mutating flag every way against every command that acts on one, runs each through both the guard and real `bash -c` in a throwaway sandbox, and asserts that whatever mutated the sandbox was denied. Building it found 27 live bypasses in the guard as it stood; a second adversarial review round on that same PR found 5 more; the shipped head has zero.

### Argus (visual ATDD)

A closed-loop harness for developing UI against a per-feature design spec where the agent signs off on its own work — trustworthy only because every judgment is externally grounded: deterministic gates (build/lint/type/contrast/a11y/snapshot/flows) are the floor; the judge is a *separate* subagent that sees the spec, reference image, design tokens, render, and structured probe but **never the diff**; two oracles (functional probe + screenshot) must agree; convergence is bounded (two consecutive passes to sign off, three attempts per dimension then freeze-and-document). Platform-agnostic via a sensor/gates adapter contract, with a web adapter built in.

### Supporting systems

- **Statusline**: a single-line bash session monitor — model tier + reasoning-effort indicator, multi-clone identity, git branch, context-vs-auto-compact-budget percentage with compaction warning, and 5-hour/7-day rate-limit bars with reset countdowns.
- **Session lifecycle**: `/startup` (repo-aware dashboard: git state, sibling sessions, tracking claims, recent merges, an intelligent next-step summary), `/handoff` (structured session handoff with a copy-paste kickoff prompt), `/sds` (autonomous shutdown: commit, update issues, reflect, handoff, broadcast), `/recall` (search prior session transcripts across all clones of a repo), `/checkpoint`.
- **Research**: `/research` (zero-dependency parallel WebSearch/WebFetch/GitHub/Reddit agents) and `/deepresearch` (Exa-MCP-backed multi-query semantic research); a heavier local-first companion pipeline lives in a separate repo (Ollama + self-hosted SearXNG + Claude synthesis).
- **Content tooling**: `/editorial-critique` (8-pass long-form review including AI-tell detection), `/design-review` (6-pass visual review at 3 viewports), `/transcript` (yt-dlp extraction + an implications doc written against project memory), brand-naming pipelines with domain/trademark/app-store checks.

---

## The Rules & Discipline Layer

The `patterns` modules encode engineering discipline in a deliberate house style — an **Iron Law** one-liner, the methodology, a **rationalizations table** ("you are about to say… / the reality is…") that names the exact excuses that precede violations, and **red flags** for self-interruption. Writing rules this way is itself a documented skill (`rule-authoring` treats rules like TDD: pressure-test with adversarial scenarios before shipping).

Highlights of the catalog:

- **Autonomy + Confusion Protocol** — execute end-to-end without narrating steps for the user; but at a genuine architectural fork, stop and ask with named options. Autonomy is executing confidently, not guessing confidently.
- **Completeness ("boil the lake")** — agent-assisted development compresses the cost of doing the whole job to minutes, so the 90% shortcut is no longer rational; a 1–10 completeness rubric with an explicit boundary against gold-plating.
- **Verification / evidence-before-claims** — no completion claims without fresh execution evidence; a table of what counts as evidence per claim; subagent self-reports are never evidence.
- **Systematic debugging** — no fixes without root-cause investigation, with companion techniques: root-cause tracing (fix at the origin, not the symptom), defense-in-depth (four independent validation layers), condition-based waiting (flaky tests are timing bugs; wait on conditions, not durations), and a three-strike escalation rule.
- **TDD + testing anti-patterns** — red-green-refactor with gate functions against the five failure modes agents default to under pressure (testing the mock, test-only production methods, mocking unread APIs, incomplete mocks, tests-as-afterthought).
- **Latent vs deterministic** — the classification discipline behind most of the architecture above.
- **Receiving code review** — verify before implementing, no performative agreement, reasoned pushback with evidence.
- **Change philosophy** — redesign as if the requirement had been foundational, rather than bolting on.
- **Common mistakes** — a living record of recurring failure patterns (shallow monorepo exploration, branching without checking open PRs, platform-specific traps) with the concrete behavior change each demands.
- **Model vetting** — the staged-access security gate for new models (provenance → format safety → license/terms → serving path → staged agentic access from chat-only to sandboxed to reviewed-implementer).
- **Writing system** — Orwell's six rules (1946) as the always-on prose standard, added July 2026 after the observation that banning AI-tell words one at a time ("no delve", "no em dashes") treats symptoms while every README still ships in the same voice. The rule governs prose only (never code or technical terms), `/rewrite` applies it to existing text, and `/editorial-critique`'s detectors now cite the same six rules as their baseline — one standard, two enforcement points.
- **Advisor mode** — a per-session posture, not just a rule: while `/advisor` is on, a hard PreToolUse gate makes "delegate, never implement" mechanical instead of advisory, closing the exact gap prior-art research found in production orchestrators — a prompt-only version of this discipline holds until an integration-pressure moment, then gets quietly overridden.

## Command Surface

87 slash commands, grouped:

| Cluster | Commands |
|---------|----------|
| Git & GitHub | `/commit`, `/pr`, `/cpm`, `/gs`, `/ghi` |
| Planning & execution | `/xplan`, `/xplana`, `/xplan-status`, `/xplan-resume`, `/etp`, `/mawf`, `/ideate`, `/brainstorm` |
| Review & quality | `/adrev`, `/ce-review`, `/document-review`, `/audit`, `/design-review`, `/editorial-critique`, `/rewrite`, `/resolve-pr-feedback`, `/scope-drift`, `/ship-ready`, `/pwv` |
| Testing | `/atdd`, `/test-vision`, `/e2e`, `/argus`, `/user-test` |
| Memory & learning | `/reflect`, `/consolidate`, `/retro`, `/dream`, `/dream-digest`, `/dream-apply`, `/dream-review`, `/dream-scorecard`, `/compound`, `/compound-refresh`, `/skillify` |
| Autoheal | `/autoheal`, `/autoheal-digest`, `/autoheal-toggle`, `/autoheal-snooze`, `/autoheal-apply`, `/permission-fix`, `/permission-audit` |
| Session lifecycle | `/startup`, `/handoff`, `/sds`, `/checkpoint`, `/recall` |
| Safety modes | `/freeze`, `/unfreeze`, `/guard`, `/advisor` |
| Worktrees | `/worktree-start`, `/worktree-finish`, `/worktree-sweep` |
| Multi-agent & remote | `/workspace-setup`, `/dispatch`, `/dispatch-status`, `/dispatch-stop`, `/vm-manage`, `/onremote`, `/agents` |
| Research & content | `/research`, `/deepresearch`, `/brand`, `/brand-check`, `/transcript`, `/copycat` |
| Docs & onboarding | `/docupdate`, `/onboarding`, `/walkthrough`, `/capabilities`, `/promote-rule`, `/pressure-test` |
| Misc | `/debug`, `/launch`, `/ccgm-sync`, `/cws-submit`, `/todo-create`, `/todo-triage`, `/todo-resolve`, `/make-interfaces-feel-better`, `/agent-native-audit` |

## Engineering Decisions Log

Decisions with their rationale, in roughly the order they were made:

1. **Pure-bash TUI, no external TUI dependency.** A flag-parsing bug in the third-party tool plus the project's own minimize-dependencies rule → removed on day one and rewritten with ANSI escapes.
2. **Public repo, zero personal data — enforced, not promised.** A CI scan blocks usernames, paths, and secret/PII shapes; rewritten from grep to Python after a BSD-grep segfault; identity files are templates so the reverse-sync tool can't leak personal content.
3. **Issue-first, hook-enforced workflow — applied to itself.** Every change to CCGM, including docs and one-line fixes, flows issue → branch → `#N:`-formatted commit → PR → squash merge. The hooks that enforce this are themselves CCGM modules.
4. **Docs counts derived, not written.** After repeated stale-count bugs, module/preset counts in docs are computed from manifests and CI-guarded; `/docupdate` after every merge is a repo law.
5. **Direct API calls for unattended analyzers.** Autoheal and dreaming call the Anthropic Messages API via curl instead of spawning nested Claude Code agents — a smaller attack surface (no exec escape), cheaper, and schedulable under launchd. API keys live in scoped 0600 env files, never shell rc (which would silently bill every SDK client on the machine).
6. **Everything that writes, alerts, or spends is default-off** behind a deliberate, logged activation flow (`memory-setup.sh`, `/autoheal-toggle`) — a public module must not surprise its installer.
7. **Append-only op-events + union merge for memory** — the storage design that makes multi-writer sync conflict-free by construction, makes rollback a computable line-set difference, and keeps a full audit trail. Chosen over a mutable record store precisely for these properties.
8. **Merge-only pull; custom revert.** Empirical testing showed `git rebase --abort` destroying an appended line and `git revert` being silently defeated by the union merge driver → both replaced with mechanisms that are provably sound under the append-only invariant.
9. **No LLM in automated write decisions.** The composite eligibility gate that admits memories to auto-integration is a deterministic scoring waterfall whose signals are re-derived from transcripts at apply time — model-assigned confidence is one input among four, and the origin gate is non-compensatory.
10. **Judges never see the diff.** Argus's judge, the two-stage reviewers, and document-review lenses all receive the spec and artifact, never the implementer's rationale — grading the defense of a change instead of the change inflates sign-off.
11. **Bash installer canonical; marketplace generated.** The native plugin path can't do the deep settings merge or always-on context, so it's a projection built by a generator with a CI parity check — never hand-edited, never the source of truth.
12. **Worktrees over clones for parallel delegation; teardown mandatory.** Ephemeral per-unit isolation with enforced cleanup replaced permanent clone farms after the disk incident; clones remain for the enumerated cases worktrees can't serve (long-lived agents, per-branch ports, cross-machine dispatch).
13. **Fail-open vs fail-closed chosen per gate, documented per gate.** Broken git state never bricks a session; anything that would *widen* a gate or *admit* an automated write fails closed.
14. **Model economics are a design input.** Fan-out agents default to cheaper models and lower effort; several commands were deliberately upgraded from the cheapest tier when reliability data demanded it; the heavy-agent concurrency cap came from a measured throttle incident.
15. **Deprecate, don't delete.** The Go agent-manager was superseded but stays in-repo for existing users, excluded from presets — install-base compatibility over repo tidiness.
16. **Ship capabilities wired-but-off when the evidence isn't in.** Optimistic memory integration is fully built, red-teamed, and held closed by its own eval gate until mined memory beats the full-context baseline — the gate's honesty matters more than the feature's activation.
17. **Dogfooding as architecture.** CCGM develops itself: symlink installs from a canonical clone, a reverse-sync command for changes made in the live config, workspace clones for parallel CCGM development, and a post-merge hook that updates the canonical clone automatically.
18. **Capability removal, not prompting, is what holds a delegation posture.** Prior-art research into production orchestrator incidents found the same pattern three separate times: a prompt-only "you never implement" instruction holds until an integration-pressure moment, then the orchestrator patches inline anyway — and the fix that held in every documented case was removing the capability, not writing a better prompt. Advisor mode's PreToolUse gate applies that lesson to CCGM itself: a denial is steering ("delegate this"), not an obstacle, and hardening the gate's own shell-parsing model went through the same discipline it enforces — spec it, delegate it, adversarially review it, fix, repeat.
19. **Cloudflare Pages creation is API-first, dashboard second.** A live run in a sibling project confirmed `POST .../pages/projects` with `source.type: "github"` creates a real, permanent Git-connected Pages project, with a one-time Cloudflare GitHub App install as the only precondition — overturning the assumption baked into the `cloudflare` rule, `common-mistakes` #8, and all of `/launch` that the dashboard's Connect-to-Git flow was the only way in. The API call does not start the first build; a separate deployment-trigger call is required and now has its own poll step. The rewrite went through three adversarial review rounds after a reviewer found the source research notes and the live transcript disagreeing on trigger behavior and field placement — the transcript, the primary evidence, won every time.
20. **A harness failure may only close a gate, never open one.** A dreamed row whose harness never launched is excluded from every mean the eval classifier reads (cost excepted, since a budget-stopped run still spent real money) and downgrades its row to `error` — inert to the gate — except when the row was already `regression`, which survives the downgrade untouched, because the gate selects regressions by bucket name and relabelling one would delete it from the gate's view. `downgrade_bucket_for_launch_failures()` is the single function that decides all three cases, arrived at after two earlier point-fixes each opened the gate in a new direction.

## Incidents & Lessons

Every one of these produced a durable control, not just a fix:

| Incident | Lesson shipped |
|----------|----------------|
| Uncommitted work on main destroyed by a sync to origin | `branch-guard` — a bypass-proof gate that fires before the first edit, not at commit time |
| ~237 GB consumed by 33 orphaned agent worktrees (each with its own multi-GB build tree) | Worktree lifecycle with mandatory delegator teardown + `/worktree-sweep` janitor with a proven-safe removal classification |
| ~10 simultaneous max-effort agents → ~1.4M tokens in 27s → server-side 429 failing the whole burst | Concurrency rule: ≤4 heavy agents, waves with cooldowns, cheaper defaults for fan-out — propagated into all 19 fan-out skills |
| `git rebase --abort` in a sync fallback silently wiped a concurrently-appended learning (no commit, no reflog) | Merge-only `pull`; rebase removed from the memory-store sync path entirely |
| `git revert` silently defeated by the union merge driver re-adding reverted lines | Custom line-set-difference revert, sound under the append-only invariant |
| macOS BSD grep segfaulted on the personal-data scan | Scan rewritten in Python; "green locally ≠ green on runner" → dual-OS CI for the memory modules |
| A third-party TUI parsed dash-prefixed content as flags | Dependency dropped; pure-bash TUI |
| Cloud platform static-site projects created via CLI can never gain Git auto-deploy retroactively | Inception-time creation rule in the platform module, with symptoms table and remediation procedure |
| Database pooler circuit breaker locked out all CLI operations after retried auth failures | Retry-once rule with explicit re-auth handoff |
| Stale documentation counts recurring across README/docs | Derived counts + CI guard; mandatory post-merge `/docupdate` |
| Memory store recognized as a prompt-injection/poisoning surface before shipping auto-writes | Write-time sanitizer, read-time quarantine-on-projection, transcript-verified origin binding, dwell windows, caps, breaker, and a published adversarial poisoning analysis with red-team tests |
| A manifest-completeness gate walked shipped files with `find -type f`, which never matches a symlink, so a file shipped as a symlink was invisible to the check meant to catch it | `find -L` to follow symlinks, landed as a regression guard while zero such symlinks existed |
| An early-exiting consumer under `set -o pipefail` could SIGPIPE-kill a still-writing producer across 21 sites in three test suites; one was a bare assignment that aborted the run partway through, so a truncated run still read green | Herestrings in place of piped consumers, removing the second process there was nothing to race |
| Bash's builtin `echo` flag-parses an argument of exactly `-n`/`-e` into empty output; what was filed as 7 sites became 13 once the sweep widened past piped `tr` calls | `printf '%s'` for flag-shaped values, and a regression test built on a git file literally named `-n` |
| Distinct from the SIGPIPE class: `grep -c` exits 1 on a count of zero, so a bare `var=$(... grep -c ...)` under `set -e` killed a suite before its own fail branch could report — the regression it guarded became a silent mid-run abort that read as a pass. The audit skill's 33 bundled suites carried ~130 more sites of the piped class | `\|\| true` guards on found-nothing assignments across the top-level suites; the herestring sweep extended to all 33 audit suites with flags preserved byte-for-byte and verified by before/after multiset comparison |
| The README install-block guard was coverage-only: it proved every declared file was copied but could not see a missing `mkdir -p` (~40 READMEs failed from scratch) or an over-install (the #951 `cp -R` that swept 40 undeclared files stayed green), and 11 of 78 modules were invisible to it — three because its heading regex was case-sensitive | The guard grew two dimensions — static directory-bootstrap checking and disk-resolved over-copy detection (gitignore-aware, fail-closed) — and the skip set fell to 3 modules, each named in the guard with the reason its install is genuinely not a flat copy |
| The advisor-mode gate's flag and predicate checks read each argument's literal text, so a quoted, ANSI-C, or expansion-carried flag reached the command with the guard exiting 0 in silence; the fix added one word normalizer every check reads instead of the raw text. An adversarial reviewer, working under a reproduce-it-against-real-bash bar, then found 21 further bypasses across expansion stages the normalizer did not model — locale quoting, brace expansion, word splitting on an internal field separator, and globbing, plus backslash-newline line continuation — all pre-existing on the default branch. At that point the docs claimed the bypass class was closed, and the new differential test harness reported a clean pass when the guard file did not exist, because Python's own file-not-found exit code matched the guard's denial exit code | Every finding landed in the same pull request rather than a follow-up, in the gate's stated over-deny direction, and the harness gained a guard-exists check plus positive and negative controls; a denial now requires the guard's exit code and non-empty stderr together, not the exit code alone. The lesson: a confirmatory test matrix built from an implementation's own model of a problem cannot find bypasses outside that model — drive the matrix from the underlying system's real behavior instead, and make a security test fail loudly when the thing it tests cannot run |
| The dreaming eval gate — the regression check optimistic auto-integration must pass nightly — read `format_error_rate: 1.0` on every row of every nightly run for seven weeks, and closed for a reason that looked like a memory problem but was a harness problem. The LaunchAgent's plist exports a fixed `PATH` that omits `~/.local/bin`, where Claude Code's native installer puts the `claude` binary, so every `claude -p` sub-run inside the eval arm failed to launch before it ran and was recorded as a format error at zero cost and zero turns. Only the earliest runs, started by hand from a login shell, ever scored real results; every LaunchAgent-started run since read the same all-failed shape and nobody noticed, because a closed gate and a broken harness produce the identical outward signal | Three durable controls close the class rather than one run: the `claude` binary now resolves to an absolute path before any task spends a token, checking the installer's real locations instead of trusting the ambient `PATH`; a run where every arm fails to launch aborts loudly, writes no results file, and leaves a `harness-broken` marker that `--gate` reads as closed until a run actually produces results; and a launch failure may only move a row toward a closed gate, never toward an open one. Getting to that last rule took three rounds — the first fix's missing results file let the gate fall back to a stale green run, the second fix's zero-scored failed launches averaged into `high_value` as manufactured uplift, and the third fix's blanket `error` override silently replaced a real `regression` bucket, reopening the gate on exactly the row that should have stayed closed. What finally pinned the class was a property test asserting through `gate_check()` itself over every bucket and every arm, rather than testing the helper function in isolation |

## Iteration Case Studies

**`/startup`** went through four architectures: sub-agent delegation with markdown output → direct bash formatting (halving token use) → plain-text alignment (dropping markdown entirely for terminal fidelity) → an intelligent summary via headless CLI invocation, then a macOS-Keychain-sourced direct API call with a fallback chain. Each rewrite was driven by measured cost and output-quality problems, not aesthetics.

**Research tooling** iterated across four forms: an early bundled deep-research command (removed), a zero-dependency `/research` (parallel search agents, works anywhere), a heavyweight local-first companion pipeline in its own repo (local LLM query generation + self-hosted metasearch — kept separate because it demands Docker, a ~40GB model, and a venv), and finally an Exa-MCP-backed `/deepresearch` module bundling the practical middle ground.

**Memory** is the longest arc: narrative MEMORY.md files → a schema-validated JSONL store with confidence decay (April) → supersede chains + compaction guard → the v2 op-event/sharded store with CAS and origin binding (July) → nightly transcript mining → optimistic integration behind dwell/caps/breaker → the composite eligibility gate with its adversarial analysis. Each layer kept the previous one's guarantees intact — the read path never depended on the write path existing.

**Review tooling** compounded rather than replaced: augmenting an external review plugin with scope-drift detection → a unified orchestrator with tiered personas → a standalone adversarial reviewer → the seven-lens document gate → xplan’s selected 1–3 adversarial passes with enforced autonomous-execution tenets. Current X-Plan/adrev/ETP review defaults to personal lead judgment, with native cross-provider review explicitly opt-in. Evidence-backed findings and spec-before-quality review remain central; personal review does not claim independent fresh context.

## Third-Party Tools & Integrations

**Hard requirements**: Claude Code, git, bash 3.2+ (the installer scripts always run under bash via their shebang, regardless of login shell), python3 (stdlib only — no pip dependencies anywhere in the hook/lib layer), jq.

**Optional, per-module**: `gh` (GitHub CLI), launchd (macOS scheduling for autoheal/dreaming), tmux (agent panes), yt-dlp (transcripts), Resend (email digests), Hetzner Cloud + Terraform + Packer (cloud dispatch), Go + Bubble Tea (the deprecated agent-manager TUI), Playwright + a Chrome extension MCP + WebMCP (browser automation tiers), Exa MCP (semantic research), Docker + Ollama + SearXNG (the separate deep-research companion), and the Anthropic Messages API (background analyzers, via curl).

**Audit spine**: eslint, gitleaks, squawk, sqlfluff, checkov — each wrapped in a normalizer that isolates config, redacts secrets, and emits schema-validated findings.

## Quality & Testing Infrastructure

- **Structural suite** (bash): manifest validation for every module, template-expansion checks, settings-merge tests, backup/restore, link-mode, uninstaller un-merge, YAML frontmatter strictness, doc-count/preset-coverage guards, and the no-personal-data scan.
- **Per-module unit tests**: pytest for Python libraries (the learnings store, miner, analyzer, eligibility core each carry their own suites, including red-team/poisoning tests and offline fixture-driven end-to-end chain smokes that run with no network and no API key), bash tests for shell tooling.
- **CI**: five GitHub Actions workflows — the main structural suite, the memory-module suite on both ubuntu and macos (macOS is ground truth for a macOS-first tool), the Go module build, a release workflow, and a guest workflow that verifies the companion ccgm-site's Cloudflare Pages deploy actually landed on every push to main (skip-with-notice when its secret is unset, so it never reds this repo's own CI). The plugin-marketplace generator runs in `--check` mode so a stale generated catalog fails the build.
- **Determinism as testability**: offline fixture modes for every network-touching pipeline, canned-response analyzers, and eval harnesses with fixed seed tasks make nightly automation regression-testable.
- **Audits against the live pipelines, not just their tests**: two report-only Claude API audits (cost, prompt shape) run against the running autoheal and dreaming analyzers found six real defects that all shipped the same day — stale fallback pricing had overstated the dreaming cost log by about 2.2x, and 57 of 250 logged Sonnet-5 map calls had been silently truncating at the output cap (see Incidents & Lessons for the eval-gate defect the same pass surfaced).

## The Meta Loop

CCGM's most distinctive property is that it is built *by* the environment it configures, and it feeds on its own exhaust:

- Sessions run under CCGM rules produce transcripts → dreaming mines them → proposals improve the learnings store → the store injects into future sessions.
- Permission friction produces autoheal events → the analyzer proposes settings fixes → applied fixes reduce future friction.
- Debugging sessions that take 3+ attempts trigger mandatory reflection → patterns land in memory or in the shared `common-mistakes` record.
- Incidents become rules; rules that get violated under pressure get hardened with the rationalization-table treatment; rules that need certainty become hooks.
- The repo enforces on itself everything it ships: its own hooks gate its own commits, its own audit packs include CCGM-specific checks, its own doc-drift guards watch its own docs.

## Notable Engineering Highlights

- Designed and shipped an 80-module configuration platform with dependency resolution, deep JSON settings merging, template expansion, manifest-tracked install/update/uninstall, and four distribution surfaces — in pure bash + jq with no runtime dependencies.
- Built a durable cross-session memory system on an append-only op-event log with read-time projection, confidence decay, conflict-free multi-writer git sync, computed rollback, three independent anti-poisoning layers, and a published adversarial security analysis — then held its automation behind an eval gate its own results hadn't yet passed.
- Built two autonomous observe-analyze-propose loops (permission friction; session transcripts) that run nightly under cost caps with direct API calls, layered defenses (dwell windows, blast-radius caps, anomaly checks, self-healing circuit breakers), and human-gated apply paths.
- Rebuilt a codebase auditor as a 21-pack engine over a deterministic multi-tool spine with schema-validated, fingerprinted findings, baseline/delta classification, and suppression/provenance workflows.
- Ran a solo-maintainer, multi-agent development practice — parallel implementer agents in isolated worktrees, spec-driven delegation, fresh-context two-stage review, adversarial plan gauntlets — that sustained 430+ issue-tracked, CI-gated merges in four months, including three separate 8-epic subsystems each landed in a single day.
- Converted every production incident into a deterministic control: hard pre-edit branch gates, enforced worktree teardown, concurrency caps derived from measured throttle data, and sync mechanisms proven sound against real data-loss findings.
- Hard-enforced a delegation posture for its own most expensive orchestrator sessions with a PreToolUse gate, then adversarially proved it against real bash: a differential harness spelling every way to disguise a mutating shell flag took the guard from 27 live parsing bypasses to zero across two review rounds, each verified by comparing the guard's decision to actual `bash -c` execution in a throwaway sandbox.
