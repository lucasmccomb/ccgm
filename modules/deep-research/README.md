# Deep Research & Debugging

Provides two powerful slash commands: `/deepresearch` for comprehensive multi-channel research and `/debug` for structured root-cause debugging with Opus delegation.

## Commands

### `/deepresearch <topic>`

Spawns parallel research agents across 15+ internet channels: Reddit, GitHub, YouTube, Exa semantic search, web search, RSS, and Twitter. Produces a comprehensive `research.md` with confidence-rated findings.

**Depth presets:** Full (all 7 agents), Technical Only, Market & Product, Lite, Custom

**Key features:**
- Query decomposition into targeted sub-questions before spawning agents
- Multi-round iterative research (broad -> focused -> validation)
- Cross-session continuity via `--extend` flag
- Full verification pass for high-stakes claims (Full depth)
- Sub-agents run on Sonnet; orchestrator runs on current model

**Usage:**
```
/deepresearch "dark mode browser extensions"
/deepresearch "food commerce platform" --depth market
/deepresearch "habit tracking apps" --output ~/code/docs/research/
/deepresearch "my topic" --extend ~/code/docs/research/prior/research.md
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

## Manual Installation

Copy the command files to your Claude commands directory:

```bash
cp commands/deepresearch.md ~/.claude/commands/deepresearch.md
cp commands/debug.md ~/.claude/commands/debug.md
```

## Dependencies

- `mcporter` (optional, for Exa semantic search in `/deepresearch`) - install via npm: `npm install -g mcporter`
- `yt-dlp` (optional, for YouTube metadata in `/deepresearch`) - install via brew: `brew install yt-dlp`
- Opus model access (for `/debug` delegation)
