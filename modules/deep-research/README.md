# Debugging

Provides `/debug` for structured root-cause debugging with Opus delegation.

## `/deepresearch` - Installed Separately

The `/deepresearch` command is available as a standalone install from **[deepresearch-local](https://github.com/lucasmccomb/deepresearch-local)**. It uses a local Ollama + SearXNG + Sonnet pipeline for comprehensive research.

If you use `/xplan`, you need `/deepresearch` installed - xplan delegates its research phase to it.

```bash
git clone https://github.com/lucasmccomb/deepresearch-local.git
cd deepresearch-local
./install.sh
```

## Commands

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

```bash
cp commands/debug.md ~/.claude/commands/debug.md
```

## Dependencies

- Opus model access (for `/debug` delegation)
