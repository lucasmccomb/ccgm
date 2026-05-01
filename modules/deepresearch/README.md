# Deep Research (Exa MCP)

Multi-query semantic research bundled as a CCGM module. Claude generates diverse queries from your topic, fans them out via parallel Exa MCP tool calls, and synthesizes a structured `research.md` from the full page contents Exa returns.

Supersedes the standalone `lem-deepresearch` repo (Ollama + SearXNG pipeline). The local pipeline degraded over time as SearXNG's scraped engines (Google, DuckDuckGo, Brave) hit CAPTCHAs and rate limits. Exa's neural search returns reliable, semantically-relevant results without scraping.

## How it works

```
Topic -> Claude generates N diverse queries
      -> Claude issues N parallel Exa MCP tool calls (web_search_exa, research_paper_search_exa, etc.)
      -> Exa returns top-K results per query with full page text
      -> Claude synthesizes research.md from the aggregated results
```

| Step | Where | Notes |
|------|-------|-------|
| Query generation | Claude (the skill) | No separate model required |
| Web search + content fetch | Exa MCP server (`web_search_exa`) | Single tool call per query, parallel fan-out |
| Synthesis | Claude (the skill) | Reads full page contents, writes structured research.md |

## Depth presets

| Preset | Queries | Results / query | Best for |
|--------|---------|-----------------|----------|
| Lite | 3 | 5 | Quick scoping |
| Standard | 5 | 5 | Most research tasks (default) |
| Full | 7 | 5 | New domains, comparative research |

## Prerequisites

- **Exa account.** Sign up at https://exa.ai.
  - Free tier: 1000 searches/mo
  - Pro tier: ~$10/mo for 10k searches
- **`EXA_API_KEY`** set in the shell environment.
- **Exa MCP server** registered with the `claude mcp` CLI (writes to `~/.claude.json`).
- **Node + npx** available on `PATH` (the MCP server runs via `npx -y exa-mcp-server`).

## Setup

1. Install this module via the CCGM installer (`./start.sh`) and pick the `full` preset, or add `deepresearch` explicitly.
2. Set `EXA_API_KEY` in your shell:
   ```bash
   echo 'export EXA_API_KEY=your_key_here' >> ~/.zshrc
   source ~/.zshrc
   ```
3. Register the Exa MCP server (note the `--` before the server name; without it the CLI parses `exa` as a value to `--env`):
   ```bash
   claude mcp add --scope user --env EXA_API_KEY="$EXA_API_KEY" -- exa npx -y exa-mcp-server
   ```
4. **Restart Claude Code** so the MCP server loads.
5. Verify with `claude mcp get exa` - expect `Status: ✓ Connected`. In a fresh Claude Code session, the `web_search_exa` tool (and friends) should be callable.

## Usage

```
/deepresearch "dark mode browser extensions"
/deepresearch "SaaS pricing strategies" --depth full
/deepresearch "React vs Vue" --depth lite --output ~/notes/react-vue.md
```

The skill writes to `~/code/docs/research/{slug}/research.md` by default, or to the path passed via `--output`.

## Cost estimate

At 100 research runs/month with `--depth standard` (5 queries × 5 results = 25 search calls), expected cost is ~$3-5/mo on the Pro tier. The free tier (1000 searches/mo) covers ~40 runs.

## Why MCP rather than a CLI

The earlier draft of this module shipped a Python CLI that called the Exa REST API directly. The MCP architecture is strictly better for a Claude Code skill:

- No shell-out, no Python venv dependency, no JSON-handshake between CLI and skill
- Parallel fan-out is native (Claude issues N tool calls in one message)
- Specialized Exa endpoints (papers, GitHub, companies, Wikipedia) are exposed as separate tools the skill can route to per topic-type
- Auth flows through the MCP server's env block (registered via `claude mcp add --env`); no separate env-var checks in our code

## Troubleshooting

- **Skill says "Exa MCP tools unavailable."** The MCP server did not load. Verify with `claude mcp get exa` (expect `Status: ✓ Connected`). If it's not registered, run the `claude mcp add` command from Setup. Confirm `EXA_API_KEY` is set in the shell that started Claude Code, and that you restarted Claude Code after the change.
- **Stale `~/.claude/mcp.json` from old CCGM docs.** Pre-#427 docs told you to hand-edit `~/.claude/mcp.json`, but current Claude Code reads `~/.claude.json` (managed by the `claude mcp` CLI). Run `bash lib/mcp-migrate.sh` from the CCGM checkout to re-register every entry, or re-run `./start.sh` (the installer migrates on update).
- **Tool call returns 401 / unauthorized.** API key invalid or revoked. Generate a new one at https://exa.ai/dashboard, update your shell rc, restart Claude Code.
- **All queries return zero results.** Topic may be too narrow or oddly phrased; try `--depth lite` to confirm the path works, then revise the topic.
- **`exa-mcp-server` install fails on first run.** `npx -y` downloads on first invocation. Confirm `node` and `npm` are on `PATH`. Check network access.
