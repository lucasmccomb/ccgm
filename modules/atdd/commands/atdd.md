---
description: Agentic Test-Driven Development - build app code to pass E2E vision specs. Reads Playwright tests, iteratively implements until all green, then ships.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
argument-hint: <feature> [--issue <number>]
---

# /atdd - Agentic Test-Driven Development

Build app code to pass E2E vision specs. Vision specs (Playwright test files) define what the app SHOULD do. This command reads the specs, builds/modifies app code until all tests pass, then ships.

**The ATDD cycle:**
1. Vision specs already exist (Playwright tests describing target behavior)
2. Agent reads specs to understand expected behavior
3. Agent runs specs, sees what fails
4. Agent implements/fixes app code (NEVER modifies spec files)
5. Agent re-runs, sees progress
6. Repeat until all green
7. Commit, push, PR

---

## Input

```
$ARGUMENTS
```

**Examples:**
```
/atdd habits
/atdd habits --issue 178
/atdd coaching --issue 180
/atdd "principles journal" --issue 181
```

---

## Phase 1: Orient

### 1.1 Parse Arguments

Parse `$ARGUMENTS`:
- Extract the feature name (single word like `habits` or quoted multi-word like `"principles journal"`)
- Extract `--issue <number>` if provided
- The feature name maps to a directory under `e2e/tests/`

### 1.2 Verify Spec Directory

Check that the spec directory exists:

```bash
ls e2e/tests/{feature}/*.spec.ts 2>/dev/null | head -20
```

If no spec files exist at `e2e/tests/{feature}/`:
- Report: "No vision specs found at `e2e/tests/{feature}/`. Write specs first (use /test-vision or /e2e), then run /atdd."
- STOP. Do not proceed without specs.

### 1.3 Issue & Branch

If `--issue` was provided, use that issue number. Otherwise, create one:

```bash
gh issue create --title "ATDD: Build web app to pass {feature} E2E vision specs" --label "enhancement" --body "Build app code to satisfy all E2E vision specs in e2e/tests/{feature}/."
```

Create the working branch:

```bash
git checkout -b {issue}-atdd-{feature} origin/main
```

### 1.4 Read All Specs

Read every spec file in the target directory to understand the expected behavior:

```bash
find e2e/tests/{feature}/ -name "*.spec.ts" -type f | sort
```

Read each file with the Read tool. Pay attention to:
- What routes/pages are tested
- What UI elements are expected (buttons, forms, headings, links)
- What user interactions are tested (clicks, form fills, navigation)
- What API responses are mocked (these define the API contract)
- What assertions define success (visible elements, URL changes, text content)

Also read any shared fixtures:

```bash
ls e2e/fixtures/*.ts 2>/dev/null
```

Read fixture files to understand mock data shapes, user personas, and state helpers.

### 1.5 Baseline Run

Run the specs to establish a baseline:

```bash
npx playwright test e2e/tests/{feature}/ --reporter=list 2>&1 | tail -40
```

Report: "X/Y tests passing. Starting ATDD loop."

If all tests already pass: report "All X tests already passing. Nothing to build." and STOP.

---

## Phase 2: Red-Green Loop

Work through failing tests systematically, not randomly. Prioritize in this order:

1. **Page load / route tests** - make sure pages render at all
2. **Structural tests** - headings, navigation, layout elements
3. **Interactive tests** - forms, buttons, user flows
4. **Edge cases** - empty states, error handling, loading states

### For each failing test:

**a. Read the test** - understand what it expects:
- What route does it navigate to?
- What UI elements must be visible?
- What interactions does it perform?
- What API mocks define the expected data shape?

**b. Identify app changes needed** - what must change:
- Missing route/page? Create it.
- Missing component? Create it.
- Missing API endpoint? Create it (matching the mock response shape).
- Wrong element text/role? Fix the component.
- Missing state management? Add it.

**c. Read relevant app code** - understand the current state:
- Check if the route exists in the router
- Check if the component exists
- Check if the API endpoint exists
- Understand the existing code patterns to follow

**d. Implement the minimum change** - make the test pass:
- Follow existing code patterns in the repo
- Don't over-engineer - just make the test green
- Match the mock data shapes exactly for API endpoints
- Use the exact accessible names the tests expect

**e. Run the specific test file**:

```bash
npx playwright test e2e/tests/{feature}/{file}.spec.ts --reporter=list 2>&1 | tail -30
```

**f. Iterate** - if still failing, read the error, diagnose, fix, re-run.

### Batch rules:

- After fixing a batch of related tests (or every 5-10 tests), run the full feature suite:
  ```bash
  npx playwright test e2e/tests/{feature}/ --reporter=list 2>&1 | tail -40
  ```
- Check for regressions - previously passing tests should still pass.
- Commit progress incrementally after each logical chunk of work:
  ```bash
  git add -A && git commit -m "#{issue}: ATDD {feature} - {X}/{Y} tests passing"
  ```

### Critical Rules:

- **NEVER modify files in `e2e/tests/` or `e2e/fixtures/`** - the specs define the target. If you change the specs to match your code, you've defeated the purpose.
- **Mocks define the API contract** - if a mock returns `{ habits: [...] }`, that's what the real API endpoint should return. Match the shape.
- **Tests define the UX** - if a test expects a button with label "Create Habit", create a button with that exact accessible name. Don't rename the test expectation.
- **If a spec seems wrong** - flag it in a code comment or commit message, but do NOT modify the spec. Move on to the next test.

---

## Phase 3: Verify

After all feature tests are green, run the full verification suite:

### 3.1 Full Feature Suite

```bash
npx playwright test e2e/tests/{feature}/ --reporter=list 2>&1 | tail -40
```

All tests must pass. If any fail, return to Phase 2 for those tests.

### 3.2 Lint

```bash
npm run lint 2>&1 | tail -20
```

Fix any lint errors in files you created or modified.

### 3.3 Type Check

```bash
npm run type-check 2>&1 | tail -20
```

Fix any type errors.

### 3.4 Unit Tests

```bash
npm run test:run 2>&1 | tail -20
```

Ensure no unit tests were broken by the changes.

### 3.5 Final Commit

If there are uncommitted changes after verification fixes:

```bash
git add -A && git commit -m "#{issue}: ATDD {feature} - all tests passing, verification clean"
```

---

## Phase 4: Ship

### 4.1 Push

```bash
git push -u origin {branch-name}
```

### 4.2 Create PR

```bash
gh pr create --title "#{issue}: ATDD - {feature} vision specs passing" --body "$(cat <<'PREOF'
## Summary

ATDD implementation for **{feature}** - built app code to pass all E2E vision specs.

## Results

- **Baseline**: {X}/{Y} tests passing
- **Final**: {Y}/{Y} tests passing (all green)

## What was implemented

{Bulleted list of what was created/changed:}
- Created {route/page} at {path}
- Created {component} at {path}
- Added {API endpoint} at {path}
- Modified {file} to {what changed}
- ...

## Spec files consumed (not modified)

{List the spec files that drove this implementation}

Closes #{issue}
PREOF
)"
```

### 4.3 Report

```
ATDD Complete: {feature}

Baseline: {X}/{Y} tests passing
Final:    {Y}/{Y} tests passing

Branch: {branch-name}
PR: {PR URL}

Files created:  {N}
Files modified: {N}
Commits:        {N}
```
