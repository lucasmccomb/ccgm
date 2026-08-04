# plugin-marketplace

Maintainer tooling that makes CCGM installable as a **native Claude Code plugin marketplace** — additively. The bash installer (`start.sh`) remains the canonical, full-fidelity path.

## What it ships

| File | Purpose |
|------|---------|
| `lib/gen_marketplace.py` | Generator. Projects `modules/*/module.json` into `.claude-plugin/marketplace.json` + per-module `.claude-plugin/plugin.json`. Deterministic; `--check` for CI. |
| `lib/validate_marketplace.py` | Dependency-free structural validator for the marketplace + every plugin manifest. CI fallback when the `claude` CLI is absent. |
| `hooks/plugin-rule-inject.py` | SessionStart hook copied into every rules-bearing plugin. Injects that plugin's `rules/*.md` as `additionalContext` (opt-in via `CCGM_PLUGIN_RULE_INJECTION`). |
| `rules/plugin-marketplace.md` | The rule explaining the two install paths and the generate-don't-hand-edit contract. |

## Why a marketplace projection

Claude Code plugins ship commands, agents, skills, hooks, and output styles — but a plugin's `CLAUDE.md` is **not** loaded as context, and a plugin can only contribute the `agent`/`subagentStatusLine` settings keys. So:

- **Commands / agents / skills / output styles** map cleanly to native plugin components.
- **Rules** (`rules/*.md`), which the bash path auto-loads, are bridged by the SessionStart rule-injection hook.
- **Deep `settings.json` merge + global `CLAUDE.md`** have no plugin equivalent — that is why the bash installer stays canonical.

## Usage

```bash
# Regenerate after changing any module.json
python3 modules/plugin-marketplace/lib/gen_marketplace.py

# CI: fail if committed output drifted from module.json
python3 modules/plugin-marketplace/lib/gen_marketplace.py --check

# Validate (no claude CLI required)
python3 modules/plugin-marketplace/lib/validate_marketplace.py

# Validate with the real CLI when available
claude plugin validate .claude-plugin/marketplace.json --strict
```

## Installing CCGM as a marketplace (end user)

```bash
claude plugin marketplace add lucasmccomb/ccgm
claude plugin install code-quality@ccgm
# rules behind a flag (opt-in, token cost):
echo 'CCGM_PLUGIN_RULE_INJECTION=true' >> ~/.claude/.ccgm.env
```

## Manual installation (without the CCGM installer)

```bash
mkdir -p ~/.claude/lib ~/.claude/hooks ~/.claude/rules
cp lib/gen_marketplace.py ~/.claude/lib/
cp lib/validate_marketplace.py ~/.claude/lib/
cp hooks/plugin-rule-inject.py ~/.claude/hooks/
cp rules/plugin-marketplace.md ~/.claude/rules/
```

## Status

`beta` — maintainer/distribution tooling, opt-in via `start.sh --add plugin-marketplace`. Not bundled in any preset.
