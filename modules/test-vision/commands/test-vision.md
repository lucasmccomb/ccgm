---
description: Comprehensive e2e test suite generation. Discovers all features, interviews user, generates infrastructure, dispatches parallel /e2e agents.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion
argument-hint: [--skip-chrome] [--skip-interview]
---

# /test-vision - Vision-Driven E2E Test Suite Generation

Discovers all features in a codebase, interviews the user to validate test cases and priorities, generates shared Playwright infrastructure, then dispatches parallel agents to build a complete e2e test suite.

Composes `/e2e` as its atomic unit: each feature domain gets its own `/e2e` agent that generates a single spec file.

**Flags:**
- `--skip-chrome` - Skip Chrome MCP visual discovery (use code-based discovery only)
- `--skip-interview` - Skip user interview, use auto-detected defaults (prints what was detected)

## Sub-Agent Model Optimization

| Phase | Agent | Model |
|-------|-------|-------|
| Phase 0 | Discovery agent | sonnet |
| Phase 4 | Spec generation agents (/e2e) | sonnet |

The orchestrator (this session) stays on the current model for synthesis, interview, and infrastructure generation.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Codebase Discovery

Launch a single Agent (model: sonnet) with the following task:

```
Analyze this codebase and produce a feature-domain map for e2e test planning.

## Pre-check: Monorepo Detection

First, check if this is a monorepo:
- ls pnpm-workspace.yaml turbo.json nx.json 2>/dev/null
- cat package.json | grep '"workspaces"' 2>/dev/null

If a monorepo is detected, list the apps/packages and STOP. Report back which apps exist so the orchestrator can ask the user which to target. Do NOT proceed with discovery in a monorepo until an app is selected.

## 7-Source Discovery Checklist

Run all of these:

1. **Route definitions**:
   - Glob: **/routes.{ts,tsx}, **/App.{ts,tsx}, **/router.{ts,tsx}, **/app/**/page.{ts,tsx}
   - Extract: path, component, auth requirement (look for ProtectedRoute, RequireAuth, or similar wrappers)

2. **Navigation component**:
   - Grep for: <nav, <Sidebar, <NavLink, <Link to=, <Link href=
   - Extract: visible navigation links and their destinations

3. **README + CLAUDE.md**:
   - Read both files if they exist
   - Extract: feature descriptions, user flow descriptions, route tables

4. **API endpoints**:
   - Glob: **/api/**/*.{ts,js}, **/functions/**/*.{ts,js}, **/routes/**/*.{ts,js}
   - Exclude node_modules
   - Extract: endpoint paths, HTTP methods, what they do

5. **Existing test coverage**:
   - Glob: **/*.spec.ts, **/*.test.ts, **/e2e/**
   - Extract: which features are already tested, which are not

6. **State stores**:
   - Glob: **/store/**/*.{ts,tsx}, **/stores/**/*.{ts,tsx}, **/context/**/*.{ts,tsx}
   - Extract: store names, actions, state shape (reveals features without dedicated routes)

7. **Form schemas**:
   - Grep for: z.object, useForm, zodResolver, yupResolver
   - Extract: form fields, validation rules, error states

## Auth Provider Detection

Check package.json dependencies for:
- better-auth -> "Better Auth"
- @supabase/supabase-js or @supabase/ssr -> "Supabase"
- @clerk/clerk-react or @clerk/nextjs -> "Clerk"
- None -> "Unknown / No Auth"

## Output Format

Return a structured feature-domain map:

Feature Domain Map:
  1. {Feature Name} (Tier {0|1|2})
     Routes: {/path1, /path2}
     Components: {ComponentA, ComponentB}
     API: {GET /api/path, POST /api/path}
     State: {storeName (if applicable)}
     Forms: {formName with N fields (if applicable)}
     Existing tests: {none | partial | full}

  2. ...

Auth Provider: {detected provider}
Total Feature Domains: {N}
```

### Monorepo Handling

If the discovery agent reports a monorepo, use AskUserQuestion:

```
"This is a monorepo with multiple apps: {list}. Which app should I generate e2e tests for?"
```

Options: one per app detected. After selection, re-run discovery scoped to that app's directory.

---

## Phase 1: Chrome MCP Visual Discovery

**Skip this phase if `--skip-chrome` flag is set or Chrome MCP tools are unavailable.**

For each route in the feature-domain map:

1. Get browser context: `tabs_context_mcp(createIfEmpty: true)`
2. Navigate to the route
3. If redirected to a login/auth page: mark as "auth-required, Chrome skipped" and continue to next route
4. If loads successfully:
   - Read the page content (`read_page`) to identify interactive elements
   - Note: page title, headings, form fields, buttons, CTAs, modals, data displays
   - Check console for JS errors (`read_console_messages`)
   - Check network for API call patterns (`read_network_requests`)

