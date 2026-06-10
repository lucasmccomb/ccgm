---
description: Codebase audit across 9 categories (security, deps, quality, architecture, TS/React, testing, docs, performance, ToS) with optional auto-fix
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebSearch, WebFetch, AskUserQuestion
---

# /audit - Codebase Audit

Run a comprehensive codebase audit across 9 categories. See the full skill for all phases and options: `~/.claude/skills/audit/SKILL.md`.

## Usage

```
/audit                    # Full audit — prompts for scope and execution strategy
/audit --fix              # Audit WITH auto-fixes (uses worktrees, creates PR)
/audit --single           # Single-session audit (8 subagents, lightweight; always read-only)
/audit --manual           # Set up tasks + output launch commands for manual orchestration
/audit --worker           # Worker mode (run from worktree/clone after --manual setup)
/audit --collect          # Compile results + create issues (after workers complete)
/audit --collect --force  # Collect even if some agents haven't completed
/audit --max-fixes 10     # Limit number of auto-fixes (only with --fix)
/audit --diff             # Audit only files changed vs the detected base branch
/audit --diff main        # Audit only files changed vs a specific ref
/audit --staged           # Audit only files currently staged for commit (always read-only; --fix ignored)
/audit [PATH]             # Audit a specific path instead of the entire repo
```

## Audit Categories

1. **Security** - Secrets in code, exposed API keys, missing input sanitization, SQL injection risks, XSS vulnerabilities, insecure dependencies
2. **Dependencies** - Outdated packages, unused dependencies, duplicate packages, missing lock files, version conflicts
3. **Code Quality** - Dead code, unused exports, large files, complex functions, inconsistent naming, missing error handling
4. **Architecture** - Circular dependencies, improper layer access, mixed concerns, missing abstractions, inconsistent patterns
5. **TypeScript/React** - Any type usage, missing return types, improper hook usage, missing error boundaries, Fast Refresh violations
6. **Testing** - Missing test coverage, untested edge cases, flaky tests, missing mocks, test anti-patterns
7. **Documentation** - Missing README sections, outdated API docs, missing JSDoc on public APIs, stale comments
8. **Performance** - Large bundle imports, missing lazy loading, unoptimized images, missing caching, N+1 queries
9. **Terms of Service & Policy Compliance** - OSS/dependency license violations, third-party API/service ToS, app/extension store policy, AI/LLM provider ToS

## Severity Levels

Findings are classified as: **critical**, **high**, **medium**, or **low**.

## Interactive Mode (no flags)

When called without flags, the skill prompts with two questions:

1. **Audit scope** — Read-only (findings report + GitHub issues) or Analyze + auto-fix (also applies safe fixes, creates PR)
2. **Execution strategy** — Parallel worktrees, single session, multi-clone, or manual setup

## Output

- Audit report at `.audit/current/audit-report.md`
- GitHub issues (optional) — grouped by category, linked to an epic tracking issue
- PR with fixes (only with `--fix`)
