# Global Claude Code Instructions

These instructions apply to ALL repositories. Project-specific instructions go in each repo's `CLAUDE.md`.

## Configuration Structure

Global behavior is defined across these locations, all loaded automatically:

| Location | Purpose |
|----------|---------|
| `~/.claude/rules/soul.md` | AI personality, philosophy, reasoning principles, communication style |
| `~/.claude/rules/human-context.md` | User identity, goals, domain knowledge, working preferences |
| `~/.claude/rules/*.md` | Behavioral rules (autonomy, git workflow, code quality, debugging, etc.) |
| `~/.claude/commands/*.md` | Slash commands (/startup, /commit, /xplan, etc.) |
| `~/.claude/hooks/*.py` | Workflow automation (auto-approve, issue enforcement, tracking) |
| `~/.claude/settings.json` | Tool permissions and plugin configuration |

All rule files are managed by CCGM modules. To modify rules, edit the rule file directly or update the source module in the CCGM repo.
