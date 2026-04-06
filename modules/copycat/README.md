# Copycat

Analyze external Claude Code configuration repos to find useful patterns, rules, commands, and techniques worth incorporating into CCGM.

## `/copycat <github-url-or-local-path>`

Clones (or reads) an external Claude Code config repo, analyzes its contents with parallel agents, compares against CCGM's existing modules, and walks you through what's worth adopting.

**Accepts:**
- GitHub URLs: `https://github.com/owner/repo` or `owner/repo`
- Local paths: `/path/to/repo`

**What it analyzes:**
- Rules and behavioral instructions (CLAUDE.md, rules/*.md)
- Commands and skills
- Hooks, settings, and MCP configurations
- Architectural patterns and novel concepts

**How it works:**
1. Discovers all config files in the target repo
2. Spawns 4 parallel analysis agents (rules, commands, hooks/settings, architecture)
3. Compares each finding against CCGM's existing modules
4. Ranks findings by impact and effort
5. Walks you through findings interactively (High Priority, Quick Wins, Worth Considering)
6. Creates GitHub issues for approved findings

**Usage:**
```
/copycat anthropics/claude-code-templates
/copycat https://github.com/someone/claude-config
/copycat ~/code/some-local-repo
```

## Manual Installation

```bash
cp commands/copycat.md ~/.claude/commands/copycat.md
```
