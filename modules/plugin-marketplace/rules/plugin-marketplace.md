# Plugin Marketplace

CCGM can be installed two ways. They are not equivalent; pick deliberately.

## The two install paths

| | Bash installer (`start.sh`) | Plugin marketplace |
|---|---|---|
| Canonical? | **Yes** — full fidelity | No — additive projection |
| Deep `settings.json` merge | Yes | No (plugins ship only `agent`/`subagentStatusLine`) |
| Global `CLAUDE.md` context | Yes (auto-loaded) | No (plugin `CLAUDE.md` is never auto-loaded) |
| Rules (`rules/*.md`) | Auto-loaded by Claude Code | Injected by a SessionStart hook (opt-in) |
| Commands / agents / skills | Installed to `~/.claude/` | Native plugin components |
| Install command | `bash start.sh` | `claude plugin marketplace add <owner>/ccgm` (owner in README) |

**When deep settings or always-on CLAUDE.md context matters, use the bash installer.** The marketplace path is for users who want CCGM's commands, agents, and skills delivered through Claude Code's native plugin manager, with rules available behind an opt-in flag.

## How the marketplace is produced

The marketplace is **generated, never hand-maintained**. The source of truth is `modules/*/module.json`. The generator projects those manifests into:

- `.claude-plugin/marketplace.json` — the catalog, one entry per module, via `metadata.pluginRoot: "./modules"`.
- `modules/<name>/.claude-plugin/plugin.json` — one manifest per module.

Run it after changing any `module.json`:

```bash
python3 modules/plugin-marketplace/lib/gen_marketplace.py          # write
python3 modules/plugin-marketplace/lib/gen_marketplace.py --check  # CI: fail if stale
```

The generator is deterministic (sorted output), so an unchanged tree produces byte-identical files. CI runs `--check` and fails if the committed output drifts from `module.json`.

## The CLAUDE.md / rules gap and the workaround

A plugin's root `CLAUDE.md` is **not** loaded as context, and a plugin can only contribute the `agent` and `subagentStatusLine` settings keys. So a rules-only module (autonomy, code-quality, git-workflow, systematic-debugging, ...) would contribute nothing under the plugin path.

The workaround: the generator wires a `SessionStart` hook into every rules-bearing plugin's `plugin.json`. The hook (`hooks/plugin-rule-inject.py`) reads that plugin's bundled `rules/*.md` and emits them as `additionalContext` at session start. It is **opt-in** — a strict no-op unless `CCGM_PLUGIN_RULE_INJECTION=true` is set in the environment or `~/.claude/.ccgm.env`, because injecting full rule bodies costs tokens. With the flag off, the plugin's commands/agents/skills still work natively.

## Validation

- `claude plugin validate .claude-plugin/marketplace.json --strict` — validates the marketplace manifest when the Claude Code CLI is available.
- `python3 modules/plugin-marketplace/lib/validate_marketplace.py` — dependency-free structural validation of the marketplace and every plugin manifest. CI runs this so the manifests stay valid even where `claude` is not installed.

## Rules of the road

- **Never hand-edit `marketplace.json` or any `plugin.json`.** Edit `module.json` and re-run the generator.
- **Never let the bash path regress** to accommodate the plugin path. The bash installer is canonical.
- After adding or changing a module, run the generator and commit its output in the same change.
