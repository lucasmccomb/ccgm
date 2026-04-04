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

## Utility commands

Installed by the **commands-utility** module.

---

### /cgr

**Clear conversation, checkout default branch, and rebase on latest origin.**

Resets the working context to a clean state - useful when starting a new task or after completing a feature.

**What happens**:
1. Clears the current conversation context
2. Checks out the default branch (main or master)
3. Rebases on `origin/main` to sync with the latest remote state

**Usage**:
```
/cgr
```

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

### /dotsync

**Sync local Claude Code config changes back to the CCGM repo.**

When you've customized files in `~/.claude/` directly, this command syncs those changes back to your local CCGM clone, keeping CCGM as the source of truth.

**What happens**:
1. Identifies which CCGM-managed files have been modified locally
2. Diffs the changes
3. Copies modified files back into the appropriate `modules/` subdirectories
4. Prompts to commit the changes

**Usage**:
```
/dotsync
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

## Research and debugging commands

Installed by the **deep-research** module.

---

### /deepresearch

**Deep multi-channel research across 15+ platforms.**

Spawns parallel research agents to gather comprehensive information from web search, GitHub, Reddit, YouTube, and other platforms using standalone tools (curl, gh, mcporter, yt-dlp, WebSearch).

**Research channels**:
- Web search (Exa via mcporter, WebSearch)
- GitHub (repos, issues, discussions via gh CLI)
- Reddit (JSON API via curl)
- YouTube (metadata via yt-dlp)
- Any web page (Jina Reader via curl)

**What happens**:
1. Breaks the research question into parallel sub-queries
2. Spawns agents per channel using standalone CLI tools
3. Aggregates and deduplicates findings
4. Synthesizes into a structured report with sources

**Usage**:
```
/deepresearch "how do teams handle multi-agent coordination in Claude Code"
/deepresearch  # Will ask for the research topic interactively
```

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

## Workflow commands

Installed by the **xplan**, **multi-agent**, and **session-logging** modules.

---

### /xplan

**Deep research, planning, and execution framework.**

An 8-phase autonomous framework for tackling complex projects, from initial research through implementation.

**Phases**:
1. **Parse input** - understand the project, create plan directory
2. **Deep research** - spawn parallel research agents (configurable preset: Full, Technical Only, Lite, Custom)
3. **Build model** - synthesize research into a contextual understanding
4. **Create plan** - design parallelized execution plan with epics and dependency waves
5. **Peer review** - specialized agents review for architecture, security, UX, and feasibility
6. **Interactive walkthrough** - present plan to user for feedback and decisions
7. **Execute** - spawn parallel agents for each wave of work
8. **Complete** - audit results, run retrospective

This command explicitly overrides autonomy rules - all phases require user confirmation before proceeding.

**Usage**:
```
/xplan "Build a SaaS dashboard with auth, billing, and analytics"
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

### /startup

**Session initialization.**

Automatically runs at session start (if auto-startup is enabled) or can be invoked manually. Provides full context for beginning a work session.

**What it does**:
1. Derives agent identity from directory name
2. Pulls latest session logs and reads today's entries
3. Reads other agents' logs for cross-agent awareness
4. Creates today's log file if it doesn't exist
5. Checks git status, syncs with remote
6. Lists open PRs and issues
7. Queries the tracking dashboard for claimed/unclaimed work
8. Checks sibling clones for what other agents are doing
9. Checks for Claude Code updates
10. Presents a session dashboard with recommended next action

**Usage**:
```
/startup
```

**Installed by**: session-logging module
