# Verification Before Completion

No completion claim without verification evidence. Never assert that something works, passes, or is fixed without proof captured this session.

## The Process

Before claiming a task is complete:

1. Identify the specific command or action that proves the claim.
2. Execute it at claim time and capture its output.
3. Read the full output, including exit codes and failure counts, not just the summary line.
4. Confirm the output supports the exact claim.
5. Report with the evidence attached, not "tests pass."

## What Counts as Evidence

| Claim | Required evidence |
|-------|-------------------|
| "Tests pass" | Test run output showing pass count and 0 failures |
| "Lint is clean" | Linter output showing 0 errors, 0 warnings |
| "Build succeeds" | Build output with exit code 0 |
| "Types check" | Type checker output showing 0 errors |
| "Bug is fixed" | The reproduction that previously failed now succeeding |
| "No regressions" | Full suite output, not just the new tests |
| "Deployed" | The deployment URL responding with the expected content |
| "UI renders correctly" | A screenshot captured this session |
| "Agent completed" | The subagent's actual diff, test run, or artifact, never its self-report |

Evidence is an artifact the machine produced this session. A reasoned argument ("the diff is small," "the types line up") is a hypothesis, and a bare assertion ("it works," "fixed") is the failure this rule exists to catch. Paste the artifact next to the claim; an artifact you ran but did not show reads as an assertion, and a claim with no artifact is downgraded to "changed X, not yet verified."

## One Check Is Not Another

Lint passing does not mean types check; a type check is not a test run; 10 of 12 tests passing means 2 are failing. Check the exit code, scroll the full output, and read warnings even when the overall status is pass. Report honestly: one failure out of a hundred is not "tests pass," a build with warnings mentions the warnings, and a verification step you could not run is stated as not run.

## When to Verify

Before claiming a bug is fixed, before reporting a task complete, before pushing with the full pre-push suite (see `code-quality.md`), and after resolving merge conflicts.
