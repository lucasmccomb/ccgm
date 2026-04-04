# Deep Research & Debugging

Provides two powerful slash commands: `/deepresearch` for comprehensive local-first research and `/debug` for structured root-cause debugging with Opus delegation.

## Commands

### `/deepresearch <topic>`

Runs a local research pipeline that combines self-hosted search with local LLM fact extraction and Anthropic API synthesis. Produces a comprehensive `research.md`.

**Pipeline:**
1. **Ollama** (qwen2.5:72b) generates diverse search queries from the topic
2. **SearXNG** (self-hosted Docker) runs parallel web searches across Google, Bing, and DuckDuckGo
3. **Ollama** extracts factual claims from each batch of search results
4. **Anthropic API** (claude-sonnet-4-6) synthesizes all facts into structured research.md

**Depth presets:** Full (7 queries, ~8 min), Standard (5 queries, ~6 min), Lite (3 queries, ~4 min)

**Key features:**
- SSRF protection (blocks RFC 1918 / loopback URLs from search results)
- HTML stripping and prompt injection mitigation on all web content
- Graceful degradation (continues with model knowledge if SearXNG returns no results)
- Structured progress output on stderr

**Usage:**
```
/deepresearch "dark mode browser extensions"
/deepresearch "food commerce platform" --depth full
/deepresearch "habit tracking apps" --output ~/code/docs/research/habits.md
```

### `/debug <problem description>`

Delegates to an Opus 4.6 agent for deep root-cause analysis. Follows a strict 7-phase workflow: gather context, reproduce, hypothesize, instrument, diagnose, fix, verify.

**Iron Laws:**
- Reproduce before fixing
- Require evidence before accepting any hypothesis
- Root cause only - no scope creep or "while I'm here" refactors
- Keep the regression test committed

**Usage:**
```
/debug TypeError: Cannot read property 'userId' of undefined in AuthContext.tsx line 42
/debug the login form submits but users don't get redirected to dashboard
/debug tests/auth.test.ts::test_login_flow fails intermittently on CI
```

## Prerequisites

`/deepresearch` requires local infrastructure. `/debug` has no prerequisites beyond Opus model access.

### 1. SearXNG (self-hosted search engine)

```bash
# Run SearXNG in Docker (one-time setup)
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=$(openssl rand -hex 32) \
  searxng/searxng:latest

# Start after reboot
docker start searxng
```

Verify: `curl -s http://localhost:8888/ | head -1` should return HTML.

### 2. Ollama (local LLM)

```bash
# Install Ollama
brew install ollama

# Start the service
brew services start ollama

# Pull the model (one-time, ~40GB download)
ollama pull qwen2.5:72b
```

Verify: `ollama list` should show `qwen2.5:72b`.

### 3. Python virtual environment

```bash
# Create venv
python3 -m venv ~/.research-tools-venv

# Install packages
~/.research-tools-venv/bin/pip install httpx ollama anthropic
```

### 4. Anthropic API key

Export `ANTHROPIC_API_KEY` in your shell profile:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
```

## Manual Installation

```bash
cp commands/deepresearch.md ~/.claude/commands/deepresearch.md
cp commands/debug.md ~/.claude/commands/debug.md
mkdir -p ~/.claude/bin
cp bin/deepresearch-cli.py ~/.claude/bin/deepresearch-cli.py
chmod +x ~/.claude/bin/deepresearch-cli.py
```

## Dependencies

- **Docker** - for running SearXNG container
- **Ollama** - for local LLM inference (qwen2.5:72b)
- **Python 3** - for the research CLI script
- **Anthropic API key** - for final synthesis step
- Opus model access (for `/debug` delegation)
