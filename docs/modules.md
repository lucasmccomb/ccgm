# Module Catalog

CCGM contains 73 modules across 5 categories. Each module is self-contained in `modules/{name}/` with a `module.json` manifest and its content files.

## How modules work

A module installs one or more of these file types:

| File type | Location | How Claude uses it |
|-----------|----------|-------------------|
| **Rules** (`rules/*.md`) | `~/.claude/rules/` | Loaded automatically at session start. Guides Claude's behavior. |
| **Commands** (`commands/*.md`) | `~/.claude/commands/` | Available as `/command-name` slash commands. |
| **Agents** (`agents/*.md`) | `~/.claude/agents/` | Reusable subagent prompts invoked by commands or skills via the Task tool. Use for prompts shared by multiple callers; keep one-off prompts inline. |
| **Hooks** (`hooks/*.py`) | `~/.claude/hooks/` | Triggered by Claude Code events (tool calls, session start, etc.). |
| **Settings** (`settings.*.json`) | `~/.claude/settings.json` | Deep-merged into the permissions configuration. |
| **Docs** (`*.md` reference files) | `~/.claude/` | Reference documentation accessible to Claude. |
| **Config** (`*.json` config files) | `~/.claude/` | Configuration data read by hooks or commands. |

## Category: core

These modules form the foundation. The **standard** preset includes all of them.

---

### global-claude-md

Slim global CLAUDE.md that serves as the root configuration reference.

**Installs**: `CLAUDE.md` (global)

**What it does**: Creates a lightweight `~/.claude/CLAUDE.md` that points Claude to all installed rules, commands, hooks, and settings without duplicating their content. This is the first file Claude reads at session start and serves as the entry point to the entire configuration.

**Dependencies**: None

---

### autonomy

Configures Claude as a fully autonomous Staff-level engineer who executes tasks end-to-end without unnecessary questions.

**Installs**: `rules/autonomy.md`

**What it does**: Sets the core operating principle of "do it, don't describe it." Instead of presenting steps for the user to follow, Claude runs commands, fixes problems, chains operations, and debugs issues itself. The rule defines clear boundaries for when to act vs when to ask (credentials, third-party dashboards, ambiguous product decisions, destructive actions).

Also defines a post-task "call to action" pattern: after finishing work, Claude prompts for next steps rather than just summarizing.

**Dependencies**: None

---

### git-workflow

Git conventions covering sync safety, branching strategy, commit attribution, and PR workflows.

**Installs**: `rules/git-workflow.md`

**What it does**: Establishes seven critical rules:

1. **No AI attribution** - never add Co-Authored-By trailers or "Generated with Claude" to commits, PRs, or git metadata
2. **PR template detection** - before creating PRs, check the repo and org for PR templates and use them
3. **Sync before history changes** - always `git fetch` before rebase, filter-branch, or reset
4. **Rebase by default** - use rebase instead of merge for feature branches
5. **Never stash** - commit instead; stashes are invisible and easy to lose
6. **Return to main after merge** - checkout main and pull after PRs are merged
7. **Pathspecs resolve from cwd** - run `git add`/`rm`/`restore` from the repo root (or with `git -C`), not from a sub-package subdir

**Dependencies**: None

---

### identity

Two foundational context files that give Claude Code a persistent identity.

**Installs**: `rules/soul.md`, `rules/human-context.md`

**What it does**: Provides two context files generated during installation based on your answers:

- **soul.md** - Defines Claude's AI personality, reasoning principles, communication style, core values, and boundaries. Establishes the engineering partner relationship.
- **human-context.md** - Captures who you are, what you're building, how you work, and where you're going. Helps Claude tailor its behavior to your experience level, priorities, and preferences.

Both files are generated from your answers during the identity interview in the installer. They are marked as templates to prevent personal data from leaking into the CCGM repo.

**Config prompts**: Role, experience, current projects, working style, goals

**Dependencies**: None

---

### settings

Base `settings.json` with 800+ pre-configured tool permission entries.

**Installs**: `settings.base.json` (merged into `settings.json`)

**What it does**: Provides a comprehensive permissions configuration for Claude Code:

- **Allow list**: 800+ tool commands pre-approved for auto-execution (git operations, npm/pnpm commands, file operations in safe paths, common CLI tools)
- **Deny list**: Dangerous commands blocked (force push to main, `rm -rf /`, dropping databases, etc.)
- **Default mode**: Configurable as `ask` (confirm before risky tools) or `dontAsk` (auto-approve everything not denied)

**Config prompts**: Permission mode (`ask` or `dontAsk`)

**Template variables**: `__HOME__`, `__CODE_DIR__`, `__DEFAULT_MODE__`

**Dependencies**: None

---

### hooks

Python hooks that automate and enforce development workflows.

**Installs**: 15 hook scripts, 6 Python libraries, settings.json fragment

This module installs the most hooks of any module. See [Hooks Reference](hooks.md) for detailed documentation of each hook.

**Hooks installed**:

| Hook | Type | Purpose |
|------|------|---------|
| `enforce-git-workflow.py` | PreToolUse:Bash | Blocks commits/pushes to protected branches, enforces `#N:` commit format |
| `enforce-issue-workflow.py` | UserPromptSubmit | Reminds Claude to follow issue-first workflow |
| `auto-approve-bash.py` | PreToolUse:Bash | Enforces bash permissions from settings.json |
| `auto-approve-file-ops.py` | PreToolUse | Enforces path-based read/edit/write permissions |
| `ccgm-update-check.py` | PreToolUse | Daily check for CCGM upstream updates |
| `port-check.py` | PreToolUse:Bash | Warns about dev server port conflicts |
| `agent-tracking-pre.py` | PreToolUse:Bash | Warns when claiming already-claimed issues |
| `agent-tracking-post.py` | PostToolUse:Bash | Records issue claims, status transitions in tracking CSV |
| `check-migration-timestamps.py` | PreToolUse | Validates Supabase migration file timestamps for duplicates before commit |
| `pretooluse-bash-dispatch.py` | PreToolUse:Bash | Consolidated dispatcher running the Bash check chain (git-workflow, destructive, patterns, port, tracking, careful) in one process |
| `check-careful.py` | PreToolUse:Bash | Force-push-to-main hard block + careful-mode destructive-command prompts |
| `check-freeze.py` | PreToolUse | Scope-locks Edit/Write to the `/freeze` directory |
| `orphan-process-check.py` | SessionStart | Warns about orphaned test worker processes (vitest/jest) |
| `session-start-enforce.py` | SessionStart | Opt-in rule-enforcement meta-instruction injection |
| `sync-ccgm-canonical.py` | PostToolUse:Bash | Auto-pulls the canonical CCGM clone after PR merges |

**Config prompts**: Protected branches (custom list), auto update check (yes/no)

**Template variables**: `__USERNAME__`

**Dependencies**: settings

---

### branch-guard

Hard PreToolUse gate that stops any work from being produced on a repo's default branch.

**Installs**: `hooks/branch-guard.py`, `rules/branch-guard.md`, settings.json fragment

**What it does**: While a repo's HEAD is on its default branch (main/master, per `origin/HEAD` with fallbacks), hard-blocks (exit 2, survives bypass mode) Edit/MultiEdit/Write/NotebookEdit and filesystem-MCP writes targeting files in that repo, plus mutating git Bash commands (`git commit`, `git add`, `git stage`, `git apply`, with `git -C` resolved). Fires before the first edit — not at commit time — so uncommitted work can never be stranded on main and destroyed by a later sync. The denial teaches the fix: `git fetch origin && git checkout -b <type>/<short-desc> origin/<default>` (type: feature/fix/chore/docs). Exempts `ALLOW_MAIN_COMMIT=1` (env or inline), in-progress rebase/merge/cherry-pick states, unborn HEAD (fresh `git init`), repos with no origin remote (nothing to sync from), repos in `~/.claude/git-flow-direct-to-main-repos.json`, and gitignored target paths (file tools only; `git check-ignore`-verified, fails closed on git errors so a broken git state can never open the gate). Complements the `hooks` module: the advisory `<workflow-reminder>` stays, `enforce-git-workflow.py` still owns commit/push time; this closes the edit-time gap.

