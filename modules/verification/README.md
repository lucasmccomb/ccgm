# verification

Evidence-before-claims methodology for task completion.

`rules/config-change-detection.md` is path-scoped (#1061): it carries `paths:` frontmatter and loads only after Claude reads a file matching one of `.github/workflows/**`, `**/.github/workflows/**`, `**/wrangler.toml`, `**/wrangler.json`, `**/wrangler.jsonc`, `**/.env*`, `**/supabase/migrations/**`, `**/vercel.json`, `**/fly.toml`, `**/Dockerfile*`, `**/docker-compose*`. It costs no context at session start otherwise.

## What It Does

Installs a rules file that requires fresh proof before asserting anything works:

1. **Identify** the command that proves the claim
2. **Execute** it fresh (no cached results)
3. **Read** the full output including exit codes
4. **Verify** the output actually supports the claim
5. **Report** with evidence attached

Covers tests, linting, builds, bug fixes, deployments, and type checking. Prevents common failures like proxy claims, stale results, and partial verification.

## Manual Installation

```bash
# Global (all projects)
mkdir -p ~/.claude/rules
cp rules/verification.md ~/.claude/rules/verification.md
cp rules/config-change-detection.md ~/.claude/rules/config-change-detection.md
mkdir -p ~/.claude/bin && cp bin/ccgm-verify-baseline ~/.claude/bin/ && chmod +x ~/.claude/bin/ccgm-verify-baseline

# Project-level
mkdir -p .claude/rules
cp rules/verification.md .claude/rules/verification.md
cp rules/config-change-detection.md .claude/rules/config-change-detection.md
```

## Files

| File | Description |
|------|-------------|
| `rules/verification.md` | 5-step verification process with evidence requirements table |
| `rules/config-change-detection.md` | Hash-of-config pattern for re-verifying expensive automation when config drifts |
| `bin/ccgm-verify-baseline` | Records which checks fail before work starts, then gates on new failures by exit code (0 none new, 1 new, 2 setup error). Checks come from `--check NAME=COMMAND`, `package.json` scripts, or `.ccgm-verify.json`. The baseline lives in the repo's git directory, per worktree. Failures are compared by test identifier when the output matches vitest/jest, pytest, bats or `FAIL:` formats, otherwise by exit code only. |
