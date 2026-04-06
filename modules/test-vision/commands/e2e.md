---
description: Generate a Playwright e2e test spec for a single feature, flow, or issue. Works standalone or as a building block for /test-vision.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion
argument-hint: <feature name | issue number | route path | description> [--file <output-path>]
---

# /e2e - Playwright E2E Spec Generator

Generates a complete Playwright e2e test spec file for a single feature, flow, or issue. Works in two modes:

- **Standalone**: Called directly by the user. Runs full discovery + Chrome MCP exploration + infrastructure setup + spec generation.
- **Composed**: Called by /test-vision as an atomic building block. Receives pre-computed context and skips discovery.

## Sub-Agent Model Optimization

When spawning discovery sub-agents, use **sonnet**. The orchestrator (this command) stays on the current model.

---

## Input

```
$ARGUMENTS
```

---

## Phase 0: Mode Detection (READ THIS FIRST)

**This is a hard branch. Follow it exactly.**

Check the agent prompt/context for a block beginning with `CONTEXT (from /test-vision discovery):`.

- **If that block IS present**: You are in **COMPOSED MODE**.
  - Skip Phase 1 (Parse & Discover) entirely.
  - Skip Phase 2 (Chrome MCP Exploration) entirely.
  - Phase 3 becomes **check-only** (verify infrastructure exists, NEVER write files).
  - Proceed directly to Phase 4 (Generate Spec) using the provided context.

- **If that block is NOT present**: You are in **STANDALONE MODE**.
  - Run all phases starting from Phase 1.

Do NOT run discovery if composed context is provided. Do NOT run Chrome MCP if composed context is provided. This is non-negotiable.

---

## Phase 1: Parse & Discover (STANDALONE MODE ONLY)

### 1.1 Parse Arguments

Parse `$ARGUMENTS`:
- If starts with `#` or is a number: treat as GitHub issue number
  ```bash
  gh issue view {number} --json title,body,labels
  ```
- If starts with `/`: treat as a route path, search for the feature owning that route
- Otherwise: treat as a feature name or description

### 1.2 Targeted Discovery

Run a focused discovery for the specific feature area:

1. **Find route definitions** matching the feature:
   ```
   Grep for the route path or feature name in: **/routes.{ts,tsx}, **/App.{ts,tsx}, **/router.{ts,tsx}
   ```

2. **Read relevant components**:
   ```
   Glob for components related to the feature in src/
   ```

3. **Check for existing tests**:
   ```
   Glob: e2e/**/*.spec.ts, **/{feature}*.spec.ts, **/{feature}*.test.ts
   ```

4. **Identify auth requirements**:
   - Look for ProtectedRoute wrappers, auth middleware, or auth checks on the routes
   - Check for `useAuth`, `useSession`, or similar hooks in the components

5. **Find related API endpoints**:
   ```
   Grep for API routes related to the feature: **/api/**/{feature}*, **/functions/**/{feature}*
   ```

6. **Check state stores** (if applicable):
   ```
   Glob: **/store/**/{feature}*, **/stores/**/{feature}*, **/context/**/{feature}*
   ```

7. **Find form schemas**:
   ```
   Grep for zod schemas or useForm in the feature's components
   ```

### 1.3 Detect Auth Provider

Check `package.json` for the auth provider:
- `better-auth` -> Better Auth
- `@supabase/supabase-js` or `@supabase/ssr` -> Supabase Auth
- `@clerk/clerk-react` or `@clerk/nextjs` -> Clerk
- None detected -> no auth or unknown provider

---

## Phase 2: Chrome MCP Exploration (STANDALONE MODE ONLY)

**Skip if Chrome MCP tools are unavailable or the dev server is not running.**

