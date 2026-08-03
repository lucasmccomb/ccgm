# commands-extra

Additional slash commands for codebase audits, visual verification, guided walkthroughs, rule promotion, safety-hook state management, and session-state checkpoints.

## What It Does

This module installs eight slash command files:

- **/audit** - Run a comprehensive codebase audit across 21 packs (security, secrets, dependencies, code quality, correctness, architecture, TypeScript/React, testing, documentation, performance, privacy, observability, reliability, CI/CD hardening, data migrations, infra/IaC, accessibility, API contract, CCGM hygiene, CCGM standards, and terms-of-service compliance) with auto-fix capabilities
- **/pwv** - Playwright Visual Verification for testing UI in a headless browser with screenshots, viewport checks, and theme verification
- **/walkthrough** - Enter step-by-step guide mode where Claude presents one step at a time and waits for confirmation before proceeding
- **/promote-rule** - Review repo-level CLAUDE.md files and suggest rules that should be promoted to the global configuration
- **/freeze** - Scope-lock Edit/Write to a directory by writing `~/.claude/freeze-dir.txt`. Reads by `check-freeze.py` (see the `hooks` module)
- **/unfreeze** - Clear the freeze scope by deleting `~/.claude/freeze-dir.txt`
- **/guard** - Compose careful + freeze for focused, safe sessions. Activates the freeze state file and confirms both safety hooks are installed
- **/checkpoint** - Save or resume a structured WIP snapshot (working-on / decisions / remaining work / notes) under `~/.claude/checkpoints/{repo}/`. Complements the session-history /recall: recall surfaces recent transcripts, checkpoints are compact handoff state

## /audit Pack Model

The audit skill uses a **pack-based architecture**. Each pack is a self-contained unit that defines which checks to apply, how to detect whether the pack is relevant (via `applies_when` rules), and which deterministic tools to run.

### 21 packs

| Pack | Description | Gating |
|------|-------------|--------|
| `accessibility` | WCAG 2.1 AA compliance, ARIA roles, color contrast | `language:javascript` |
| `api-contract` | REST/GraphQL contract validation, breaking changes | `language:javascript` |
| `architecture` | Circular dependencies, layer violations, coupling | always |
| `ccgm-hygiene` | CCGM configuration health | always |
| `ccgm-standards` | CCGM coding standards compliance | always |
| `ci-cd` | GitHub Actions security (unpinned actions, dangerous triggers, permissions) | `has_workflows` |
| `code-quality` | Dead code, complexity, naming, error handling | always |
| `correctness` | Logic bugs, type errors, linting rule violations | `language:javascript` |
| `data-migrations` | SQL safety, migration anti-patterns, RLS policy gaps | `has_migrations` |
| `dependencies` | Outdated/vulnerable packages, CVEs (npm/pip/cargo/gem) | `language:javascript` |
| `documentation` | Missing README sections, stale docs, JSDoc gaps | always |
| `infra-iac` | Terraform/Checkov misconfigurations | `has_iac` |
| `observability` | Logging gaps, missing error tracking | always |
| `performance` | Bundle size, N+1 queries, missing caching | always |
| `privacy` | PII handling, data retention, GDPR/CCPA | always |
| `reliability` | Error boundaries, retry logic, timeout handling | `language:javascript` |
| `secrets` | Leaked credentials, hardcoded tokens, gitleaks | always |
| `security` | Injection, auth gaps, CVEs, semgrep rules | always |
| `testing` | Coverage gaps, flaky tests, missing edge cases | always |
| `tos-compliance` | OSS license compliance, API/service ToS, store policy | always |
| `typescript-react` | Type safety, hook rules, key props, Fast Refresh | `language:javascript` |

### Flags

```
/audit                    # Full audit — prompts for scope and execution strategy
/audit --single           # Single-session (all packs, one session, 8 subagents)
/audit --diff             # Audit only files changed vs detected base branch
/audit --diff main        # Audit only files changed vs a specific ref
/audit --staged           # Audit only staged files (always read-only)
/audit --baseline <file>  # Classify findings vs a prior run's findings.jsonl
/audit --new-only         # With --baseline: report only newly introduced findings
/audit --fix              # Apply auto-fixes and create a PR
```

### Suppression

Findings can be suppressed at two levels:

- **Inline**: add a `# audit-ignore: <check-id> [optional reason]` comment on the triggering line (or the line above it)
- **File-level**: create `.auditignore.yaml` at the repo root with path/check-id patterns

### Provenance, CODEOWNERS, and per-package scoping

The audit output includes a provenance record (tool versions, timestamp, repo path) for
every run. When the repo has a `CODEOWNERS` file, findings are annotated with the owning
team so issues can be routed automatically. For monorepos, the `--repo` flag scopes the
run to a specific package subtree.

## Manual Installation

Copy the command files into your Claude configuration:

