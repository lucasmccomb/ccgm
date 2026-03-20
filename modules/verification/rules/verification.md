# Verification Before Completion

Evidence before claims, always. Never assert that something works, passes, or is fixed without fresh proof.

## The 5-Step Verification Process

Before claiming any task is complete:

1. **Identify** the specific command or action that proves the claim
2. **Execute** the command fresh (do not rely on cached or prior results)
3. **Read** the full output, including exit codes and failure counts
4. **Verify** the output actually supports the claim you are making
5. **Report** with evidence attached (not just "tests pass")

## What Counts as Evidence

| Claim | Required Evidence |
|-------|-------------------|
| "Tests pass" | Fresh test run output showing pass count and 0 failures |
| "Lint is clean" | Fresh linter output showing 0 errors, 0 warnings |
| "Build succeeds" | Build command output with exit code 0 |
| "Bug is fixed" | Reproduction steps that previously failed now succeed |
| "No regressions" | Full test suite output, not just the new tests |
| "Types check" | Type checker output showing 0 errors |
| "Deployed successfully" | Deployment URL responding with expected content |

## Rules

### Run Fresh

- Do NOT rely on previous runs, even from earlier in the same session
- Do NOT assume passing one check means another also passes (lint passing does not mean types check)
- Do NOT trust partial output (10/12 tests passing means 2 are failing)

### Read Fully

- Check the exit code, not just the visible output
- Scroll through the full output, not just the summary line
- Look for warnings that might indicate problems even if the overall status is "pass"

### Report Honestly

- If 1 out of 100 tests fails, do not say "tests pass"
- If the build succeeds with warnings, mention the warnings
- If you could not run a verification step, say so explicitly

## Common Verification Failures

- **Proxy claims**: "Lint passed so the code must be correct" - wrong, they check different things
- **Stale results**: "Tests passed earlier" - they might not pass now after your changes
- **Partial verification**: Running a subset of tests instead of the full suite
- **Assumed verification**: "This change is trivial, it can't break anything" - run the checks anyway

## When to Verify

- Before every commit
- Before claiming a bug is fixed
- Before reporting a task as complete
- After any refactoring, no matter how minor
- After resolving merge conflicts