1. Check if a dev server is running:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || \
   curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null
   ```

2. If the app is running and Chrome MCP tools are available:
   - Navigate to the feature's primary route
   - Read the page content to identify interactive elements
   - Note: forms, buttons, modals, dropdowns, data displays
   - Check console for errors
   - If redirected to login/auth: note as "auth-required" and proceed with code-based discovery only

3. If Chrome MCP unavailable or app not running: skip this phase and note in output. Code-based discovery from Phase 1 is sufficient.

---

## Phase 3: Infrastructure Check/Generate

### Standalone Mode

Before writing the spec, ensure infrastructure exists. For each missing file, generate it:

1. **Check for Playwright**:
   ```bash
   grep -q "@playwright/test" package.json 2>/dev/null
   ```
   If missing:
   ```bash
   npm install -D @playwright/test
   npx playwright install chromium
   ```

2. **Check for `playwright.config.ts`**:
   If missing, generate based on auth detection:

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
       {
         name: 'chromium',
         use: { ...devices['Desktop Chrome'] },
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

3. **Check for `e2e/fixtures.ts`** (only if auth detected):
   If missing, generate:
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

4. **Check for `e2e/auth.setup.ts`** (only if auth detected):
   If missing, generate based on provider. See auth templates below.

5. **Create directories**:
   ```bash
   mkdir -p e2e/features e2e/.auth
   ```

6. **Gitignore auth state**:
   ```bash
   echo '*' > e2e/.auth/.gitignore
   grep -q "e2e/.auth" .gitignore 2>/dev/null || echo "e2e/.auth/" >> .gitignore
   ```

### Composed Mode (CHECK-ONLY)

Verify all infrastructure files exist:
```bash
ls e2e/fixtures.ts e2e/auth.setup.ts playwright.config.ts 2>/dev/null
ls e2e/features/ 2>/dev/null
```

If any required file is missing, report the error: "Infrastructure file missing: {file}. This should have been generated by /test-vision Phase 3. Aborting." Do NOT attempt to create infrastructure files in composed mode.

---

## Phase 4: Generate Spec File

Determine the output file path:
- If `--file <path>` was provided: use that path
- If in composed mode: use the path from the context block
- Otherwise: default to `e2e/features/{feature-name-kebab}.spec.ts`

Generate the spec file following this template:

```typescript
import { test, expect } from '../fixtures'
// For projects without auth, use: import { test, expect } from '@playwright/test'

/**
 * {Feature Name} E2E Tests
 *
 * Covers: {list the flows covered}
 * Auth required: {yes/no}
 * Routes tested: {/path1, /path2}
 * Generated by: /e2e
 */

test.describe('{Feature Name}', () => {

  // ---- Tier 1: Route loads ----

  test.describe('Page Load', () => {
    test('{feature} page loads without errors', async ({ page }) => {
      await page.goto('{route}')
      await expect(page).not.toHaveURL(/error|404/)
      await expect(page.getByRole('main')).toBeVisible()
    })
  })

  // ---- Tier 2: Structural landmarks ----

  test.describe('Structure', () => {
    test('displays expected headings and navigation', async ({ authenticatedPage: page }) => {
      await page.goto('{route}')
      await expect(page.getByRole('heading', { name: /{feature}/i })).toBeVisible()
      // Add assertions for key UI landmarks
    })
  })

  // ---- Tier 3: Behavioral interactions ----

  test.describe('{Primary Flow}', () => {
    test('{expected behavior}', async ({ authenticatedPage: page }) => {
      await page.goto('{route}')
      await page.waitForLoadState('networkidle')
      // Add interaction assertions
    })
  })

  // ---- Error states ----

  test.describe('Error States', () => {
    test('redirects unauthenticated users', async ({ page }) => {
      await page.goto('{protected-route}')
      await expect(page).toHaveURL(/login|signin|sign-in/)
    })
  })

})
```

### Spec Generation Rules

- **Direct locators**: Use `getByRole`, `getByText`, `getByTestId`, `getByLabel`. No CSS selectors unless absolutely necessary.
- **No shared state**: Every test calls `page.goto()` directly. No state carried between tests.
- **Auth fixtures**: Protected routes use `authenticatedPage` fixture. Public routes use `page`.
- **Graceful skip**: Auth-dependent tests skip when credentials are absent (handled by the fixture).
- **`.or()` combinator**: For features with multiple valid states (empty vs populated), use `.or()` to accept any valid state.
- **No exact copy assertions**: Use regex matchers (`/pattern/i`) for text assertions. Copy changes shouldn't break tests.
- **Test count**: Aim for 6-15 tests per spec file. Fewer means missing coverage. More means testing implementation details.
- **Three tiers**: Always include Tier 1 (route loads). Include Tier 2 (structural) for all features with UI. Include Tier 3 (behavioral) for features with interactions.
- **Error states**: Include auth redirect tests for protected routes. Include form validation tests if forms exist.

### Auth Setup Templates (used in Phase 3)

#### Better Auth (email/password - UI-based)
```typescript
import { test as setup, expect } from '@playwright/test'