5. Enrich the feature-domain map with visual context:
   - Actual page titles and headings found
   - Form field labels and types
   - Button text and available actions
   - Data display patterns (tables, lists, cards)
   - Any JS errors or failed network requests observed

Partial data is expected. Public routes get full Chrome context; auth-required routes rely on code-based discovery only.

---

## Phase 2: User Interview

**Skip this phase if `--skip-interview` flag is set. Instead, print auto-detected defaults:**
```
--skip-interview mode:
  Auth provider: {detected}
  Feature domains: {N}
  Auth credentials expected: E2E_USER_EMAIL, E2E_USER_PASSWORD
  Generating with defaults... (run without --skip-interview to customize)
```

### Step 1: Feature Validation

Present the feature-domain map using AskUserQuestion:

```
question: "I've identified {N} feature domains in this codebase:

{Feature-domain map summary - show feature names, route counts, auth tiers}

Does this cover everything?"
options:
  - "Looks complete - proceed"
  - "Missing features (I'll describe)"
  - "Remove some (I'll specify)"
```

For repos with >12 domains, show a condensed summary (feature name + route count only) rather than the full map. Expand on request.

### Step 1b: Unbuilt Features

```
question: "Are there any planned features not yet in the codebase that you'd like test specs for? These specs will use permissive assertions so they serve as executable specifications for agents building the features."
options:
  - "No, just test what exists"
  - "Yes (I'll describe the planned features)"
```

If yes, add the described features to the domain map with a `[PLANNED]` marker.

### Step 2: Priority & Scope

```
question: "Which features are highest priority for e2e coverage?"
options:
  - "All of them - full coverage"
  - "Critical path only (I'll specify which)"
  - "Let me rank them"
```

### Step 3: Auth Setup

```
question: "I detected {auth provider}. For e2e tests, I'll generate auth.setup.ts using {strategy description}. Test credentials will be read from env vars (E2E_USER_EMAIL, E2E_USER_PASSWORD). Sound right?"
options:
  - "Yes, proceed"
  - "Different auth approach (I'll describe)"
```

### Step 4: Delegation Review

```
question: "Here's how I'll delegate the work:

{N} parallel agents, each generating one spec file:
  Agent 1 -> e2e/features/{domain1}.spec.ts (~{M} tests)
  Agent 2 -> e2e/features/{domain2}.spec.ts (~{M} tests)
  ...

Estimated total: {N} spec files, ~{M} total tests.

Ready to proceed?"
options:
  - "Proceed with spec generation"
  - "Adjust delegation (I'll describe changes)"
```

---

## Phase 3: Infrastructure Generation

Generate the shared test infrastructure using the Write tool. All files must be written and verified before Phase 4.

### 3.1 Install Playwright (if needed)

```bash
grep -q "@playwright/test" package.json 2>/dev/null || npm install -D @playwright/test
npx playwright install chromium 2>/dev/null
```

### 3.2 Generate playwright.config.ts

If `playwright.config.ts` does not already exist, generate it.

**With auth detected:**
```typescript
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: 'html',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      dependencies: ['setup'],
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
})
```

**Without auth:**
Omit the `setup` project and `dependencies`.

### 3.3 Generate e2e/fixtures.ts (if auth detected)

```typescript
import { test as base, type Page } from '@playwright/test'
import { existsSync } from 'fs'

const USER_STORAGE_STATE = 'e2e/.auth/user.json'

export const test = base.extend<{
  authenticatedPage: Page
}>({
  authenticatedPage: async ({ browser }, use, testInfo) => {
    if (!existsSync(USER_STORAGE_STATE)) {
      testInfo.skip(true, 'Auth not configured. Set E2E_USER_EMAIL and E2E_USER_PASSWORD env vars, then run: npx playwright test --project=setup')
      return
    }
    const context = await browser.newContext({ storageState: USER_STORAGE_STATE })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },
})

export { expect } from '@playwright/test'
```

### 3.4 Generate e2e/auth.setup.ts (if auth detected)

Select the appropriate template based on detected auth provider:

- **Better Auth**: UI-based email/password form fill
- **Supabase**: Programmatic API with `signInWithPassword()` and session injection
- **Clerk**: UI-based with Clerk's two-step sign-in flow
- **Unknown**: Generic UI-based with customization comments

See `/e2e` command for the full templates.

### 3.5 Create Directories and Gitignore

```bash
mkdir -p e2e/features e2e/.auth
echo '*' > e2e/.auth/.gitignore
grep -q "e2e/.auth" .gitignore 2>/dev/null || echo "e2e/.auth/" >> .gitignore
```

### 3.6 Verify Infrastructure (MANDATORY)

Before proceeding to Phase 4, verify ALL infrastructure files exist:

```bash
ls -la playwright.config.ts e2e/fixtures.ts e2e/auth.setup.ts e2e/features/ 2>&1
```

If auth was not detected, `e2e/fixtures.ts` and `e2e/auth.setup.ts` may not exist - that is correct. But `playwright.config.ts` and `e2e/features/` must always exist.

