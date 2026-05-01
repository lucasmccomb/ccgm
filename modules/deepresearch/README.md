# Deep Research (Exa)

Multi-query semantic research bundled as a CCGM module. Claude generates diverse queries from your topic, Exa runs each query and returns top-K results with full clean page contents, then Claude synthesizes a structured `research.md`.

This module supersedes the standalone `lem-deepresearch` repo (Ollama + SearXNG pipeline). The local pipeline degraded over time as SearXNG's scraped engines (Google, DuckDuckGo, Brave) hit CAPTCHAs and rate limits. Exa is purpose-built for AI agents and returns reliable, semantically-relevant results.

## How it works

```
Topic -> Claude generates N diverse queries
      -> deepresearch-cli.py fans out to Exa in parallel
      -> Exa returns top-K results per query with full page text
      -> Claude synthesizes research.md from the structured JSON
```

| Step | Where | Notes |
|------|-------|-------|
| Query generation | Claude (the skill) | No separate model required |
| Web search + content fetch | Exa `/search` with `contents.text=true` | Single round-trip per query |
| Synthesis | Claude (the skill) | Reads full page contents, writes structured research.md |

## Depth presets

| Preset | Queries | Results / query | Best for |
|--------|---------|-----------------|----------|
| Lite | 3 | 5 | Quick scoping |
| Standard | 5 | 5 | Most research tasks (default) |
| Full | 7 | 5 | New domains, comparative research |

## Prerequisites

- An Exa API key. Sign up at https://exa.ai.
  - Free tier: 1000 searches/mo
  - Pro tier: ~$10/mo for 10k searches
- Python 3 with `httpx` available. The CLI uses the standard `~/.research-tools-venv` if it exists, otherwise system Python.

## Setup

1. Install this module via the CCGM installer (`./start.sh`)
2. Set `EXA_API_KEY` in your shell environment:
   ```bash
   echo 'export EXA_API_KEY=your_key_here' >> ~/.zshrc
   source ~/.zshrc
   ```
3. Verify:
   ```bash
   curl -s -H "x-api-key: $EXA_API_KEY" -H "Content-Type: application/json" \
     -d '{"query":"test","numResults":1,"contents":{"text":true}}' \
     https://api.exa.ai/search | head -c 200
   ```

## Usage

```bash
/deepresearch "dark mode browser extensions"
/deepresearch "SaaS pricing strategies" --depth full
/deepresearch "React vs Vue" --depth lite --output ~/notes/react-vue.md
```

The skill writes to `~/code/docs/research/{slug}/research.md` by default, or to the path you pass via `--output`.

## Cost estimate

At 100 research runs/month with `--depth standard` (5 queries × 5 results = 25 search calls), expected cost is ~$3-5/mo on the Pro tier. The free tier (1000 searches/mo) covers ~40 runs.

## Troubleshooting

- `ERROR: EXA_API_KEY not set` - Set the env var per the Setup section above.
- `ERROR: Exa returned 401` - Key invalid or rotated. Generate a new one at https://exa.ai/dashboard.
- `ERROR: Exa returned 429` - You hit the rate limit on your tier. Wait or upgrade.
- All queries return zero results - Check that your topic is searchable, or try `--depth lite` to confirm the API path works before committing to a full run.