const USER_AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate as user', async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL
  const password = process.env.E2E_USER_PASSWORD

  if (!email || !password) {
    console.log('Skipping auth setup: E2E_USER_EMAIL and E2E_USER_PASSWORD not set')
    return
  }

  await page.goto('/login')
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/password/i).fill(password)
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await page.waitForURL(/dashboard|home|\/$/)
  await page.context().storageState({ path: USER_AUTH_FILE })
})
```

#### Supabase Auth (programmatic API)
```typescript
import { test as setup } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'

const USER_AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate via Supabase API', async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL
  const password = process.env.E2E_USER_PASSWORD
  const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL
  const supabaseKey = process.env.VITE_SUPABASE_PUBLISHABLE_KEY || process.env.SUPABASE_PUBLISHABLE_KEY

  if (!email || !password || !supabaseUrl || !supabaseKey) {
    console.log('Skipping auth setup: E2E credentials or Supabase config not set')
    return
  }

  const supabase = createClient(supabaseUrl, supabaseKey)
  const { data, error } = await supabase.auth.signInWithPassword({ email, password })

  if (error || !data.session) {
    console.log(`Auth failed: ${error?.message || 'no session'}`)
    return
  }

  await page.goto('/')
  await page.evaluate((session) => {
    const storageKey = Object.keys(localStorage).find(k => k.startsWith('sb-')) || 'sb-auth-token'
    localStorage.setItem(storageKey, JSON.stringify(session))
  }, data.session)
  await page.reload()
  await page.waitForURL(/dashboard|home|\/$/)
  await page.context().storageState({ path: USER_AUTH_FILE })
})
```

#### Clerk (UI-based)
```typescript
import { test as setup } from '@playwright/test'

const USER_AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate as user', async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL
  const password = process.env.E2E_USER_PASSWORD

  if (!email || !password) {
    console.log('Skipping auth setup: E2E_USER_EMAIL and E2E_USER_PASSWORD not set')
    return
  }

  await page.goto('/sign-in')
  await page.getByLabel(/email/i).fill(email)
  await page.getByRole('button', { name: /continue/i }).click()
  await page.getByLabel(/password/i).fill(password)
  await page.getByRole('button', { name: /continue|sign in/i }).click()
  await page.waitForURL(/dashboard|home|\/$/)
  await page.context().storageState({ path: USER_AUTH_FILE })
  // If Clerk test mode is enabled, consider @clerk/testing/playwright
})
```

#### Generic / Unknown Provider
```typescript
import { test as setup } from '@playwright/test'

const USER_AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate as user', async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL
  const password = process.env.E2E_USER_PASSWORD

  if (!email || !password) {
    console.log('Skipping auth setup: E2E credentials not set')
    return
  }

  // Customize for your auth provider:
  await page.goto('/login')
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/password/i).fill(password)
  await page.getByRole('button', { name: /sign in|log in|submit/i }).click()
  await page.waitForURL('**/*', { timeout: 10000 })
  await page.context().storageState({ path: USER_AUTH_FILE })
})
```

---

## Phase 5: Validate

1. Verify the spec file was created:
   ```bash
   ls -la {output-file-path}
   ```

2. Run test discovery to confirm the file is valid:
   ```bash
   npx playwright test {output-file-path} --list 2>&1
   ```

3. If the feature exists and a dev server is running, optionally run the tests:
   ```bash
   npx playwright test {output-file-path} --project=chromium 2>&1 | tail -30
   ```

---

## Phase 6: Output

Report the results:

```
E2E Spec Generated

File: {output-file-path}
Feature: {feature name}
Routes: {/path1, /path2}
Auth: {required/not required}
Tests: {N} ({tier breakdown})
  Tier 1 (route loads): {N}
  Tier 2 (structural): {N}
  Tier 3 (behavioral): {N}
  Error states: {N}

Validation: {passed/failed}
{If failed: specific error and fix needed}

Next steps:
  1. Set E2E_USER_EMAIL and E2E_USER_PASSWORD in .env (if auth required)
  2. Run: npx playwright test --project=setup (to authenticate)
  3. Run: npx playwright test {file} (to run these tests)
```
