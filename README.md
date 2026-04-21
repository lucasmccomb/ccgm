# CCGM (Claude Code God Mode)

<img width="369" height="135" alt="image" src="https://github.com/user-attachments/assets/29953ee7-3e7c-47cc-9ef7-e8b2e8ccbc89" />

Modular configuration system for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - pick the modules you want, install in seconds. Works with Claude Code CLI, VS Code, Cursor, the macOS Claude app, and any other editor with Claude Code support.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Table of Contents

- [What is CCGM?](#what-is-ccgm)
- [Requirements](#requirements)
- [Install](#install)
- [Module Catalog](#module-catalog)
  - [Companion module: /deepresearch](#companion-module-deepresearch)
- [Customization](#customization)
- [Manual Installation](#manual-installation)
- [Utilities](#utilities)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## What is CCGM?

CCGM is a curated collection of 56 configuration modules for Claude Code. Instead of hand-crafting rules, hooks, commands, and permissions from scratch, you pick modules and install them with a single command.

Each module is self-contained with its own README, so you can also [copy individual files manually](#manual-installation) without the installer.

### What gets installed

CCGM places files into `~/.claude/` (global) or `.claude/` (project-level):

| Directory | What | How Claude Uses It |
|-----------|------|-------------------|
| `rules/*.md` | Behavior rules | Loaded automatically at session start |
| `commands/*.md` | Slash commands | Available as `/commit`, `/pr`, etc. |
| `agents/*.md` | Subagent prompts | Reusable prompts invoked by commands and skills via the Task tool |
| `hooks/*.py` | Workflow hooks | Triggered on Claude Code events |
| `settings.json` | Permissions | Controls tool access and auto-approval |

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- macOS or Linux
- bash 4+ or zsh
- git

The installer checks for Claude Code, additional tools (jq, Python 3, gh CLI), and offers to install any that are missing.

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
| `CCGM_NON_INTERACTIVE` | Set to `1` to skip all prompts | - |
| `CCGM_USERNAME` | GitHub username | auto-detected via `gh` |
| `CCGM_CODE_DIR` | Code workspace directory | `~/code` |
| `CCGM_TIMEZONE` | Timezone | auto-detected |

Restart Claude Code or start a new session after installation.

### Presets

For a quick install with a preset:

```bash
./start.sh --preset standard
```

| Preset | Modules | Best For |
|--------|---------|----------|
| **minimal** | global-claude-md, autonomy, git-workflow | Getting started |
| **standard** | global-claude-md, autonomy, identity, git-workflow, hooks, settings, commands-core, commands-utility | Most users |
| **full** | All 41 stable modules | Power users |
| **team** | global-claude-md, autonomy, git-workflow, hooks, settings, commands-core, github-protocols, code-quality, systematic-debugging, verification | Teams |

### Other install options

```bash
./start.sh --scope project    # Install to .claude/ in current project instead of ~/.claude/
./start.sh --link             # Symlink instead of copy (for CCGM developers)
```

### Update / Uninstall

```bash
./update.sh      # Pull latest changes and re-apply
./uninstall.sh   # Remove only CCGM-installed files
```

## Module Catalog

| Module | Category | Description | Dependencies |
|--------|----------|-------------|--------------|
| **global-claude-md** | core | Slim global CLAUDE.md - the root config reference that points to rules, commands, hooks, and settings | - |
| **autonomy** | core | Claude as a fully autonomous engineer - executes tasks end-to-end without unnecessary questions | - |
| **identity** | core | Two foundational context files: soul.md (AI personality and philosophy) and human-context.md (who you are, your goals, how you work) | - |
| **git-workflow** | core | Git rules: sync before history changes, rebase by default, post-merge cleanup, no AI attribution | - |
| **settings** | core | Base settings.json with 800+ tool permissions, deny list, plugin config. Defaults to safe 'ask' mode | - |
| **hooks** | core | Python hooks: issue-first workflow, commit format, branch protection, auto-approval for safe ops | settings |
| **commands-core** | commands | /commit, /pr, /cpm (commit-PR-merge), /gs (git status), /ghi (create issue) | - |
| **commands-extra** | commands | /audit (codebase audit), /pwv (Playwright verify), /walkthrough, /promote-rule | - |
| **commands-utility** | commands | /cws-submit (Chrome Web Store walkthrough), /ccgm-sync (sync config to CCGM + lem-deepresearch), /user-test (browser user testing) | - |
| **ce-review** | commands | /ce-review unified code-review orchestrator. Composes scope-drift, learnings-researcher, tier-sharpener, and review-synthesizer with structured JSON findings | - |
| **onboarding** | commands | /onboarding - analyzes a repository and generates a structured ONBOARDING.md for new contributors | - |
| **pr-review-toolkit** | commands | Augments the external pr-review-toolkit plugin with scope-drift detection on top of the standard code/test/comment/silent-failure/type passes | - |
| **ship-readiness** | commands | /ship-ready - at-a-glance merge-gate dashboard for the current branch: checks, conflicts, diff size, reviewer state | - |
| **documentation** | commands | /docupdate (comprehensive documentation audit: README, TOC, onboarding, packages, module coverage) | - |
| **copycat** | commands | /copycat (analyze external Claude Code config repos for CCGM improvements) | - |
| **debugging** | commands | /debug (structured root-cause debugging with Opus) | - |
| **brand-naming** | commands | /brand (full naming pipeline with word exploration, domain/trademark/app store checks) and /brand-check (single-name deep verification) | - |
| **editorial-critique** | commands | /editorial-critique - 8-pass editorial review of long-form writing: prose craft, AI-tell detection, argument, conciseness, accuracy, structure, impact, grammar. Scored report with auto-fix | - |
| **design-review** | commands | /design-review - 6-pass visual design review: spacing, typography, responsive, hierarchy, accessibility, consistency. Screenshots + CSS analysis with auto-fix | - |
| **ideate** | commands | /ideate - structured ideation framework: Socratic interview to refine ideas to 95% clarity, then hand off to /deepresearch or /xplan | - |
| **brainstorm** | commands | /brainstorm - design-before-implementation gate: forbids code until a design spec with 2-3 approach tradeoffs is written and user-approved, then hands off to /xplan | - |
| **research** | commands | /research - multi-channel research using parallel agents with WebSearch, WebFetch, GitHub, Reddit. Zero dependencies.* | - |
| **github-protocols** | workflow | Issue-first workflow, PR conventions, label taxonomy, code review standards | - |
| **startup-dashboard** | workflow | Plain-text `/startup` dashboard: git state, tracking claims, live sessions, recent activity (via session-history /recall) | session-history |
| **session-history** | workflow | `/recall` for unified session transcript history across all clones of a repo; session-historian agent for deeper retrieval | - |
| **multi-agent** | workflow | Multi-clone parallel agent work with issue claiming, port allocation, /mawf workflow | startup-dashboard |
| **atdd** | workflow | Agentic Test-Driven Development. /atdd reads Playwright vision specs, iteratively builds app code until all tests pass, then ships | - |
| **test-vision** | workflow | Vision-driven e2e test suite generation. /test-vision for full repo analysis + parallel test suite creation. /e2e for single-feature spec generation | browser-automation, multi-agent |
| **xplan** | workflow | Interactive planning framework: discovery interview, deep research, tech stack sign-off, peer review, parallel agent execution. Requires [/deepresearch](#companion-module-deepresearch) | multi-agent |
| **remote-server** | workflow | SSH access to a configured remote server with /onremote command for health checks and remote task execution | - |
| **agent-manager** | workflow | [BETA] Go-based terminal UI (/agents) for monitoring and controlling Claude Code agent processes across multi-clone repos via tmux | multi-agent |
| **cloud-dispatch** | workflow | Delegate GitHub issues to autonomous Claude Code agents on Hetzner Cloud VMs. Includes /dispatch, /dispatch-status, /dispatch-stop, /vm-manage commands | - |
| **self-improving** | workflow | Meta-learning system: /reflect and /consolidate commands, PostToolUse hook (PR merge/issue close reminders), PreCompact hook (pre-compaction capture), prescriptive reflection triggers | - |
| **subagent-patterns** | workflow | Subagent dispatch: task decomposition, spec-driven delegation, two-stage review, parallel coordination | - |
| **commands-preamble** | workflow | [EXPERIMENTAL] UserPromptSubmit hook that injects a compact preamble of iron-law principles into every prompt | - |
| **compound-knowledge** | workflow | Team-shared learnings in `docs/solutions/`. After solving a non-trivial problem, capture the pattern in a versioned schema | - |
| **document-review** | workflow | Seven-lens plan-quality gate. /document-review fans out to 7 role-specific reviewers (coherence, feasibility, product, scope, design, security, adversarial) with structured JSON findings | skill-authoring, subagent-patterns |
| **git-worktrees** | workflow | Solo-agent worktree-based isolation for feature work. Lighter alternative to multi-clone | - |
| **pr-feedback** | workflow | /resolve-pr-feedback - fetches unresolved PR review threads via GraphQL, clusters 3+ items by category, dispatches parallel resolver agents | skill-authoring, subagent-patterns |
| **todos** | workflow | File-based review-finding tracker. Review findings, PR nitpicks, and tech debt tracked with structured YAML | - |
| **code-quality** | patterns | Code standards, testing requirements, error handling, security, build verification | - |
| **browser-automation** | patterns | Browser tool selection (Chrome, Playwright, WebMCP), verification priority, UI testing workflow | - |
| **common-mistakes** | patterns | 8 battle-tested anti-patterns: shallow exploration, dependency blindness, ESLint Fast Refresh, more | - |
| **frontend-design** | patterns | Distinctive web UI: intentional aesthetics, typography, color systems, spatial composition | - |
| **systematic-debugging** | patterns | 4-phase root cause investigation: investigate, analyze, test hypotheses, implement fix | - |
| **test-driven-development** | patterns | Strict red-green-refactor TDD discipline. No production code without a failing test first | - |
| **verification** | patterns | Evidence-before-claims: fresh execution of verification commands, read full output before asserting done | - |
| **agent-native** | patterns | Principles and audit skill for building applications where an agent is a first-class client | - |
| **make-interfaces-feel-better** | patterns | Design-engineering details that compound into polished interfaces. Model-invoked skill covering typography, surfaces, animations, performance | - |
| **rule-authoring** | patterns | Discipline for writing rules that hold up under pressure. Treats rule authoring as a first-class skill with iron-law structure | - |
| **skill-authoring** | patterns | Discipline for writing skills and slash commands that stay efficient, portable, and structured across models | - |
| **cloudflare** | tech-specific | Pages vs Workers selection, deployment methods, Git integration requirements | - |
| **supabase** | tech-specific | API key terminology, env var naming, migration validation, database workflow | - |
| **mcp-development** | tech-specific | Building MCP servers: project structure, tool design, error handling, testing, evaluation patterns | - |
| **shadcn** | tech-specific | shadcn/ui patterns: composition, semantic theming tokens, form architecture, accessibility | - |
| **tailwind** | tech-specific | Tailwind CSS v4 design system: CSS-first config, design tokens, CVA variants, dark mode, responsive grids | - |

*\* `/research` works out of the box with no setup. For higher-quality results, install [/deepresearch](#companion-module-deepresearch) - a local pipeline that's faster, cheaper, and more reliable, but requires additional infrastructure.*

### Companion module: /deepresearch

The `/deepresearch` command is a more powerful research pipeline that lives in its own repo: **[lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch)**. It replaces `/research`'s parallel subagent approach with a local-first pipeline that produces higher-quality, source-backed research documents.

**How it works:** Ollama (qwen2.5:72b) generates search queries and extracts facts, SearXNG (self-hosted Docker) runs parallel web searches across Google/Bing/DuckDuckGo, and Claude Code synthesizes everything into a structured research.md. The pipeline is fully local - no external API keys required beyond what Claude Code already uses.

**Why it's separate:** It requires local infrastructure (Docker, Ollama with a ~40GB model, a Python venv) that not every CCGM user will want. But if you use `/xplan`, you'll want this - xplan delegates its research phase to `/deepresearch`.

**Install:**

```bash
git clone https://github.com/lucasmccomb/lem-deepresearch.git
cd lem-deepresearch
./install.sh
```

The installer sets up SearXNG, Ollama, the Python environment, and copies the command files into `~/.claude/`. See the [lem-deepresearch README](https://github.com/lucasmccomb/lem-deepresearch) for manual setup and troubleshooting.

## Customization

| What | How |
|------|-----|
| Personal rules | Create `~/.claude/rules/personal.md` - CCGM won't overwrite it |
| Settings overrides | Use `~/.claude/settings.local.json` (native Claude Code feature) |
| MCP servers | Configure in `~/.claude/mcp.json` (not managed by CCGM) |

### Template variables

Config files use placeholders that are expanded during installation:

| Variable | Description | Used By |
|----------|-------------|---------|
| `__HOME__` | Home directory path | settings |
| `__USERNAME__` | GitHub username | hooks |
| `__CODE_DIR__` | Code workspace directory | settings |
| `__TIMEZONE__` | Your timezone | - |
| `__DEFAULT_MODE__` | Permission mode (ask/dontAsk) | settings |

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
🧠 O-4.6 | code main | ctx:8% | 5h:62% ███░░ 2h26m | 7d:79% ████░ 3d8h
```

**Features:**
- Model with tier emoji (🧠 Opus, 🐢 Sonnet, ⚠️ Haiku) and abbreviation (O-4.6, S-4.6, H-4.5, etc.)
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
| [Module Catalog](docs/modules.md) | Detailed reference for all 56 modules |
| [Commands Reference](docs/commands.md) | All 36 slash commands with usage examples |
| [Hooks Reference](docs/hooks.md) | All 13 hooks explained - what they do and when they fire |
| [Presets](docs/presets.md) | Preset breakdowns and recommendations |
| [Installer](docs/installer.md) | How the installer works, updating, uninstalling |
| [Configuration](docs/configuration.md) | Customization, template variables, settings overrides |
| [Multi-Agent System](docs/multi-agent.md) | Parallel agent coordination, port allocation, issue tracking |
| [Session Memory](docs/session-memory.md) | Native JSONL transcripts, `/recall`, `CLAUDE.md`/`MEMORY.md`, retired agent-log-repo |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on creating modules, the module.json schema, and how to submit changes.

## License

[MIT](LICENSE)