**Dependencies**: settings

---

## Category: commands

Slash commands that extend Claude Code with new capabilities.

---

### commands-core

Essential slash commands for daily development workflow.

**Installs**: 5 command files

| Command | Description |
|---------|-------------|
| `/commit` | Stage all changes and commit with conventional format |
| `/pr` | Push branch and create a pull request |
| `/cpm` | One-shot commit + PR + merge workflow |
| `/gs` | Git status dashboard |
| `/ghi` | Create a GitHub issue with labels |

See [Commands Reference](commands.md) for detailed usage of each command.

**Dependencies**: None

---

### commands-extra

Additional slash commands for codebase audits, visual verification, guided walkthroughs, rule promotion, safety-hook state management, and session-state checkpoints.

**Installs**: 8 command files + audit skill (21 packs, deterministic tool spine, schemas, reference docs)

| Command | Description |
|---------|-------------|
| `/audit` | Pack-based codebase audit across 21 packs with deterministic spine + LLM workers |
| `/pwv` | Playwright visual verification |
| `/walkthrough` | Step-by-step guided mode |
| `/promote-rule` | Review and promote repo rules to global |
| `/freeze` | Scope-lock Edit/Write to a directory |
| `/unfreeze` | Clear the active freeze scope |
| `/guard` | Compose careful + freeze for focused, safe sessions |
| `/checkpoint` | Save or resume a WIP session-state checkpoint |

See [Commands Reference](commands.md) for detailed usage of each command.

**Dependencies**: None

---

### brand-naming

Research tools for naming products, companies, or projects.

**Installs**: 2 command files

| Command | Description |
|---------|-------------|
| `/brand` | Full naming pipeline with word exploration, generation, and multi-source verification |
| `/brand-check` | Deep verification of a single name across domains, trademarks, app stores, and social |

Commands use a sub-agent model for parallel word exploration and verification phases, optimized for throughput across the multi-source checks.

**Config prompts**: Whether to register the Instant Domain Search MCP server via `claude mcp add --scope user`

**Dependencies**: None

---

### commands-utility

Miscellaneous utility commands for common workflow tasks.

**Installs**: 3 command files

| Command | Description |
|---------|-------------|
| `/cws-submit` | Guided walkthrough for submitting a Chrome extension to the Chrome Web Store |
| `/ccgm-sync` | Sync local Claude Code config changes back to CCGM and lem-deepresearch repos |
| `/user-test` | Browser-based user testing simulation using Chrome automation tools |

**Dependencies**: None

---

### documentation

Comprehensive documentation audit and update command.

**Installs**: 1 command file

| Command | Description |
|---------|-------------|
| `/docupdate` | Audit and update README, TOC, onboarding flow, package lists, and module coverage against actual codebase state |

**What it does**: Spawns parallel audit agents to check all documentation against the real codebase, then applies targeted fixes. Checks packages listed vs installed, TOC entries vs actual headings, setup steps vs actual requirements, and module docs vs source. Works in any project type.

**Dependencies**: None

---

### editorial-critique

Deep editorial review of long-form writing.

**Installs**: 1 skill file

| Command | Description |
|---------|-------------|
| `/editorial-critique` | 8-pass editorial review: prose craft, AI-tell detection, argument architecture, conciseness, data verification, structure, impact, grammar |

**What it does**: Spawns 8 parallel analysis agents that each evaluate writing from a different angle. Produces a scored report with specific line-level feedback. Optionally applies auto-fixes for mechanical issues (grammar, conciseness, AI tells).

**Dependencies**: None

---

### design-review

Visual design review for web pages.

**Installs**: 1 skill file

| Command | Description |
|---------|-------------|
| `/design-review` | 6-pass visual design review: spacing, typography, responsive, visual hierarchy, accessibility, component consistency |

**What it does**: Takes screenshots at 3 viewports (mobile, tablet, desktop), then runs 6 parallel analysis passes. Produces a scored report with specific CSS/layout recommendations. Optionally applies auto-fixes.

**Dependencies**: None

---

### ideate

Structured ideation framework.

**Installs**: 1 skill file

| Command | Description |
|---------|-------------|
| `/ideate` | Socratic interview to refine a loose idea into a concrete concept at 95% clarity |

**What it does**: Uses progressive Socratic questioning with confidence tracking to help you refine a loose idea into a well-defined concept. Once the idea reaches sufficient clarity, it can hand off to `/deepresearch` for validation or `/xplan` for planning and execution.

**Dependencies**: None

---

### brainstorm

Design-before-implementation gate.

**Installs**: 1 skill file

| Command | Description |
|---------|-------------|
| `/brainstorm` | Hard gate forbidding code until a design spec with 2-3 approach tradeoffs is written and user-approved |

**What it does**: Forbids code, scaffolding, or implementation until a design spec is written and explicitly approved. Explores context with read-only tools, proposes 2-3 genuinely distinct approaches with honest tradeoffs, writes a spec to `docs/brainstorm-notes/`, self-reviews for TBDs and contradictions, then waits for user approval before handoff to `/xplan`. Pairs with `/ideate` (concept refinement) to enforce spec-before-plan-before-code separation.

**Dependencies**: None

---

### research

Multi-channel research using parallel agents.

**Installs**: 1 command file

| Command | Description |
|---------|-------------|
| `/research` | Parallel multi-channel research with WebSearch, WebFetch, GitHub, and Reddit |

**What it does**: Spawns up to 7 parallel research agents that each investigate a topic from a different angle (domain, technical, competitive, adjacent, UX, infrastructure, monetization). Decomposes topics into targeted sub-questions, runs iterative multi-round searches, and synthesizes into a structured research.md. Zero external dependencies.

For higher-quality results, install the bundled `deepresearch` module - same fan-out shape, but backed by the Exa MCP server (semantic search with full page contents) instead of WebSearch snippets. See `modules/deepresearch/README.md`.

**Dependencies**: None

---

### debugging

Structured root-cause debugging with Opus delegation.

**Installs**: 1 command file

| Command | Description |
|---------|-------------|
| `/debug` | Structured root-cause debugging with Opus - reproduce, hypothesize, instrument, diagnose, fix, verify |

**What it does**: Enforces a disciplined debugging workflow (reproduce, hypothesize, instrument, diagnose, fix, verify) using Opus for deep root-cause analysis. Invoked automatically by the `systematic-debugging` module's routing rule.

**Dependencies**: None

---

### copycat

Analyze external Claude Code configuration repos to find useful patterns worth adopting into CCGM.

**Installs**: 1 command file

| Command | Description |
|---------|-------------|
| `/copycat` | Analyze an external Claude Code config repo and walk through what's worth incorporating into CCGM |

**What it does**: Accepts a GitHub URL or local path to any Claude Code config repo. Clones/reads the repo, spawns 4 parallel analysis agents (rules, commands, hooks/settings, architecture patterns), compares each finding against CCGM's existing modules, ranks by impact and effort, and walks you through findings interactively. Creates GitHub issues for approved improvements.

**Dependencies**: None

---

### ce-review

Unified code-review orchestrator that composes scope-drift, learnings, and tiered reviewer personas.

**Installs**: `skills/ce-review/`, `agents/reviewers/{correctness,testing,maintainability,project-standards,security,performance,reliability,api-contract,data-migrations,adversarial}-reviewer.md`

**What it does**: Runs a tiered review against changes — baseline specialists (correctness, testing, maintainability, project-standards) plus conditional specialists (security, performance, reliability, api-contract, data-migrations) chosen by the diff shape — then runs an adversarial/red-team reviewer with access to the specialists' findings. Confidence-gated autofix routing classifies each finding as safe_auto, gated_auto, manual, or advisory. Modes: interactive, autofix, report-only, headless.

**Dependencies**: compound-knowledge, pr-review-toolkit, subagent-patterns