```bash
# Global (all projects)
cp commands/audit.md ~/.claude/commands/audit.md
cp commands/pwv.md ~/.claude/commands/pwv.md
cp commands/walkthrough.md ~/.claude/commands/walkthrough.md
cp commands/promote-rule.md ~/.claude/commands/promote-rule.md
cp commands/freeze.md ~/.claude/commands/freeze.md
cp commands/unfreeze.md ~/.claude/commands/unfreeze.md
cp commands/guard.md ~/.claude/commands/guard.md
cp commands/checkpoint.md ~/.claude/commands/checkpoint.md

# Skill (pack registry, detectors/wrappers, schemas, reference docs)
# Copies exactly what module.json declares under skills/audit/ -- not a
# blanket `cp -R skills/audit/*`, which would also sweep in the skill's own
# bundled test suite (skills/audit/tests/) and any __pycache__/ droppings,
# neither of which start.sh installs.
mkdir -p ~/.claude/skills/audit
cp skills/audit/SKILL.md ~/.claude/skills/audit/SKILL.md
cp -R skills/audit/packs ~/.claude/skills/audit/packs
cp -R skills/audit/reference ~/.claude/skills/audit/reference
cp -R skills/audit/schemas ~/.claude/skills/audit/schemas
cp -R skills/audit/scripts ~/.claude/skills/audit/scripts
find ~/.claude/skills/audit/scripts -type d -name '__pycache__' -exec rm -rf {} +

# Project-level
cp commands/audit.md .claude/commands/audit.md
cp commands/pwv.md .claude/commands/pwv.md
cp commands/walkthrough.md .claude/commands/walkthrough.md
cp commands/promote-rule.md .claude/commands/promote-rule.md
cp commands/freeze.md .claude/commands/freeze.md
cp commands/unfreeze.md .claude/commands/unfreeze.md
cp commands/guard.md .claude/commands/guard.md
cp commands/checkpoint.md .claude/commands/checkpoint.md
```

## Files

| File | Description |
|------|-------------|
| `commands/audit.md` | Codebase audit command with 21 packs and auto-fix |
| `commands/pwv.md` | Playwright visual verification command |
| `commands/walkthrough.md` | Step-by-step guided walkthrough command |
| `commands/promote-rule.md` | Rule promotion from repo to global config |
| `commands/freeze.md` | Activate the freeze scope (writes `~/.claude/freeze-dir.txt`) |
| `commands/unfreeze.md` | Clear the freeze scope (deletes `~/.claude/freeze-dir.txt`) |
| `commands/guard.md` | Compose careful + freeze for focused, safe sessions |
| `commands/checkpoint.md` | Save or resume a WIP session-state checkpoint under `~/.claude/checkpoints/{repo}/` |
| `skills/audit/SKILL.md` | Skill definition backing the /audit command (pack model, orchestration, flags) |
| `skills/audit/packs/*/pack.json` | Pack manifests: check-ids, applies_when gating, tool bindings |
| `skills/audit/packs/*/checks.md` | Per-pack check descriptions with severity, confidence, and fix guidance |
| `skills/audit/scripts/detect-ecosystems.sh` | Phase-0 ecosystem detector (outputs JSON consumed by the registry) |
| `skills/audit/scripts/registry.py` | Pack registry: reads detector output, applies gating, returns selected packs |
| `skills/audit/scripts/assign-packs.py` | Distributes selected packs across parallel worker agents |
| `skills/audit/scripts/lint-pack.py` | Validates pack.json + checks.md against schemas and rubric |
| `skills/audit/scripts/merge-findings.py` | Merges spine JSONL + LLM findings, applies rubric severity |
| `skills/audit/scripts/spine/run.sh` | Deterministic tool spine: runs 18 wrapped tools, reports per-tool progress to stderr, applies the junk-path post-filter, emits finding JSONL |
| `skills/audit/scripts/spine/wrap-*.sh` | Per-tool wrappers (gitleaks, semgrep, knip, eslint, trivy, …) |
| `skills/audit/scripts/spine/exclude-dirs.txt` | Canonical excluded-dir list (node_modules, worktrees, build output) — single source of truth |
| `skills/audit/scripts/spine/exclude-file-globs.txt` | Canonical excluded file-glob list (`*.min.js`, `*.bundle.js`, `*.map`) — catches vendored/minified files by name regardless of directory |
| `skills/audit/scripts/spine/exclude.sh` / `exclude.py` | Build per-tool exclusion flags (sh) and the gitleaks config + always-on post-filter (py) from the dir + file-glob lists. The post-filter also drops findings on `.gitignore`d paths and a looks-minified backstop drops lint/SAST findings on minified vendored files (e.g. `js-dos.js`); the gitleaks config allowlists gitignored files so a never-committed `.env.local` is not reported as a leaked credential |
| `skills/audit/schemas/finding.schema.json` | JSON schema for normalized finding records |
| `skills/audit/schemas/severity-rubric.json` | Per-check severity + confidence overrides |
| `skills/audit/reference/*.md` | Runtime reference docs: security patterns, fix-patterns, architecture guides, output templates |
