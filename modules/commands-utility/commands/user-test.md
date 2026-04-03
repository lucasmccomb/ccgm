# /user-test - Browser-Based User Testing Simulation

Simulate real user testing of a deployed web app using Chrome automation. Generates a problem-space doc and solution-space doc, then optionally auto-iterates.

## Usage
```
/user-test <url> [--flows "login, search, checkout"] [--persona "new user"] [--iterate N]
```

## Workflow

### Phase 1: Setup

1. Parse the target URL and optional flow descriptions
2. If no flows specified, read the app's README or CLAUDE.md to understand key user flows
3. Get browser context and navigate to the target URL

### Phase 2: Explore & Test

For each user flow, simulate a real user:

1. **Navigate** to the starting point
2. **Read the page** - what does a user see? Is the intent clear?
3. **Interact** - click buttons, fill forms, navigate menus
4. **Check for errors** - console errors, network failures, broken UI
5. **Assess UX** - is it intuitive? confusing? slow? ugly?
6. **Screenshot** key states for evidence

Record every issue found with:
- **What happened** (factual observation)
- **Expected behavior** (what a user would expect)
- **Severity** (blocker / major / minor / cosmetic)
- **Screenshot** or console evidence

### Phase 3: Problem Space Document

Write `docs/user-test-problems.md` in the project directory:

```markdown
# User Test Report - [App Name]
**Date**: YYYY-MM-DD
**URL**: [tested URL]
**Persona**: [who we simulated]

## Critical Issues
- [blocker-level problems]

## UX Issues  
- [confusing flows, unclear UI, accessibility gaps]

## Visual Issues
- [layout bugs, inconsistencies, responsive problems]

## Performance Issues
- [slow loads, janky interactions]

## Console/Network Errors
- [JS errors, failed API calls, 4xx/5xx responses]
```

### Phase 4: Solution Space Document

Write `docs/user-test-solutions.md` in the project directory:

```markdown
# Solution Proposals - [App Name]
**Based on**: user-test-problems.md

## Priority Fixes (address these first)
For each critical/major issue:
- **Problem**: [reference]
- **Root cause**: [what's actually wrong in the code]
- **Proposed fix**: [specific code change]
- **Files**: [which files to modify]

## UX Improvements
- [design changes, flow improvements]

## Quick Wins
- [cosmetic fixes, easy improvements]
```

### Phase 5: Auto-Iterate (if --iterate N)

If `--iterate` flag is set:
1. Create GitHub issues from the solution doc (one per fix category)
2. Fix the top N issues automatically
3. Re-deploy and re-test to verify fixes
4. Update both docs with results

## Guidelines

- Test as a real user would - don't rely on knowing the codebase
- Check mobile viewport too (resize browser)
- Test error states - submit empty forms, use invalid data
- Check loading states - are there spinners? skeleton screens?
- Verify auth flows work end-to-end
- Look for accessibility basics (contrast, focus indicators, alt text)
- Time key interactions - anything over 2 seconds is a problem

## Output

After completing the test:
1. Print a summary of findings (counts by severity)
2. Point the user to the two docs
3. Ask if they want to auto-fix the top issues
