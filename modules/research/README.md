# Research

Multi-channel research using parallel Claude agents with WebSearch, WebFetch, GitHub CLI, and Reddit. No external dependencies - works out of the box with any Claude Code installation.

## `/research <topic>`

Spawns up to 7 parallel research agents that each investigate the topic from a different angle (domain, technical, competitive, adjacent, UX, infrastructure, monetization). Decomposes the topic into targeted sub-questions, runs iterative multi-round searches, and synthesizes everything into a structured research.md with confidence-rated findings.

**Depth presets:** Full (all 7 agents), Technical Only, Market & Product, Lite, Custom

**Key features:**
- Query decomposition into targeted sub-questions before spawning agents
- Multi-round iterative research (broad, focused, validation)
- Cross-session continuity via `--extend` flag
- Verification pass for high-stakes claims (Full depth)
- Sub-agents run on Sonnet; orchestrator runs on current model

**Usage:**
```
/research "dark mode browser extensions"
/research "food commerce platform" --depth market
/research "habit tracking apps" --output ~/docs/research/
/research "my topic" --extend ~/docs/research/prior/research.md
```

## /deepresearch - Local Pipeline Upgrade

For higher-quality, faster, and cheaper research, install **[lem-deepresearch](https://github.com/lucasmccomb/lem-deepresearch)**. It replaces parallel subagents with a fully local pipeline: Ollama for query generation and fact extraction, SearXNG for web search. Claude Code performs the final synthesis using its own model. No external API keys required.

`/deepresearch` requires Docker, Ollama (~40GB model), and a Python venv. See the [lem-deepresearch README](https://github.com/lucasmccomb/lem-deepresearch) for setup.

## Manual Installation

```bash
cp commands/research.md ~/.claude/commands/research.md
```
