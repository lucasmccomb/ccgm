# Module Catalog

CCGM contains 34 modules across 5 categories. Each module is self-contained in `modules/{name}/` with a `module.json` manifest and its content files.

## How modules work

A module installs one or more of these file types:

| File type | Location | How Claude uses it |
|-----------|----------|-------------------|
| **Rules** (`rules/*.md`) | `~/.claude/rules/` | Loaded automatically at session start. Guides Claude's behavior. |
| **Commands** (`commands/*.md`) | `~/.claude/commands/` | Available as `/command-name` slash commands. |
| **Hooks** (`hooks/*.py`) | `~/.claude/hooks/` | Triggered by Claude Code events (tool calls, session start, etc.). |
| **Settings** (`settings.*.json`) | `~/.claude/settings.json` | Deep-merged into the permissions configuration. |
| **Docs** (`*.md` reference files) | `~/.claude/` | Reference documentation accessible to Claude. |
| **Config** (`*.json` config files) | `~/.claude/` | Configuration data read by hooks or commands. |

## Category: core

These modules form the foundation. The **standard** preset includes all four.

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

**What it does**: Establishes six critical rules:

1. **No AI attribution** - never add Co-Authored-By trailers or "Generated with Claude" to commits, PRs, or git metadata
2. **PR template detection** - before creating PRs, check the repo and org for PR templates and use them
3. **Sync before history changes** - always `git fetch` before rebase, filter-branch, or reset
4. **Rebase by default** - use rebase instead of merge for feature branches
5. **Never stash** - commit instead; stashes are invisible and easy to lose
6. **Return to main after merge** - checkout main and pull after PRs are merged

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

**Installs**: 9 hook scripts, 1 Python library, settings.json fragment

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

**Config prompts**: Protected branches (custom list), auto update check (yes/no)

**Template variables**: `__USERNAME__`

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

Additional slash commands for code quality and guided workflows.

**Installs**: 4 command files

| Command | Description |
|---------|-------------|
| `/audit` | Multi-phase codebase audit across 8 categories |
| `/pwv` | Playwright visual verification |
| `/walkthrough` | Step-by-step guided mode |
| `/promote-rule` | Review and promote repo rules to global |

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

**Config prompts**: Whether to add the Instant Domain Search MCP server to `mcp.json`

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

### debugging

Structured root-cause debugging with Opus delegation.

**Installs**: 1 command file

| Command | Description |
|---------|-------------|
| `/debug` | Structured root-cause debugging with Opus - reproduce, hypothesize, instrument, diagnose, fix, verify |

**What it does**: Enforces a disciplined debugging workflow (reproduce, hypothesize, instrument, diagnose, fix, verify) using Opus for deep root-cause analysis. Invoked automatically by the `systematic-debugging` module's routing rule.

For `/deepresearch`, see [lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch) (installed separately).

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

### session-logging

Structured agent session logging with mandatory triggers, log management, and auto-startup.

**Installs**: `rules/session-logging.md`, `log-system.md` (reference doc), `commands/startup.md`, `hooks/auto-startup.py`, settings.json fragment

**What it does**: Creates a system for tracking work across sessions:

- **Session logs**: Markdown files in a dedicated log repo (`~/code/{log-repo}/`)
- **Mandatory triggers**: Logs must be updated after commits, PR creation, PR merge, issue close, and before context compaction
- **Agent identity**: Each clone gets a unique agent ID derived from its directory name
- **Auto-startup**: A SessionStart hook automatically runs `/startup` to initialize each session
- **Cross-agent awareness**: Agents read each other's logs to avoid duplicate work

The `/startup` command is the primary interface. It pulls logs, checks git status, queries the tracking dashboard, checks for Claude Code updates, and presents a session dashboard.

**Config prompts**: Log repo name, whether to create the log repo, whether to enable auto-startup

**Dependencies**: None

---

### multi-agent

Multi-clone architecture for running multiple Claude agents in parallel on the same repo.

