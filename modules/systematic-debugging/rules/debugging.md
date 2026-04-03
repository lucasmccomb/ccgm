---
name: debugging-skill-trigger
description: When to invoke the /debug skill for structured root-cause debugging
type: feedback
---

# Debugging: Use /debug Skill

When the user asks to:
- Fix a bug, error, or unexpected failure
- Debug something that is not working correctly
- Investigate why a test is failing
- Trace an error or stack trace
- Figure out why something behaves unexpectedly

**Invoke the `/debug` skill** using the Skill tool before starting any analysis or making code changes. The skill runs the debugging agent on Opus 4.6 for deep root-cause analysis.

## Why This Matters

Ad-hoc debugging (read a file, guess at a fix, apply it) frequently fixes symptoms rather than root causes. The `/debug` skill enforces: reproduce → hypothesize → instrument → diagnose → fix → verify. This prevents regressions and ensures you understand why the fix works.

## When NOT to Use /debug

- User asks what an error message means (diagnostic question only, no fix needed)
- User asks you to explain a piece of code (not a bug report)
- Trivial one-line fix where the root cause is obvious from the error message alone
- The user explicitly says to skip the structured workflow

## Usage

```
/debug <problem description or error message>
```

Examples:
```
/debug TypeError: Cannot read property 'userId' of undefined in AuthContext.tsx line 42
/debug the login form submits but users don't get redirected to dashboard
/debug tests/auth.test.ts::test_login_flow fails intermittently on CI
```