---

### deepresearch

Multi-query semantic research using the Exa MCP server.

**Installs**: `commands/deepresearch.md`

**What it does**: `/deepresearch` generates diverse queries from your topic, fans them out via parallel Exa MCP tool calls, and synthesizes a structured `research.md` from full page contents. Requires the Exa MCP server registered via `claude mcp add` and an Exa API key.

**Dependencies**: None

---

### onboarding

Generates a structured ONBOARDING.md for any repository.

**Installs**: `commands/onboarding.md`, `scripts/inventory.mjs`, `skills/onboarding/`

**What it does**: `/onboarding` runs a language-aware inventory script to build a structural map of the repo, then reads only the files that map surfaces and writes prose covering architecture, dev setup, key commands, test workflow, and a glossary. Strict voice rules keep the output reading like a knowledgeable teammate rather than generated documentation.

**Dependencies**: None

---

### pr-review-toolkit

Augments the external pr-review-toolkit plugin with scope-drift detection and a Fix-First output format.

**Installs**: `rules/fix-first-review.md`, `skills/scope-drift/`

**What it does**: Scope-drift compares a PR's stated intent (title, body, linked issue) against the actual diff and flags work that wasn't asked for. Fix-First splits review output into AUTO-FIXED (already addressed in the diff) vs NEEDS INPUT (requires a decision). Ported from garrytan/gstack.

**Dependencies**: None

---

### ship-readiness

At-a-glance dashboard of what gates a merge on the current branch.

**Installs**: `commands/ship-ready.md`

**What it does**: `/ship-ready` surfaces failing tests, open PR count, stale branches, outdated deps, merge velocity, review freshness, and unresolved risks from `docs/solutions/`. Reads ce-review envelopes for commit-hash staleness detection so a finding from N commits ago is flagged as potentially stale.

**Dependencies**: None

---

### capability-router

A decision map for CCGM's overlapping command/skill clusters - answers "which one do I use?"

**Installs**: `commands/capabilities.md`, `rules/capability-map.md`

**What it does**: `/capabilities [cluster]` prints a decision map for the clusters that overlap most - research (`/research` vs `/deepresearch`), review (`scope-drift`, `/ce-review`, `document-review`, `editorial-critique`, `design-review`, `adrev`, `/resolve-pr-feedback`), planning/execution (`/xplan`, `/xplana`, `/etp`, `/mawf`), debugging (`/debug`), and knowledge (`/reflect` vs `/compound` vs `session-history`). A tight always-on rule carries the most-confused one-liners and points at the command, so the full map costs no idle tokens.

**Dependencies**: None

---

## Category: workflow

Development workflow patterns and coordination systems.

---

### github-protocols

Issue-first workflow, PR conventions, label taxonomy, and code review standards.

**Installs**: `rules/github-protocols.md`, `github-repo-protocols.md` (reference doc)

**What it does**: Establishes a structured development workflow:

- **Issue-first**: Every code change starts with an issue
- **Label taxonomy**: Consistent labels for type (feature, bug, refactor), priority, and status
- **PR conventions**: Branch naming, PR description format, review checklist
- **Code review standards**: What to look for, how to give feedback
- **Rule promotion**: Instructions for identifying repo-specific rules that should become global

**Dependencies**: None

---

### startup-dashboard

Plain-text `/startup` dashboard for Claude Code sessions.

**Installs**: `commands/startup.md`, `lib/startup-gather.sh`, `lib/startup-summary.sh`, `lib/startup-summary-prompt.md`, `lib/startup-dashboard.sh`, `hooks/auto-startup.py`

**What it does**: Emits a single-screen dashboard at session start:

