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

# Project-level
mkdir -p .claude/rules
cp rules/verification.md .claude/rules/verification.md
cp rules/config-change-detection.md .claude/rules/config-change-detection.md
```

## Files

| File | Description |
|------|-------------|
| `rules/verification.md` | 5-step verification process with evidence requirements table |
| `rules/verification.md` | Mechanical L1/L2/L3 evidence gate: a completion claim with no fresh L1 artifact auto-fails |
| `rules/config-change-detection.md` | Hash-of-config pattern for re-verifying expensive automation when config drifts |