**Do NOT proceed to Phase 4 until this verification passes.**

---

## Phase 4: Parallel /e2e Dispatch

### 4.1 Pre-Assign File Paths

For each feature domain, assign a unique output file:
```
{domain-1} -> e2e/features/{domain-1-kebab}.spec.ts
{domain-2} -> e2e/features/{domain-2-kebab}.spec.ts
...
```

No two agents may touch the same file.

### 4.2 Scalability

For repos with >12 feature domains, split into two dispatch waves of 6-8 agents each. This keeps orchestrator context manageable. Files don't conflict between waves, so this is purely for orchestrator management.

### 4.3 Dispatch Agents

For each feature domain, spawn a Task agent (model: sonnet) with the following prompt:

```
Read the file ~/.claude/commands/e2e.md and follow its instructions exactly.

CONTEXT (from /test-vision discovery):
- Feature: {feature name}
- Auth tier: {0=public, 1=authenticated, 2=admin}
- Routes: {list of routes for this feature}
- Components: {key components identified}
- API endpoints: {related API paths}
- Interactive elements: {forms, buttons, modals from Chrome MCP if available}
- Visual context: {page titles, headings, CTA text from Chrome MCP if available}
- Auth provider: {detected provider}
- Planned/unbuilt: {yes/no - if yes, use permissive three-tier assertions}

CONSTRAINTS:
- Output file: {pre-assigned path}
- Import from '../fixtures' for authenticatedPage (or '@playwright/test' if no auth)
- Use direct locators (getByRole, getByText, getByTestId, getByLabel)
- Every test calls page.goto() directly - no shared navigation state
- Graceful credential skipping via the fixture
- Use .or() for features with multiple valid states (empty vs populated)
- No exact copy assertions - use regex matchers
- Aim for 6-15 tests
- Three-tier assertions: route loads, structural landmarks, behavioral interactions

Write the complete spec file to the output path.
```

### 4.4 Wait for Completion

Wait for all dispatched agents to complete. Track which succeeded and which failed.

---

## Phase 5: Integration & Validation

After all /e2e agents complete:

### 5.1 Verify Files Created

```bash
ls -la e2e/features/*.spec.ts
```

Compare against the pre-assigned file list. Report any missing files.

### 5.2 Run Test Discovery

```bash
npx playwright test --list 2>&1
```

All generated tests should be discoverable. If any file has syntax errors, fix them.

### 5.3 Check for Import Path Errors

```bash
grep -rn "from.*fixtures" e2e/features/ | grep -v "../fixtures"
```

Any result here is a misconfigured import path. Fix `./fixtures` to `../fixtures`.

### 5.4 Check for Duplicate Test Names

```bash
grep -rh "test('" e2e/features/ | sort | uniq -d
```

If duplicates exist, rename them to be unique (add the feature name as prefix).

### 5.5 Smoke Check (optional)

If a dev server is running, run the full suite:

```bash
npx playwright test --project=chromium 2>&1 | tail -30
```

Report results. Tests for unbuilt features are expected to fail - this is correct behavior.

---

## Phase 6: CI/CD Workflow Generation

Generate `.github/workflows/e2e.yml` (or update existing):

```bash
mkdir -p .github/workflows
```

```yaml
name: E2E Tests

on:
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npx playwright test
        env:
          CI: true
          # Auth-dependent tests require these GitHub Actions secrets.
          # Set in: Settings > Secrets and variables > Actions
          # Tests gracefully skip if not configured.
          E2E_USER_EMAIL: ${{ secrets.E2E_USER_EMAIL }}
          E2E_USER_PASSWORD: ${{ secrets.E2E_USER_PASSWORD }}
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 30
```

---

## Phase 7: Report

Present the final summary:

```
Test Vision Complete

Feature Domains: {N}
Spec Files Generated: {N}
Total Tests: {N}
Infrastructure Files: {N} (playwright.config.ts, fixtures.ts, auth.setup.ts)
CI Workflow: .github/workflows/e2e.yml

Coverage by Domain:
  {domain}.spec.ts - {N} tests (Tier {0|1|2})
  {domain}.spec.ts - {N} tests (Tier {0|1|2})
  ...

{If any planned/unbuilt features:}
Tests for Planned Features (expected to fail until built):
  {feature name} - {N} tests in {file}

Validation:
  Test discovery: {pass/fail}
  Import paths: {pass/fail}
  Duplicate names: {pass/fail}
  Smoke check: {pass/fail/skipped}

Next Steps:
  1. Set E2E_USER_EMAIL and E2E_USER_PASSWORD in .env
  2. Run: npx playwright test --project=setup (authenticate)
  3. Run: npx playwright test (run full suite)
  4. Add GitHub Actions secrets for CI (Settings > Secrets)
  5. Use /e2e to add tests for new features as they're built
```
