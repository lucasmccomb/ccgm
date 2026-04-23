# Commands Reference

CCGM installs slash commands as `.md` files in `~/.claude/commands/`. Each file contains a description, the list of tools the command may use, and detailed instructions that Claude follows when the command is invoked.

Commands are invoked by typing `/command-name` in a Claude Code session.

## Core commands

Installed by the **commands-core** module.

---

### /commit

**Stage all changes and commit with conventional format.**

Stages all modified and untracked files, runs the project's verification suite (lint, type-check, tests, build), and creates a commit with a formatted message.

**Commit message format**: `#{issue_number}: {description}`

The issue number is extracted from the branch name. If the branch is `42-add-login-form`, the commit message will start with `#42:`.

**What happens**:
1. Stages all changes (`git add`)
2. Runs the project's full verification suite
3. If verification passes, creates the commit
4. If verification fails, fixes the issues and retries

**Usage**:
```
/commit
```

---

### /pr

**Push branch and create a pull request.**

Runs verification, rebases on the base branch, pushes, and creates a PR with proper formatting.

**What happens**:
1. Runs the project's full verification suite
2. Rebases on `origin/main` (or the project's base branch)
3. Pushes the branch with `--force-with-lease` if needed
4. Checks for PR templates (repo root, `.github/`, org `.github` repo)
5. Creates a PR using the template format, with `Closes #{issue}` in the body
6. Reports the PR URL

**Usage**:
```
/pr
```

---

### /cpm

**One-shot: commit, create PR, and merge.**

The complete workflow in a single command. Commits changes, creates a PR, and squash-merges it.

**What happens**:
1. Stages all changes
2. Runs full verification suite
3. Creates a commit with conventional format
4. Rebases on `origin/main`
5. Pushes the branch
6. Creates a PR (using template if available)
7. Squash-merges the PR
8. Closes the associated issue
9. Returns to main branch and pulls
10. Reports the final state

**Usage**:
```
/cpm
```

---

### /gs

**Git status dashboard.**

Displays a formatted overview of the current repository state.

**What it shows**:
- Current branch and remote tracking status
- Ahead/behind counts relative to main
- Working directory state (modified, staged, untracked files)
- Open pull requests
- Recommended next action based on the current state

**Usage**:
```
/gs
```

---

### /ghi

**Create a GitHub issue with labels.**

Interactively creates a GitHub issue with appropriate type labels.

**What happens**:
1. Asks for the issue type (feature, bug, refactor, chore, documentation, human-agent)
2. Asks for the title and description
3. Creates missing labels if they don't exist on the repo
4. Structures the issue body based on type (features get acceptance criteria, bugs get reproduction steps)
5. Creates the issue and returns the URL

**Usage**:
```
/ghi
```

---

## Extra commands

Installed by the **commands-extra** module.

---

### /audit

**Multi-phase codebase audit.**

Runs a comprehensive audit across 8 categories using parallel specialized agents, then optionally applies auto-fixes and creates GitHub issues for manual findings.

**Audit categories**:
1. Security (injection, auth, secrets, dependencies)
2. Dependencies (outdated, unused, duplicated, license issues)
3. Code quality (complexity, duplication, naming, dead code)
4. Architecture (coupling, layering, circular dependencies)
5. TypeScript/React (type safety, component patterns, hooks usage)
6. Testing (coverage gaps, test quality, missing edge cases)
7. Documentation (outdated docs, missing API docs)
8. Performance (bundle size, render performance, memory leaks)

**Severity levels**: Critical, High, Medium, Low

**Usage**:
```
/audit                         # Full audit, all categories
/audit security                # Single category
/audit security,testing        # Multiple categories
/audit --fix                   # Auto-fix applicable findings
/audit --no-issues             # Skip GitHub issue creation
```

---

### /pwv

**Playwright visual verification.**

Launches a headless browser to verify that a page renders correctly, checking for console errors and network failures.

**What happens**:
1. Ensures a dev server is running (starts one if needed)
2. Navigates to the specified URL
3. Takes screenshots (desktop and optionally mobile viewports)
4. Checks the browser console for JavaScript errors
5. Checks network requests for failed API calls
6. Reports findings with screenshots

**Usage**:
```
/pwv                           # Verify localhost default page
/pwv https://localhost:5173    # Specific URL
/pwv /dashboard                # Specific route
/pwv /dashboard --mobile       # Include mobile viewport
/pwv --dark                    # Test dark mode
```

---

### /walkthrough

**Step-by-step guided mode.**

Breaks a complex task into discrete steps and presents them one at a time, waiting for user confirmation before proceeding.

**Behavior**:
- Shows progress as "Step N/Total"
- Presents one step at a time with clear instructions
- Waits for user to confirm completion, ask questions, or provide information
- Never skips ahead or presents multiple steps
- Incorporates user-provided information (API keys, URLs, etc.) into subsequent steps

**Trigger words**: "walk me through", "guide me through", "step me through", or `/walkthrough`

**Usage**:
```
/walkthrough
walk me through deploying to Cloudflare
```

---

### /promote-rule

**Review and promote repo rules to global.**

Scans the current repo's CLAUDE.md for rules that could be promoted to the global `~/.claude/CLAUDE.md`.

**What happens**:
1. Reads the repo's CLAUDE.md
2. Looks for `<!-- CANDIDATE:GLOBAL -->` markers
3. Identifies implicit candidates (rules that aren't project-specific)
4. Checks the global CLAUDE.md for duplicates
5. Presents candidates for approval
6. Applies approved promotions

**Usage**:
```
/promote-rule              # Interactive review
/promote-rule --all        # Show all candidates without filtering
/promote-rule --dry-run    # Preview without making changes
```

---

### /checkpoint

**Save or resume a structured WIP checkpoint.**

Captures a compact "pick up here next time" snapshot (current task, decisions, remaining work) stored as YAML-fronted markdown under `~/.claude/checkpoints/{repo}/`. Different from the session log: session logs are chronological narrative, checkpoints are handoff state between sessions or between clones in a workspace.

**Usage**:
```
/checkpoint save [title]     # Write a checkpoint now
/checkpoint resume           # Load the most recent checkpoint for this repo
/checkpoint resume [query]   # Load by title substring or YYYYMMDD date
/checkpoint list             # Show checkpoints for this repo, newest first
```

---

### /freeze

**Scope-lock Edit/Write to a directory.**

Activates the `check-freeze.py` PreToolUse hook by writing a path to `~/.claude/freeze-dir.txt`. While a freeze is active, Edit and Write calls outside that directory are denied. Bash is not scope-locked - pair with `/guard` for destructive-command warnings.

**Usage**:
```
/freeze                      # Freeze to the current working directory
/freeze <path>               # Freeze to an absolute or relative path
```

---

### /unfreeze

**Clear the active freeze scope.**

Deletes `~/.claude/freeze-dir.txt`, restoring unrestricted Edit and Write. The hook itself stays installed - it is a no-op when no freeze is set.

**Usage**:
```
/unfreeze
```

---

### /guard

**Compose careful + freeze for focused, safe sessions.**

Combines the two safety hooks shipped by the `hooks` module: `check-careful.py` (prompts on destructive Bash commands) and `check-freeze.py` (denies writes outside the frozen directory). Activates both for a named scope. Use during investigation or refactors where you want to stay inside one module and avoid destructive surprises.

**Usage**:
```
/guard                       # Guard the current working directory
/guard <path>                # Guard an absolute or relative path
```

---

## Utility commands

Installed by the **commands-utility** module.

---

### /cws-submit

**Guided Chrome Web Store submission walkthrough.**

Walks through the process of packaging and submitting a Chrome extension to the Chrome Web Store step by step.

**What happens**:
1. Checks extension manifest and required assets
2. Guides through packaging the extension zip
3. Walks through the Chrome Web Store Developer Dashboard submission form
4. Covers privacy policy, screenshots, and store listing requirements
5. Handles common submission errors

**Usage**:
```
/cws-submit
```

---

### /ccgm-sync

**Sync local Claude Code config changes back to the CCGM repo and lem-deepresearch repo.**

When you've customized files in `~/.claude/` directly, this command syncs those changes back to your local CCGM clone and lem-deepresearch repo, keeping them as the source of truth.

**What happens**:
1. Identifies which CCGM-managed files have been modified locally
2. Diffs the changes
3. Copies modified files back into the appropriate `modules/` subdirectories
4. Checks if deepresearch command or CLI script have changed and syncs to lem-deepresearch repo
5. Prompts to commit the changes

**Usage**:
```
/ccgm-sync
```

---

### /user-test

**Browser-based user testing simulation.**

Simulates a user testing session using Chrome automation tools to test a web application as a real user would.

**What happens**:
1. Opens the specified URL in Chrome
2. Performs a scripted or exploratory user journey
3. Checks for console errors and network failures
4. Takes screenshots at key steps
5. Reports usability issues and errors found

**Usage**:
```
/user-test
/user-test https://localhost:5173
/user-test "test the checkout flow"
```

---

## Documentation commands

Installed by the **documentation** module.

---

### /docupdate

**Comprehensive documentation audit and update.**

Spawns parallel audit agents to find every gap between your documentation and actual codebase state, then applies targeted fixes.

**What it audits**:
- README accuracy (packages, features, commands, setup steps, versions)
- Table of contents vs actual headings in every doc file
- Onboarding/setup flow vs actual prerequisites, env vars, and scripts
- Package/dependency lists vs what is actually installed
- Module and feature coverage vs what exists in source

**Usage**:
```
/docupdate                    # Full audit and fix
/docupdate --scope toc        # TOC only
/docupdate --scope readme     # README only
/docupdate --dry-run          # Report gaps without making changes
```

**Works in**: Any project type (npm, Cargo, Python, Ruby, Go, monorepo).

Installed by the **documentation** module.

---

## Research commands

Installed by the **research** module.

---

### /research

**Multi-channel research using parallel agents.**

Spawns up to 7 parallel research agents that each investigate a topic from a different angle (domain, technical, competitive, adjacent, UX, infrastructure, monetization). Decomposes the topic into targeted sub-questions, runs iterative multi-round searches, and synthesizes everything into a structured research.md.

**Depth presets**: Full (all 7 agents), Technical Only, Market & Product, Lite, Custom

**Key features**:
- Query decomposition into targeted sub-questions before spawning agents
- Multi-round iterative research (broad, focused, validation)
- Cross-session continuity via `--extend` flag
- Verification pass for high-stakes claims (Full depth)
- Sub-agents run on Sonnet; orchestrator runs on current model

**Usage**:
```
/research "dark mode browser extensions"
/research "food commerce platform" --depth market
/research "habit tracking apps" --output ~/docs/research/
/research "my topic" --extend ~/docs/research/prior/research.md
```

For higher-quality results, install [/deepresearch](https://github.com/lucasmccomb/lem-deepresearch) - a local pipeline that's faster, cheaper, and more reliable.

**Installed by**: research module

---

## Debugging commands

Installed by the **debugging** module. For `/deepresearch`, see [lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch) (standalone repo, installed separately).

---

### /debug

**Structured root-cause debugging with Opus.**

Enforces a disciplined debugging workflow instead of ad-hoc guessing. Runs on Opus for deep root-cause analysis.

**Debugging phases**:
1. **Reproduce**: Confirm the bug can be reliably reproduced
2. **Hypothesize**: Form ranked theories about the root cause
3. **Instrument**: Add logging or breakpoints to test hypotheses
4. **Diagnose**: Identify the exact root cause with evidence
5. **Fix**: Implement the minimal fix for the root cause (not symptoms)
6. **Verify**: Confirm the fix and check for regressions

This command is also invoked automatically by the `systematic-debugging` module's routing rule when you ask Claude to fix a bug or debug an error.

**Usage**:
```
/debug TypeError: Cannot read property 'userId' of undefined in AuthContext.tsx line 42
/debug "the login form submits but users don't get redirected"
/debug  # Will ask for the problem description interactively
```

---

## Brand commands

Installed by the **brand-naming** module.

---

### /brand

**Full naming pipeline.**

Comprehensive brand name research using parallel word exploration, name generation, and multi-source verification.

**Phases**:
1. **Input**: Gather naming preferences (industry, vibe, constraints)
2. **Word exploration**: 4 parallel research agents query Datamuse, ConceptNet, Big Huge Thesaurus, and philosophical/etymological sources
3. **Name generation**: Generate 150-250 candidates across 6 categories (single words, compounds, vowel-dropped, invented/neo-Latin, philosophical/classical, word+TLD combos)
4. **Domain checks**: Verify domain availability via Instant Domain Search MCP or DNS/whois fallback
5. **Trademark screening**: USPTO and WIPO trademark pre-search
6. **App store and social checks**: Apple App Store, Google Play, GitHub, Twitter/X, Instagram, and more
7. **Scoring**: Rate candidates across 8 criteria and produce a final ranked report

**Usage**:
```
/brand
/brand "AI productivity tool for developers"
```

---

### /brand-check

**Deep verification of a single brand name.**

Performs thorough availability checking for one or more specific names.

**Checks performed**:
- Domain availability across all specified TLDs (default: .ai, .io, .com, .life, .work, .app, .co, .dev, .org, .net)
- USPTO and WIPO trademark search
- Apple App Store and Google Play search
- Social handle availability (GitHub, Twitter/X, Instagram, Reddit, YouTube, TikTok, LinkedIn, ProductHunt)
- Existing business/product search

**Usage**:
```
/brand-check acmecorp
/brand-check "acme corp" "acme labs" "acme ai"    # Compare multiple names
```

---

## Copycat commands

Installed by the **copycat** module.

---

### /copycat

**Analyze external Claude Code config repos for CCGM improvements.**

Clones or reads an external Claude Code configuration repo and identifies patterns, rules, commands, and techniques worth incorporating into CCGM.

**Phases**:
1. **Acquire**: Clone from GitHub URL or read from local path
2. **Discover**: Map all config files (CLAUDE.md, rules, commands, hooks, settings, MCP)
3. **Analyze**: 4 parallel agents examine rules, commands, hooks/settings, and architecture patterns
4. **Rank**: Score findings by impact (1-5) and effort (1-5), sort into priority groups
5. **Walkthrough**: Present findings interactively, group by group (High Priority, Quick Wins, Worth Considering)
6. **Implement**: Create GitHub issues for approved findings

**Usage**:
```
/copycat owner/repo
/copycat https://github.com/someone/claude-config
/copycat ~/code/some-local-repo
```

---

## ATDD commands

Installed by the **atdd** module.

---

### /atdd

**Build app code to pass E2E vision specs.**

Reads Playwright vision specs from `e2e/tests/{feature}/`, iteratively builds app code until all tests pass, then ships.

**Phases**:
1. **Orient** - Read all spec files, establish baseline (X/Y tests passing), create issue and branch
2. **Red-Green Loop** - Systematically work through failing tests: read test, implement minimum code, re-run, commit incrementally
3. **Verify** - Run lint, type-check, unit tests
4. **Ship** - Push and create PR with baseline/final results

**The ATDD contract**: specs are immutable (never modify test files), mocks define the API contract, UI assertions define the design spec.

**Usage**:
```
/atdd habits
/atdd habits --issue 178
/atdd coaching --issue 180
/atdd "principles journal" --issue 181
```

**Installed by**: atdd module

---

## Test Vision commands

Installed by the **test-vision** module.

---

### /test-vision

**Comprehensive e2e test suite generation.**

Discovers all features in a codebase, interviews the user to validate test cases, generates Playwright infrastructure, dispatches parallel `/e2e` agents, and produces a complete test suite with CI/CD integration.

**Phases**:
1. **Phase 0** - Codebase discovery (7-source checklist: routes, nav, README, API, tests, stores, forms)
2. **Phase 1** - Chrome MCP visual discovery (explore running app, identify interactive elements)
3. **Phase 2** - User interview (validate feature domains, prioritize, confirm auth setup, review delegation)
4. **Phase 3** - Infrastructure generation (playwright.config.ts, fixtures.ts, auth.setup.ts)
5. **Phase 4** - Parallel /e2e dispatch (one agent per feature domain, pre-assigned file paths)
6. **Phase 5** - Integration and validation (test discovery, import paths, duplicates, smoke check)
7. **Phase 6** - CI/CD workflow generation (GitHub Actions)
8. **Phase 7** - Summary report

**Flags**:
- `--skip-chrome` - Skip Chrome MCP visual discovery (code-based only)
- `--skip-interview` - Use auto-detected defaults without interview

**Usage**:
```
/test-vision
/test-vision --skip-chrome
/test-vision --skip-interview
```

**Installed by**: test-vision module

---

### /e2e

**Generate a Playwright e2e spec for a single feature.**

Generates a complete Playwright spec file for one feature, flow, or GitHub issue. Works standalone or as the atomic building block within `/test-vision`.

**Modes**:
- **Standalone** - Called directly. Runs its own discovery, Chrome MCP exploration, infrastructure setup, and spec generation.
- **Composed** - Called by `/test-vision`. Receives pre-computed context and skips discovery.

**What it generates**:
- Three-tier assertions: route loads, structural landmarks, behavioral interactions
- Direct locators (getByRole, getByText, getByTestId)
- Graceful credential skipping via auth fixtures
- Auth provider detection (Better Auth, Supabase, Clerk)

**Usage**:
```
/e2e authentication
/e2e #42
/e2e /dashboard/settings
/e2e payments --file e2e/features/payments.spec.ts
```

**Installed by**: test-vision module

---

## Self-improving commands

Installed by the **self-improving** module.

---

### /reflect

**Run the structured reflection checklist inline.**

Walks through the self-improving reflection loop within the current session (not delegated to a subagent, so full session context is preserved).

**What happens**:
1. Recalls what happened in the current session (tasks, debugging, corrections)
2. Reads `git log --oneline -10` to ground in recent commits
3. Walks the reflection checklist: task summary, surprises, reusable patterns, common mistakes, user preferences, tool gotchas
4. Writes patterns to appropriate memory files (feedback, user, project types)
5. Reports what was captured (or "nothing notable to capture")

**Usage**:
```
/reflect
```

**When to use**: After completing a feature, after a debugging session, when prompted by the PostToolUse hook, or before context compaction.

**Installed by**: self-improving module

---

### /consolidate

**Review and maintain memory files.**

Delegates to a Sonnet agent that reads all memory files, identifies duplicates, contradictions, and stale entries, and cleans them up.

**What happens**:
1. Reads MEMORY.md index and all referenced memory files
2. Identifies: duplicates, contradictions, stale entries, too-specific or too-vague entries
3. Updates or removes problematic entries
4. Updates MEMORY.md index if files were added/removed
5. Reports: files reviewed, updated, removed, unchanged

**Usage**:
```
/consolidate
```

**When to use**: Periodically (every few weeks) or when memory files feel cluttered.

**Installed by**: self-improving module

---

### /retro

**Weekly retrospective from git history.**

Synthesizes what shipped in a time window by walking the git log, surfacing hotspots, per-author activity, and patterns worth capturing as learnings. Different from `/reflect` (which introspects one session), `/retro` surveys all commits across the window - including work by sibling-clone agents, co-workers, and past sessions you no longer remember. Global mode aggregates across every repo under the code directory.

**Usage**:
```
/retro                     # Last 7 days, this repo
/retro [N]d                # Last N days (e.g. /retro 14d)
/retro [YYYY-MM-DD]        # From that date through today
/retro global              # Aggregate across ALL repos under the code directory
/retro global [window]     # Global + windowed
```

**Installed by**: self-improving module

---

## Workflow commands

Installed by the **xplan**, **multi-agent**, and **startup-dashboard** modules.

---

### /xplan

**Interactive deep research, planning, and execution framework.**

A human-in-the-loop planning framework that interviews you upfront, researches your concept deeply, proposes tech stack and architecture for your sign-off, creates a parallelized execution plan, reviews it with specialized agents, and executes via parallel agents.

**Phases** (interactive mode):
- **Phase 0** - Parse input, create plan directory
- **Phase 0.5** - Discovery interview: confirm core concept, choose research depth (Full / Technical Only / Market & Product / Lite / Custom)
- **Phase 1** - Deep research via parallel specialized agents
- **Phase 1.5** - Research review: business viability assessment, confirm to proceed
- **Phase 2** - Naming ideation (optional)
- **Phase 2.5** - Tech stack sign-off: propose stack, get approval
- **Phase 2.6** - Scope sign-off: approve epic structure
- **Phase 2.7** - Multi-agent setup review
- **Phase 3** - Plan creation with parallelized epics and dependency waves
- **Phase 4** - Peer review by security, architecture, and business logic agents
- **Phase 5** - Write plan.md
- **Phase 6** - Final confirmation gate before execution
- **Phase 7** - Execute via parallel agents in separate clones
- **Phase 8** - Verification, audit, and retrospective

**Flags**:
- `--repo <path>` - Analyze and plan work for an existing repo
- `--light` - Skip interactive interview phases (Phases 0.5, 1.5, 2.5, 2.6, 2.7); uses minimal clarification + traditional walkthrough instead

**Usage**:
```
/xplan "Build a SaaS dashboard with auth, billing, and analytics"
/xplan "Add dark mode to my app" --repo ~/code/myapp
/xplan "Build a CLI tool" --light
/xplan  # Will ask for project description interactively
```

**Installed by**: xplan module

---

### /xplan-status

**Check progress on a running or completed xplan.**

Reads the plan's `progress.md`, checks live GitHub issue and PR states, inspects clone states, and shows wave completion.

**Usage**:
```
/xplan-status
```

**Installed by**: xplan module

---

### /xplan-resume

**Resume an interrupted xplan execution.**

Reconstructs context from plan files (`progress.md`, `plan.md`, `decisions.md`, `research.md`), verifies live state vs checkpoint, handles in-flight work, and continues execution.

**Usage**:
```
/xplan-resume
```

**Installed by**: xplan module

---

### /mawf

**Multi-Agent Workflow.**

Takes unstructured feedback or a list of tasks, parses them into typed GitHub issues, plans agent allocation by dependency wave, spawns parallel agents, monitors progress, and reports final state.

**What happens**:
1. Parses input into individual work items
2. Creates GitHub issues for each item
3. Plans waves (groups of independent issues that can run in parallel)
4. Spawns agents in separate clones for each wave
5. Monitors progress and handles failures
6. Merges results and syncs clones between waves
7. Reports final state

**Usage**:
```
/mawf "Fix the login bug, add dark mode toggle, update the API docs"
```

**Installed by**: multi-agent module

---

### /workspace-setup

**Create workspace-based multi-agent directory structure.**

Sets up isolated workspace directories with multiple clones for parallel agent work.

**What it creates**:
- N clones of the repo per workspace
- `.env.clone` files with agent identity and port assignments
- GitHub labels for each workspace and clone
- Workspace-level CLAUDE.md for coordinator agents
- Log directory structure

**Usage**:
```
/workspace-setup my-repo
```

**Installed by**: multi-agent module

---

### /handoff

**Write a handoff note for peer clones.**

Writes a short markdown handoff under `~/.claude/handoffs/{repo}/` so sibling clones on this machine can orient quickly on startup. `auto-startup.py` reads these on SessionStart, filters out the current agent's own notes and anything older than 7 days, and injects a compact block into the fresh session. Lightweight alternative between "nothing" and a full `/recall` transcript dive.

**When to use**: After `gh pr merge` on non-trivial work, before ending a session that touched shared code, or when handing off a blocker.

**Usage**:
```
/handoff                           # Prompt yourself to fill in three sections
/handoff {one-line description}    # Pre-seed the title
```

**Installed by**: multi-agent module

---

### /startup

**Session initialization dashboard.**

Runs on demand at the start of a session. Prints a plain-text dashboard with everything you need to orient.

**What it does**:
1. Derives agent identity from directory name
2. Checks git status and syncs with remote
3. Lists open PRs and tracking.csv claims for the current repo
4. Lists live Claude Code sessions on the machine
5. Lists sibling clone branches
6. Surfaces the last 7 days of recent activity across all clones of the repo (via session-history `/recall`)
7. Warns about orphan test processes
8. Checks for Claude Code updates

**Usage**:
```
/startup
```

**Installed by**: startup-dashboard module

---

## Remote server commands

Installed by the **remote-server** module.

---

### /onremote

**Run a task on a remote server by describing it in natural language.**

Delegates to a Haiku agent to minimize token usage. Interprets natural language input, determines the appropriate SSH commands, runs them on the configured remote server, and reports results in plain language.

**Modes**:
- **No arguments** - health check: shows uptime, disk usage, and active processes
- **With arguments** - task mode: interprets intent and runs appropriate SSH commands

**What happens**:
1. Delegates to Haiku agent
2. Interprets the natural language task description
3. Determines SSH commands needed to accomplish it
4. Runs commands via `ssh user@host "..."`
5. Reports what was done and what the result was

**Usage**:
```
/onremote                                       # Health check
/onremote "check if myapp is running"
/onremote "how much disk space is left"
/onremote "show the last 50 lines of the app log"
/onremote "restart the myservice process"
```

**Installed by**: remote-server module

---

## Agent manager commands

Installed by the **agent-manager** module.

---

### /agents

**Launch the Agent Manager TUI.**

Opens a terminal dashboard for monitoring and controlling Claude Code agent processes across multi-clone repos.

**What it shows**:
- All agents running in tmux panes with health status and last activity
- Real-time log streaming per agent
- Controls: launch, stop, restart, force-kill

**Usage**:
```
/agents
```

**Installed by**: agent-manager module

---

## Cloud dispatch commands

Installed by the **cloud-dispatch** module.

---

### /dispatch

**Dispatch GitHub issues to cloud VMs.**

Provisions Hetzner Cloud VMs, injects secrets, sets up agent workspaces, and launches autonomous Claude Code agents to work on specified GitHub issues.

**What happens**:
1. Validates prerequisites (hcloud CLI, gh CLI, Hetzner auth)
2. Creates or health-checks existing VMs
3. Injects GitHub token and SSH keys to all VMs
4. Clones repos and assigns issues to agent slots
5. Launches agents headlessly with configurable turn/time limits
6. Reports dispatch summary and estimated cost (~$0.015/hr per cx22 VM)

**Usage**:
```
/dispatch lucasmccomb/my-repo --issues 42,43,44
/dispatch my-repo --issues 42 --vms 1 --max-turns 100
```

**Installed by**: cloud-dispatch module

---

### /dispatch-status

**Check status of dispatched agents.**

Polls all VMs, shows each agent's current status and last commit, and collects PR URLs and completed work.

**Usage**:
```
/dispatch-status
```

**Installed by**: cloud-dispatch module

---

### /dispatch-stop

**Stop dispatched agents and optionally destroy VMs.**

Stops all running agents, collects final results, then asks whether to keep VMs running (for reuse) or destroy them (stops billing).

**Usage**:
```
/dispatch-stop
```

**Installed by**: cloud-dispatch module

---

### /vm-manage

**Manage Hetzner Cloud VMs.**

Create, destroy, health-check, check status, or SSH into dispatch VMs.

**Actions**:
- `status` - List all VMs with IP, state, and uptime
- `create [N]` - Create N VMs (default 3)
- `destroy [--all | name]` - Destroy one or all VMs
- `health` - Run health checks on all VMs
- `ssh <name>` - Open SSH session into a VM

**Usage**:
```
/vm-manage status
/vm-manage create 3
/vm-manage destroy --all
/vm-manage health
/vm-manage ssh ccgm-agent-1
```

**Installed by**: cloud-dispatch module

---

## Session history commands

Installed by the **session-history** module.

---

### /recall

**Search session history across all clones of a repo.**

Reads Claude Code's native JSONL transcripts at `~/.claude/projects/**/*.jsonl` and surfaces session history for the current repo, unified across all of its clones (flat-clone and workspace models). No separate index or database - transcripts are the source of truth, read on demand.

**Usage**:
```
/recall                         # Last 7 days, current repo, all clones
/recall <query>                 # Filter to turns matching query (case-insensitive regex)
/recall --days N                # Custom time window
/recall --repo <name>           # Switch to a different repo (canonical name)
/recall --session <id>          # Dump a specific session's transcript
/recall --full <query>          # Do not truncate matched turn content
/recall --limit N               # Max sessions/results (default 50)
```

---

## Ship readiness commands

Installed by the **ship-readiness** module.

---

### /ship-ready

**Ship readiness dashboard.**

One-screen dashboard summarizing whether the current branch is ready to merge. Shows branch context, failing tests, open PRs, stale branches, outdated deps, merge velocity, review freshness (from `/ce-review` envelopes), and unresolved risks (via `learnings-researcher`). Read-only - never runs tests or modifies files. Prints a final GATE line (GREEN / YELLOW / RED).

**Usage**:
```
/ship-ready                   # Dashboard for the current branch
/ship-ready base:origin/main  # Override the base ref
/ship-ready mode:strict       # Exit non-zero if any gate is red (for CI or /cpm)
```

---

## Onboarding commands

Installed by the **onboarding** module.

---

### /onboarding

**Generate a structured ONBOARDING.md for the current repo.**

Analyzes the repository via an inventory script and writes `ONBOARDING.md` at the repo root. Covers Overview, Architecture, Dev Setup, Key Commands, Test Workflow, and Glossary - sized so a new engineer (or fresh Claude session) can get productive in under ten minutes. Always regenerates from scratch; never diffs against an existing ONBOARDING.md.

**Usage**:
```
/onboarding                   # Write ONBOARDING.md at current repo root
/onboarding <path>            # Target a different repo root
/onboarding --dry-run         # Print to stdout instead of writing
```

---

## Rule authoring commands

Installed by the **rule-authoring** module.

---

### /pressure-test

**Pressure-test a candidate rule with adversarial scenarios.**

Generates 5-10 adversarial scenarios targeting a rule's discipline, dispatches subagents with and without the rule loaded, captures rationalizations, and proposes additions to the rule's Rationalizations Table and Red Flags list. Runs a RED baseline, a GREEN run with the rule loaded, then an adversarial self-test against new scenarios the rule was not designed for.

**Usage**:
```
/pressure-test <path-to-rule-file>
/pressure-test modules/verification/rules/verification.md
```

---

## Git worktrees commands

Installed by the **git-worktrees** module.

---

### /worktree-start

**Start a new worktree for solo-agent feature work.**

Creates an isolated git worktree in `.worktrees/<branch-name>/` (or `~/code/worktrees/` as fallback), verifies `.worktrees/` is gitignored, detects project type, runs install and a baseline test, and copies local `.env` files from the main checkout. For solo-agent parallel branch work - for multi-agent, use the `multi-agent` module's clone setup.

**Usage**:
```
/worktree-start <branch-name>
/worktree-start <branch-name> <base-branch>    # base defaults to origin/main
```

---

### /worktree-finish

**Finish a worktree with an explicit four-option gate.**

Ends feature work in a worktree without silently merging, pushing, or discarding. Presents four options (merge locally / push + PR / keep / discard) and waits for a numeric reply. The discard option requires typing the branch name to confirm.

**Usage**:
```
/worktree-finish                    # Current directory if it is a worktree
/worktree-finish <worktree-path>
```

---

## Skills

Skills are packaged capabilities invokable by name (e.g. `/brainstorm`). Each skill installs to `~/.claude/skills/{name}/SKILL.md` and lives under `modules/<name>/skills/<skill>/SKILL.md` in the CCGM source.

Unlike commands, skills may carry supporting assets (sub-docs, scripts, reference material) alongside the `SKILL.md` entry point.

---

### /brainstorm

**Design-before-implementation gate.**

Forbids code, scaffolding, or implementation until a design spec has been written and explicitly approved by the user. Explores context, proposes 2-3 approaches with tradeoffs, writes a spec to `docs/brainstorm-notes/`, self-reviews for TBDs and contradictions, then hands off to `/xplan`. Pairs with `/ideate` to enforce spec-before-plan-before-code separation.

**Usage**:
```
/brainstorm "how should we structure the auth layer"
```

**Installed by**: brainstorm module

---

### /ce-review

**Unified review orchestrator.**

Dispatches tiered reviewer personas (correctness, testing, maintainability, plus conditional security, performance, reliability, api-contract, data-migrations) in parallel, then runs an adversarial/red-team lens with access to the specialists' findings. Merges JSON findings with P0-P3 severity and confidence, routes by `autofix_class` (safe_auto / gated_auto / manual / advisory), and pulls prior learnings from `docs/solutions/` via `learnings-researcher` before dispatch.

**Modes**: interactive, autofix, report-only, headless.

**Usage**:
```
/ce-review
/ce-review mode:autofix
/ce-review mode:report-only
```

**Installed by**: ce-review module

---

### /compound

**Capture a durable learning to docs/solutions/.**

After solving a non-trivial problem, writes a team-shared learning to `docs/solutions/{category}/{slug}.md` in the current repo. Two modes: Full (parallel research subagents, strict schema, overlap check) and Lightweight (single-pass, direct from current conversation). Re-injected as grounding context on future `/xplan` and `/review` runs via the `learnings-researcher` agent.

**Usage**:
```
/compound
/compound mode:lightweight
```

**Installed by**: compound-knowledge module

---

### /compound-refresh

**Maintenance pass over docs/solutions/.**

Walks every doc under `docs/solutions/**/*.md` and classifies each as Keep / Update / Consolidate / Replace / Delete based on staleness, referenced-code existence, and overlap with newer learnings. Run monthly, after a major refactor, or when retrieval feels noisy.

**Modes**: interactive, autofix, report-only.

**Usage**:
```
/compound-refresh
/compound-refresh mode:report-only
```

**Installed by**: compound-knowledge module

---

### /design-review

**Visual design review for web pages.**

Takes screenshots at multiple viewports via Chrome browser tools, analyzes CSS/HTML source, and runs 6 parallel analysis passes covering spacing, typography, responsive design, visual hierarchy, accessibility, and component consistency. Produces a prioritized list of actionable fixes; `--fix` applies them automatically.

**Usage**:
```
/design-review                                         # Current dev server page
/design-review http://localhost:3000/some/page
/design-review http://localhost:3000/some/page --fix
```

**Installed by**: design-review module

---

### /document-review

**Seven-lens plan-quality gate.**

Before a plan, spec, or requirements doc ships to execution, dispatches 7 role-specific reviewer agents (coherence, feasibility, product-lens, scope-guardian, design-lens, security-lens, adversarial) in parallel and merges their structured findings with severity (P0-P3) and confidence. Each lens has tight what-you-flag boundaries so findings do not overlap. For documents, not code - use `/review` or `pr-review-toolkit` for diffs.

**Usage**:
```
/document-review <path-to-plan-or-spec>
```

**Installed by**: document-review module

---

### /editorial-critique

**Deep editorial critique of long-form writing.**

Runs 8 parallel analysis passes covering prose craft, AI-tell detection, argument architecture, sentence-level quality, grammar, data accuracy, structure, and conciseness. Produces a scored, prioritized report. Use for blog posts, essays, reports, or any prose that needs to be sharp.

**Usage**:
```
/editorial-critique                              # Most recent .md in content/posts/
/editorial-critique path/to/file.md
/editorial-critique path/to/file.md --fix        # Apply fixes automatically
/editorial-critique path/to/file.md --score-only
```

**Installed by**: editorial-critique module

---

### /ideate

**Idea refinement through structured interview.**

Takes a loose, half-formed idea and interviews you until the concept is sharp enough to act on. Uses Socratic questioning, progressive refinement, and confidence tracking to reach 95% clarity before confirming. Can delegate to `/deepresearch` for validation and `/xplan` for planning once the idea is locked.

**Usage**:
```
/ideate "I want to build an app that helps people track habits"
/ideate                                          # Asks what you're thinking about
/ideate --resume                                 # Resume a saved ideation session
```

**Installed by**: ideate module

---

### /make-interfaces-feel-better

**Design-engineering principles for polished interfaces.**

Reference skill for making interfaces feel polished. Covers concentric border radius, optical alignment, shadows over borders, interruptible animations, typography details (tabular numbers, font smoothing), performance (transition specificity, `will-change`), and micro-interactions. Invoke when building UI components, reviewing frontend code, or polishing visual details.

**Usage**:
```
/make-interfaces-feel-better
```

**Installed by**: make-interfaces-feel-better module

---

### /resolve-pr-feedback

**Structured resolver for PR review comments.**

Fetches unresolved review threads via GraphQL, triages new vs already-handled, and (if 3+ new items arrive) runs cluster analysis across 11 fixed concern categories grouped by spatial proximity. Dispatches parallel `pr-comment-resolver` subagents for unambiguous fixes, posts inline replies via `gh api`, and resolves threads. Taste questions are batched for human decision. Skips cluster overhead when only 1-2 new comments exist.

**Usage**:
```
/resolve-pr-feedback
```

**Installed by**: pr-feedback module

---

### /scope-drift

**Intent-versus-diff audit before code review.**

Compares stated intent (PR body, commit messages, TODOs, plan files) against the actual diff. Classifies every plan item as DONE / PARTIAL / NOT DONE / CHANGED and flags out-of-scope changes. Runs before code-quality review as the first pass of `/ce-review`, or standalone at the start of any PR review.

**Usage**:
```
/scope-drift
```

**Installed by**: pr-review-toolkit module

---

### /todo-create

**Write a todo to .claude/todos/.**

Captures a review finding, PR comment, or tech-debt item as a file under `.claude/todos/` in the current repo. Writes `NNN-{status}-{priority}-{slug}.md` with YAML frontmatter per the schema. Canonical writer - other skills (`/todo-triage`, `/todo-resolve`, `/ce-review`) call this one. Todos start as `status:pending` by default; promote via `/todo-triage`.

**Usage**:
```
/todo-create "add tests for the auth middleware"
```

**Installed by**: todos module

---

### /todo-triage

**Promote pending todos to ready.**

Walks every pending todo in `.claude/todos/` one at a time. For each, confirm / skip / modify / drop, and on confirm, promote to `status:ready` with a concrete Proposed Change section. Runs before `/todo-resolve` so the resolver only sees scoped, agreed-upon items.

**Modes**: interactive, autofix, report-only.

**Usage**:
```
/todo-triage
/todo-triage mode:autofix
/todo-triage mode:report-only
```

**Installed by**: todos module

---

### /todo-resolve

**Batch-resolve ready todos.**

Dispatches parallel subagents (one per ready todo) with pass-paths-not-contents, aggregates their fixes, updates each todo's status to complete, and optionally feeds the pattern back into `/compound` for team knowledge. Filter by priority, source, or explicit numbers. Skips todos whose dependencies are not complete.

**Modes**: interactive, autofix, report-only, headless.

**Usage**:
```
/todo-resolve
/todo-resolve mode:autofix
```

**Installed by**: todos module

---

### /agent-native-audit

**Agent-native architecture audit.**

Scores a codebase against the four agent-native principles (parity, granularity, composability, emergent capability) and returns a report with concrete counts ("agent can do X of Y user actions"), named examples of violations, and concrete first-PR recommendations. Dispatches eight parallel research subagents (two per principle, one measures and one critiques). The report is the output; the skill does not modify code.

**Usage**:
```
/agent-native-audit
```

**Installed by**: agent-native module
