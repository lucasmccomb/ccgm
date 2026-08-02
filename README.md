# CCGM (Claude Code God Mode)

<img width="369" height="135" alt="image" src="https://github.com/user-attachments/assets/29953ee7-3e7c-47cc-9ef7-e8b2e8ccbc89" />

Modular configuration system for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - pick the modules you want, install in seconds. Works with Claude Code CLI, VS Code, Cursor, the macOS Claude app, and any other editor with Claude Code support.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Table of Contents

- [What is CCGM?](#what-is-ccgm)
- [Install via agent (paste this)](#install-via-agent-paste-this)
- [Requirements](#requirements)
- [Install](#install)
- [Module Catalog](#module-catalog)
- [Memory System](#memory-system)
- [Customization](#customization)
- [Manual Installation](#manual-installation)
- [Utilities](#utilities)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## What is CCGM?

CCGM is a curated collection of 78 configuration modules for Claude Code. Instead of hand-crafting rules, hooks, commands, and permissions from scratch, you pick modules and install them with a single command.

Each module is self-contained with its own README, so you can also [copy individual files manually](#manual-installation) without the installer.

### What gets installed

CCGM places files into `~/.claude/` (global) or `.claude/` (project-level):

| Directory | What | How Claude Uses It |
|-----------|------|-------------------|
| `rules/*.md` | Behavior rules | Loaded automatically at session start |
| `commands/*.md` | Slash commands | Available as `/commit`, `/pr`, etc. |
| `skills/*/SKILL.md` | Packaged capabilities | Invoked by name, e.g. `/brainstorm`, `/ce-review` |
| `agents/*.md` | Subagent prompts | Reusable prompts invoked by commands and skills via the Task tool |
| `hooks/*.py` | Workflow hooks | Triggered on Claude Code events |
| `settings.json` | Permissions | Controls tool access and auto-approval |

## Install via agent (paste this)

Paste the block below into a fresh Claude Code session. The agent detects your environment, picks a preset, runs the installer, and reports what was installed. No flags, no shell environment to configure first.

```
Install CCGM (Claude Code God Mode) for me.

Steps:
1. Detect my OS (uname -s), shell ($SHELL), and home directory ($HOME).
2. Clone the repo if it does not already exist:
     git clone https://github.com/lucasmccomb/ccgm.git ~/code/ccgm
   If it already exists, pull the latest main:
     cd ~/code/ccgm && git fetch origin && git checkout main && git pull --ff-only origin main
3. Read the available presets: ls ~/code/ccgm/presets/
   Available presets and what they include:
     - minimal  : global-claude-md, autonomy, git-workflow
     - standard : the above + identity, hooks, branch-guard, ask-context, model-vetting, live-testing-guard, settings, commands-core, commands-utility, self-improving, output-formatting, writing-system, statusline
     - team     : standard core (minus identity, commands-utility, model-vetting, live-testing-guard, self-improving, statusline) + github-protocols, code-quality, systematic-debugging, verification, autoheal, and review/compound-knowledge tooling (ce-review, pr-feedback, document-review, compound-knowledge, skill-authoring, subagent-patterns, pr-review-toolkit)
     - cloud-agent : large set for power users running autonomous agents
     - full     : every stable module
   Based on what you know about my workflow, recommend one preset. Ask me to confirm or pick a different one before continuing. (One question only — do not ask anything else.)
4. Check what is already installed by looking at ~/.claude/rules/, ~/.claude/commands/, ~/.claude/hooks/. List any CCGM files already present and note you will skip overwriting them.
5. Read ~/.claude/settings.json if it exists and note its content. The installer will merge non-destructively — it will not delete keys that are already there.
6. Run the installer:
     cd ~/code/ccgm
     CCGM_NON_INTERACTIVE=1 \
       CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo '')" \
       ./start.sh --preset <chosen-preset>
7. Verify the install succeeded by checking that these paths exist:
     ~/.claude/rules/
     ~/.claude/CLAUDE.md   (if global-claude-md was in the preset)
   List the files now present in ~/.claude/rules/ and ~/.claude/commands/.
8. Report: which preset was installed, which modules were skipped (already present), and any errors.
```

For blocks pre-selecting a specific preset, and for how to dry-run this safely, see [docs/install-via-agent.md](docs/install-via-agent.md).

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- macOS or Linux
- bash 3.2+ (the installer scripts always run under bash via their shebang, regardless of your login shell)
- git
- python3
- jq

The installer checks for these tools (plus the optional gh CLI) and offers to install any that are missing.

## Install

```bash
git clone https://github.com/lucasmccomb/ccgm.git
cd ccgm
./start.sh
```

The interactive setup handles everything: prerequisite checks, module selection, and configuration. No flags needed.

### Installing from an editor

If you use Claude Code in VS Code, Cursor, or another editor with a built-in terminal, run the install commands in that terminal. If your editor doesn't have one, use Terminal.app (macOS) or any terminal emulator. CCGM installs to `~/.claude/`, which is shared across all Claude Code environments - install once, works everywhere.

### Agent installation

For AI agents installing CCGM programmatically:

```bash
git clone https://github.com/lucasmccomb/ccgm.git ~/ccgm
cd ~/ccgm
CCGM_NON_INTERACTIVE=1 \
  CCGM_USERNAME="$(gh api user --jq '.login' 2>/dev/null || echo 'github-user')" \
  ./start.sh --preset standard
```

| Variable | Description | Default |
|----------|-------------|---------|
| `CCGM_CODE_DIR` | Code workspace directory | `~/code` |
| `CCGM_NON_INTERACTIVE` | Set to `1` to skip all prompts | - |
| `CCGM_TIMEZONE` | Timezone | auto-detected |
| `CCGM_USERNAME` | GitHub username | auto-detected via `gh` |

Restart Claude Code or start a new session after installation.

### Presets

For a quick install with a preset:

```bash
./start.sh --preset standard
```

| Preset | Modules | Best For |
|--------|---------|----------|
| **minimal** | global-claude-md, autonomy, git-workflow | Getting started |
| **standard** | global-claude-md, autonomy, identity, git-workflow, hooks, branch-guard, ask-context, model-vetting, live-testing-guard, settings, commands-core, commands-utility, self-improving, output-formatting, writing-system, statusline | Most users |
| **team** | global-claude-md, autonomy, git-workflow, hooks, branch-guard, ask-context, settings, commands-core, github-protocols, code-quality, systematic-debugging, verification, autoheal, output-formatting, writing-system, ce-review, pr-feedback, pr-review-toolkit, document-review, compound-knowledge, skill-authoring, subagent-patterns (+ deps) | Teams |
| **cloud-agent** | 55 modules | Autonomous/headless agents |
| **full** | 74 modules | Power users |

### Other install options

```bash
./start.sh --scope project    # Install to .claude/ in current project instead of ~/.claude/
./start.sh --link             # Symlink instead of copy (for CCGM developers)
./start.sh --add <module>     # Add one module to an existing install (inherits scope + link mode)
```

### Update / Uninstall

```bash
./update.sh      # Pull latest changes and re-apply
./uninstall.sh   # Remove only CCGM-installed files
```

### Install as a native plugin marketplace

CCGM is also published as a [Claude Code plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces). This is an **additive** path — the bash installer above remains canonical.

```bash
claude plugin marketplace add lucasmccomb/ccgm
claude plugin install code-quality@ccgm     # install any module as a plugin
```

**The bash installer is canonical; the marketplace is a projection.** A plugin's `CLAUDE.md` is not auto-loaded and a plugin can only contribute the `agent`/`subagentStatusLine` settings keys, so the marketplace path does **not** perform CCGM's deep `settings.json` merge or write the always-on global `CLAUDE.md` context. Use the bash installer when those matter.

| Component | Bash installer | Marketplace |
|-----------|----------------|-------------|
| Commands / agents / skills / output styles | `~/.claude/` | Native plugin components |
| Rules (`rules/*.md`) | Auto-loaded | Injected by a SessionStart hook, opt-in via `CCGM_PLUGIN_RULE_INJECTION=true` |
| Deep `settings.json` merge + global `CLAUDE.md` | Yes | No |

The marketplace catalog (`.claude-plugin/marketplace.json`) and per-module `plugin.json` files are **generated** from `modules/*/module.json` by `modules/plugin-marketplace/lib/gen_marketplace.py` — never hand-edited. See the [plugin-marketplace module](modules/plugin-marketplace/README.md).

## Module Catalog

| Module | Category | Commands | Description | Dependencies |
|--------|----------|----------|-------------|--------------|
| **adversarial-review** | workflow | `/adrev` | Adversarial review of a plan or any entity (file, PR, issue, dir, concept). Separate reviewer agent attacks premises and failure modes; plan targets get findings incorporated automatically and four autonomous-execution tenets enforced (minimal human work, follow-up completion, decision context, comprehensive E2E coverage) unless told not to | subagent-patterns |
| **agent-manager** [DEPRECATED] | workflow | `/agents` | Go-based terminal UI (/agents) for monitoring Claude Code agent processes via tmux. Unmaintained; not offered for new installs, kept in-repo for existing users | multi-agent |
| **agent-native** | patterns | `/agent-native-audit` | Principles, audit skill, and a self-eval / red-team rubric for building applications where an agent is a first-class client | subagent-patterns |
| **argus** | workflow | `/argus` | Closed-loop visual-ATDD harness: deterministic gates plus a separate judge agent score UI renders against a design spec until convergence | subagent-patterns |
| **ask-context** | core | - | Hard PreToolUse gate: no AskUserQuestion whose decision context is invisible to the user. Blocks deictic references, identical re-asks after pushback, and mid-workstream questions with no visible text | settings |
| **atdd** | workflow | `/atdd` | Agentic Test-Driven Development. /atdd reads Playwright vision specs, iteratively builds app code until all tests pass, then ships | - |
| **autoheal** | workflow | `/autoheal`, `/autoheal-apply`, `/autoheal-digest`, `/autoheal-snooze`, `/autoheal-toggle`, `/permission-audit`, `/permission-fix` | Self-healing observability loop: captures permission events, tool failures, and user-correction signals to a local JSONL log; daily analyzer (direct Anthropic API) surfaces a digest of proposed config fixes via `/autoheal-digest` and `/autoheal-apply`. Default-off opt-ins: `realtime_alerts_enabled` (mid-session security alerts), `auto_apply_enabled` (confidence-gated apply), `email_enabled` (Resend digest), `webhook_url` (future dev.lem.work seam). Bring-up: `bash start.sh --add autoheal` then `bash modules/autoheal/bin/autoheal-install.sh` | hooks |
| **autonomy** | core | - | Claude as a fully autonomous engineer - executes tasks end-to-end without unnecessary questions | - |
| **brainstorm** | commands | `/brainstorm` | Design-before-implementation gate: forbids code until a design spec with 2-3 approach tradeoffs is written and user-approved, then hands off to /xplan | - |
| **branch-guard** | core | - | Hard PreToolUse gate: no edits or git mutations while HEAD is on the default branch. Fires before the first edit | settings |
| **brand-naming** | commands | `/brand`, `/brand-check` | Full naming pipeline: word exploration, then domain, trademark, app store, and social handle checks. `/brand-check` runs the same verification against one name you already have | - |
| **browser-automation** | patterns | - | Browser tool selection (Chrome, Playwright, WebMCP), verification priority, UI testing workflow | - |
| **capability-router** | commands | `/capabilities` | Decision map for CCGM's overlapping command clusters (research, review, planning, debugging, knowledge), plus a tight always-on pointer rule | - |
| **ccgm-doctor** | workflow | - | Audit tool for Claude Code installs: dangling hook/command refs, lexical overlap between command descriptions, and a routing eval | - |
| **ce-review** | commands | `/ce-review` | /ce-review unified code-review orchestrator. Composes scope-drift, learnings-researcher, tier-sharpener, and review-synthesizer with structured JSON findings | compound-knowledge, pr-review-toolkit, subagent-patterns |
| **cloud-dispatch** | workflow | `/dispatch`, `/dispatch-status`, `/dispatch-stop`, `/vm-manage` | Delegate GitHub issues to autonomous Claude Code agents on Hetzner Cloud VMs. Includes /dispatch, /dispatch-status, /dispatch-stop, /vm-manage commands | - |
| **cloudflare** | tech-specific | - | Pages vs Workers selection, deployment methods, Git integration requirements | - |
| **code-quality** | patterns | - | Code standards, testing requirements, error handling, security, build verification | - |
| **commands-core** | commands | `/commit`, `/cpm`, `/ghi`, `/gs`, `/pr`, `/pr-description` | The everyday git loop: commit with an issue-prefixed message, open a PR that closes its issue, or run commit-PR-merge end to end. Plus repo status, issue creation, and a pure PR-body writer callable by other commands | - |
| **commands-extra** | commands | `/audit`, `/checkpoint`, `/freeze`, `/guard`, `/promote-rule`, `/pwv`, `/unfreeze`, `/walkthrough` | Codebase audit, Playwright visual verification, step-by-step walkthrough mode, promoting a repo rule to global, and scope control: `/freeze` locks edits to one directory until `/unfreeze`, `/guard` pairs that with careful mode, `/checkpoint` saves and resumes work-in-progress state | - |
| **commands-preamble** | workflow | - | [EXPERIMENTAL] UserPromptSubmit hook that injects a compact preamble of iron-law principles into every prompt | settings, autonomy, code-quality |
| **commands-utility** | commands | `/ccgm-sync`, `/cws-submit`, `/user-test` | Chrome Web Store submission walkthrough, syncing local config changes back to the CCGM repo, and browser-driven user testing | - |
| **common-mistakes** | patterns | - | 8 battle-tested anti-patterns: shallow exploration, dependency blindness, ESLint Fast Refresh, more | - |
| **compound-knowledge** | workflow | `/compound`, `/compound-refresh`, `/compound-reproject` | Team-shared learnings in `docs/solutions/`. After solving a non-trivial problem, capture the pattern in a versioned schema | skill-authoring |
| **copycat** | commands | `/copycat` | Analyzes external Claude Code config repos and reports the patterns, rules, and techniques worth adopting into CCGM | - |
| **debugging** | commands | `/debug` | Structured root-cause debugging on Opus: reproduce, hypothesize, instrument, diagnose, fix, verify, instead of guessing at a fix | - |
| **deepresearch** | commands | `/deepresearch` | Multi-query semantic research via the Exa MCP server: parallel query fan-out synthesized into a structured research.md | - |
| **design-review** | commands | `/design-review` | 6-pass visual design review: spacing, typography, responsive, hierarchy, accessibility, consistency. Screenshots + CSS analysis with auto-fix | - |
| **docs-for-agents** | patterns | - | AGENTS.md rule + template: machine-readable docs with copy-pasteable command blocks alongside the human docs | - |
| **document-review** | workflow | `/document-review` | Seven-lens plan-quality gate. /document-review fans out to 7 role-specific reviewers (coherence, feasibility, product, scope, design, security, adversarial) with structured JSON findings | skill-authoring, subagent-patterns |
| **documentation** | commands | `/docupdate` | Comprehensive documentation audit: README accuracy, table of contents, onboarding flow, package lists, and module coverage against actual codebase state | - |
| **dreaming** [BETA] | workflow | `/dream`, `/dream-apply`, `/dream-digest`, `/dream-review`, `/dream-scorecard` | Nightly, cost-capped transcript-mining pipeline: deterministic miner extracts cross-session friction from session transcripts, map-reduce analyzer (direct Anthropic API) proposes evidence-tagged `self-improving` learnings-store changes, digest via `/dream-digest`, read-only reconciliation report against Claude Code's own auto-memory, a memory eval harness (with/without-memory A/B, four-bucket outcome classification), and a weekly observability scorecard (`/dream-scorecard`). Human-gated apply (`/dream-apply`) is always available; opt-in `optimistic_integration` (default off, activated via `memory-setup.sh`, never a hand JSON edit) auto-integrates per-op-kind instead — immediate for `verify`, a 24h dwell window for `add`/`supersede`/`contradict`/`deprecate` — bounded by per-slug blast caps, a batch-anomaly check, a windowed circuit breaker, and an opt-in composite eligibility gate (add/supersede only, default off) that scores admission on four transcript-verified signals, with post-hoc review + rollback via `/dream-review` and `ccgm-learnings-sync revert`. Bring-up: `bash start.sh --add dreaming` then `bash modules/dreaming/bin/dream-install.sh` | hooks, self-improving, session-history |
| **editorial-critique** | commands | `/editorial-critique` | 8-pass editorial review of long-form writing: prose craft, AI-tell detection, argument, conciseness, accuracy, structure, impact, grammar. Scored report with auto-fix | - |
| **git-workflow** | core | - | Git rules: sync before history changes, rebase by default, post-merge cleanup, no AI attribution | - |
| **git-worktrees** | workflow | `/worktree-finish`, `/worktree-start`, `/worktree-sweep` | Git worktrees as the default isolation for parallel sub-agent delegation on one machine, with a safe janitor (/worktree-sweep) that enforces teardown so worktrees never silently fill the disk | - |
| **github-protocols** | workflow | - | Issue-first workflow, PR conventions, label taxonomy, code review standards | - |
| **global-claude-md** | core | - | Slim global CLAUDE.md - the root config reference that points to rules, commands, hooks, and settings | - |
| **hooks** | core | - | Python hooks: issue-first workflow, commit format, branch protection, auto-approval for safe ops | settings |
| **ideate** | commands | `/ideate` | Structured ideation framework: Socratic interview to refine ideas to 95% clarity, then hand off to /deepresearch or /xplan | - |
| **identity** | core | - | Two foundational context files: soul.md (AI personality and philosophy) and human-context.md (who you are, your goals, how you work) | - |
| **launch** | workflow | `/launch` | Takes a one-page spec to a deployed Cloudflare Pages site, stopping only for the Connect-to-Git dashboard step | cloudflare, git-workflow, docs-for-agents |
| **live-testing-guard** | core | - | Live/UI/app testing runs only on the dedicated runner machine, never the dev machine, and only under a permission grant recorded in the plan | - |
| **make-interfaces-feel-better** | patterns | `/make-interfaces-feel-better` | Design-engineering details that compound into polished interfaces. Model-invoked skill covering design direction, typography, surfaces, animations, performance | - |
| **mcp-development** | tech-specific | - | Building MCP servers: project structure, tool design, error handling, testing, evaluation patterns | - |
| **model-vetting** | core | - | Security vetting gate for new AI models: weights provenance, format safety, license/data terms, serving path, staged agentic access | - |
| **multi-agent** | workflow | `/handoff`, `/mawf`, `/workspace-setup` | Multi-clone parallel agent work with issue claiming, port allocation, /mawf workflow | startup-dashboard, hooks |
| **onboarding** | commands | `/onboarding` | Analyzes a repository and generates a structured ONBOARDING.md for new contributors | - |
| **orrery** | commands | `/orrery` | Deep-dives a codebase with parallel read-only scouts and renders an interactive, zoomable, embeddable system-design map as one self-contained HTML file: 4 zoom tiers, GitHub links pinned to an anchor SHA, per-node product prose; `/orrery update` refreshes it | - |
| **output-formatting** | patterns | - | Copy-pasteable content goes in fenced code blocks, never blockquotes, so it pastes clean anywhere | - |
| **output-styles** | patterns | - | Packages the always-on tone rules as Claude Code output styles - a prompt-cached system-prompt layer instead of per-turn rule files | - |
| **plugin-marketplace** [BETA] | core | - | Maintainer tooling that projects CCGM modules into a native Claude Code plugin marketplace. The bash installer stays canonical | - |
| **pr-feedback** | workflow | `/resolve-pr-feedback` | Fetches unresolved PR review threads via GraphQL, clusters 3+ items by category, dispatches parallel resolver agents | skill-authoring, subagent-patterns |
| **pr-review-toolkit** | commands | `/scope-drift` | Augments the external pr-review-toolkit plugin with scope-drift detection on top of the standard code/test/comment/silent-failure/type passes | - |
| **relevance-injection** [BETA] | workflow | - | Opt-in relevance-scoped rule injection with a tiered always-on safety core. Off by default | hooks |
| **remote-server** | workflow | `/onremote` | SSH access to a configured remote server with /onremote command for health checks and remote task execution | - |
| **research** | commands | `/research` | Multi-channel research using parallel agents with WebSearch, WebFetch, GitHub, Reddit. Zero dependencies.* | - |
| **rule-authoring** | patterns | `/pressure-test` | Discipline for writing rules that hold up under pressure. Treats rule authoring as a first-class skill with iron-law structure | - |
| **self-improving** | workflow | `/consolidate`, `/reflect`, `/retro` | Meta-learning system: /reflect and /consolidate commands, PostToolUse hook (PR merge/issue close reminders), PreCompact hook (pre-compaction capture), prescriptive reflection triggers | - |
| **session-history** | workflow | `/recall` | `/recall` for unified session transcript history across all clones of a repo; session-historian agent for deeper retrieval | - |
| **session-lifecycle** | workflow | `/sds` | Autonomous session shutdown: commit dirty work, update issues, reflect, write a handoff, broadcast to sibling clones | multi-agent, self-improving, git-workflow |
| **settings** | core | - | Base settings.json with 800+ tool permissions, deny list, plugin config. Defaults to safe 'ask' mode | - |
| **shadcn** | tech-specific | - | shadcn/ui patterns: composition, semantic theming tokens, form architecture, accessibility | - |
| **ship-readiness** | commands | `/ship-ready` | At-a-glance merge-gate dashboard for the current branch: checks, conflicts, diff size, reviewer state | - |
| **skill-authoring** | patterns | - | Discipline for writing skills and slash commands that stay efficient, portable, and structured across models | - |
| **skillify** | workflow | `/skillify` | Promotes an ad-hoc session capability into a durable skill with triggers, an optional helper script, and a pinning test | - |
| **startup-dashboard** | workflow | `/startup` | Plain-text `/startup` dashboard: git state, tracking claims, live sessions, recent activity (via session-history /recall) | session-history |
| **statusline** | workflow | - | Compact statusline: model + effort, clone identity, dir + branch, context %, session cost, rate-limit bars | - |
| **subagent-patterns** | workflow | - | Subagent dispatch: task decomposition, spec-driven delegation, two-stage review, parallel coordination, concurrency/rate-limit throttling | - |
| **supabase** | tech-specific | - | API key terminology, env var naming, migration validation, database workflow | - |
| **systematic-debugging** | patterns | - | 4-phase root cause investigation: investigate, analyze, test hypotheses, implement fix | - |
| **tailwind** | tech-specific | - | Tailwind CSS v4 design system: CSS-first config, design tokens, CVA variants, dark mode, responsive grids | - |
| **test-driven-development** | patterns | - | Strict red-green-refactor TDD discipline. No production code without a failing test first | - |
| **test-vision** | workflow | `/e2e`, `/test-vision` | Vision-driven e2e test suite generation. /test-vision for full repo analysis + parallel test suite creation. /e2e for single-feature spec generation | browser-automation, multi-agent |
| **todos** | workflow | `/todo-create`, `/todo-resolve`, `/todo-triage` | File-based review-finding tracker. Review findings, PR nitpicks, and tech debt tracked with structured YAML | skill-authoring, subagent-patterns |
| **verification** | patterns | - | Evidence-before-claims: fresh execution of verification commands, read full output before asserting done | - |
| **writing-system** | patterns | `/rewrite` | Orwell's six rules as the global prose standard for docs, PR text, commits, and reports, plus /rewrite (violations list, then rewrite; mode:landing swap test) | - |
| **xplan** | workflow | `/etp`, `/xplan`, `/xplan-resume`, `/xplan-status`, `/xplana` | Interactive planning framework: discovery interview, deep research, tech stack sign-off, constructive peer review + a 3-pass sequential adversarial review that enforces four plan-execution tenets (minimal/edge-bucketed human work, follow-up completion, autonomous decision context, comprehensive autonomous E2E test suite), parallel agent execution. Requires [/deepresearch](#companion-module-deepresearch) | multi-agent, adversarial-review |
| **youtube-transcripts** | commands | `/transcript` | Extracts a YouTube transcript via yt-dlp AND dispatches a subagent to write an opinionated implications doc against your project memory. One slug+date, two saved files | - |

*\* `/research` works out of the box with no setup. For higher-quality results, install [/deepresearch](#companion-module-deepresearch) - the same fan-out backed by Exa semantic search with full page contents. Needs a free Exa API key.*

### Companion module: /deepresearch

`/deepresearch` is the bundled `deepresearch` module: multi-query semantic research over the Exa MCP server. Claude generates diverse queries from your topic, fans them out as parallel Exa tool calls, and synthesizes a structured `research.md` from the full page contents Exa returns. `/xplan` delegates its research phase to it.

**Setup:** an Exa account (free tier: 1000 searches/mo at [exa.ai](https://exa.ai)), `EXA_API_KEY` in your shell, and the Exa MCP server registered once:

```bash
claude mcp add --scope user --env EXA_API_KEY="$EXA_API_KEY" -- exa npx -y exa-mcp-server
```

Then restart Claude Code and verify with `claude mcp get exa`. Full walkthrough: [modules/deepresearch/README.md](modules/deepresearch/README.md).

**History:** this module supersedes the standalone [lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch) repo (Ollama + self-hosted SearXNG, fully local). That pipeline degraded as SearXNG's scraped engines hit CAPTCHAs and rate limits; Exa's neural search returns reliable results without scraping.

## Memory System

CCGM has a durable, cross-session memory: a store that learns from your work and surfaces what it knows at the start of each new session. It comes in two halves that share one store:

| Half | Module | What it does | Cost |
|------|--------|--------------|------|
| **Read path** | `self-improving` | Stores learnings and injects the project's top-ranked ones into each fresh session, ranked by confidence with time-decay and staleness. | Local, free, no network |
| **Write path** | `dreaming` | A nightly analyzer mines your session transcripts into evidence-tagged *proposals* for new learnings, behind a human gate. | Opt-in; spends Anthropic API tokens |

The read path is the valuable, always-safe half and works on its own — you never need the write path to benefit from memory. A learning is captured (via `/reflect` or the CLI), stored as an append-only op-event, injected at the *next* fresh session start, and reinforced when it pays off again (`verify`). Dreaming's proposals are human-reviewed via `/dream-apply` by default; an opt-in `optimistic_integration` mode (default off) can auto-integrate instead, behind a 24h dwell window, per-slug blast caps, and a self-healing circuit breaker, with post-hoc review and rollback via `/dream-review`.

Activate it with the idempotent setup script, which enables session-start injection, initializes the learnings git store, and (if `dreaming` is installed) offers to configure the nightly analyzer and, separately, optimistic auto-integration:

```bash
bash ~/.claude/bin/memory-setup.sh
```

**→ See [docs/memory-system.md](docs/memory-system.md) for the comprehensive technical reference** — the op-event data model, the projection and confidence-decay math, the integrity/quarantine layers, cross-machine git sync, the full dreaming pipeline, and the safety gates. A visual overview lives in [docs/memory-system.html](docs/memory-system.html).

## Customization

| What | How |
|------|-----|
| Personal rules | Create `~/.claude/rules/personal.md` - CCGM won't overwrite it |
| Settings overrides | Use `~/.claude/settings.local.json` (native Claude Code feature) |
| MCP servers | Add via `claude mcp add --scope user ...` (writes to `~/.claude.json`, not managed by CCGM) |

### Template variables

Config files use placeholders that are expanded during installation:

| Variable | Description | Used By |
|----------|-------------|---------|
| `__CODE_DIR__` | Code workspace directory | settings |
| `__DEFAULT_MODE__` | Permission mode (ask/dontAsk) | settings |
| `__HOME__` | Home directory path | settings |
| `__TIMEZONE__` | Your timezone | - |
| `__USERNAME__` | GitHub username | hooks |

## Manual Installation

Every module has its own README with copy-paste instructions. Browse `modules/` and copy what you want:

```bash
# Example: install the autonomy module
mkdir -p ~/.claude/rules
cp modules/autonomy/rules/autonomy.md ~/.claude/rules/

# Example: install core commands
mkdir -p ~/.claude/commands
cp modules/commands-core/commands/*.md ~/.claude/commands/
```

## Utilities

### statusline.sh - Claude Code Session Monitor

Display live session metrics at the bottom of your Claude Code terminal. Shows model, directory, git branch, context usage, and rate limits with reset countdowns.

**Usage:**

```bash
# Copy to your Claude Code config
cp lib/statusline.sh ~/.claude/statusline-command.sh
chmod +x ~/.claude/statusline-command.sh
```

Then configure Claude Code settings:

```bash
/statusline use ~/.claude/statusline-command.sh
```

Or manually add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline-command.sh"
  }
}
```

**Display Example:**

```
🧠 O-4.8 | code main | ctx:8% | 5h:62% ███░░ 2h26m | 7d:79% ████░ 3d8h
```

**Features:**
- Model with tier emoji (🧠 Opus, 🐢 Sonnet, ⚠️ Haiku) and abbreviation (O-4.8, S-4.6, H-4.5, etc.)
- Current directory and git branch
- Context window usage (0-100%)
- 5-hour rate limit with bar and reset countdown
- 7-day rate limit with bar and reset countdown
- Color-coded by usage: green <60%, yellow <85%, red 85%+

## Documentation

The `docs/` directory contains comprehensive documentation:

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation walkthrough, first session, prerequisites |
| [Install via Agent](docs/install-via-agent.md) | Per-preset paste-blocks and how to dry-run them safely |
| [Module Catalog](docs/modules.md) | Detailed reference for all 78 modules |
| [Commands Reference](docs/commands.md) | All 89 slash commands with usage examples |
| [Hooks Reference](docs/hooks.md) | All 31 hooks explained - what they do and when they fire |
| [Presets](docs/presets.md) | Preset breakdowns and recommendations |
| [Installer](docs/installer.md) | How the installer works, updating, uninstalling |
| [Configuration](docs/configuration.md) | Customization, template variables, settings overrides |
| [Multi-Agent System](docs/multi-agent.md) | Parallel agent coordination, port allocation, issue tracking |
| [Session Memory](docs/session-memory.md) | Native JSONL transcripts, `/recall`, `CLAUDE.md`/`MEMORY.md`, retired agent-log-repo |
| [Memory System](docs/memory-system.md) | Durable cross-session memory: read path (learnings store + injection) and opt-in `dreaming` write path, activation, safety posture, troubleshooting |
| [Project Story](docs/project-story.md) | Living knowledge base: development history, major systems, engineering decisions, incidents and lessons, iteration case studies |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on creating modules, the module.json schema, and how to submit changes.

## License

[MIT](LICENSE)