- **Git state**: branch, status, sync with origin/main
- **Live sessions**: other Claude Code processes on the machine
- **Open PRs and tracking.csv claims** for the current repo
- **Sibling branches** across clones in the same workspace
- **Last handoff**: recent handoffs from peer clones (and from the same clone's previous `/sds` run, marked `(you)`) so the next session picks up where the last one stopped
- **Recent activity**: last 7 days of session transcripts across every clone of the repo, powered by the `session-history` module's `/recall`
- **Update banner** when a new Claude Code release is available

There are no agent-discipline logging rules, no log repo writes, and no triggers to remember. Claude Code captures session transcripts natively as JSONL; `/recall` queries them on demand.

**Config prompts**: None

**Dependencies**: session-history

---

### multi-agent

Multi-clone architecture for running multiple Claude agents in parallel on the same repo.

**Installs**: `rules/multi-agent.md`, `multi-agent-system.md` (reference doc), `commands/mawf.md`, `commands/workspace-setup.md`, `commands/handoff.md`, `lib/handoff.py`, `port-registry.json`

**What it does**: Enables parallel development with multiple Claude Code instances:

- **Clone organization**: Two models supported - workspace model (`{repo}-workspaces/{repo}-wX/{repo}-wX-cY/`) and flat model (`{repo}-repos/{repo}-N/`)
- **Port allocation**: Each clone gets unique ports via `port-registry.json` and `.env.clone` to prevent dev server collisions
- **Issue claiming**: Agents claim issues via the tracking CSV, preventing duplicate work
- **Workspace setup**: `/workspace-setup` creates isolated workspace directories with clones, labels, and agent identity files

Commands installed:

| Command | Description |
|---------|-------------|
| `/mawf` | Multi-Agent Workflow - parse feedback into issues, spawn parallel agents |
| `/workspace-setup` | Create workspace directory structure for a repo |

**Dependencies**: startup-dashboard

---

### xplan

Deep research, planning, and execution framework for complex projects.

**Installs**: 5 command files + 2 lib files

**What it does**: An interactive, human-in-the-loop planning framework:

- **Phase 0** - Parse input, create plan directory
- **Phase 0.5** - Discovery interview: confirm concept, choose research depth
- **Phase 1** - Deep research via parallel agents (Full / Technical Only / Market & Product / Lite / Custom presets)
- **Phase 1.5** - Research review with business viability assessment; confirm to proceed
- **Phase 2** - Naming ideation (optional)
- **Phase 2.5/2.6/2.7** - Tech stack sign-off, scope sign-off, multi-agent setup review
- **Phase 3** - Plan creation with parallelized epics and dependency waves. Every plan builds a **comprehensive autonomous E2E test suite** (Phase 3.3.5): new projects get a Wave-1 test-harness epic and per-epic E2E coverage; existing repos get a coverage-gap audit and optimistic gap-fill for touched areas. The suite is wired into CI as a blocking merge gate so it, not the user, is the ready-to-merge oracle.
- **Phase 4** - Constructive peer review by security, architecture, and business logic agents (review stage 1 of 2)
- **Phase 5 (+5.6)** - Write plan.md, then a self-review loop for placeholders, identifier drift, and autonomous-execution readiness
- **Phase 5.7** - Adversarial review sequence (stage 2 of 2): 3 sequential `adrev-reviewer` passes on Opus 4.8 (max effort), each attacking the plan after the prior pass's fixes are incorporated, and enforcing the four plan-execution tenets (minimal/edge-bucketed human work, follow-up completion, autonomous decision context, comprehensive autonomous E2E coverage)
- **Phase 6** - Web review + final confirmation gate
- **Phase 7** - Execute via parallel agents in separate clones; waves and completion gate on a green E2E suite and completion of all in-scope follow-up work
- **Phase 8** - Verification, audit, and retrospective

Every plan is engineered to execute with minimal human involvement: human work is bucketed to the start or end (never mid-run), unplanned follow-on work is completed before the run is reported done, and the autonomous E2E suite certifies the result so the user does not test manually.

Use `--light` to skip the interview phases and use a traditional walkthrough instead.

Commands installed:

| Command | Description |
|---------|-------------|
| `/xplan` | Launch the full planning and execution pipeline |
| `/xplana` | Autonomous alias - `/xplan --autonomous` (full-depth, zero mid-flow prompts) |
| `/xplan-status` | Check progress on a running or completed plan |
| `/xplan-resume` | Resume an interrupted plan execution |
| `/etp` | Execute a ready plan or GitHub issue(s) end-to-end with adversarial PR review |

**Dependencies**: multi-agent (which depends on startup-dashboard), adversarial-review (which depends on subagent-patterns; provides the `adrev-reviewer` agent for Phase 5.7)

---

### atdd

Agentic Test-Driven Development - build app code to pass E2E vision specs.

**Installs**: 1 command file, 1 rule file

**What it does**: Provides a spec-driven development workflow where E2E vision specs (Playwright tests) define target behavior and agents iteratively build app code until all specs pass. The `/atdd` command runs a 4-phase workflow:

- **Phase 1 (Orient)**: Read all spec files, establish baseline (X/Y tests passing), create branch
- **Phase 2 (Red-Green Loop)**: Systematically work through failing tests - read each test, implement the minimum app code to make it pass, commit incrementally
- **Phase 3 (Verify)**: Run lint, type-check, and unit tests to ensure clean code
- **Phase 4 (Ship)**: Push and create PR with baseline/final results

The ATDD contract: specs are immutable (never modify test files), mocks define the API contract, UI assertions define the design spec.

Commands installed:

| Command | Description |
|---------|-------------|
| `/atdd` | Build app code to pass vision specs in `e2e/tests/{feature}/` |

**Dependencies**: None

---

### youtube-transcripts

`/transcript <url>` - extract a YouTube transcript AND analyze it against your project memory in one invocation.

**Installs**: 1 command file, 1 rule file, 1 shell script (`lib/grab-transcript.sh`), 1 prompt template (`lib/analyze-transcript.md`)

**What it does**: One slash command runs the full pipeline:

- **Phase 1 (deterministic)**: `lib/grab-transcript.sh` calls `yt-dlp` to pull captions, then awk/sed clean the VTT into prose with `>>` speaker turns. Writes `~/code/docs/transcripts/<slug>-<upload_date>.md` with YAML frontmatter (title, source, url, uploader, upload_date, duration, type, caption_source, note).
- **Phase 2 (latent)**: dispatches a subagent in headless mode that reads the saved transcript + your `MEMORY.md` + workspace `CLAUDE.md`, follows the analysis template, and writes an opinionated 6-section implications doc to `~/code/docs/transcript-analysis/<same-slug>-<upload_date>.md`.

Both filenames share the same slug + upload-date so the pair correlates by name. The analysis is intentionally opinionated and project-specific — it names files, names projects from `MEMORY.md`, and explicitly flags low-confidence claims.

`--no-analysis` skips Phase 2. `mode:headless` suppresses prompts and emits paths only.

The Phase 1 script is callable directly from a shell (`~/.claude/lib/grab-transcript.sh <url>`) for extraction without analysis.

Commands installed:

| Command | Description |
|---------|-------------|
| `/transcript <url>` | Extract YouTube transcript + dispatch analysis subagent |

**Requirements**: `yt-dlp` (`brew install yt-dlp` or `pipx install yt-dlp`)

**Dependencies**: None

---

### test-vision

Vision-driven e2e test suite generation using multi-agent orchestration.

**Installs**: 2 command files

**What it does**: Provides two composable commands for generating comprehensive Playwright e2e test suites:

- **`/test-vision`** - Full repo orchestrator: discovers all features via 7-source checklist + Chrome MCP visual exploration, interviews the user to validate test cases and priorities, generates shared Playwright infrastructure (config, fixtures, auth setup by provider), dispatches parallel `/e2e` agents per feature domain, validates the suite, and generates a CI/CD workflow.
- **`/e2e`** - Atomic spec generator: generates a single Playwright spec file for a feature, flow, or issue. Works standalone (with its own discovery) or as a building block within `/test-vision`. Supports three-tier assertions for unbuilt features (route loads, structural landmarks, behavioral interactions).

Key design: `/test-vision` composes `/e2e` as its atomic unit. File paths are pre-assigned before dispatch to prevent merge conflicts. Infrastructure is generated before agents are spawned.

Commands installed:

| Command | Description |
|---------|-------------|
| `/test-vision` | Full repo e2e test suite generation with parallel agents |
| `/e2e` | Single-feature Playwright spec generation |

**Dependencies**: browser-automation, multi-agent

---

### remote-server

SSH access to a configured remote server.

**Installs**: `commands/onremote.md`, `rules/remote-server.md`, settings.json fragment

**What it does**: Enables Claude to run commands and health checks on a remote server over SSH:

- **`/onremote`**: Natural-language task runner - describe what you want to do, Claude figures out the SSH commands
- **Health check mode**: When invoked with no arguments, shows uptime, disk usage, and active processes
- **Task mode**: Interprets natural language, runs appropriate SSH commands, reports results
- **Delegation**: All operations delegate to Haiku to minimize token usage
- **Settings**: Adds `ssh`, `scp`, `rsync` to the tool allow list

**Config prompts**: Remote hostname, SSH username, server alias

**Template variables**: `__REMOTE_HOST__`, `__REMOTE_USER__`, `__REMOTE_ALIAS__`

**Dependencies**: None

---

### self-improving

Meta-learning system with automated reflection triggers, commands, and hooks, backed by a schema-validated JSONL learnings store.

**Installs**: `rules/self-improving.md`, `rules/learnings-store.md`, `commands/reflect.md`, `commands/consolidate.md`, `commands/retro.md`, `hooks/reflection-trigger.py`, `hooks/precompact-reflection.py`, `hooks/learnings-inject.py`, `lib/learnings_store.py`, `bin/ccgm-learnings-log`, `bin/ccgm-learnings-search`, `bin/ccgm-learnings-sync`, `bin/memory-setup.sh`, `settings.partial.json`

**What it does**: Combines rules, commands, hooks, and a durable store to create an active self-improvement loop:

- **Prescriptive triggers**: Reflection fires at specific moments (after PR merge, after 3+ debugging attempts, before context compaction, after user corrections)
- **Reflection checklist**: Mechanical checklist walked at each trigger point to identify patterns worth capturing
- **Learnings store**: `lib/learnings_store.py` -- append-only, per-agent-sharded JSONL with confidence decay, staleness detection, prompt-injection sanitization, supersede chains, and a promotion-only `_global` scope. `~/.claude/learnings/` is a git repo (`ccgm-learnings-sync`) for versioning, rollback, and cross-machine sync.
- **Commands**: `/reflect` (inline structured reflection, dual-writes to the JSONL store), `/consolidate` (delta-first store maintenance via subagent -- supersede/verify/contradict over whole-entry rewrites), `/retro` (windowed retrospective surfacing candidate learnings)
- **Hooks**: PostToolUse hook injects a reflection reminder after `gh pr merge` and `gh issue close`; PreCompact hook reminds the agent to capture patterns before context compression; opt-in SessionStart hook (`learnings-inject.py`, `CCGM_LEARNINGS_INJECT=true`) surfaces the project's top-ranked learnings at fresh session start
- **Cross-module integration**: Works with systematic-debugging (three-strike capture), common-mistakes (living document), and `dreaming` (the nightly mining pipeline that proposes changes to this same store)

**Dependencies**: None (soft references to systematic-debugging, common-mistakes)

---

### subagent-patterns

Methodology for decomposing tasks and delegating to subagents.

**Installs**: `rules/subagent-patterns.md`, `rules/concurrency-and-rate-limits.md`

**What it does**: Provides a structured approach to using Claude Code's Agent tool:

- **When to use subagents**: Parallel independent research, parallel implementation across files, isolated exploration
- **Task decomposition**: How to write specs for subagents (context, deliverable, constraints, success criteria)
- **Dispatch patterns**: Parallel research with aggregation, parallel implementation with separate clones
- **Two-stage review**: First check spec compliance, then check code quality
- **Coordination rules**: No shared mutable state, aggregate results in the parent, report failures immediately
- **Concurrency and rate limits**: Cap simultaneous heavy agents (4, never >5), launch fan-outs in waves, default to cheaper models / lower effort, and recover from server-side 429 throttles — applies to both the Workflow tool and direct parallel Agent dispatch

**Dependencies**: None

---

### agent-manager

[DEPRECATED] Go-based terminal UI for managing Claude Code agent processes. Unmaintained; no longer offered for new installs (not shown in the installer list, not in any preset), kept in-repo for existing users.

**Installs**: `commands/agents.md`. The Go binary (`~/.ccgm/bin/ccgm-agents`) is **not** installed by CCGM — run `modules/agent-manager/postInstall.sh` manually to fetch it.

**What it does**: Provides a terminal dashboard for monitoring and controlling Claude Code agents across multi-clone repos:

- **Agent list**: Shows all agents running in tmux panes with health status, current task, and last activity
- **Log viewer**: Stream or browse agent log output in real time
- **Controls**: Launch, stop, restart, and force-kill agents from the TUI
- **Filtering**: Filter agent list by name, status, or repo

The `/agents` command launches the TUI. The CCGM installer has no post-install hook, so the binary is not installed automatically — fetch it by running `modules/agent-manager/postInstall.sh` manually (it downloads and checksum-verifies the release binary into `~/.ccgm/bin/`).

| Command | Description |
|---------|-------------|
| `/agents` | Launch the Agent Manager TUI |

**Status**: Deprecated - unmaintained and not offered for new installs. Development is paused in favor of a GUI-based replacement.

**Dependencies**: multi-agent

---

### cloud-dispatch

Delegate GitHub issues to autonomous Claude Code agents on Hetzner Cloud VMs.

**Installs**: 4 command files, 1 rule file, lib scripts for VM lifecycle and workspace management

**What it does**: A complete cloud agent dispatch system for running CCGM agents on remote VMs:

- **VM lifecycle**: Create, health-check, and destroy Hetzner Cloud cx22 VMs from the CLI
- **Secret management**: Inject GitHub tokens and SSH keys at session start; revoke on cleanup
- **Workspace provisioning**: Clone repos, set up agent identities, and assign issues to agent slots
- **Agent launch**: Start CCGM agents headlessly across all VMs with configurable turn limits
- **Status and collection**: Check agent progress, pull PR URLs, and collect completed work

Commands installed:

| Command | Description |
|---------|-------------|
| `/dispatch` | Dispatch GitHub issues to cloud VMs |
| `/dispatch-status` | Check status of dispatched agents across all VMs |
| `/dispatch-stop` | Stop agents and optionally destroy VMs |
| `/vm-manage` | Create, destroy, health-check, or SSH into dispatch VMs |

**Config prompts**: Set `HCLOUD_TOKEN` in your shell environment (see Hetzner Cloud console)

**Dependencies**: None

---

### ccgm-doctor

Audit tool for Claude Code installs.

**Installs**: `bin/ccgm-doctor`, `lib/doctor.py`, `evals/routing.json`

**What it does**: Three subcommands: `check-resolvable` verifies hook references, command descriptions, and script paths point to real files; `dry` measures lexical overlap between command descriptions to spot ambiguous routing; `resolver-eval` runs a routing suite of `{intent, expected}` assertions against keyword-overlap scoring. Ships a default routing suite covering common slash commands.

**Dependencies**: None

---

### commands-preamble

Experimental UserPromptSubmit hook that injects iron-law principles before slash commands run.

**Installs**: `hooks/inject-preamble.py`, `preamble/preamble.md`, `settings.partial.json`

**What it does**: Injects a compact preamble (Confusion Protocol, Completeness, Evidence Before Claims, Root Cause Before Fix) at the start of slash-command invocations. Opt-in, disabled by default. Useful for ensuring agents internalize the discipline rules even when a specific command file doesn't explicitly reference them.

**Dependencies**: settings, autonomy, code-quality

---

### autoheal

Continuous self-improvement loop: capture hook events, daily transcript analysis via direct Anthropic API, local digest plus optional Resend email, opt-in real-time security alerts, opt-in confidence-gated auto-apply, cross-clone file locking, per-repo overrides, retention sweep, and a webhook publisher seam pre-built for future dev.lem.work integration.

**Installs**: 6 hooks (`permission-event-logger.py`, `failure-logger.py`, `user-correction-detector.py`, `permission-request-suppress.py`, `post-prompt-introspect.py`, `realtime-security-scanner.py`), 7 commands (`/autoheal`, `/autoheal-apply`, `/autoheal-digest`, `/autoheal-snooze`, `/autoheal-toggle`, `/permission-audit`, `/permission-fix`), 10 bin scripts under `~/.claude/autoheal/`, `rules/autoheal.md`, JSONL schemas, redaction patterns, and a LaunchAgent installer.

**What it does**: Four event-capture hooks (`PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`) record permission requests, tool failures, and user-correction phrases to `~/.claude/autoheal/events/{date}.jsonl` (cross-clone fcntl-locked). A daily `launchd` LaunchAgent runs `autoheal-analyze.sh` (direct `curl` to Anthropic — no claude -p, no exec-escape surface), which proposes small hook/settings fixes filtered by a privilege-escalation gate. Proposals render to a local markdown digest, optionally email via Resend (multi-recipient with per-recipient idempotency keys), and feed into `/permission-fix` (in-session) and `/autoheal-apply` (manual or auto-applied via the strict confidence-9 / breadth-1 / settings-only gate). Default OFF for the three opt-in surfaces (real-time alerts, auto-apply, email/webhook).

**Dependencies**: hooks

---

### dreaming [BETA]

Nightly, cost-capped service that mines session transcripts for cross-session failure patterns and optimistically auto-integrates evidence-tagged memory-store changes — write-then-review, made safe by per-op-kind postures, a 24h dwell window, per-run blast caps, batch-anomaly detection, a windowed circuit breaker, an eval gate, a daily report, and git-backed rollback. `autoheal`'s capture-analyze-propose pipeline, retargeted at transcripts instead of permission events.

**Installs**: `rules/dreaming.md`; 7 bin scripts (`dream-analyze.sh`, `dream-digest.sh`, `dream-daily.sh`, `dream-reconcile.sh`, `dream-eval.sh`, `dream-install.sh`, `dream-scorecard.sh`); 5 commands (`/dream`, `/dream-digest`, `/dream-review`, `/dream-apply`, `/dream-scorecard`); lib files for the transcript miner, map/reduce analyzer, optimistic integration engine, apply path, auto-memory reconciliation, weekly observability scorecard, evidence-bundle and proposal JSON schemas, prompt templates, and LaunchAgent/cron templates; 9 eval seed tasks plus fixtures under `eval/tasks/`.

**What it does**: The deterministic transcript miner (`discover()`/`mine()`/`cluster()`/`budget()` plus a schema-drift canary) turns session transcripts into a bounded, redacted (secrets + PII) evidence bundle, re-deriving each transcript's owning learnings-store slug from its own `cwd` field rather than a directory-name heuristic. The map-reduce analyzer (`dream_analyze.py`, direct Anthropic API over `curl` -- no nested agent runtime) turns that evidence into per-change proposals against the `self-improving` learnings store, written to `~/.claude/dreaming/proposals/{date}.jsonl` and rendered as a digest (`/dream-digest`). The optimistic integration engine (`run_optimistic_integrate`) is the primary write path: it auto-integrates eligible proposals with per-op-kind postures (verify integrates immediately; add/supersede land under a 24h dwell window before injection; evictions quarantine), bounded by per-run blast caps, batch-anomaly detection, and a windowed self-healing circuit breaker. An opt-in composite eligibility gate (`lib/eligibility.py`, default off, `add`/`supersede` only) can decide those two op-kinds' admission by a deterministic no-LLM waterfall -- static floor, non-compensatory origin gate, then a four-signal composite score (`confidence`/`prevalence`/`recency`/`novelty`) re-derived from the transcripts and live store at apply time -- with a read-only `eligibility-dry-run` CLI to preview a day before opting in; evictions and `verify` are untouched. `/dream-review` inspects auto-integrated + dwelling rows and vetoes/reverts them post-hoc; `/dream-apply` remains the back-compat human-gated path (and the only path a `_global` proposal is promoted through). A nightly `launchd` LaunchAgent (`dream-install.sh`) chains analyze -> eval-refresh -> optimistic-integrate -> digest -> reconcile -> retention; optimistic integration is default OFF (`optimistic_integration.enabled`) and eval-gated. A read-only reconciliation report (`reconcile_automemory.py`) compares Claude Code's own harness auto-memory (`~/.claude/projects/*/memory/`) against the learnings store and appends import-candidate/contradiction findings to the digest, never writing to auto-memory itself. The memory eval harness (`eval/`) runs a with/without-memory A/B (plus a full-context-dump third arm) across 9 seed tasks -- uplift, canary, contradiction, and one end-to-end task exercising the analyzer's own mined output -- with four-bucket outcome classification; `dream-eval.sh --gate` is the regression gate the optimistic engine must pass. A read-only weekly observability scorecard (`/dream-scorecard`, `lib/scorecard.py`) aggregates captured / injected / reused / applied counts plus store health from the on-disk signals (learnings store, injection telemetry, proposals), so the read path's value is reviewable at a glance without touching the store.

**Dependencies**: hooks, self-improving, session-history

---

### compound-knowledge

Team-shared learnings persisted in `docs/solutions/` and re-injected as grounding into later runs.

**Installs**: `skills/compound/`, `skills/compound-refresh/`, `skills/compound-reproject/`, `agents/learnings-researcher.md`

**What it does**: After solving a non-trivial problem, `/compound` writes a structured markdown doc with YAML frontmatter to `docs/solutions/`. Later `/xplan` and `/review` runs use the learnings-researcher agent to find relevant entries and inject them as grounding. Counterpart to self-improving's personal MEMORY.md — compound-knowledge is committed and code-reviewed, self-improving stays on your machine.

**Dependencies**: skill-authoring

---

### document-review

Seven-lens plan-quality gate before a spec ships to execution.

**Installs**: `skills/document-review/`, `agents/{coherence,feasibility,product-lens,scope-guardian,design-lens,security-lens,adversarial-document}-reviewer.md`

**What it does**: `/document-review` fans out to seven role-specific reviewer agents (coherence, feasibility, product-lens, scope-guardian, design-lens, security-lens, adversarial) and merges structured JSON findings with severity and confidence. Each lens has tight "what you flag" boundaries so they don't overlap.

**Dependencies**: skill-authoring, subagent-patterns

---

### adversarial-review

One hostile lens against a plan or any entity, with automatic plan incorporation.

**Installs**: `skills/adrev/`, `agents/adrev-reviewer.md`

**What it does**: `/adrev` resolves a target (plan, doc, PR, issue, code directory, or stated concept) and dispatches a fresh-context adrev-reviewer agent that attacks premises, hunts failure modes, steelmans the strongest opposing case, and checks falsifiability and reversal costs. When the target is a plan, the reviewing agent incorporates its findings into the plan automatically - high-confidence findings revise sections directly, judgment calls land in `## Risks & Open Questions`, and the full review is written to the plan's `reviews/` directory - unless invoked with `--no-apply`. Plan targets also get four **autonomous-execution tenets** enforced (not just noted - the reviewer expands the plan to satisfy them): T1 human work minimized and bucketed to the edges, T2 a follow-up-completion contract, T3 enough decision context to direct unplanned work without a human, T4 a comprehensive autonomous E2E test suite over every testable surface. Non-plan targets are never modified. The single-lens, any-entity counterpart to document-review's 7-lens doc gate.

**Dependencies**: subagent-patterns

---

### git-worktrees

Solo-agent worktree-based isolation for feature work.

**Installs**: `rules/git-worktrees.md`, `commands/worktree-start.md`, `commands/worktree-finish.md`

**What it does**: Lighter alternative to the multi-clone setup when only one agent is active. `/worktree-start` creates a new worktree for a feature branch; `/worktree-finish` merges and cleans up. Uses git's native worktree command so the main checkout stays on whatever branch you want.

**Dependencies**: None

---

### launch

One-prompt spec to deployed Cloudflare Pages site.

**Installs**: `skills/launch/`, `examples/sample-spec.md`

**What it does**: `/launch` takes a one-page spec and reaches a deployed Cloudflare Pages site without further human input — except for the unavoidable Connect-to-Git dashboard step, which the skill stops to ask for. Inspired by Karpathy's Sequoia talk on shrinking the prompt-to-production loop. Doubles as a forcing function for surfacing every place the infra is still human-shaped.

**Dependencies**: cloudflare, git-workflow, docs-for-agents

---

### pr-feedback

Structured resolver for PR review comments with clustering.

**Installs**: `skills/resolve-pr-feedback/`, `agents/pr-comment-resolver.md`, `scripts/get-pr-comments`

**What it does**: `/resolve-pr-feedback` fetches unresolved review threads via GraphQL, triages new vs already-handled, and (above a threshold) runs cluster analysis — categorizes each into 11 fixed concern categories and groups by category + spatial proximity. Clusters surface systemic issues instead of dispatching 10 one-off fixes. Parallel pr-comment-resolver subagents apply unambiguous fixes, post inline replies, and resolve threads; taste questions are batched for human decision.

**Dependencies**: skill-authoring, subagent-patterns

---

### session-history

Cross-platform session historian agent for surfacing institutional knowledge from prior sessions.

**Installs**: `agents/session-historian.md`, `commands/recall.md`, `scripts/{discover-sessions.sh,extract-metadata.py,recall.py,repo_detect.py,add-agents-md-symlinks.sh}`

**What it does**: Searches prior Claude Code and Codex session transcripts on the same repo for what was tried, what failed, and what was decided. `/recall` runs the search directly; other skills (`/compound`, `/xplan`, `/debug`) invoke the agent to ground their work in earlier sessions a fresh agent cannot see.

**Dependencies**: None

---

### session-lifecycle

Structured session shutdown via `/sds`.

**Installs**: `commands/sds.md`, `lib/sds-broadcast.sh`

**What it does**: `/sds` runs an autonomous end-of-session wrap-up sweep — commits dirty work, updates referenced issues, runs `/reflect`, writes a handoff via `handoff.py`, broadcasts a session-ended event to sibling clones, then terminates the Claude Code session (`kill -TERM $PPID`). Bookend to `/startup`. Composes existing primitives rather than duplicating them.

**Dependencies**: multi-agent, self-improving, git-workflow

---

### skillify

Slash command that promotes an ad-hoc session capability into a durable skill.

**Installs**: `commands/skillify.md`, `bin/ccgm-skillify-check`

**What it does**: Inspired by the pattern where every repeated failure becomes structurally unreachable by being turned into a tested skill. `/skillify` takes a capability the agent demonstrated this session, generates a command file with triggers and rules, an optional deterministic helper script, a pinning test, and a learnings-store entry pointing at the new skill.

**Dependencies**: None

---

### todos

File-based review-finding tracker for things that don't merit a GitHub issue.

**Installs**: `skills/todo-create/`, `skills/todo-triage/`, `skills/todo-resolve/`

**What it does**: Review findings, PR nitpicks, and tech debt that fall between "fix immediately" and "cut a full issue" go to `.claude/todos/NNN-{status}-{priority}-{description}.md` with YAML frontmatter. Three skills compose — `/todo-create` (canonical writer), `/todo-triage` (interactive pending→ready transition), `/todo-resolve` (batch-resolve ready todos via parallel subagents).

**Dependencies**: skill-authoring, subagent-patterns

---

### argus

Visual-ATDD convergence loop: develop UI against a design spec and self-sign-off via deterministic gates plus a separate judge agent.

**Installs**: `skills/argus/SKILL.md` (`/argus`), `agents/argus-judge.md`, `rules/argus.md`, plus spec/verdict/gate/rubric schemas and six dependency-free deterministic gate scripts under `skills/argus/`

**What it does**: Runs an implement → render → externally-judge → converge loop for a feature's UI. An `implementer` subagent edits code, deterministic gates (build/lint/type/WCAG-contrast/a11y/snapshot/flows) form an ungameable floor, and a *separate* `argus-judge` subagent scores the render against the spec, a reference image, and the design system — never seeing the diff. The loop signs off after two consecutive rubric passes (3-attempt-per-dimension cap, then freeze + document), then commits a snapshot baseline. Platform-agnostic via a pluggable sensor+gates adapter: a web adapter is built in (Chrome capture); iOS/macOS plug in via a project adapter. Minimal human input — ≤1 reference image per screen plus one spot-check.

**Dependencies**: subagent-patterns

---

### statusline

A compact, dependency-free single-line Claude Code statusline.

**Installs**: `statusline.sh` (script), `settings.partial.json` (wires the `statusLine` setting)

**What it does**: Consumes the statusline JSON Claude Code pipes on stdin and renders, separated by ` | `: model + effort (`🧠 O-4.8 Max`), multi-clone identity (`⛓ agent-2`, read from `.env.clone`), directory + git branch, context-used percentage measured against the auto-compact budget (`ctx:42%`), a `⚠ COMPACT SOON` warning when nearing that budget, session cost (`$1.23`, from `.cost.total_cost_usd`), and 5h/7d rate-limit bars with reset countdowns. Every field is optional — a missing JSON key drops its section, so the bar degrades gracefully on older Claude Code versions.

Unlike the statusline script bundled in `commands-utility` (which is never wired to the `statusLine` setting), this module ships the script *and* a settings partial, so `--add statusline` produces a working statusline with no manual `settings.json` editing. It is a superset of that script — it adds clone identity, session cost, and the compaction warning. Depends only on `jq`.

**Dependencies**: None

---

### relevance-injection [BETA]

Opt-in, backward-compatible relevance-scoped rule injection plus a tiered always-on safety core.

**Installs**: `rules/relevance-injection.md`, `hooks/relevance-inject.py`, `lib/relevance_select.py`, `lib/applicability-schema.json`, `settings.partial.json` (SessionStart hook)

**What it does**: Addresses the always-on rule-token load without changing default behavior. Two pieces:

- **Tiered safety core**: an authoritative precedence for the always-on Iron Laws (safety/permissions > confusion protocol > TDD/verification > the rest), so they are tiered rather than nine-way flat. Documentation + metadata only.
- **Opt-in injection**: when `CCGM_RELEVANCE_INJECTION=true` is set in `~/.claude/.ccgm.env`, a `SessionStart` hook emits an `additionalContext` pointer naming the safety core plus the modules relevant to an optional task profile (`CCGM_RELEVANCE_LANGS`, `CCGM_RELEVANCE_TASKTYPES`). When the flag is unset (the default), the hook no-ops and all rules load exactly as before.

Selection lives in a pure, deterministic, tested library (`relevance_select.py`). Modules may add an optional `applicability` field to their `module.json` (absent or `{"always": true}` == always applicable, preserving pre-feature behavior); otherwise `{"langs": [...]}` / `{"taskTypes": [...]}` scope the module to a profile.

**Dependencies**: hooks

---

## Category: patterns

Reusable development patterns and methodologies.

---

### code-quality

Code standards, testing requirements, error handling, security practices, and build verification.

**Installs**: `rules/code-quality.md`, `rules/change-philosophy.md`

**What it does**: A comprehensive code quality ruleset covering:

- **Dependency minimization**: Prefer built-in over library over framework
- **Migration validation**: PostgreSQL reserved keyword quoting, idempotent patterns, local testing
- **Component patterns**: Functional React/TypeScript components, path aliases
- **Testing**: What to test (features, edge cases, bug fixes, complex logic)
- **Error handling**: Frontend (error boundaries, toasts) and backend (centralized middleware, no leaked internals)
- **Security**: Input sanitization, upload validation, no committed secrets, RLS
- **Build verification**: Pre-push only (not after every change), CI parity
- **Living documents**: When and how to update README.md and project-story.md after merges

The `change-philosophy.md` rule establishes an elegant integration design philosophy: prefer additive, composable changes over rewrites; respect existing patterns; make the smallest change that achieves the goal.

**Dependencies**: None

---

### browser-automation

Browser tool selection hierarchy and verification workflows.

**Installs**: `rules/browser-automation.md`

**What it does**: Establishes rules for when and how to use browser automation:

- **Tool selection hierarchy**: WebMCP tools > Chrome extension > Playwright
- **Verification priority**: CLI tools > MCP servers > API calls > WebMCP > browser automation
- **When browser IS appropriate**: Visual layout verification, client-side interactivity testing, OAuth flows, screenshots
- **UI verification workflow**: Get browser context, navigate, wait, check errors, screenshot
- **Deployment verification**: Never test until deployment is actually complete

**Dependencies**: None

---

### common-mistakes

Eight documented anti-patterns extracted from real mistakes.

**Installs**: `rules/common-mistakes.md`

**What it does**: Prevents Claude from repeating known failure patterns:

1. **Shallow directory exploration** - always use two-method verification in monorepos
2. **Dependency blindness** - check open PRs before creating branches
3. **ESLint Fast Refresh violations** - never mix component and non-component exports
4. **Suggesting already-tried solutions** - assume the user already tried the obvious
5. **Premature solutions** - check linter configs and existing patterns first
6. **Git multi-clone confusion** - branch from `origin/main`, check sibling clones
7. **Cloudflare Pages vs Workers** - know which product to use
8. **CF Pages without Git integration** - must be created with Git integration at inception (cannot be retrofitted)

**Dependencies**: None

---

### output-formatting

Formatting rules for user-facing output, starting with copy-pasteable content.

**Installs**: `rules/copy-paste-output.md`

**What it does**: When output is meant to be copy-pasted somewhere else (emails, texts, social posts, bios, form answers, prompts for other tools, config snippets), Claude delivers it in a fenced code block containing exactly the text that should land at the destination - never a blockquote, which renders as a vertical line in the terminal and copies dirty. Commentary stays outside the block; plain text by default, markdown source only when the destination renders markdown.

**Dependencies**: None

---

### make-interfaces-feel-better

Design-engineering details that compound into polished interfaces. Implementation-level reference files are vendored from [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better) (MIT); the design-direction reference is a CCGM addition (folded in from the former `frontend-design` module).

**Installs**: `skills/make-interfaces-feel-better/` (SKILL.md + design-direction.md, typography.md, surfaces.md, animations.md, performance.md)

**What it does**: A model-invoked skill. Claude loads it automatically when the conversation is about UI polish, animations, shadows, borders, typography, micro-interactions, aesthetic direction, or any visual-detail work. Covers:

- **Design direction** (CCGM addition): Aesthetic identity (minimal/brutalist/editorial/…), typeface and color-palette selection, spacing scale, motion philosophy, avoiding generic AI-generated aesthetics
- **Typography**: `text-wrap: balance` / `pretty`, font smoothing on macOS, tabular numbers for dynamic values
- **Surfaces**: Concentric border radius, optical vs geometric alignment, shadows instead of borders, image outlines, hit areas
- **Animations**: Interruptible animations (transitions vs keyframes), enter/exit transitions, icon micro-interactions, scale on press
- **Performance**: Transition specificity, `will-change` usage

Complements `design-review` (automated review) with both aesthetic direction and implementation-level detail.

**Dependencies**: None

---

### systematic-debugging

Structured 4-phase root cause investigation methodology.

**Installs**: `rules/systematic-debugging.md`, `rules/debugging.md`

**What it does**: Prevents scattered debugging by enforcing a systematic process:

1. **Investigate**: Read the actual error, identify the exact failure point
2. **Analyze**: Look for patterns, check recent changes, trace data flow
3. **Hypothesize**: Form testable theories, rank by likelihood
4. **Implement**: Fix the root cause (not symptoms), verify the fix, check for regressions

Also includes a "three-strike rule": if you try three approaches without progress, step back and reassess your understanding of the problem.

The `debugging.md` rule routes bug fix and debugging requests to the `/debug` skill (from the debugging module) for structured Opus-powered root-cause analysis, rather than ad-hoc investigation.

**Dependencies**: None

---

### test-driven-development

Strict red-green-refactor TDD discipline.

**Installs**: `rules/test-driven-development.md`

**What it does**: Enforces TDD when writing new code:

- **Red**: Write a failing test first
- **Green**: Write the minimum code to make it pass
- **Refactor**: Clean up without changing behavior
- **For features**: Test the public API, not implementation details
- **For bug fixes**: Write a test that reproduces the bug before fixing it
- **When TDD applies**: New features, bug fixes, complex logic, refactoring
- **Rationalizations to reject**: "This is too simple to test," "I'll add tests later," "The types guarantee correctness"

**Dependencies**: None

---

### verification

Evidence-before-claims methodology for confirming work is done.

**Installs**: `rules/verification.md`

**What it does**: Prevents Claude from claiming completion without proof:

- **5-step process**: Plan verification, execute commands, read full output, evaluate results, report honestly
- **Evidence table**: What evidence to provide for each claim type (bug fix, feature, deployment, etc.)
- **Fresh-run requirement**: Always re-execute verification commands rather than relying on earlier output
- **Honest reporting**: If verification fails, say so - never claim success without evidence

**Dependencies**: None

---

### agent-native

Principles for designing applications where an agent is a first-class user — alongside humans.

**Installs**: `rules/agent-native.md`, `rules/agent-native-self-eval.md`, `skills/agent-native-audit/`, `agents/reviewers/agent-native-reviewer.md`

**What it does**: Defines four principles — parity (every UI action has a programmable equivalent), granularity (composable primitives), composability (operations chain into workflows), and emergent capability (combinations exceed the sum). Ships `/agent-native-audit` which scores a codebase against the principles with concrete counts, and a reviewer persona that plugs into the unified review orchestrator. Also includes a self-eval / red-team rubric (`agent-native-self-eval.md`) that scores a surface against the four principles using a reference test surface and parallel red-team probing — a repeatable standard for self-auditing a system or assessing agentic engineering work.

**Dependencies**: subagent-patterns

---

### docs-for-agents

Convention for shipping machine-readable docs alongside human docs.

**Installs**: `rules/docs-for-agents.md`

**What it does**: Any project an agent will install, build, test, deploy, or debug should have an `AGENTS.md` next to its `README.md` — copy-pasteable command blocks, not prose, not "open the dashboard and click..." steps. The rule explains what to include and what to leave out.

**Dependencies**: None

---

### rule-authoring

TDD-style discipline for writing rules that hold up under pressure.

**Installs**: `rules/rule-authoring.md`, `rules/pressure-testing.md`, `commands/pressure-test.md`

**What it does**: Treats rule authoring as test-driven development — pressure-test a candidate rule with adversarial scenarios, capture the rationalizations agents use to bypass it, and rewrite until the rule closes those loopholes. The `/pressure-test` command runs the loop interactively.

**Dependencies**: None

---

### skill-authoring

Discipline for writing skills and slash commands that stay efficient, portable, and context-safe.

**Installs**: `rules/skill-authoring.md`

**What it does**: Covers reference-file inclusion (vs. inlining), conditional content extraction, tool selection (when to spawn a subagent vs. handle inline), and writing style for skill markdown. Aimed at avoiding skills that bloat context or hide important behavior in opaque scripts.

**Dependencies**: None

---

### output-styles

Packages CCGM's always-on tone rules as a Claude Code output style instead of always-loaded `rules/*.md`.

**Installs**: `output-styles/ccgm-terse.md` (the `CCGM Terse` output style)

**What it does**: Consolidates three tone-shaping behaviors — terse, action-first communication (`identity`/`soul.md`), autonomous end-to-end execution (`autonomy`), and clean copy-paste output (`output-formatting`) — into a single output style. Claude Code applies output styles as a system-prompt layer **fixed at session start and prompt-cached**, rather than re-sending rule files as conversation context every turn, so stable always-on tone instructions cost fewer tokens there. Select it via `/config`.

The module does **not** delete the source rules; it offers a styled alternative. The tradeoff (cached tokens vs. per-rule granularity and per-repo overrides) is documented in the module README, along with the recommendation to remove the redundant tone rules once the style is selected, to avoid sending the same guidance twice.

**Dependencies**: None

---

## Category: tech-specific

Guides for specific technologies and platforms.

---

### cloudflare

Cloudflare Pages and Workers deployment guide.

**Installs**: `rules/cloudflare.md`

**What it does**: Prevents common Cloudflare deployment mistakes:

- **Pages vs Workers**: Comparison table for choosing the right product
- **Git integration**: Pages projects MUST be created via Connect-to-Git at inception — Cloudflare cannot retrofit Git integration onto an existing direct-upload project
- **Red flags**: How to detect a misconfigured Pages project
- **Migration**: The destructive remediation procedure if you inherit a Pages project without Git integration

**Dependencies**: None

---

### supabase

Supabase API key terminology, environment variables, and migration workflow.

**Installs**: `rules/supabase.md`

**What it does**: Ensures correct Supabase terminology and practices:

- **Key terminology**: Publishable key (not "anon key"), secret key (not "service_role key")
- **Environment variables**: Correct naming conventions for client and server
- **Circuit breaker**: Rules to prevent tripping Supabase connection pooler lockouts
- **Migration workflow**: References the code-quality module for validation details

**Dependencies**: None

---

### mcp-development

Guide for building MCP (Model Context Protocol) servers.

**Installs**: `rules/mcp-development.md`

**What it does**: Provides patterns for building MCP servers:

- **Language choice**: TypeScript for ecosystem breadth, Python for data/ML
- **Transport**: stdio for local, Streamable HTTP for remote
- **Tool naming**: `{service}_{action}_{resource}` convention
- **Input schemas**: Required vs optional fields, enum types, validation
- **Error handling**: Structured error responses, retry guidance
- **Testing**: MCP Inspector for interactive testing
- **Quality checklist**: Pre-publish verification steps

**Dependencies**: None

---

### shadcn

Patterns for using shadcn/ui components in React projects.

**Installs**: `rules/shadcn.md`

**What it does**: Establishes conventions for shadcn/ui usage:

- **Composition over custom**: Use existing components before building new ones
- **Semantic theming**: Use `bg-primary` not `bg-blue-500`; define tokens in CSS variables
- **Form architecture**: Use React Hook Form + Zod, wrap in `<Form>`, use `<FormField>` components
- **Layout patterns**: Prefer `flex` + `gap` over margins, use `size-*` for square elements
- **Accessibility**: ARIA labels, keyboard navigation, focus management
- **CLI workflow**: Use `npx shadcn@latest add {component}` to install components

**Dependencies**: None

---

### tailwind

Tailwind CSS v4 design system patterns.

**Installs**: `rules/tailwind.md`, `rules/frontend-css.md`

**What it does**: Guides Tailwind v4 usage (CSS-first configuration, not the deprecated `tailwind.config.ts`):

- **CSS-first config**: All configuration in CSS using `@theme`, `@custom-variant`, and `@utility`
- **Design token hierarchy**: Primitive (raw values), semantic (contextual names), component (specific elements)
- **Color system**: OKLCH for perceptual uniformity, CSS custom properties for theming
- **CVA variants**: Use class-variance-authority for component variant management
- **Dark mode**: `@custom-variant dark (&:where(.dark, .dark *))` pattern
- **Responsive**: Mobile-first with `sm:`, `md:`, `lg:` breakpoints
- **v3 to v4 migration**: Mapping table for changed utility names

The `frontend-css.md` rule covers the Tailwind v4 `cursor: pointer` gotcha - v4's preflight no longer sets cursor styles on `<button>` elements. Includes the correct `@layer base` pattern to add at project start.

**Dependencies**: None
