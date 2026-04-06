# Test Vision Module

Vision-driven e2e test suite generation for any codebase. Provides two composable commands:

- **`/test-vision`** - Full repo analysis: discovers all features, interviews you to validate test cases, generates Playwright infrastructure, dispatches parallel agents to build a complete e2e test suite with CI/CD integration.
- **`/e2e`** - Single feature: generates one Playwright spec file for a specific feature, flow, or issue. Works standalone or as the atomic building block within `/test-vision`.

## Architecture

`/test-vision` composes `/e2e` as its atomic unit. The orchestrator handles discovery, infrastructure, and coordination. Each feature domain gets its own `/e2e` agent that generates a single spec file. File paths are pre-assigned before dispatch to prevent conflicts.

```
/test-vision
  |-- Phase 0: Codebase Discovery (7-source checklist)
  |-- Phase 1: Chrome MCP Visual Discovery
  |-- Phase 2: User Interview (validate, prioritize, sign off)
  |-- Phase 3: Infrastructure Generation (config, fixtures, auth)
  |-- Phase 4: Parallel /e2e Dispatch (one agent per feature domain)
  |-- Phase 5: Integration & Validation
  |-- Phase 6: CI/CD Workflow Generation
  |-- Phase 7: Report
```

## Usage

### Full Test Suite Generation

```bash
# Run in any repo to generate a complete e2e test suite
/test-vision

# Skip Chrome MCP discovery (code-based only)
/test-vision --skip-chrome

# Skip user interview (use auto-detected defaults)
/test-vision --skip-interview
```

### Single Feature Spec

```bash
# By feature name
/e2e authentication

# By issue number
/e2e #42

# By route path
/e2e /dashboard/settings

# By description
/e2e user profile editing with avatar upload

# With explicit output path
/e2e payments --file e2e/features/payments.spec.ts
```

## What Gets Generated

### Test Infrastructure
- `playwright.config.ts` - with auth setup project, webServer config
- `e2e/fixtures.ts` - authenticatedPage fixture with graceful skip
- `e2e/auth.setup.ts` - auth provider-specific setup (Better Auth, Supabase, Clerk)
- `e2e/.auth/.gitignore` - ignore auth state files

### Spec Files
- `e2e/features/{domain}.spec.ts` - one per feature domain
- Three-tier assertions: route loads, structural landmarks, behavioral interactions
- Direct locators (getByRole, getByText, getByTestId)
- Graceful credential skipping

### CI/CD
- `.github/workflows/e2e.yml` - GitHub Actions workflow with artifact upload

## Test-Driven Feature Development

The generated test suite supports building features test-first:

1. Run `/test-vision` to generate specs for all planned features
2. Tests for unbuilt features will fail (this is expected)
3. Give an agent the failing spec: "Using the e2e tests in `e2e/features/payments.spec.ts` and Playwright, build out the payments feature"
4. The agent builds the feature to make the tests pass
5. Use `/e2e` to add specs for new features as they're designed

## Supported Auth Providers

| Provider | Strategy | Env Vars |
|----------|----------|----------|
| Better Auth | UI-based form fill | E2E_USER_EMAIL, E2E_USER_PASSWORD |
| Supabase | Programmatic API injection | E2E_USER_EMAIL, E2E_USER_PASSWORD, VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY |
| Clerk | UI-based two-step sign-in | E2E_USER_EMAIL, E2E_USER_PASSWORD |
| Unknown | Generic UI-based (customizable) | E2E_USER_EMAIL, E2E_USER_PASSWORD |

## Dependencies

- `browser-automation` - Chrome MCP tool permissions for visual discovery
- `multi-agent` - Task agent dispatch for parallel spec generation

## Manual Installation

1. Copy `commands/test-vision.md` to `~/.claude/commands/test-vision.md`
2. Copy `commands/e2e.md` to `~/.claude/commands/e2e.md`
3. Ensure `browser-automation` and `multi-agent` modules are installed