**Installs**: `rules/multi-agent.md`, `multi-agent-system.md` (reference doc), `commands/mawf.md`, `commands/workspace-setup.md`, `port-registry.json`

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

**Dependencies**: session-logging

---

### xplan

Deep research, planning, and execution framework for complex projects.

**Installs**: 3 command files

**What it does**: An interactive, human-in-the-loop planning framework:

- **Phase 0** - Parse input, create plan directory
- **Phase 0.5** - Discovery interview: confirm concept, choose research depth
- **Phase 1** - Deep research via parallel agents (Full / Technical Only / Market & Product / Lite / Custom presets)
- **Phase 1.5** - Research review with business viability assessment; confirm to proceed
- **Phase 2** - Naming ideation (optional)
- **Phase 2.5/2.6/2.7** - Tech stack sign-off, scope sign-off, multi-agent setup review
- **Phase 3** - Plan creation with parallelized epics and dependency waves
- **Phase 4** - Peer review by security, architecture, and business logic agents
- **Phase 5-6** - Write plan.md, final confirmation gate
- **Phase 7** - Execute via parallel agents in separate clones
- **Phase 8** - Verification, audit, and retrospective

Use `--light` to skip the interview phases and use a traditional walkthrough instead.

Commands installed:

| Command | Description |
|---------|-------------|
| `/xplan` | Launch the full planning and execution pipeline |
| `/xplan-status` | Check progress on a running or completed plan |
| `/xplan-resume` | Resume an interrupted plan execution |

**Dependencies**: multi-agent (which depends on session-logging)

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

Meta-learning patterns for improving across sessions.

**Installs**: `rules/self-improving.md`

**What it does**: Instructs Claude to reflect on completed tasks and extract reusable lessons:

- **Reflection loop**: After completing work, extract observations, distill into rules, write to memory, consolidate periodically
- **What to capture**: Non-obvious decisions, surprising root causes, patterns that worked, user preferences
- **What to skip**: Obvious patterns, one-time fixes, already-documented conventions
- **Confidence levels**: High (save immediately), medium (note for confirmation), low (watch for patterns)

**Dependencies**: None

---

### subagent-patterns

Methodology for decomposing tasks and delegating to subagents.

**Installs**: `rules/subagent-patterns.md`

**What it does**: Provides a structured approach to using Claude Code's Agent tool:

- **When to use subagents**: Parallel independent research, parallel implementation across files, isolated exploration
- **Task decomposition**: How to write specs for subagents (context, deliverable, constraints, success criteria)
- **Dispatch patterns**: Parallel research with aggregation, parallel implementation with separate clones
- **Two-stage review**: First check spec compliance, then check code quality
- **Coordination rules**: No shared mutable state, aggregate results in the parent, report failures immediately

**Dependencies**: None

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
8. **CF Pages without Git integration** - always connect for auto-deploy

**Dependencies**: None

---

### frontend-design

Principles for building distinctive, production-grade web interfaces.

**Installs**: `rules/frontend-design.md`

**What it does**: Guides Claude away from generic AI-generated aesthetics toward intentional design:

- **Typography**: Establish clear hierarchy, use 2-3 font sizes max per component
- **Color systems**: WCAG AA compliance, semantic color tokens, purposeful contrast
- **Spatial composition**: Consistent spacing scale, intentional whitespace
- **Motion**: Purposeful animations (feedback, orientation, delight), not decoration
- **What to avoid**: Default framework styles, generic card grids, excessive gradients
- **Implementation checklist**: Questions to ask before writing UI code

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

## Category: tech-specific

Guides for specific technologies and platforms.

---

### cloudflare

Cloudflare Pages and Workers deployment guide.

**Installs**: `rules/cloudflare.md`

**What it does**: Prevents common Cloudflare deployment mistakes:

- **Pages vs Workers**: Comparison table for choosing the right product
- **Git integration**: Always connect Pages projects to GitHub for auto-deploy
- **Red flags**: How to detect a misconfigured Pages project
- **Fix steps**: What to do when Git integration is missing

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
