# Debugging

Provides `/debug` for structured root-cause debugging with Opus delegation.

## `/debug <problem description>`

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

- Opus model access (for delegation)
