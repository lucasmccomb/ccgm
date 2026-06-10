---
description: Pack-based codebase audit across 21 packs (security, secrets, deps, quality, correctness, architecture, TS/React, testing, docs, performance, privacy, observability, reliability, CI/CD, data-migrations, infra-iac, accessibility, api-contract, ccgm-hygiene, ccgm-standards, tos-compliance) with optional auto-fix
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebSearch, WebFetch, AskUserQuestion
---

# /audit - Codebase Audit

Run a comprehensive codebase audit using 21 self-contained packs. See the full skill for all phases and options: `~/.claude/skills/audit/SKILL.md`.

## Usage

```
/audit                    # Full audit — prompts for scope and execution strategy
/audit --single           # Single-session (all packs, one session, 8 subagents)
/audit --diff             # Audit only files changed vs the detected base branch
/audit --diff main        # Audit only files changed vs a specific ref
/audit --staged           # Audit only files currently staged for commit (always read-only)
/audit --baseline <file>            # Classify findings vs a previous run's findings.jsonl
/audit --baseline <file> --new-only # Report only newly introduced findings
/audit --fix              # Apply auto-fixes and create a PR
/audit --max-fixes 10     # Limit number of auto-fixes (only with --fix)
/audit --manual           # Set up tasks + output launch commands for manual orchestration
/audit --worker           # Worker mode (run from worktree/clone after --manual setup)
/audit --collect          # Compile results + create issues (after workers complete)
/audit --collect --force  # Collect even if some agents haven't completed
```

## Packs (21 total)

Packs are gated by `applies_when` rules — only packs matching the detected ecosystems run.

| Pack | What it checks | Gating |
|------|----------------|--------|
| `security` | Injection, auth gaps, CVEs, semgrep | always |
| `secrets` | Leaked credentials, hardcoded tokens, gitleaks | always |
| `dependencies` | Outdated/vulnerable packages (npm/pip/cargo/gem) | `language:javascript` |
| `code-quality` | Dead code, complexity, naming, error handling | always |
| `correctness` | Logic bugs, type errors, linting violations | `language:javascript` |
| `architecture` | Circular deps, layer violations, coupling | always |
| `typescript-react` | Type safety, hook rules, key props, Fast Refresh | `language:javascript` |
| `testing` | Coverage gaps, flaky tests, missing edge cases | always |
| `documentation` | Missing README sections, stale docs, JSDoc gaps | always |
| `performance` | Bundle size, N+1 queries, missing caching | always |
| `privacy` | PII handling, data retention, GDPR/CCPA | always |
| `observability` | Logging gaps, missing error tracking | always |
| `reliability` | Error boundaries, retry logic, timeout handling | `language:javascript` |
| `ci-cd` | Unpinned actions, dangerous triggers, permissions | `has_workflows` |
| `data-migrations` | SQL safety, migration anti-patterns, RLS gaps | `has_migrations` |
| `infra-iac` | Terraform/Checkov misconfigurations | `has_iac` |
| `accessibility` | WCAG 2.1 AA, ARIA roles, color contrast | `language:javascript` |
| `api-contract` | REST/GraphQL contract validation, breaking changes | `language:javascript` |
| `ccgm-hygiene` | CCGM configuration health | always |
| `ccgm-standards` | CCGM coding standards compliance | always |
| `tos-compliance` | OSS license, API ToS, store policy | always |

## Severity Levels

Findings are classified as: **critical**, **high**, **medium**, or **low**.

## Suppression

- **Inline**: add `# audit-ignore: <check-id> [optional reason]` on the triggering line (or `// audit-ignore: <check-id> [reason]` for JS/TS)
- **File-level**: create `.auditignore.yaml` at the repo root with path/check-id patterns

## Interactive Mode (no flags)

When called without flags, the skill prompts with two questions:

1. **Audit scope** — Read-only (findings report) or Analyze + auto-fix (applies safe fixes, creates PR)
2. **Execution strategy** — Parallel worktrees, single session, multi-clone, or manual setup

## Output

- Findings JSONL at `.audit/current/findings.jsonl` (stable fingerprint per finding)
- Audit report at `.audit/current/audit-report.md`
- PR with fixes (only with `--fix`)
