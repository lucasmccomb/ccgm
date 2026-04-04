---
description: Deep multi-channel research using web search across multiple platforms
allowed-tools: Bash, Read, Write, Glob, Grep, AskUserQuestion
argument-hint: <topic> [--depth full|standard|lite] [--output <path>] [--plan-dir <path>] [--extend <prior-research-path>]
---

# /deepresearch - Deep Multi-Channel Research

A research skill that runs a local Ollama + SearXNG + Sonnet synthesis pipeline to produce
a comprehensive research.md. The pipeline runs as a Python subprocess via the Bash tool.

**Can be used:**
- Standalone: `/deepresearch "dark mode browser extensions"` - writes to `__CODE_DIR__/docs/research/`
- From xplan: xplan Phase 1 delegates to this skill
- From any skill that needs deep research

**Prerequisites** (one-time setup):
- SearXNG running in Docker on localhost:8888 (`docker start searxng`)
- Ollama running with qwen2.5:72b pulled (`brew services start ollama && ollama pull qwen2.5:72b`)
- Python packages in `~/.research-tools-venv`: httpx, ollama, anthropic
- `ANTHROPIC_API_KEY` exported in shell environment

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Parse Arguments

Extract from arguments:
- **Topic**: The research subject (required)
- **`--depth <preset>`**: `lite` (3 queries), `standard` (5 queries, default), or `full` (7 queries)
- **`--output <path>`**: Custom output path for research.md (optional)
- **`--plan-dir <path>`**: When called from xplan, the plan directory (research.md written here)
- **`--extend <path>`**: Path to prior research.md (accepted for compatibility, gracefully ignored)

If no topic is provided, use AskUserQuestion to ask what to research.

### Determine Output Path

```
if --plan-dir provided:
  output = {plan-dir}/research.md          # xplan mode - CLI uses --plan-dir directly
elif --output provided:
  output = {output}                        # custom path - must end in .md
else:
  slug = kebab-case(topic)
  mkdir -p __CODE_DIR__/docs/research/{slug}
  output = __CODE_DIR__/docs/research/{slug}/research.md  # standalone default
```

---

## Phase 1: Research Configuration

### If `--depth` was provided (e.g., from xplan delegation)

Use the provided depth preset directly. Skip the interactive question.

### If `--depth` was NOT provided

Ask the user what level of research they want using AskUserQuestion:

> "What level of research should I run?"

| Option | Queries | Time Estimate | Best For |
|--------|---------|---------------|----------|
| **Standard (Recommended)** | 5 | ~6 min | Most research tasks |
| **Full** | 7 | ~8 min | New products, unfamiliar domains |
| **Lite** | 3 | ~4 min | Quick research, well-understood topics |

---

## Phase 2: Run Research Pipeline

IMPORTANT: Allow up to 10 minutes for this command. Use a Bash tool timeout of 600000ms (600 seconds).

The pipeline includes:
- Ollama model warmup (30-90s if cold - the 72B model takes time to load from disk)
- Parallel SearXNG searches (fast, runs concurrently)
- Ollama fact extraction per result batch (sequential)
- Single Sonnet synthesis call

Run the following command and wait for it to complete. Do NOT interrupt it.

If --plan-dir was provided:
```bash
~/.research-tools-venv/bin/python ~/.claude/bin/deepresearch-cli.py \
  --topic "TOPIC" \
  --output "OUTPUT_PATH" \
  --plan-dir "PLAN_DIR" \
  --depth DEPTH
```

Otherwise:
```bash
~/.research-tools-venv/bin/python ~/.claude/bin/deepresearch-cli.py \
  --topic "TOPIC" \
  --output "OUTPUT_PATH" \
  --depth DEPTH
```

**Bash tool configuration**:
- Set `timeout` to `600000` (600 seconds = 10 minutes)
- If the command exits non-zero, read the full stderr output and surface the error to the user
- Do NOT retry on failure without diagnosing the error first

**Expected progress output on stderr** (informational, not errors):
```
[start] deepresearch-cli.py
[start] Topic: ...
[check] Verifying SearXNG...
[check] SearXNG OK.
[check] Verifying Ollama model qwen2.5:72b...
[warmup] qwen2.5:72b not loaded - triggering load (30-90s for 72B)...  <- first run only
[warmup] qwen2.5:72b ready (45s load time).
[pipeline] Step 1/4: Generating search queries...
[pipeline] Step 2/4: Searching (parallel)...
[pipeline] Step 3/4: Extracting facts via Ollama...
[pipeline] Step 4/4: Synthesizing with Sonnet...
[done] Wrote N chars to /path/to/research.md
```

**Common failure modes and fixes**:
- `ERROR: SearXNG not reachable at http://localhost:8888` - Run `docker start searxng`
- `ERROR: Could not load model qwen2.5:72b` - Run `brew services start ollama` then retry
- `ERROR: ANTHROPIC_API_KEY not set` - Export the key in shell and retry
- `ERROR: Anthropic API authentication failed` - Check API key validity at console.anthropic.com

---

## Phase 3: Report Results

After the command completes successfully (exit code 0):

1. Read the output research.md using the Read tool
2. Report to the user:
   - Output path
   - Executive Summary (2-3 sentences)
   - Key Insights list (numbered, from the Key Insights section)
   - Number of sources collected
3. If standalone (not called from xplan), suggest next steps:
   - "Run `/xplan` with this research to plan an implementation"
   - "Run `/deepresearch --extend {output-path} ...` to go deeper on specific areas (coming soon)"
