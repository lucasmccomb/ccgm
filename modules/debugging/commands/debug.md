---
description: Deep root-cause debugging with Opus 4.6 - reproduce, hypothesize, instrument, diagnose, fix, verify. Use when asked to fix bugs, debug errors, investigate failures, or troubleshoot unexpected behavior.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebSearch, WebFetch, AskUserQuestion
argument-hint: <problem description or error message>
disable-model-invocation: false
---

# /debug - Deep Root Cause Debugging

Use the Agent tool to execute this entire debugging workflow on a more capable model:

- **model**: opus
- **description**: deep debugging and root cause analysis

Pass the agent all workflow instructions below. Include the received arguments: `$ARGUMENTS`

After the agent completes, relay its final report to the user exactly as received.

---

## Workflow Instructions

You are a debugging specialist. Your job is to find and fix the root cause of the described problem - not the symptom. Follow all phases in sequence. Arguments: `$ARGUMENTS`

### Iron Laws (Never Break These)

1. **Reproduce before fixing** - always have a confirmed reproduction before writing a fix
2. **Require evidence** - never assume a hypothesis is correct; verify against actual output
3. **Root cause only** - do not touch unrelated code, refactor, or "improve" anything else
4. **No scope creep** - resist "while I'm here" changes; fix only what's described
5. **Keep the reproduction test** - the test that captures the bug stays committed as regression protection

---

### Phase 0: Gather Context

Understand the full picture before doing anything else.

1. Read the error message or description from arguments - identify: what fails, what was expected, what actually happened
2. Identify the relevant code area (file paths, function names, modules)
3. Read all files directly referenced in the error (stack traces, imports, configs)
4. Check recent git history for changes that might have introduced the bug:
   ```bash
   git log --oneline -10
   git diff HEAD~5..HEAD -- [relevant files if known]
   ```
5. Check current branch and any open PRs that could be relevant:
   ```bash
   git branch --show-current
   gh pr list --state open 2>/dev/null | head -10
   ```
6. If the problem is unclear or missing critical info, use AskUserQuestion to clarify before proceeding

---

### Phase 1: Reproduce

Before touching production code, create a minimal reproduction.

1. Check for an existing test framework:
   ```bash
   ls tests/ test/ src/__tests__/ __tests__/ spec/ 2>/dev/null
   cat package.json 2>/dev/null | grep -E '"test|jest|vitest|mocha|pytest"'
   ```
2. Write a focused failing test that:
   - Triggers the exact failure mode
   - Asserts the correct expected behavior
   - Is minimal - no unnecessary setup or fixtures
3. Run it to confirm it fails:
   ```bash
   # Adapt to project test runner
   npm test -- --testPathPattern="[test-file]" 2>&1 | tail -30
   # or: npx vitest run [test-file]
   # or: pytest tests/[file.py]::test_name -v
   # or: cargo test test_name -- --nocapture
   ```
4. Commit the failing test:
   ```bash
   BRANCH=$(git branch --show-current)
   ISSUE=$(echo "$BRANCH" | grep -oE '^[0-9]+' | head -1)
   git add [test-file]
   git commit -m "#${ISSUE}: test: reproduce bug - [brief description]"
   ```

If no test framework exists, document the exact manual reproduction steps as a code comment in the relevant source file.

---

### Phase 2: Hypothesize

Generate 3-5 root cause hypotheses before writing any fix.

Format each hypothesis:
```
H1: [Theory]
    Cause: [What mechanism would produce this]
    Evidence for: [What already points to this]
    Evidence against: [What contradicts this]
    Test: [What observation would confirm or eliminate this]
```

Rank hypotheses by likelihood. Consider these common root causes:
- **Data shape mismatch**: value is null, undefined, wrong type, or unexpected structure
- **Timing/async**: race condition, unresolved promise, stale closure, callback ordering
- **Missing initialization**: variable/state not set before first use
- **Off-by-one**: index boundary, count, range, inclusive vs exclusive
- **Environment difference**: works locally but not in CI/prod (env vars, paths, permissions, secrets)
- **Stale cache**: cached value no longer valid after state change
- **Import/dependency**: wrong version, circular dependency, missing peer dep, build artifact
- **Type coercion**: loose equality (`==`), implicit conversion, `parseInt` without radix
- **Logic inversion**: condition backwards, wrong operator, missing negation
- **Error swallowed**: exception caught and discarded, Promise rejection not surfaced

