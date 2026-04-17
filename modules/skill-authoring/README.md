# skill-authoring

Discipline for writing skills and slash commands that stay efficient, portable, and context-safe.

## What It Does

Installs a rule file that governs how new skills and commands are authored:

- **Reference-file inclusion** - when to use backtick CWD-relative paths versus `@` inline embeds
- **Conditional content extraction** - move late-sequence or conditionally-used blocks into `references/` so they do not live in every subsequent message
- **Tool selection** - prefer native tools (Glob, Grep, Read) over shell equivalents
- **Bash invocation** - one simple command per call, no chaining in the agent-runtime shell
- **Pre-resolution probes** - use `!` backticks for environment probes so the value is resolved once at skill load
- **Path discipline** - never reference files outside the skill directory
- **Writing style** - imperative/infinitive voice, no second-person "you," no AI attribution

Ported from the cross-platform skill-authoring checklist in EveryInc/compound-engineering, trimmed to the rules that apply within Claude Code (slash commands, Agent SDK skills, subagent prompts).

## Manual Installation

```bash
# Global (all projects)
cp rules/skill-authoring.md ~/.claude/rules/skill-authoring.md

# Project-level
cp rules/skill-authoring.md .claude/rules/skill-authoring.md
```

## Files

| File | Description |
|------|-------------|
| `rules/skill-authoring.md` | Authoring discipline for skills, slash commands, and subagent prompts |