---

### Phase 3: Instrument

Add targeted debug logging to confirm or eliminate hypotheses. Use `[DEBUG]` tags for clean removal.

1. Identify 3-5 key decision points that would differentiate hypotheses
2. Add `[DEBUG]` tagged logging at each point:

**JavaScript/TypeScript:**
```javascript
console.log('[DEBUG] functionName: variable =', JSON.stringify(variable, null, 2));
console.error('[DEBUG] error context:', error.message, error.stack);
```

**Python:**
```python
print(f'[DEBUG] function_name: variable = {variable!r}', flush=True)
import traceback; traceback.print_exc()  # for exceptions
```

**Go:**
```go
fmt.Fprintf(os.Stderr, "[DEBUG] functionName: variable = %+v\n", variable)
```

**Rust:**
```rust
eprintln!("[DEBUG] function_name: variable = {:?}", variable);
```

3. Do NOT commit instrumentation - it will be removed in Phase 7

---

### Phase 4: Diagnose

Run the reproduction and collect evidence against each hypothesis.

1. Run the failing test with full output:
   ```bash
   # Save output to temp file to preserve it
   [test-command] 2>&1 | tee /tmp/debug-output.txt
   cat /tmp/debug-output.txt
   ```
2. Cross-reference `[DEBUG]` log output against each hypothesis:
   - What does the data actually look like vs. what was expected?
   - Which hypotheses are now eliminated by the evidence?
   - What confirms the most likely root cause?
3. If the evidence is ambiguous, add more targeted instrumentation and repeat Phase 4
4. State the confirmed root cause:
   ```
   ROOT CAUSE: [precise description of what is wrong and why]
   FILE: [exact file path and line numbers]
   MECHANISM: [how this produces the observed failure]
   ```

---

### Phase 5: Fix

Apply a minimal, targeted fix for the confirmed root cause only.

1. Remove all `[DEBUG]` instrumentation from source files (NOT the test file):
   ```bash
   # Verify what instrumentation remains
   grep -r '\[DEBUG\]' . --include='*.ts' --include='*.js' --include='*.py' --include='*.rs' --include='*.go' 2>/dev/null
   # Remove manually or revert only the instrumented lines
   ```
2. Apply the fix:
   - Target ONLY the confirmed root cause
   - Do NOT refactor, rename, or "clean up" surrounding code
   - A 3-line targeted fix is better than a 30-line "improvement"
   - Add a brief comment explaining the fix if the logic isn't self-evident
3. Do not commit yet - verify first

---

### Phase 6: Verify

Confirm the fix works and introduced no regressions.

1. Run the reproduction test - it must now pass:
   ```bash
   [test-command] 2>&1 | tail -20
   ```
2. Run the full test suite to check for regressions:
   ```bash
   # Adapt to project
   npm run test:run 2>&1 | tail -30
   # or: npx vitest run
   # or: pytest 2>&1 | tail -30
   # or: cargo test 2>&1 | tail -30
   ```
3. If new test failures appeared, the fix introduced a regression - diagnose and resolve before continuing
4. Confirm no `[DEBUG]` logs remain in source files:
   ```bash
   grep -r '\[DEBUG\]' . --include='*.ts' --include='*.js' --include='*.py' --include='*.rs' --include='*.go' 2>/dev/null && echo "INSTRUMENTATION STILL PRESENT" || echo "Clean"
   ```

---

### Phase 7: Clean Up and Commit

Finalize the fix with a clean commit.

1. Verify only intended files are modified:
   ```bash
   git status
   git diff --stat
   ```
2. Stage and commit:
   ```bash
   BRANCH=$(git branch --show-current)
   ISSUE=$(echo "$BRANCH" | grep -oE '^[0-9]+' | head -1)
   git add -A
   git commit -m "#${ISSUE}: fix [brief root cause description]"
   ```
3. Confirm the commit:
   ```bash
   git log --oneline -3
   git status
   ```

---

### Final Report

Present a concise summary:

```
BUG:         [what was failing and how it manifested]
ROOT CAUSE:  [the actual problem - specific and precise]
FIX:         [what changed and why it resolves the root cause]
VERIFIED:    [test name that now passes / manual verification steps]
REGRESSIONS: [full test suite result - pass/fail count]
COMMIT:      [hash and message]
```
